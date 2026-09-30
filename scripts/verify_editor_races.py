"""Create a synthetic project and supervise the browser regression process tree."""
import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

import httpx
import psutil
from fastapi.testclient import TestClient
from PIL import Image

from openphoto.api import create_app
from openphoto.processes import OwnedProcesses, configure_threads
from openphoto.service import Pipeline, enqueue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    source = folder / "source"
    source.mkdir()
    configure_threads()
    for i in range(3):
        Image.new("RGB", (360, 240), (60 + i * 30, 100, 150)).save(source / f"Frame-{i}.jpg")
    Image.new("RGB", (360, 240), (90, 100, 150)).save(folder / "fixture.jpg")
    project = folder / "project"
    app = create_app(project, token="synthetic-fixture", start_worker=False)
    pipeline = Pipeline(project)
    try:
        with TestClient(app, headers={"X-OpenPhoto-Token": "synthetic-fixture"}) as client:
            job = enqueue(pipeline.catalog, "import", {"paths": [str(source)], "shoot_name": "Browser fixture"})
            pipeline.run(job)
            photos = client.get("/api/photos").json()["photos"]
            ids = [p["id"] for p in photos]
            details = {identifier: client.get(f"/api/photos/{identifier}").json() for identifier in ids}
            details[ids[1]]["recipe"]["develop"]["exposure"] = .75
            (folder / "ui-fixture.json").write_text(json.dumps({"ids": ids, "photos": photos, "details": details}), encoding="utf-8")
    finally:
        pipeline.catalog.engine.dispose()
    session_path, session, cleanup, result = folder / "launch-session.json", None, {}, 1
    try:
        with (folder / "server.log").open("w", encoding="utf-8") as log, OwnedProcesses() as owner:
            process = owner.popen([sys.executable, "-m", "openphoto", "--browser", "--no-worker",
                                   "--project", str(project), "--session-file", str(session_path)], stdout=log, stderr=log)
            for _ in range(200):
                if session_path.exists():
                    session = json.loads(session_path.read_text())
                    try:
                        if httpx.get(session["url"] + "/api/status", headers={"X-OpenPhoto-Token": session["token"]}, timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                if process.poll() is not None:
                    raise RuntimeError("Test server exited")
                time.sleep(.1)
            else:
                raise RuntimeError("Test server readiness timeout")
            browser = owner.popen(["node", str(Path(__file__).with_suffix(".cjs")), str(folder)],
                                  env=dict(os.environ), stdout=sys.stdout, stderr=sys.stderr)
            try:
                result = browser.wait(timeout=160)
            finally:
                cleanup["owned_pids"] = [p.pid for p in psutil.Process(process.pid).children(recursive=True)] + [process.pid, browser.pid]
    finally:
        session_path.unlink(missing_ok=True)
        cleanup["remaining_pids"] = [pid for pid in cleanup.get("owned_pids", []) if psutil.pid_exists(pid)]
        if session:
            port = int(session["url"].rsplit(":", 1)[1])
            with socket.socket() as connection:
                cleanup["port_closed"] = connection.connect_ex(("127.0.0.1", port)) != 0
        (folder / "cleanup.json").write_text(json.dumps(cleanup, indent=2))
    assert not cleanup["remaining_pids"] and cleanup.get("port_closed"), cleanup
    return result


if __name__ == "__main__":
    raise SystemExit(main())
