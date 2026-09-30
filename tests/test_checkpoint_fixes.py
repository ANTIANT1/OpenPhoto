"""Regressions for the owner/lead audit and its independent reproductions."""
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import import_all
from openphoto import exports
from openphoto.api import create_app
from openphoto.cache import protect, reserve, trim
from openphoto.database import AnalysisResult, Catalog, PhotoAsset, ProcessingJob, UserDecision, dumps
from openphoto.job_lifecycle import cleanup_cancelled, job_lock, recover_exports
from openphoto.service import enqueue


def evidence(pipeline, photos, locked=True):
    pipeline.catalog.set_setting("keeper_fraction", .01)
    with pipeline.catalog.session() as s:
        for i, p in enumerate(photos):
            photo = s.get(PhotoAsset, p["id"])
            photo.group_id, photo.group_locked, photo.captured = "burst", locked, i
            photo.score, photo.review = .9 - .2 * i, False
            s.merge(AnalysisResult(photo_id=photo.id, data=dumps({"review": False, "phash": [0] * 64})))


def test_batch_undo_is_one_atomic_operation_and_legacy_undo_works(workspace):
    client, pipeline, source, _ = workspace
    ids = [p["id"] for p in import_all(client, pipeline, source)]
    client.post("/api/decisions", json={"photo_ids": ids[:1], "action": "rating", "value": 4})
    result = client.post("/api/decisions", json={"photo_ids": ids + ids[:1], "action": "keep"})
    assert result.json()["updated"] == len(ids)
    assert set(client.post("/api/decisions/undo").json()["photo_ids"]) == set(ids)
    photos = client.get("/api/photos").json()["photos"]
    assert all(p["status"] == "unreviewed" for p in photos)
    assert next(p for p in photos if p["id"] == ids[0])["rating"] == 4
    with pipeline.catalog.session() as s:
        photo = s.get(PhotoAsset, ids[0])
        photo.rating = 2
        s.add(UserDecision(photo_id=ids[0], action="rating", previous=dumps({"rating": 4})))
    assert client.post("/api/decisions/undo").json()["photo_ids"] == ids[:1]
    assert client.get(f"/api/photos/{ids[0]}").json()["rating"] == 4


def test_batch_decision_invalid_member_rolls_back_every_member(workspace):
    client, pipeline, source, _ = workspace
    identifier = import_all(client, pipeline, source)[0]["id"]
    assert client.post("/api/decisions", json={"photo_ids": [identifier, "missing"], "action": "keep"}).status_code == 404
    assert client.get(f"/api/photos/{identifier}").json()["status"] == "unreviewed"
    assert client.post("/api/decisions/undo").json() == {"undone": False}


def test_review_is_recomputed_without_losing_technical_or_explicit_reasons(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    evidence(pipeline, photos)
    a, b, c, d = [p["id"] for p in photos]
    with pipeline.catalog.session() as s:
        s.get(PhotoAsset, b).score = .875
        s.get(PhotoAsset, c).review_flags = dumps(["crop_transfer"])
        s.get(AnalysisResult, d).data = dumps({"review": True})
    pipeline.group_and_select([b])
    assert client.get(f"/api/photos/{b}").json()["review"]
    with pipeline.catalog.session() as s:
        s.get(PhotoAsset, b).score = .1
    pipeline.group_and_select([b])
    state = {p["id"]: p for p in client.get("/api/photos").json()["photos"]}
    assert not state[a]["review"] and not state[b]["review"]
    assert state[c]["review"] and state[d]["review"]
    pipeline.group_and_select([b])
    assert state == {p["id"]: p for p in client.get("/api/photos").json()["photos"]}


def test_reanalysis_can_split_old_automatic_group_and_is_idempotent(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    evidence(pipeline, photos, locked=False)
    ids = [p["id"] for p in photos]
    pipeline.group_and_select(ids)
    with pipeline.catalog.session() as s:
        s.get(AnalysisResult, ids[2]).data = dumps({"review": False, "phash": [1] * 64})
        s.get(AnalysisResult, ids[3]).data = dumps({"review": False, "phash": [1] * 64})
    pipeline.group_and_select(ids[2:3])
    state = client.get("/api/photos").json()["photos"]
    assert len({p["group_id"] for p in state}) == 2
    assert sum(p["suggested"] for p in state) == 2
    pipeline.group_and_select(ids)
    assert client.get("/api/photos").json()["photos"] == state


def test_merge_split_settings_refresh_and_user_decisions_survive(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    evidence(pipeline, photos)
    ids = [p["id"] for p in photos]
    client.post("/api/decisions", json={"photo_ids": ids[-1:], "action": "keep"})
    assert client.post("/api/groups", json={"photo_ids": ids, "action": "merge"}).status_code == 200
    assert sum(p["suggested"] for p in client.get("/api/photos").json()["photos"]) == 1
    assert client.patch("/api/settings", json={"keeper_fraction": .75}).status_code == 200
    assert sum(p["suggested"] for p in client.get("/api/photos").json()["photos"]) == 3
    client.post("/api/groups", json={"photo_ids": ids, "action": "split"})
    state = client.get("/api/photos").json()["photos"]
    assert all(p["suggested"] and p["review"] for p in state)
    assert next(p for p in state if p["id"] == ids[-1])["status"] == "keep"


def test_paused_partial_analysis_recomputes_completed_changes(workspace, monkeypatch):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    evidence(pipeline, photos)
    ids = [p["id"] for p in photos]
    job = enqueue(pipeline.catalog, "analyze", {"photo_ids": ids})

    def analyze(identifier, payload):
        with pipeline.catalog.session() as s:
            s.get(PhotoAsset, identifier).score = .01
        pipeline.update(job, state="paused")

    monkeypatch.setattr(pipeline, "analyze_photo", analyze)
    pipeline.run(job)
    state = client.get("/api/photos").json()["photos"]
    assert not next(p for p in state if p["id"] == ids[0])["suggested"]
    assert next(p for p in state if p["id"] == ids[1])["suggested"]


def test_reimport_and_empty_folder_do_not_create_empty_shoots(workspace):
    client, pipeline, source, project = workspace
    original = import_all(client, pipeline, source)
    assert import_all(client, pipeline, source) == original
    empty = project / "empty"
    empty.mkdir()
    import_all(client, pipeline, empty)
    shoots = client.get("/api/shoots").json()
    assert len(shoots) == 1 and shoots[0]["count"] == 4


def test_late_raw_promotes_jpeg_card_preserving_edits_and_queued_export(workspace, monkeypatch):
    client, pipeline, _, project = workspace
    folder = project / "pair"
    folder.mkdir()
    Image.new("RGB", (120, 80), (40, 90, 150)).save(folder / "Sony.JPG")
    identifier = import_all(client, pipeline, folder)[0]["id"]
    client.post("/api/decisions", json={"photo_ids": [identifier], "action": "rating", "value": 5})
    before = client.get(f"/api/photos/{identifier}").json()
    before["recipe"]["develop"]["exposure"] = .75
    client.put(f"/api/photos/{identifier}/recipe", json={"recipe": before["recipe"], "expected_revision": 0})
    draft = json.loads(json.dumps(before["recipe"]))
    draft["color"]["warmth"] = .1
    assert client.put(f"/api/photos/{identifier}/draft", json={"recipe": draft, "expected_revision": 1}).status_code == 200
    job = enqueue(pipeline.catalog, "export", {"photo_ids": [identifier], "directory": str(project / "export")}, 0)
    (folder / "Sony.ARW").write_bytes(b"RAW pairing fixture")

    def preview(photo, *args):
        photo.width, photo.height, photo.error = 6000, 4000, None

    monkeypatch.setattr(pipeline, "prepare_preview", preview)
    photos = import_all(client, pipeline, folder)
    assert len(photos) == 1 and photos[0]["id"] == identifier
    assert photos[0]["raw"] and photos[0]["paired"] and photos[0]["rating"] == 5
    after = client.get(f"/api/photos/{identifier}").json()
    assert after["recipe"] == before["recipe"] and after["revision"] == 2
    assert after["draft"] == draft
    assert len(client.get("/api/shoots").json()) == 1
    pipeline.run(job)
    with pipeline.catalog.session() as s:
        assert s.get(ProcessingJob, job).state == "completed"
    image = next((project / "export").glob("*.jpg"))
    assert Image.open(image).size == (120, 80)
    manifest = json.loads(image.with_suffix(".jpg.openphoto.json").read_text(encoding="utf-8"))
    assert manifest["source_name"] == "Sony.JPG" and manifest["revision"] == 1


def test_active_jobs_are_never_hidden_by_history_limit(workspace):
    client, pipeline, _, _ = workspace
    with pipeline.catalog.session() as s:
        for state in ("queued", "running", "paused"):
            s.add(ProcessingJob(id=state, kind="export", payload="{}", state=state, created="2000"))
        for i in range(105):
            s.add(ProcessingJob(id=f"done-{i}", kind="render", payload="{}", state="completed", created="2026"))
    jobs = client.get("/api/jobs").json()
    assert {j["id"] for j in jobs[:3]} == {"queued", "running", "paused"}
    assert len(jobs) == 103


def pending_bundle(pipeline, directory, state="prepared"):
    directory.mkdir(exist_ok=True)
    job = enqueue(pipeline.catalog, "export", {"directory": str(directory), "photo_ids": []})
    record = exports.reserve_bundle(directory, "portrait", ".jpg", ["", ".xmp"], job + "-photo")
    for name in record["names"]:
        (Path(record["staging"]) / name).write_bytes(b"our image")
    if state in {"prepared", "committed"}:
        exports.prepare(record)
    if state == "committed":
        exports.publish(record)
    with pipeline.catalog.session() as s:
        row = s.get(ProcessingJob, job)
        row.state, row.payload = "paused", dumps({"directory": str(directory), "photo_ids": ["photo"]})
        row.result = dumps({"files": {"photo": record}})
    return job, record


@pytest.mark.parametrize("state", ["reserved", "prepared", "committed"])
def test_cancel_paused_export_cleans_own_files_and_preserves_completed_output(workspace, state):
    client, pipeline, _, project = workspace
    directory = project / "exports"
    job, record = pending_bundle(pipeline, directory, state)
    foreign = directory / "foreign.txt"
    foreign.write_text("untouched")
    if state == "prepared":
        first = record["names"][0]
        (Path(record["staging"]) / first).rename(directory / first)
    assert client.post(f"/api/jobs/{job}/cancel").status_code == 200
    expected = {"foreign.txt"} | (set(record["names"]) if state == "committed" else set())
    assert {p.name for p in directory.iterdir()} == expected
    cleanup_cancelled(pipeline.catalog, job)
    assert {p.name for p in directory.iterdir()} == expected


def test_cancel_does_not_delete_files_while_worker_owns_job(workspace):
    client, pipeline, _, project = workspace
    job, record = pending_bundle(pipeline, project / "exports")
    lock = job_lock(pipeline.catalog, job)
    lock.acquire()
    try:
        client.post(f"/api/jobs/{job}/cancel")
        assert Path(record["staging"]).exists()
        cleanup_cancelled(pipeline.catalog, job, locked=True)
        assert not Path(record["staging"]).exists()
    finally:
        lock.release()


def test_startup_cleans_cancelled_export_and_unjournaled_reservation(workspace):
    _, pipeline, _, project = workspace
    directory = project / "exports"
    job, record = pending_bundle(pipeline, directory)
    pipeline.update(job, state="cancelled")
    orphan = exports.reserve_bundle(directory, "orphan", ".jpg", [""], job + "-unrecorded")
    with pipeline.catalog.session() as s:
        s.get(ProcessingJob, job).payload = dumps({"directory": str(directory), "photo_ids": ["photo", "unrecorded"]})
    unknown = exports.reserve_bundle(directory, "foreign", ".jpg", [""], "another-project")
    recover_exports(pipeline.catalog)
    assert not Path(record["marker"]).exists() and not Path(orphan["marker"]).exists()
    assert Path(unknown["marker"]).exists()
    exports.cleanup(unknown)


def test_cache_is_trimmed_between_items_and_on_interruption(workspace, monkeypatch):
    client, pipeline, source, project = workspace
    ids = [p["id"] for p in import_all(client, pipeline, source)]
    pipeline.catalog.set_setting("cache_gb", 1000 / 1024**3)
    pipeline.trim_cache()
    job = enqueue(pipeline.catalog, "render", {"photo_ids": ids})
    calls = []

    def render(identifier, *args):
        assert sum(p.stat().st_size for p in (project / "cache").rglob("*") if p.is_file()) <= 1000
        calls.append(identifier)
        (project / "cache" / (identifier + ".jpg")).write_bytes(b"x" * 700)
        if len(calls) == 3:
            pipeline.update(job, state="paused")
            raise InterruptedError()

    monkeypatch.setattr(pipeline, "render_photo", render)
    pipeline.run(job)
    assert len(calls) == 3
    assert sum(p.stat().st_size for p in (project / "cache").rglob("*") if p.is_file()) <= 1000


def test_cache_reserves_before_decode_and_protects_long_running_nested_writer(tmp_path, monkeypatch):
    from openphoto import cache

    nested = tmp_path / "nested"
    nested.mkdir()
    active = nested / "active.tif"
    old = tmp_path / "old.tif"
    old.write_bytes(b"o" * 300)
    with protect(active):
        active.write_bytes(b"a" * 200)
        marker = next(nested.glob(".lease-*"))
        os.utime(marker, (0, 0))
        reserve(tmp_path, 500, 300)
        assert not old.exists() and active.exists()
        with pytest.raises(RuntimeError, match="Кэш занят"):
            reserve(tmp_path, 500, 400)
    trim(tmp_path, 0)
    assert not active.exists()
    monkeypatch.setattr(cache.shutil, "disk_usage", lambda _: type("Disk", (), {"free": 0})())
    with pytest.raises(RuntimeError, match="недостаточно места"):
        reserve(tmp_path, 500, 300)


def test_migration_backs_up_v2_catalog_before_changes(tmp_path):
    project = tmp_path / "legacy"
    catalog = Catalog(project)
    catalog.initialize()
    catalog.engine.dispose()
    database = project / "catalog.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX ix_decisions_operation_id")
        db.execute("ALTER TABLE decisions DROP COLUMN operation_id")
        db.execute("ALTER TABLE photos DROP COLUMN review_flags")
        db.execute("UPDATE alembic_version SET version_num='0002'")
    app = create_app(project, token="fixture", start_worker=False)
    with TestClient(app):
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0003"
        backup = next((project / "backups").glob("*.sqlite"))
        with sqlite3.connect(backup) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002"
            assert "review_flags" not in {r[1] for r in db.execute("PRAGMA table_info(photos)")}
