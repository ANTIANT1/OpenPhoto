import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import import_all
from openphoto import exports
from openphoto.api import create_app
from openphoto.database import Catalog, PhotoAsset, ProcessingJob, Shoot, StyleProfile, dumps, loads
from openphoto.desktop import DesktopBridge
from openphoto.job_lifecycle import recover_exports
from openphoto.projects import backup_project, restore_copy, validate_project
from openphoto.service import enqueue


def test_catalog_pagination_beyond_1000_keeps_ties_and_decisions(workspace):
    client, pipeline, source, _ = workspace
    first = import_all(client, pipeline, source)[0]
    with pipeline.catalog.session() as session:
        root_id = session.get(PhotoAsset, first['id']).root_id
        shoot = Shoot(name='Pagination fixture')
        session.add(shoot)
        session.flush()
        shoot_id = shoot.id
        for index in range(1007):
            session.add(PhotoAsset(id=f'page-{index:04}', shoot_id=shoot_id, root_id=root_id,
                                   relative_path=f'{index}.jpg', name=f'{index}.jpg',
                                   fingerprint=f'fixture-{index}', captured=1, rating=0))
    # All sort values tie: a stable secondary key must prevent omissions or repeats.
    for sort in ('time', 'rating'):
        seen = []
        for offset in range(0, 1007, 250):
            response = client.get('/api/photos', params={
                'shoot_id': shoot_id, 'offset': offset, 'limit': 250, 'sort': sort,
            })
            assert response.status_code == 200
            page = response.json()
            assert page['total'] == 1007
            seen.extend(p['id'] for p in page['photos'])
        assert seen == [f'page-{index:04}' for index in range(1007)]
    response = client.post('/api/decisions', json={'photo_ids':['page-1006'], 'action':'keep'})
    assert response.status_code == 200
    kept = client.get('/api/photos', params={'shoot_id':shoot_id, 'filter':'keep'}).json()
    assert kept['total'] == 1 and kept['photos'][0]['id'] == 'page-1006'


@pytest.mark.parametrize('scope', ['selection', 'group', 'shoot'])
def test_batch_development_for_each_ui_scope_only_transfers_jpeg_exposure(workspace, scope):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    a, b, *others = [p['id'] for p in photos]
    with pipeline.catalog.session() as session:
        for identifier in (a, b):
            session.get(PhotoAsset, identifier).group_id = 'our-group'
    detail = client.get(f'/api/photos/{a}').json()
    recipe = detail['recipe']
    recipe['develop'].update(exposure=.5, temperature=2700, denoise=.9)
    response = client.post('/api/recipes/batch', json={
        'photo_ids':[b] if scope=='selection' else [a], 'source_photo_id':a,
        'scope':scope, 'sections':['develop'], 'recipe':recipe,
    })
    assert response.status_code == 200, response.text
    assert set(response.json()['updated']) == ({b, *others} if scope=='shoot' else {b})
    target = client.get(f'/api/photos/{b}').json()['recipe']['develop']
    assert target['exposure']==.5 and target['temperature'] is None and target['denoise']==0


def test_history_pages_and_compact_events_do_not_ship_recipes(workspace):
    client, pipeline, _, _ = workspace
    with pipeline.catalog.session() as s:
        for i in range(115):
            s.add(ProcessingJob(id=f"done-{i:03}", kind="export", state="completed", payload="{}", created="2026",
                                result=dumps({"snapshots": {"private": {"recipe": "x" * 20000}}, "files": {"one": {"state": "committed"}}})))
        s.add(ProcessingJob(id="active", kind="render", state="paused", payload="{}", created="2000"))
    compact = client.get("/api/jobs?compact=true").json()
    assert compact[0]["id"] == "active"
    assert len(json.dumps(compact)) < 50000
    assert all("snapshots" not in j["result"] and "files" not in j["result"] for j in compact)
    cursor, seen = None, []
    while True:
        page = client.get("/api/jobs/history", params={"limit": 23, **({"cursor": cursor} if cursor else {})}).json()
        seen.extend(j["id"] for j in page["jobs"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 115 and "active" not in seen
    assert "snapshots" in client.get("/api/jobs/done-001").json()["result"]
    assert client.get("/api/jobs/history?cursor=invalid").status_code == 400


def test_export_outputs_only_list_committed_files_and_folder_is_job_bound(workspace, monkeypatch):
    client, pipeline, _, project = workspace
    output = project / "results"
    output.mkdir()
    image = output / "ready.jpg"
    image.write_bytes(b"fixture")
    job = enqueue(pipeline.catalog, "export", {"directory": str(output)})
    with pipeline.catalog.session() as s:
        s.get(ProcessingJob, job).result = dumps({"files": {"ready": {"path": str(image), "state": "committed"},
                                                          "pending": {"path": str(output / "pending.jpg"), "state": "reserved"}}})
    result = client.get(f"/api/jobs/{job}/outputs").json()
    assert result["total"] == 1 and result["files"] == [{"path": str(image), "available": True}]
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path), raising=False)
    if os.name == "nt":
        assert client.post(f"/api/jobs/{job}/open-folder").status_code == 200
        assert opened == [output]
    assert client.post("/api/jobs/unknown/open-folder").status_code == 404


def test_restore_is_independent_and_cannot_clean_original_export(workspace):
    _, pipeline, source, project = workspace
    import_all(workspace[0], pipeline, source)
    output = project / "results"
    output.mkdir()
    job = enqueue(pipeline.catalog, "export", {"directory": str(output), "include_proposed": True})
    with pipeline.catalog.session() as s:
        photo_id = loads(s.get(ProcessingJob, job).payload)["photo_ids"][0]
    backup = backup_project(pipeline.catalog)
    # Reservation appears AFTER the backup, so it is absent from the restored journal.
    record = exports.reserve_bundle(output, "photo", ".jpg", [""], job + "-" + photo_id)
    sentinel = Path(record["staging"]) / "running.tmp"
    sentinel.write_bytes(b"original worker owns this")
    restored = restore_copy(pipeline.catalog, backup.name)
    assert restored != project
    clone = Catalog(restored)
    clone.initialize()
    try:
        recover_exports(clone)
        assert sentinel.read_bytes() == b"original worker owns this"
        with clone.session() as s:
            exports_in_clone = s.query(ProcessingJob).filter_by(kind="export").all()
            assert all(j.id != job and j.state == "paused" for j in exports_in_clone)
    finally:
        clone.engine.dispose()
        exports.cleanup(record)
    assert (project / "catalog.sqlite").exists()
    with pytest.raises(ValueError):
        restore_copy(pipeline.catalog, "../../catalog.sqlite")


def test_project_restore_ignores_historical_receipts_and_rejects_corruption(workspace):
    _, pipeline, _, project = workspace
    directory = project / "output"
    directory.mkdir()
    record = exports.reserve_bundle(directory, "history", ".jpg", [""], "original-owner")
    sentinel = Path(record["staging"]) / "sentinel"
    sentinel.write_text("preserve")
    exports.cleanup({**record, "historical": True}, rollback=True)
    assert sentinel.exists()
    exports.cleanup(record)
    backup = project / "backups" / "bad.sqlite"
    backup.parent.mkdir(exist_ok=True)
    backup.write_bytes(b"not sqlite")
    with pytest.raises(ValueError, match="повреждена"):
        restore_copy(pipeline.catalog, backup.name)
    assert not list(project.parent.glob("*-restored-*.partial"))


def test_library_management_preserves_photos_and_references(workspace):
    client, pipeline, source, project = workspace
    photos = import_all(client, pipeline, source)
    shoot = photos[0]["shoot_id"]
    assert client.patch(f"/api/shoots/{shoot}", json={"name": "Новое имя"}).status_code == 200
    assert client.delete(f"/api/shoots/{shoot}").status_code == 409
    with pipeline.catalog.session() as s:
        s.add(Shoot(id="empty", name="empty"))
        s.add(StyleProfile(id="profile", name="style", data=dumps({"references": []})))
    assert client.delete("/api/shoots/empty").status_code == 200
    assert client.patch("/api/profiles/profile", json={"name": "   "}).status_code == 422
    assert client.patch("/api/profiles/profile", json={"name": "Портрет"}).status_code == 200
    assert client.delete("/api/profiles/profile").status_code == 200
    assert list((project / "backups").glob("*.sqlite"))
    assert len(list(source.glob("*.jpg"))) == len(photos)


def test_bridge_only_restarts_after_validating_project(tmp_path):
    source = tmp_path / "photos"
    source.mkdir()
    (source / "photo.jpg").write_bytes(b"source")
    with pytest.raises(ValueError, match="пустую"):
        validate_project(source, create=True)
    with pytest.raises(ValueError):
        validate_project(source)
    bridge = DesktopBridge()
    destroyed = []
    bridge._window = type("Window", (), {"destroy": lambda self: destroyed.append(True)})()
    target = tmp_path / "new-project"
    assert bridge.open_project(str(target), True) == {"restarting": True}
    assert destroyed == [True] and bridge._next_project == target


def test_startup_backup_api_is_authenticated(tmp_path):
    app = create_app(tmp_path / "project", token="fixture", start_worker=False)
    with TestClient(app) as client:
        assert client.post("/api/project/backups").status_code == 401
        response = client.post("/api/project/backups", headers={"x-openphoto-token": "fixture"})
        assert response.status_code == 200
