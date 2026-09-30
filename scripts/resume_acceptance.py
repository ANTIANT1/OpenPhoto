"""Resume an interrupted acceptance export and verify its durable checkpoint."""

import argparse
import json
import socket
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import psutil
from PIL import Image

from openphoto.processes import OwnedProcesses, configure_threads
from verify_personal import digest


def run(original, sources, directory):
    configure_threads()
    original, sources, directory = original.resolve(), sources.resolve(), directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {"checks": {}, "ok": False, "peak_rss_mb": 0}

    def checkpoint(stage):
        report["stage"] = stage
        (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(stage, flush=True)

    project = original / "project"
    with (
        sqlite3.connect(project / "catalog.sqlite") as source,
        sqlite3.connect(directory / "before-resume.sqlite") as target,
    ):
        source.backup(target)
    existing = {
        p.name: digest(p)
        for p in (original / "whole-export").iterdir()
        if p.is_file() and not p.name.startswith(".")
    }
    log = (directory / "server.log").open("w", encoding="utf-8")
    session_file = directory / "launch-session.json"
    owner = OwnedProcesses()
    process = owner.popen(
        [
            sys.executable,
            "-m",
            "openphoto",
            "--browser",
            "--project",
            str(project),
            "--session-file",
            str(session_file),
        ],
        stdout=log,
        stderr=log,
    )
    client = None
    descendants = {}
    port = None
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert process.poll() is None, "Server stopped"
            if session_file.exists():
                try:
                    data = json.loads(session_file.read_text())
                    if client is None:
                        client = httpx.Client(
                            base_url=data["url"], headers={"X-OpenPhoto-Token": data["token"]}, timeout=90
                        )
                        port = int(data["url"].rsplit(":", 1)[1])
                    if client.get("/api/status").status_code == 200:
                        break
                except (httpx.ConnectError, json.JSONDecodeError):
                    pass
            time.sleep(0.2)
        else:
            raise TimeoutError("Server startup")
        jobs = client.get("/api/jobs").json()
        job = next(j for j in jobs if j["kind"] == "export" and j["state"] == "paused" and j["total"] == 321)
        report["checks"]["restored_completed"] = job["completed"]
        identifier = job["id"]
        response = client.post(f"/api/jobs/{identifier}/resume")
        response.raise_for_status()
        checkpoint("Resuming incomplete export")
        start, last_update = time.monotonic(), 0
        while time.monotonic() - start < 7200:
            root = psutil.Process(process.pid)
            tree = [root, *root.children(recursive=True)]
            rss = 0
            for child in tree:
                descendants[(child.pid, child.create_time())] = child
                try:
                    rss += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            report["peak_rss_mb"] = round(max(report["peak_rss_mb"], rss / 1024**2), 1)
            job = next(j for j in client.get("/api/jobs").json() if j["id"] == identifier)
            if job["state"] == "completed":
                break
            if job["state"] in {"failed", "completed_with_errors", "paused", "cancelled"}:
                raise RuntimeError(json.dumps(job))
            if time.monotonic() - last_update > 20:
                checkpoint(f"Export {job['completed']}/{job['total']}")
                last_update = time.monotonic()
            time.sleep(0.75)
        else:
            raise TimeoutError("Resumed export timeout")
        report["resume_seconds"] = round(time.monotonic() - start, 2)
        report["checks"]["completed_exports"] = job["completed"]
        checkpoint("Verifying every export and previous checkpoint")
        for item in job["result"]["files"].values():
            image_path = Path(item["path"])
            with Image.open(image_path) as image:
                assert max(image.size) == 2048 and image.info.get("icc_profile")
            for suffix in (".xmp", ".openphoto.json"):
                assert image_path.with_suffix(image_path.suffix + suffix).is_file()
            assert item["state"] == "committed"
        report["checks"]["all_export_dimensions_icc_sidecars"] = True
        report["checks"]["previous_exports_unchanged"] = all(
            digest(original / "whole-export" / name) == sha for name, sha in existing.items()
        )
        report["checks"]["no_export_temporaries"] = not any(
            p.name.startswith(".") for p in (original / "whole-export").iterdir()
        )
        end = time.monotonic() + 40
        while (
            time.monotonic() < end and client.get("/api/status").json()["resources"]["worker_pid"] is not None
        ):
            time.sleep(1)
        report["checks"]["idle_worker_released"] = (
            client.get("/api/status").json()["resources"]["worker_pid"] is None
        )
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
        end = time.monotonic() + 10
        while time.monotonic() < end and any(p.is_running() for p in descendants.values()):
            time.sleep(0.1)
        report["checks"]["owned_processes_closed"] = all(not p.is_running() for p in descendants.values())
        if port:
            with socket.socket() as sock:
                report["checks"]["port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
        checkpoint("Rechecking all source hashes")
        before = json.loads((original / "originals-before.json").read_text())
        report["checks"]["originals_unchanged"] = all(
            digest(sources / name) == sha for name, sha in before.items()
        )
        report["ok"] = report["ok"] and all(value is not False for value in report["checks"].values())
        checkpoint("Recovery acceptance completed" if report["ok"] else "Recovery acceptance failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    run(args.original, args.sources, args.directory)
