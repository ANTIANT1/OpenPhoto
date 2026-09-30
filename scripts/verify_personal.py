"""Read-only source acceptance through the real local API, with an owned server."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import time
from pathlib import Path

import httpx
import psutil
from PIL import Image

from openphoto.processes import OwnedProcesses, configure_threads


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def spread(items, count):
    return (
        [
            items[round(i * (len(items) - 1) / (min(count, len(items)) - 1))]
            for i in range(min(count, len(items)))
        ]
        if len(items) > 1
        else items
    )


def run(sources, directory, whole=False):
    configure_threads()
    sources, directory = sources.resolve(), directory.resolve()
    if directory.is_relative_to(sources) or sources.is_relative_to(directory):
        raise ValueError("The acceptance project must be separate from originals")
    directory.mkdir(parents=True, exist_ok=False)
    report = {"checks": {}, "timings": {}, "peak_server_tree_rss_mb": 0, "ok": False}
    report_path = directory / "report.json"

    def checkpoint(message):
        report["stage"] = message
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(message, flush=True)

    checkpoint("Hashing every source, including existing sidecars and PSDs")
    files = sorted(p for p in sources.rglob("*") if p.is_file())
    originals = {str(p.relative_to(sources)): digest(p) for p in files}
    (directory / "originals-before.json").write_text(json.dumps(originals, indent=2), encoding="utf-8")
    report["checks"]["source_files"] = len(originals)
    raw = [p for p in files if p.suffix.lower() == ".arw"]
    jpeg = [p for p in files if p.suffix.lower() in {".jpg", ".jpeg"}]
    selected_raw = spread(raw, 20)
    selected_jpeg = spread([p for p in jpeg if p.stem.casefold() not in {r.stem.casefold() for r in raw}], 5)
    sample = (
        selected_raw
        + selected_jpeg
        + [p for p in jpeg if p.stem.casefold() in {r.stem.casefold() for r in selected_raw}]
    )
    owner = OwnedProcesses()
    log = (directory / "server.log").open("w", encoding="utf-8")
    session_file = directory / "launch-session.json"
    process = owner.popen(
        [
            sys.executable,
            "-m",
            "openphoto",
            "--browser",
            "--project",
            str(directory / "project"),
            "--session-file",
            str(session_file),
        ],
        stdout=log,
        stderr=log,
    )
    client = None
    port = None
    descendants = {}

    def metrics():
        try:
            tree = [psutil.Process(process.pid), *psutil.Process(process.pid).children(recursive=True)]
            for child in tree:
                descendants[(child.pid, child.create_time())] = child
            total = sum(p.memory_info().rss for p in tree if p.is_running()) / 1024**2
            report["peak_server_tree_rss_mb"] = round(max(total, report["peak_server_tree_rss_mb"]), 1)
        except psutil.NoSuchProcess:
            pass

    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Server stopped; inspect its private log")
            if session_file.exists():
                try:
                    session = json.loads(session_file.read_text())
                    if client is None:
                        client = httpx.Client(
                            base_url=session["url"],
                            headers={"X-OpenPhoto-Token": session["token"]},
                            timeout=60,
                        )
                        port = int(session["url"].rsplit(":", 1)[1])
                    if client.get("/api/status").status_code == 200:
                        break
                except (httpx.ConnectError, json.JSONDecodeError):
                    pass
            time.sleep(0.2)
        else:
            raise TimeoutError("Server startup")

        def request(method, path, data=None):
            response = client.request(method, "/api" + path, json=data)
            response.raise_for_status()
            return response.json()

        def wait(job_id, timeout=3600):
            end, last_progress = time.monotonic() + timeout, 0
            while time.monotonic() < end:
                metrics()
                job = next(j for j in request("GET", "/jobs") if j["id"] == job_id)
                if job["state"] == "completed":
                    return job
                if job["state"] in {"failed", "completed_with_errors", "cancelled", "paused"}:
                    raise RuntimeError(json.dumps(job, ensure_ascii=False))
                if time.monotonic() - last_progress > 20:
                    print(f"{job['kind']}: {job['completed']}/{job['total']}", flush=True)
                    last_progress = time.monotonic()
                time.sleep(0.5)
            raise TimeoutError("Job " + job_id)

        def timed(label, operation):
            checkpoint(label)
            start = time.perf_counter()
            result = operation()
            report["timings"][label] = round(time.perf_counter() - start, 2)
            return result

        def all_photos():
            result = []
            while True:
                page = request("GET", f"/photos?offset={len(result)}&limit=250")
                result.extend(page["photos"])
                if len(result) >= page["total"]:
                    return result

        request("PATCH", "/settings", {"cache_gb": 8, "worker_idle_seconds": 10, "cpu_threads": 4})
        timed(
            "Import representative sample",
            lambda: wait(
                request(
                    "POST", "/import", {"paths": list(map(str, sample)), "shoot_name": "Контрольный набор"}
                )["job_id"]
            ),
        )
        photos = all_photos()
        assert len(photos) == len(selected_raw) + len(selected_jpeg)
        assert sum(p["raw"] and p["paired"] for p in photos) == len(selected_raw)
        report["checks"]["sample_assets"] = len(photos)
        ids = [p["id"] for p in photos]
        timed("Analyze sample", lambda: wait(request("POST", "/analyze", {"photo_ids": ids})["job_id"]))
        details = [request("GET", "/photos/" + i) for i in ids]
        assert all(d["analysis"].get("embedding") and not d["analysis"].get("model_errors") for d in details)
        report["checks"]["analysis_devices"] = sorted({d["analysis"]["device"] for d in details})
        report["checks"]["faces_detected"] = sum(len(d["analysis"]["faces"]) for d in details)
        sample_raw = next(p for p in photos if p["raw"])
        timed(
            "Develop sample RAW preview",
            lambda: wait(request("POST", "/photos/" + sample_raw["id"] + "/render")["job_id"]),
        )
        camera = client.get("/api/photos/" + sample_raw["id"] + "/image?variant=camera-full")
        assert camera.status_code == 200
        report["checks"]["camera_jpeg_full"] = True
        # Export all sample frames at original resolution, through actual RAW development.
        job = timed(
            "Export sample full-size JPEG",
            lambda: wait(
                request(
                    "POST",
                    "/export",
                    {"photo_ids": ids, "directory": str(directory / "sample-export"), "format": "jpeg"},
                )["job_id"]
            ),
        )
        for p in photos:
            output = Path(job["result"]["files"][p["id"]]["path"])
            with Image.open(output) as image:
                assert image.width > 0 and image.height > 0 and image.info.get("icc_profile")
                assert (image.width > image.height) == (p["width"] > p["height"])
            assert output.with_suffix(output.suffix + ".xmp").exists()
            assert output.with_suffix(output.suffix + ".openphoto.json").exists()
        report["checks"]["full_size_sample_exports"] = len(photos)
        import tifffile

        tiffjob = timed(
            "Export 16-bit TIFF",
            lambda: wait(
                request(
                    "POST",
                    "/export",
                    {
                        "photo_ids": [sample_raw["id"]],
                        "directory": str(directory / "sample-export"),
                        "format": "tiff",
                        "profile": "prophoto",
                    },
                )["job_id"]
            ),
        )
        with tifffile.TiffFile(tiffjob["result"]["files"][sample_raw["id"]]["path"]) as tif:
            assert str(tif.pages[0].dtype) == "uint16" and len(tif.pages[0].tags[34675].value) > 100
            report["checks"]["tiff16_shape"] = list(tif.pages[0].shape)
        timed(
            "Repeat import sample",
            lambda: wait(
                request(
                    "POST", "/import", {"paths": list(map(str, sample)), "shoot_name": "Повторная проверка"}
                )["job_id"]
            ),
        )
        assert len(all_photos()) == len(photos)
        report["checks"]["idempotent_import"] = True
        if whole:
            timed(
                "Import whole folder",
                lambda: wait(
                    request(
                        "POST", "/import", {"paths": [str(sources)], "shoot_name": "Вся контрольная папка"}
                    )["job_id"]
                ),
            )
            photos = all_photos()
            ids = [p["id"] for p in photos]
            assert not any(p["error"] for p in photos)
            report["checks"]["whole_assets"] = len(photos)
            report["checks"]["whole_raw_pairs"] = sum(p["raw"] and p["paired"] for p in photos)
            timed(
                "Analyze whole folder",
                lambda: wait(request("POST", "/analyze", {"photo_ids": ids})["job_id"]),
            )
            timed(
                "Export whole folder 2048 JPEG",
                lambda: wait(
                    request(
                        "POST",
                        "/export",
                        {
                            "photo_ids": ids,
                            "directory": str(directory / "whole-export"),
                            "format": "jpeg",
                            "long_edge": 2048,
                        },
                    )["job_id"]
                ),
            )
            report["checks"]["whole_exports"] = len(ids)
        checkpoint("Waiting for idle worker to release models")
        end = time.monotonic() + 40
        while time.monotonic() < end and request("GET", "/status")["resources"]["worker_pid"] is not None:
            metrics()
            time.sleep(1)
        assert request("GET", "/status")["resources"]["worker_pid"] is None
        report["checks"]["idle_worker_released"] = True
        report["ok"] = True
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        if client:
            client.close()
        owner.close()
        process.wait(timeout=10)
        log.close()
        session_file.unlink(missing_ok=True)
        report["checks"]["owned_processes_closed"] = all(not p.is_running() for p in descendants.values())
        if port:
            with socket.socket() as sock:
                report["checks"]["port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        checkpoint("Checking originals after workflow")
        after = {str(p.relative_to(sources)): digest(p) for p in files}
        report["checks"]["originals_unchanged"] = after == originals
        report["ok"] = (
            report["ok"]
            and report["checks"]["originals_unchanged"]
            and report["checks"]["owned_processes_closed"]
            and report["checks"].get("port_closed", False)
        )
        checkpoint("Acceptance completed" if report["ok"] else "Acceptance failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--whole", action="store_true")
    args = parser.parse_args()
    run(args.sources, args.directory, args.whole)
