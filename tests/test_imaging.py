import numpy as np
import pytest
import tifffile
from pydantic import ValidationError

from openphoto.analysis import composition, crop_is_safe, propose_crops
from openphoto.imaging import (apply_recipe, convert, face_skin_mask, icc_profile,
                               read_rgb, retouch_image, to_srgb, write_image)
from openphoto.schemas import Crop, EditRecipe, Retouch, Stroke


def test_colour_managed_float_roundtrip():
    rgb = np.random.default_rng(2).uniform(.05, .95, (24, 32, 3)).astype(np.float32)
    linear = convert(rgb, icc_profile("srgb"))
    recovered = to_srgb(linear)
    assert np.max(abs(recovered-rgb)) < .001
    assert linear.dtype == np.float32


def test_image_encoding_is_protected_against_concurrent_cache_trim(tmp_path, monkeypatch):
    from PIL import Image
    from openphoto.cache import trim
    from openphoto.imaging import write_preview

    original = Image.Image.save
    def save(image, path, *args, **kwargs):
        original(image, path, *args, **kwargs)
        trim(tmp_path, 0)
        assert __import__('pathlib').Path(path).is_file()
    monkeypatch.setattr(Image.Image, 'save', save)
    target = tmp_path / 'preview.jpg'
    write_preview(Image.new('RGB', (30, 40)), target)
    assert target.is_file()
    assert not list(tmp_path.glob('.lease-*'))
    assert not list(tmp_path.glob('*.tmp'))


def test_tiff_does_not_quantize_to_eight_bits(tmp_path):
    values = np.linspace(.1, .9, 2048, dtype=np.float32)[None, :, None]
    linear = np.tile(values, (2, 1, 3))
    path = tmp_path / "precision.tiff"
    write_image(path, linear, "tiff", "prophoto")
    encoded = tifffile.imread(path)
    assert len(np.unique(encoded)) > 1900
    assert np.max(abs(read_rgb(path)-linear)) < .001


def test_disabled_retouch_exactly_preserves_pixels():
    image = np.random.default_rng(3).random((90, 100, 3), dtype=np.float32)
    result, changed = retouch_image(image, Retouch(), np.ones((90, 100), np.float32))
    np.testing.assert_array_equal(image, result)
    assert changed.max() == 0


def test_retouch_never_changes_outside_mask_or_protected_area():
    image = np.random.default_rng(3).random((100, 120, 3), dtype=np.float32)
    mask = np.zeros((100, 120), np.float32)
    mask[20:80, 30:90] = 1
    params = Retouch(strength=.3, color_evenness=.2, protected=[Stroke(points=[(.5,.5)],radius=.1)])
    result, _ = retouch_image(image, params, mask)
    np.testing.assert_array_equal(result[mask == 0], image[mask == 0])
    np.testing.assert_array_equal(result[48:52, 58:62], image[48:52, 58:62])
    assert np.any(result != image)


def test_no_face_landmarks_no_guessed_retouch_mask():
    mask = face_skin_mask((100, 100, 3), {"skin_mask": np.ones((20,20)).tolist()})
    assert mask.max() == 0


def test_crop_bounds_and_area_safety():
    face = {"box": [.4, .05, .6, .3]}
    assert not crop_is_safe(Crop(x=.1,y=.1,w=.9,h=.9), [face], [])
    assert not crop_is_safe(Crop(x=.1,y=.1,w=.7,h=.7), [], [])
    assert crop_is_safe(Crop(x=.025,y=0,w=.95,h=.95), [face], [])
    with pytest.raises(ValidationError):
        Crop(x=.8,w=.5)


def test_crop_proposals_preserve_detected_face():
    face = {"box": [.60,.1,.8,.45], "gaze_proxy": 0}
    options = propose_crops(6000,4000,[face],[])
    assert len(options) <= 3
    for option in options:
        crop = Crop(**option["crop"])
        if option["auto_eligible"]:
            assert crop.w*crop.h >= .8
            assert crop_is_safe(crop,[face],[])
    assert propose_crops(6000,4000,[],[]) == []


def test_joint_outside_crop_is_protected():
    pose = [{"x":.5,"y":.5,"visibility":0} for _ in range(33)]
    pose[15] = {"x":.02,"y":.6,"visibility":.95}
    assert not crop_is_safe(Crop(x=.05,y=0,w=.95,h=1), [], [pose])


def test_center_composition_is_valid():
    score = composition([.3,.2,.7,.8], [])
    assert score["placement"] == 1


def test_geometry_and_preview_export_match(tmp_path):
    image = np.random.default_rng(5).random((240,320,3),dtype=np.float32)*.5
    recipe = EditRecipe(crop=Crop(x=.05,y=.1,w=.9,h=.8))
    output, _ = apply_recipe(image, recipe)
    assert output.shape == (192,288,3)
    path = tmp_path / "render.tiff"
    write_image(path, output, "tiff", "prophoto")
    np.testing.assert_allclose(output, read_rgb(path), atol=.0003)


def test_invalid_brush_and_nan_rejected():
    with pytest.raises(ValidationError):
        Stroke(points=[(1.2,.5)])
    with pytest.raises(ValidationError):
        EditRecipe(rotation=float('nan'))


def test_raw_thumbnail_without_exif_uses_camera_rotation(tmp_path, monkeypatch):
    import io
    import sys
    from types import SimpleNamespace
    from PIL import Image
    from openphoto.imaging import oriented_preview
    stream = io.BytesIO()
    Image.new("RGB", (80,40), "red").save(stream, format="JPEG")

    class FakeRaw:
        sizes = SimpleNamespace(flip=6)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_thumb(self):
            return SimpleNamespace(format=1, data=stream.getvalue())

    monkeypatch.setitem(sys.modules, "rawpy", SimpleNamespace(imread=lambda _: FakeRaw(), ThumbFormat=SimpleNamespace(JPEG=1)))
    assert oriented_preview(tmp_path / "vertical.ARW").size == (40,80)


def test_aspect_change_is_always_reviewed_and_spots_never_apply_themselves():
    from openphoto.analysis import spot_candidates
    face = {"box": [.4,.2,.6,.5], "gaze_proxy": 0}
    assert not any(o["auto_eligible"] for o in propose_crops(6000,4000,[face],[],ratio=1))
    gray = np.full((200,200), 180, np.uint8)
    gray[99:101,99:101] = 30
    original = gray.copy()
    assert spot_candidates(gray, np.ones(gray.shape))
    np.testing.assert_array_equal(gray, original)
    assert not spot_candidates(gray, np.zeros(gray.shape))
