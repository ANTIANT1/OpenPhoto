import hashlib
import json

import numpy as np
import tifffile
from PIL import Image

from conftest import import_all


def test_full_cycle_preserves_originals_and_resumes(workspace):
    client, pipeline, source, project = workspace
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    photos = import_all(client, pipeline, source)
    assert len(photos) == 4
    first = photos[0]["id"]
    job_id = client.post("/api/analyze", json={}).json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/pause").status_code == 200
    pipeline.run(job_id)
    assert client.get(f"/api/photos/{first}").json()["analysis"] is None
    assert client.post(f"/api/jobs/{job_id}/resume").status_code == 200
    pipeline.run(job_id)
    detail = client.get(f"/api/photos/{first}").json()
    assert detail["analysis"]["source"] == "embedded"
    assert detail["analysis"]["models"]["clip"] is False
    assert detail["analysis"]["composition"]["confidence"] == 0
    recipe = detail["recipe"]
    recipe["color"]["warmth"] = 0.025
    recipe["crop"] = {"x": .05, "y": .05, "w": .9, "h": .9}
    result = client.put(f"/api/photos/{first}/recipe", json={"recipe": recipe, "expected_revision": 0})
    assert result.status_code == 200, result.text
    pipeline.run(result.json()["job_id"])
    rendered = project / "cache" / f"render-{first}-1.jpg"
    assert Image.open(rendered).size == (288, 216)
    assert client.post("/api/decisions", json={"photo_ids": [first], "action": "keep"}).status_code == 200
    destination = project / "export"
    job_id = client.post("/api/export", json={"directory": str(destination), "format": "tiff", "profile": "prophoto", "sharpen": 0}).json()["job_id"]
    pipeline.run(job_id)
    tiffs = list(destination.glob("*.tiff"))
    assert len(tiffs) == 1
    with tifffile.TiffFile(tiffs[0]) as tf:
        assert tf.asarray().dtype == np.uint16
        assert tf.asarray().shape == (216, 288, 3)
        assert tf.pages[0].tags[34675].value
    saved = json.loads(tiffs[0].with_suffix(".tiff.openphoto.json").read_text(encoding="utf-8"))
    assert saved["revision"] == 1
    assert tiffs[0].with_suffix(".tiff.xmp").exists()
    # A completed job must not emit a second copy when its checkpoint is replayed.
    pipeline.run(job_id)
    assert len(list(destination.glob("*.tiff"))) == 1
    repeated = client.post("/api/export", json={"directory": str(destination), "format": "tiff"}).json()["job_id"]
    pipeline.run(repeated)
    assert len(list(destination.glob("*.tiff"))) == 2
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}


def test_reimport_and_corrupt_image_are_safe(workspace):
    client, pipeline, source, _ = workspace
    import_all(client, pipeline, source)
    (source / "broken.jpg").write_bytes(b"not a photo")
    photos = import_all(client, pipeline, source)
    assert len(photos) == 5
    assert next(p for p in photos if p["name"] == "broken.jpg")["error"]


def test_stale_render_does_not_replace_manual_revision(workspace):
    client, pipeline, source, project = workspace
    first = import_all(client, pipeline, source)[0]["id"]
    detail = client.get(f"/api/photos/{first}").json()
    old = client.post(f"/api/photos/{first}/render").json()["job_id"]
    recipe = detail["recipe"]
    recipe["color"]["contrast"] = .1
    edited = client.put(f"/api/photos/{first}/recipe", json={"recipe": recipe, "expected_revision": 0}).json()
    pipeline.run(old)
    assert not (project / "cache" / f"render-{first}-0.jpg").exists()
    pipeline.run(edited["job_id"])
    assert (project / "cache" / f"render-{first}-1.jpg").exists()
    conflict = client.put(f"/api/photos/{first}/recipe", json={"recipe": recipe, "expected_revision": 0})
    assert conflict.status_code == 409
    assert client.get(f"/api/photos/{first}").json()["revision"] == 1


def test_decisions_undo_and_unreviewed_not_negative(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    first = photos[0]["id"]
    client.post("/api/decisions", json={"photo_ids": [first], "action": "reject"})
    assert client.get(f"/api/photos/{first}").json()["status"] == "reject"
    client.post("/api/decisions/undo")
    assert client.get(f"/api/photos/{first}").json()["status"] == "unreviewed"
    job = client.post("/api/ranker/train").json()["job_id"]
    pipeline.run(job)
    status = client.get("/api/status").json()["settings"]["ranker_status"]
    assert status["comparisons"] == 0
    assert status["promoted"] is False


def test_relink_verifies_content(workspace, tmp_path):
    client, pipeline, source, _ = workspace
    import_all(client, pipeline, source)
    root = client.get("/api/roots").json()[0]
    new = tmp_path / "Moved"
    source.rename(new)
    assert client.post(f"/api/roots/{root['id']}/relink", json={"path": str(new)}).status_code == 200
    wrong = tmp_path / "Wrong"
    wrong.mkdir()
    assert client.post(f"/api/roots/{root['id']}/relink", json={"path": str(wrong)}).status_code == 400
    assert client.get("/api/roots").json()[0]["path"] == str(new)


def test_batch_preserves_manual_and_local_masks(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    first, second = photos[:2]
    detail = client.get(f"/api/photos/{first['id']}").json()
    recipe = detail["recipe"]
    recipe["color"]["warmth"] = .05
    recipe["retouch"]["healing"] = [{"x": .5, "y": .5, "radius": .01}]
    client.put(f"/api/photos/{first['id']}/recipe", json={"recipe": recipe, "expected_revision": 0})
    result = client.post("/api/recipes/batch", json={"photo_ids": [first["id"], second["id"]], "recipe": recipe, "sections": ["color", "retouch"]})
    assert result.status_code == 200, result.text
    assert first["id"] in result.json()["skipped"]
    updated = client.get(f"/api/photos/{second['id']}").json()["recipe"]
    assert updated["color"]["warmth"] == .05
    assert updated["retouch"]["healing"] == []


def test_style_profile_and_color_proposal(workspace):
    client, pipeline, source, _ = workspace
    photo = import_all(client, pipeline, source)[0]
    job = client.post("/api/profiles", json={"name": "Reference", "paths": [str(source)]}).json()["job_id"]
    pipeline.run(job)
    profile = client.get("/api/profiles").json()[0]
    assert len(profile["references"]) == 4
    job = client.post("/api/style/propose", json={"photo_ids": [photo["id"]], "profile_id": profile["id"]}).json()["job_id"]
    pipeline.run(job)
    result = client.get(f"/api/photos/{photo['id']}").json()
    assert result["revision"] == 0  # A suggestion is not a manual edit.
    assert "style_proposal" in result["analysis"]


def test_no_export_of_unreviewed_by_default(workspace):
    client, pipeline, source, project = workspace
    import_all(client, pipeline, source)
    job = client.post("/api/export", json={"directory": str(project / "out")}).json()["job_id"]
    pipeline.run(job)
    assert not list((project / "out").glob("*.jpg"))


def test_restored_recipe_creates_new_revision(workspace):
    client, pipeline, source, _ = workspace
    photo = import_all(client, pipeline, source)[0]
    detail = client.get(f"/api/photos/{photo['id']}").json()
    detail["recipe"]["color"]["contrast"] = .1
    client.put(f"/api/photos/{photo['id']}/recipe", json={"recipe": detail["recipe"], "expected_revision": 0})
    response = client.post(f"/api/photos/{photo['id']}/restore/0")
    assert response.json()["revision"] == 2
    restored = client.get(f"/api/photos/{photo['id']}").json()
    assert restored["recipe"]["color"]["contrast"] == 0
    assert len(restored["history"]) == 3
