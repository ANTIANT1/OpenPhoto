"""Read Photoshop's saved merged image, without reinterpreting its layers."""
from pathlib import Path

import numpy as np
from PIL import Image


def psd_preview(path: Path, edge=2048):
    from psd_tools import PSDImage
    import gc

    # Reference decoding runs one file at a time. Bound both compressed input
    # and psd-tools' decompression/allocation budget before creating arrays.
    if path.stat().st_size > 1024**3:
        raise ValueError("PSD больше 1 ГБ: сохраните сведённый TIFF для референса.")
    psd = PSDImage.open(path, max_alloc_bytes=1536 * 1024**2)
    try:
        return _merged_preview(psd, edge)
    finally:
        # PSDImage and its layer tree hold cycles containing large compressed
        # buffers. Release them at each file boundary, not at an arbitrary GC.
        del psd
        gc.collect()


def _merged_preview(psd, edge):
    from psd_tools.constants import ColorMode, Resource
    from psd_tools.api.utils import has_transparency, get_transparency_index
    from .imaging import convert, icc_profile, resize

    if psd.width * psd.height > 60_000_000 or psd.channels > 4:
        raise ValueError("PSD слишком велик: сохраните уменьшенный сведённый TIFF для референса.")
    if psd.color_mode != ColorMode.RGB or psd.depth not in (8, 16):
        raise ValueError("Для референса нужен RGB PSD 8/16 бит или сведённый TIFF с ICC-профилем.")
    if not psd.has_preview():
        raise ValueError("В PSD нет сведённого изображения. Сохраните его с максимальной совместимостью Photoshop.")
    profile = psd.image_resources.get_data(Resource.ICC_PROFILE)
    if not profile:
        raise ValueError("В PSD нет ICC-профиля. Сохраните референс со встроенным цветовым профилем.")
    # numpy uses the saved merged data and keeps the native 16-bit precision.
    data = psd.numpy()
    if data is None or data.ndim != 3 or data.shape[2] < 3 or not np.isfinite(data).all():
        raise ValueError("Сведённое изображение PSD повреждено.")
    data = resize(data, edge)
    linear = convert(data[..., :3], profile)
    if has_transparency(psd):
        # Reference statistics need a defined background for transparent pixels.
        alpha = np.clip(data[..., get_transparency_index(psd), None], 0, 1)
        linear = linear * alpha + (1 - alpha)
    srgb = convert(linear, icc_profile("linear-prophoto"), "srgb")
    return Image.fromarray(np.uint8(np.clip(srgb, 0, 1) * 255 + 0.5))
