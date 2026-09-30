import numpy as np
import pytest
from psd_tools import PSDImage
from psd_tools.constants import Resource
from psd_tools.psd.image_resources import ImageResource

from openphoto.imaging import convert, fingerprint, icc_profile, oriented_preview
from openphoto.service import discover


def fixture(path, profile=True):
    psd = PSDImage.new("RGB", (512, 8), depth=16)
    ramp = np.linspace(3000, 60000, 512, dtype=np.uint16)
    data = np.tile(ramp[None, :, None], (8, 1, 3))
    psd._record.image_data.set_data([data[..., i].astype(">u2").tobytes() for i in range(3)], psd._record.header)
    if profile:
        psd.image_resources[Resource.ICC_PROFILE] = ImageResource(
            key=Resource.ICC_PROFILE, data=icc_profile("prophoto"))
    psd.save(path)
    return psd, data


def test_16bit_merged_reference_uses_embedded_profile_and_preserves_file(tmp_path):
    path = tmp_path / "референс.psd"
    _, original = fixture(path)
    before = fingerprint(path)
    result = np.asarray(oriented_preview(path, 512))
    expected = np.uint8(np.clip(convert(original, icc_profile("prophoto"), "srgb"), 0, 1) * 255 + .5)
    np.testing.assert_allclose(result, expected, atol=1)
    assert result.shape == (8, 512, 3)
    assert fingerprint(path) == before
    assert discover([str(path)])[0] == []
    assert len(discover([str(path)], references=True)[0]) == 1


def test_missing_profile_or_composite_is_reported(tmp_path):
    path = tmp_path / "reference.psd"
    psd, _ = fixture(path, profile=False)
    with pytest.raises(ValueError, match="ICC"):
        oriented_preview(path)
    psd.image_resources[Resource.VERSION_INFO].data.has_composite = False
    psd.save(path)
    with pytest.raises(ValueError, match="совместимостью"):
        oriented_preview(path)
