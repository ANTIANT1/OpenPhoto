from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import import_all
from openphoto.api import create_app
from openphoto.database import AnalysisResult, PhotoAsset, ProcessingJob, dumps
from openphoto.service import enqueue
from openphoto import exports


def run_export(client, pipeline, identifier, directory):
    job = client.post("/api/export", json={"photo_ids": [identifier], "directory": str(directory)}).json()[
        "job_id"
    ]
    pipeline.run(job)
    return next(j for j in client.get("/api/jobs").json() if j["id"] == job)


def test_existing_sidecars_reserve_entire_bundle(workspace):
    client, pipeline, source, project = workspace
    photo = import_all(client, pipeline, source)[0]
    output = project / "exports"
    output.mkdir()
    stem = Path(photo["name"]).stem + "_openphoto"
    xmp, recipe = output / (stem + ".jpg.xmp"), output / (stem + "_1.jpg.openphoto.json")
    xmp.write_text("existing rating", encoding="utf-8")
    recipe.write_text("existing recipe", encoding="utf-8")
    job = run_export(client, pipeline, photo["id"], output)
    assert job["state"] == "completed"
    assert (output / (stem + "_2.jpg")).exists()
    assert xmp.read_text() == "existing rating" and recipe.read_text() == "existing recipe"
    assert not list(output.glob(".openphoto-*")) and not list(output.glob(".*reservation"))


def test_failed_export_has_no_final_placeholders(workspace):
    client, pipeline, source, project = workspace
    photo = import_all(client, pipeline, source)[0]
    with pipeline.catalog.session() as session:
        item = session.get(PhotoAsset, photo["id"])
        recipe = pipeline.catalog.recipe(item, session)
        recipe.runtime = {"pipeline": "incompatible"}
        pipeline.catalog.save_recipe(session, item, recipe, item.revision)
    directory = project / "failure"
    assert run_export(client, pipeline, photo["id"], directory)["state"] == "completed_with_errors"
    assert list(directory.iterdir()) == []


def test_export_reservations_and_collision_do_not_overwrite(tmp_path):
    a = exports.reserve_bundle(tmp_path, "photo", ".jpg", ["", ".xmp"], "a")
    b = exports.reserve_bundle(tmp_path, "photo", ".jpg", ["", ".xmp"], "b")
    assert a["path"] != b["path"]
    for name in a["names"]:
        (Path(a["staging"]) / name).write_bytes(b"our export")
    exports.prepare(a)
    foreign = tmp_path / a["names"][1]
    foreign.write_bytes(b"external sidecar")
    with pytest.raises(FileExistsError):
        exports.publish(a)
    exports.cleanup(a, rollback=True)
    exports.cleanup(b, rollback=True)
    assert foreign.read_bytes() == b"external sidecar"
    assert list(tmp_path.iterdir()) == [foreign]


def test_export_resumes_after_partial_publication(tmp_path):
    record = exports.reserve_bundle(tmp_path, "photo", ".jpg", ["", ".xmp"], "resumed")
    for name in record["names"]:
        (Path(record["staging"]) / name).write_bytes(b"complete output")
    exports.prepare(record)
    first = record["names"][0]
    (Path(record["staging"]) / first).rename(tmp_path / first)
    exports.publish(record)
    exports.cleanup(record)
    assert record["state"] == "committed"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(record["names"])


def test_corrupt_import_is_reported_and_repair_retries_one_card(workspace):
    client, pipeline, _, project = workspace
    source = project / "damaged"
    source.mkdir()
    broken = source / "broken.jpg"
    broken.write_bytes(b"broken")
    job = enqueue(pipeline.catalog, "import", {"paths": [str(source)], "shoot_name": "damaged"})
    pipeline.run(job)
    with pipeline.catalog.session() as session:
        assert session.get(ProcessingJob, job).state == "completed_with_errors"
        identifier = session.query(PhotoAsset).one().id
    Image.new("RGB", (120, 200), (40, 100, 160)).save(broken)
    assert client.post(f"/api/jobs/{job}/retry").status_code == 200
    pipeline.run(job)
    photos = client.get("/api/photos").json()["photos"]
    assert len(photos) == 1 and photos[0]["id"] == identifier and photos[0]["error"] is None


def test_late_jpeg_is_attached_to_existing_raw(workspace, monkeypatch):
    client, pipeline, _, project = workspace
    folder = project / "pair"
    folder.mkdir()
    (folder / "Sony.ARW").write_bytes(b"RAW pairing fixture")

    def preview(photo, *args):
        photo.width, photo.height = 6000, 4000

    monkeypatch.setattr(pipeline, "prepare_preview", preview)
    photos = import_all(client, pipeline, folder)
    identifier = photos[0]["id"]
    Image.new("RGB", (120, 80)).save(folder / "Sony.JPG")
    photos = import_all(client, pipeline, folder)
    assert len(photos) == 1 and photos[0]["id"] == identifier and photos[0]["paired"]
    assert client.get(f"/api/photos/{identifier}/image?variant=camera").status_code == 200


def test_partial_group_refresh_replaces_recommendations(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    with pipeline.catalog.session() as session:
        for index, p in enumerate(photos):
            photo = session.get(PhotoAsset, p["id"])
            photo.group_id = "burst"
            photo.group_locked = True
            photo.score = 0.9 - index * 0.1
            photo.review = False
    pipeline.catalog.set_setting("keeper_fraction", 0.01)
    pipeline.group_and_select([p["id"] for p in photos])
    pipeline.group_and_select([photos[-1]["id"]])
    assert sum(p["suggested"] for p in client.get("/api/photos").json()["photos"]) == 1


def test_developed_analysis_updates_catalog_score(workspace):
    client, pipeline, source, _ = workspace
    identifier = import_all(client, pipeline, source)[0]["id"]
    pipeline.analyze_photo(identifier, {})
    recipe = client.get(f"/api/photos/{identifier}").json()["recipe"]
    recipe["develop"]["exposure"] = 3
    job = client.put(
        f"/api/photos/{identifier}/recipe", json={"recipe": recipe, "expected_revision": 0}
    ).json()["job_id"]
    pipeline.run(job)
    photo = client.get(f"/api/photos/{identifier}").json()
    assert photo["score"] == photo["analysis"]["score"]


def test_cross_orientation_crop_is_reviewed_if_area_is_insufficient(workspace):
    client, pipeline, source, _ = workspace
    Image.new("RGB", (200, 300), (80, 90, 130)).save(source / "portrait.jpg")
    photos = import_all(client, pipeline, source)
    portrait = next(p for p in photos if p["name"] == "portrait.jpg")
    landscape = next(p for p in photos if p["width"] > p["height"])
    with pipeline.catalog.session() as session:
        for p in (portrait, landscape):
            session.merge(
                AnalysisResult(
                    photo_id=p["id"], data=dumps({"faces": [{"box": [0.45, 0.45, 0.55, 0.55]}], "poses": []})
                )
            )
    recipe = client.get(f"/api/photos/{landscape['id']}").json()["recipe"]
    recipe["crop"] = {"x": 0.1, "y": 0, "w": 0.8, "h": 1}
    result = client.post(
        "/api/recipes/batch",
        json={
            "photo_ids": [portrait["id"]],
            "source_photo_id": landscape["id"],
            "sections": ["crop"],
            "recipe": recipe,
            "preserve_manual": False,
        },
    ).json()
    assert result["updated"] == [] and portrait["id"] in result["skipped"]
    current = client.get(f"/api/photos/{portrait['id']}").json()
    assert current["recipe"]["crop"] == {"x": 0, "y": 0, "w": 1, "h": 1} and current["review"]


def test_all_cache_variants_are_budgeted_and_preview_regenerated(workspace):
    client, pipeline, source, project = workspace
    identifier = import_all(client, pipeline, source)[0]["id"]
    cache = project / "cache"
    for name in ("render-test.jpg", "base-test.jpg", "mask-test.png"):
        (cache / name).write_bytes(b"x" * 5000)
    pipeline.catalog.set_setting("cache_gb", 100 / 1024**3)
    pipeline.trim_cache()
    assert sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()) <= 100
    assert client.get(f"/api/photos/{identifier}/image").status_code == 200


def test_missing_legacy_bundle_relocates_but_explicit_override_is_retained(tmp_path, monkeypatch):
    from openphoto import api
    from openphoto.analysis import MODEL_FILES

    bundle = tmp_path / "current-install"
    for relative in (
        "tools/vendor/rawtherapee/rawtherapee-cli.exe",
        "tools/vendor/exiftool/exiftool.exe",
        *("models/" + name for name in MODEL_FILES.values()),
    ):
        item = bundle / relative
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(b"fixture")
    monkeypatch.setattr(api, "resource_root", lambda: bundle)
    project = tmp_path / "project"
    app = create_app(project, token="test", start_worker=False)
    with TestClient(app) as client:
        for key in ("rawtherapee", "exiftool", "models_directory"):
            app.state.catalog.set_setting(key, str(tmp_path / "previous-install" / key))
            app.state.catalog.set_setting(key + "_source", None)
    app = create_app(project, token="test", start_worker=False)
    with TestClient(app, headers={"x-openphoto-token": "test"}) as client:
        status = client.get("/api/status").json()
        assert status["raw_ready"] and all(status["models"].values())
        custom = tmp_path / "custom-models"
        custom.mkdir()
        assert client.patch("/api/settings", json={"models_directory": str(custom)}).status_code == 200
    app = create_app(project, token="test", start_worker=False)
    with TestClient(app):
        assert app.state.catalog.settings()["models_directory"] == str(custom)
