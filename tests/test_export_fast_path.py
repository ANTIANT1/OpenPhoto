import json

import numpy as np
import pytest

from conftest import import_all
from openphoto import imaging, service
from openphoto.schemas import Color, Crop, EditRecipe, Retouch


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("color", [Color(), Color(contrast=0.2, protect_skin=False), Color(strength=0)])
def test_fast_export_has_identical_pixels(version, color, monkeypatch):
    source = np.random.default_rng(40).uniform(0.1, 0.7, (60, 80, 3)).astype(np.float32)
    recipe = EditRecipe(version=version, color=color, crop=Crop(x=0.1, y=0.05, w=0.8, h=0.9), rotation=4)
    fast, mask = imaging.apply_recipe(source, recipe, {}, 40)
    monkeypatch.setattr(imaging, "recipe_needs_masks", lambda _: True)
    previous, old_mask = imaging.apply_recipe(source, recipe, {}, 40)
    np.testing.assert_array_equal(fast, previous)
    np.testing.assert_array_equal(mask, old_mask)


def test_local_corrections_still_require_masks():
    assert imaging.recipe_needs_masks(EditRecipe(retouch=Retouch(body_strength=0.2)))
    assert imaging.recipe_needs_masks(EditRecipe(color=Color(contrast=0.2)))


def test_neutral_export_does_not_load_models(workspace, monkeypatch):
    client, pipeline, source, project = workspace
    identifier = import_all(client, pipeline, source)[0]["id"]

    def unexpected(*args, **kwargs):
        raise AssertionError("Neutral export must not run image models")

    monkeypatch.setattr(service, "analyze", unexpected)
    job = client.post(
        "/api/export", json={"photo_ids": [identifier], "directory": str(project / "out")}
    ).json()["job_id"]
    pipeline.run(job)
    result = next(j for j in client.get("/api/jobs").json() if j["id"] == job)
    assert result["state"] == "completed"
    from pathlib import Path

    path = Path(result["result"]["files"][identifier]["path"])
    recipe = json.loads(path.with_suffix(".jpg.openphoto.json").read_text(encoding="utf-8"))
    assert recipe["analysis"]["source"] == "not_required"
