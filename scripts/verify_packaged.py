"""Run an isolated end-to-end check against the frozen executable's real workers."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx
import tifffile
from PIL import Image


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(executable, sources, directory, expected_device=None):
    directory.mkdir(parents=True, exist_ok=False)
    started_workflow = time.perf_counter()
    report = {
        "executable": executable.name,
        "executable_sha256": sha(executable),
        "frozen": True,
        "checks": {},
        "errors": [],
    }
    originals = {str(p): sha(p) for p in sources.iterdir() if p.is_file()}
    report["source_sha256"] = {Path(p).name: value for p, value in originals.items()}
    log = (directory / "server.log").open("w", encoding="utf-8")
    from openphoto.processes import OwnedProcesses

    owner = OwnedProcesses()
    session_file = directory / "launch-session.json"
    process = owner.popen(
        [
            str(executable),
            "--browser",
            "--project",
            str(directory / "project"),
            "--session-file",
            str(session_file),
        ],
        stdout=log,
        stderr=log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    client = None
    try:
        deadline = time.monotonic() + 90
        session = None
        while time.monotonic() < deadline:
            text = (directory / "server.log").read_text(encoding="utf-8", errors="replace")
            if session_file.exists():
                try:
                    session = json.loads(session_file.read_text())
                    break
                except json.JSONDecodeError:
                    pass
            if process.poll() is not None:
                raise RuntimeError("Frozen server stopped: " + text[-2000:])
            time.sleep(0.3)
        if not session:
            raise TimeoutError("Frozen server startup timed out")
        client = httpx.Client(
            base_url=session["url"], headers={"X-OpenPhoto-Token": session["token"]}, timeout=60
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                client.get("/api/status").raise_for_status()
                break
            except httpx.ConnectError:
                if process.poll() is not None:
                    raise RuntimeError("Frozen server stopped before accepting requests")
                time.sleep(0.1)
        else:
            raise TimeoutError("Frozen HTTP listener startup timed out")

        def post(path, data):
            response = client.post(path, json=data)
            response.raise_for_status()
            return response.json()

        def wait_job(identifier):
            end = time.monotonic() + 600
            while time.monotonic() < end:
                job = next(j for j in client.get("/api/jobs").json() if j["id"] == identifier)
                if job["state"] == "completed":
                    return job
                if job["state"] in {"failed", "completed_with_errors", "cancelled"}:
                    raise RuntimeError(str(job))
                time.sleep(0.5)
            raise TimeoutError(identifier)

        wait_job(
            post("/api/import", {"paths": [str(sources)], "shoot_name": "Packaged acceptance"})["job_id"]
        )
        photos = client.get("/api/photos").json()["photos"]
        ids = [p["id"] for p in photos]
        assert len(ids) == len(originals)
        report["checks"]["import"] = len(ids)
        print("Frozen import passed", flush=True)
        wait_job(post("/api/analyze", {"photo_ids": ids})["job_id"])
        detail = [client.get("/api/photos/" + p["id"]).json() for p in photos]
        assert all(not d["analysis"].get("model_errors") and d["analysis"].get("embedding") for d in detail)
        devices = sorted({d["analysis"].get("device", "unknown") for d in detail})
        if expected_device:
            assert devices == [expected_device], f"Expected {expected_device}, got {devices}"
        report["checks"]["analysis"] = len(ids)
        report["analysis_devices"] = devices
        print(f"Frozen analysis passed ({', '.join(devices)})", flush=True)
        raw = next(p for p in photos if p["raw"])
        wait_job(post("/api/photos/" + raw["id"] + "/render", {})["job_id"])
        assert client.get(f"/api/photos/{raw['id']}/image?variant=render&revision=0").status_code == 200
        report["checks"]["raw_preview"] = True
        started = time.perf_counter()
        output = directory / "export"
        job = wait_job(
            post(
                "/api/export",
                {
                    "photo_ids": ids,
                    "directory": str(output),
                    "format": "tiff",
                    "profile": "prophoto",
                    "include_proposed": True,
                },
            )["job_id"]
        )
        report["export_seconds"] = time.perf_counter() - started
        images = []
        for receipt in job["result"]["files"].values():
            path = Path(receipt["path"])
            with tifffile.TiffFile(path) as tif:
                page = tif.pages[0]
                assert str(page.dtype) == "uint16" and len(page.tags[34675].value) > 100
                images.append(
                    {
                        "name": path.name,
                        "shape": list(page.shape),
                        "dtype": str(page.dtype),
                        "icc_bytes": len(page.tags[34675].value),
                    }
                )
            assert path.with_suffix(path.suffix + ".xmp").exists()
            manifest = json.loads(
                path.with_suffix(path.suffix + ".openphoto.json").read_text(encoding="utf-8")
            )
            assert manifest["source_sha256"] in originals.values()
        report["checks"]["tiff_exports"] = images
        payload = {
            "photo_ids": [raw["id"]],
            "directory": str(output),
            "format": "jpeg",
            "long_edge": 1200,
            "include_proposed": True,
        }
        paths = []
        for _ in range(2):
            receipt = wait_job(post("/api/export", payload)["job_id"])["result"]["files"][raw["id"]]
            path = Path(receipt["path"])
            with Image.open(path) as im:
                assert max(im.size) == 1200 and im.info.get("icc_profile")
            paths.append(str(path))
        assert len(set(paths)) == 2
        report["checks"]["jpeg_and_safe_names"] = True
        report["checks"]["original_hashes_unchanged"] = all(
            sha(Path(p)) == expected for p, expected in originals.items()
        )
        assert report["checks"]["original_hashes_unchanged"]
        report["ok"] = True
        print("Frozen exports and original hashes passed", flush=True)
    except Exception as error:
        report["ok"] = False
        report["errors"].append(str(error))
        raise
    finally:
        if client:
            client.close()
        owner.close()
        process.wait(timeout=20)
        session_file.unlink(missing_ok=True)
        log.close()
        report["workflow_seconds"] = time.perf_counter() - started_workflow
        (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, default=Path("dist/OpenPhoto/OpenPhoto-Diagnostics.exe"))
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--expected-device", choices=("cpu", "cuda"))
    args = parser.parse_args()
    run(args.executable.resolve(), args.sources.resolve(), args.directory.resolve(), args.expected_device)
