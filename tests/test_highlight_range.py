from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tifffile

from openphoto import imaging
from openphoto.schemas import Color, EditRecipe


def test_float_tiff_preserves_highlight_detail_above_display_white(tmp_path):
    values = np.linspace(0.1, 4, 240, dtype=np.float32).reshape(10, 24, 1)
    expected = np.repeat(values, 3, axis=2)
    profile = imaging.icc_profile("linear-prophoto")
    path = tmp_path / "scene.tiff"
    tifffile.imwrite(path, expected, photometric="rgb", metadata=None,
                     extratags=[(34675, "B", len(profile), profile, False)])
    actual = imaging.read_rgb(path)
    np.testing.assert_allclose(actual, expected, atol=1e-5)
    recovered = imaging.color_grade(actual, Color(exposure=-2))
    np.testing.assert_allclose(recovered, expected / 4, atol=1e-5)
    assert len(np.unique(recovered)) >= 240


def test_partial_style_scales_exposure_without_clipped_blending():
    values = np.repeat(np.linspace(1, 4, 128, dtype=np.float32)[None, :, None], 3, axis=2)
    result = imaging.color_grade(values, Color(exposure=-2, strength=0.65))
    np.testing.assert_allclose(result, values * 2**-1.3, atol=1e-5)
    assert np.all(np.diff(result[0, :, 0]) > 0)
    assert result.max() > 1  # Clipping belongs to the final display/export encoding.
    np.testing.assert_array_equal(imaging.color_grade(values, Color(exposure=-2, strength=0)), values)


def test_old_recipes_keep_the_original_colour_math():
    pixels = np.repeat(np.linspace(0.01, 1, 60, dtype=np.float32)[None, :, None], 3, axis=2)
    color = Color(exposure=-1.2, contrast=0.2, strength=0.65, protect_skin=False)
    expected = imaging.color_grade(pixels, color, legacy=True)
    for version, pipeline in ((1, "openphoto-float-v1"), (2, "openphoto-float-v2")):
        recipe = EditRecipe(version=version, runtime={"pipeline": pipeline}, color=color)
        actual, _ = imaging.apply_recipe(pixels, recipe)
        np.testing.assert_array_equal(actual, expected)
    current, _ = imaging.apply_recipe(pixels, EditRecipe(color=color))
    assert not np.array_equal(current, expected)


def test_raw_cache_separates_legacy_integer_and_new_float_intermediates(tmp_path, monkeypatch):
    import rawpy

    class Raw:
        sizes = SimpleNamespace(width=32, height=24)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    monkeypatch.setattr(rawpy, "imread", lambda _: Raw())
    executable = tmp_path / "raw-engine.exe"
    executable.touch()
    calls = []

    def run(args, **_):
        if "-v" in args:
            return SimpleNamespace(stdout="RawTherapee 5.13", stderr="", returncode=0)
        calls.append(args)
        profile_text = Path(args[args.index("-p") + 1]).read_text(encoding="utf-8")
        hdr = "-b32" in args
        assert ("ClampOOG=false" in profile_text) == hdr
        assert ("Method=Luminance" in profile_text) == hdr
        pixels = np.full((24, 32, 3), 2.0, np.float32) if hdr else np.full((24, 32, 3), 65535, np.uint16)
        profile = imaging.icc_profile("linear-prophoto")
        tifffile.imwrite(args[args.index("-o") + 1], pixels, photometric="rgb", metadata=None,
                         extratags=[(34675, "B", len(profile), profile, False)])
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    monkeypatch.setattr(imaging.subprocess, "run", run)
    developer = imaging.RawDeveloper(str(executable), tmp_path / "cache")
    current = EditRecipe(runtime=imaging.processing_environment())
    legacy = current.model_copy(update={"runtime": {**current.runtime, "pipeline": "openphoto-float-v2"}})
    source = tmp_path / "photo.arw"
    np.testing.assert_allclose(developer.develop(source, "same-source", legacy), 1, atol=1e-5)
    np.testing.assert_allclose(developer.develop(source, "same-source", current), 2, atol=1e-5)
    developer.develop(source, "same-source", legacy)
    developer.develop(source, "same-source", current)
    assert len(calls) == 2
    assert not list((tmp_path / "cache").glob("*.partial.tif"))
