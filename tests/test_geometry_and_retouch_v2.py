import numpy as np

from openphoto.imaging import apply_recipe, geometry, retouch_tiled, skin_masks
from openphoto.schemas import Crop, EditRecipe, Retouch


def test_versioned_geometry_and_mask_canvas():
    y, x = np.mgrid[:180, :240]
    image = np.stack([x / 240, y / 180, (x + y) / 420], axis=-1).astype(np.float32)
    crop = Crop(x=0.12, y=0.2, w=0.6, h=0.7)
    legacy = EditRecipe(version=1, crop=crop, rotation=8)
    modern = legacy.model_copy(update={"version": 2})
    old, _ = apply_recipe(image, legacy)
    new, _ = apply_recipe(image, modern)
    assert np.array_equal(old, geometry(image, crop, 8))
    assert np.array_equal(new, geometry(geometry(image, Crop(), 8), crop))
    assert not np.array_equal(old, new)


def test_tiled_retouch_is_seamless_and_keeps_unmasked_pixels():
    rng = np.random.default_rng(44)
    image = rng.uniform(0.15, 0.3, (260, 330, 3)).astype(np.float32)
    face = np.zeros((260, 330), np.float32)
    face[25:200, 20:170] = 1
    body = np.zeros_like(face)
    body[100:230, 180:300] = 1
    params = Retouch(strength=0.3, color_evenness=0.15, body_strength=0.2, body_color_evenness=0.1)
    tiled, changed = retouch_tiled(image, params, face, body, tile_size=80)
    full, _ = retouch_tiled(image, params, face, body, tile_size=1000)
    assert np.max(np.abs(tiled - full)) < 1e-6
    outside = (face + body) == 0
    assert np.array_equal(tiled[outside], image[outside])
    assert not changed[outside].any()
    off, mask = retouch_tiled(image, Retouch(), face, body)
    assert np.array_equal(off, image) and not mask.any()


def test_body_mask_requires_pose_and_excludes_disabled_face():
    image = np.full((120, 160, 3), 0.3, np.float32)
    data = {"body_skin_mask": np.ones((16, 16)).tolist(), "faces": [{"box": [0.3, 0.2, 0.7, 0.6]}]}
    _, body = skin_masks(image, data)
    assert not body.any()
    data["poses"] = [[{"x": 0.5, "y": 0.5, "visibility": 0.9}]]
    _, body = skin_masks(image, data, disabled=[0])
    assert not body[24:72, 48:112].any() and body[100, 10] > 0
