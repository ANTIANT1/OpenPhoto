import json
import os
import subprocess
import sys
import time

import psutil
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from openphoto.api import create_app
from openphoto.processes import OwnedProcesses


def until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Process lifecycle deadline exceeded")


def test_worker_starts_on_demand_and_retires(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    Image.new("RGB", (120, 80), (120, 140, 160)).save(source / "one.jpg")
    app = create_app(tmp_path / "project", token="test", start_worker=True)
    app.state.catalog.set_setting("worker_idle_seconds", 0.5)
    with TestClient(app, headers={"x-openphoto-token": "test"}) as client:
        supervisor = app.state.supervisor
        assert supervisor.status()["worker_pid"] is None
        job = client.post("/api/import", json={"paths": [str(source)], "shoot_name": "idle-test"}).json()[
            "job_id"
        ]
        until(
            lambda: any(j["id"] == job and j["state"] == "completed" for j in client.get("/api/jobs").json()),
            40,
        )
        until(lambda: supervisor.status()["worker_pid"] is None)
        assert len(client.get("/api/photos").json()["photos"]) == 1
    assert not supervisor.thread.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object ownership")
def test_crashed_owner_terminates_child_and_grandchild(tmp_path):
    gate = tmp_path / "go"
    pids = tmp_path / "children.json"
    ready = tmp_path / "ready"
    child_code = """import subprocess,sys,time,json
from pathlib import Path
gate,pids=map(Path,sys.argv[1:])
while not gate.exists(): time.sleep(.05)
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
pids.write_text(json.dumps([__import__('os').getpid(),child.pid]))
time.sleep(60)
"""
    child_file = tmp_path / "child.py"
    child_file.write_text(child_code)
    owner_file = tmp_path / "owner.py"
    owner_file.write_text("""import subprocess,sys,time
from pathlib import Path
from openphoto.processes import OwnedProcesses
script,gate,pids,ready=map(Path,sys.argv[1:])
owner=OwnedProcesses()
child=owner.popen([sys.executable,str(script),str(gate),str(pids)])
gate.touch()
ready.write_text(str(__import__('os').getpid()))
time.sleep(60)
""")
    log = (tmp_path / "owner.log").open("w")
    fallback = OwnedProcesses()
    owner = fallback.popen(
        [sys.executable, str(owner_file), str(child_file), str(gate), str(pids), str(ready)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=log,
        stderr=log,
    )
    children = []
    try:

        def launched():
            assert owner.poll() is None, (tmp_path / "owner.log").read_text()
            return ready.exists() and pids.exists()

        until(launched)
        children = json.loads(pids.read_text())
        psutil.Process(int(ready.read_text())).kill()
        owner.wait(timeout=5)
        until(lambda: all(not psutil.pid_exists(pid) for pid in children))
    finally:
        fallback.close()
        owner.wait(timeout=5)
        log.close()
