"""Float32, colour-managed rendering shared by previews and final exports.

Version 1 retains crop-then-rotation after local edits. Version 2 coordinates
refer to the oriented, lens-corrected and rotated canvas before final cropping.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tempfile
import importlib.metadata
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path

import cv2
import imagecodecs
import numpy as np
import tifffile
from PIL import Image, ImageOps

from .schemas import Color, Crop, EditRecipe, Retouch

RAW_EXTENSIONS = {".arw", ".dng", ".nef", ".cr2", ".cr3", ".raf", ".rw2", ".orf", ".pef"}
IMAGE_EXTENSIONS = RAW_EXTENSIONS | {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
PIPELINE_VERSION = "openphoto-float-v3"


def extended_range(recipe: EditRecipe):
    """Old recipes retain integer RAW intermediates and their original colour math."""
    return recipe.version == 2 and recipe.runtime.get("pipeline", PIPELINE_VERSION) == PIPELINE_VERSION


@lru_cache
def processing_environment(version=2):
    versions = {
        name: importlib.metadata.version(name)
        for name in ("numpy", "scipy", "imagecodecs", "opencv-contrib-python", "rawpy")
    }
    try:
        versions["mediapipe"] = importlib.metadata.version("mediapipe")
    except importlib.metadata.PackageNotFoundError:
        versions["mediapipe"] = "unavailable"
    versions["pipeline"] = "openphoto-float-v1" if version == 1 else PIPELINE_VERSION
    versions["icc"] = hashlib.sha256(
        b"".join(icc_profile(p) for p in ("srgb", "prophoto", "linear-prophoto"))
    ).hexdigest()
    versions["models"] = hashlib.sha256(
        (Path(__file__).parent / "resources/models.lock.json").read_bytes()
    ).hexdigest()
    return versions


@lru_cache
def icc_profile(name="srgb") -> bytes:
    fixed = Path(__file__).parent / "resources" / "icc" / f"{name}.icc"
    if fixed.is_file():
        return fixed.read_bytes()
    if name == "srgb":
        return imagecodecs.cms_profile("srgb")
    return imagecodecs.cms_profile(
        "rgb",
        whitepoint=(0.3457, 0.3585),
        primaries=(0.7347, 0.2653, 0.1596, 0.8404, 0.0366, 0.0001),
        gamma=1 if name == "linear-prophoto" else 1.8,
    )


def convert(array, source: bytes, target="linear-prophoto"):
    return imagecodecs.cms_transform(
        np.ascontiguousarray(array),
        source,
        icc_profile(target),
        colorspace="RGB",
        outcolorspace="RGB",
        outdtype="float32",
        intent=1,
    )


def to_srgb(array):
    return np.clip(convert(array, icc_profile("linear-prophoto"), "srgb"), 0, 1)


def fingerprint(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resize(array, long_edge=2048):
    h, w = array.shape[:2]
    if not long_edge or max(w, h) <= long_edge:
        return array
    scale = long_edge / max(w, h)
    return cv2.resize(
        array, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA
    )


def oriented_preview(path: Path, edge=2048):
    if path.suffix.lower() == ".psd":
        from .references import psd_preview

        return psd_preview(path, edge)
    if path.suffix.lower() in RAW_EXTENSIONS:
        import rawpy

        with rawpy.imread(str(path)) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    with Image.open(io.BytesIO(thumb.data)) as im:
                        orientation = im.getexif().get(274)
                        image = ImageOps.exif_transpose(im).convert("RGB")
                        if orientation is None:
                            image = _raw_orientation(image, raw.sizes.flip)
                else:
                    image = Image.fromarray(thumb.data)
                    image = _raw_orientation(image, raw.sizes.flip)
            except rawpy.LibRawNoThumbnailError:
                image = Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))
        image.thumbnail((edge, edge))
        return image
    with Image.open(path) as original:
        source_profile = original.info.get("icc_profile")
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((edge, edge))
        if source_profile:
            array = convert(np.asarray(image), source_profile, "srgb")
            image = Image.fromarray(np.uint8(np.clip(array, 0, 1) * 255 + 0.5))
        return image


def _raw_orientation(image, flip):
    return (
        image.transpose(
            {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90, 6: Image.Transpose.ROTATE_270}[flip]
        )
        if flip in (3, 5, 6)
        else image
    )


def read_rgb(path: Path):
    """Read developed RGB at its native precision; never route a TIFF through 8-bit PIL."""
    if path.suffix.lower() in {".tif", ".tiff"}:
        with tifffile.TiffFile(path) as tf:
            data = tf.asarray()
            page = tf.pages[0]
            tag = page.tags.get(34675)
            profile = tag.value if tag else icc_profile("srgb")
            orientation = page.tags.get(274)
            orientation = int(orientation.value) if orientation else 1
        if data.ndim == 2:
            data = np.repeat(data[..., None], 3, axis=-1)
        data = data[..., :3]
        data = orient_array(data, orientation)
        return convert(data, profile)
    with Image.open(path) as original:
        profile = original.info.get("icc_profile", icc_profile("srgb"))
        image = ImageOps.exif_transpose(original).convert("RGB")
        return convert(np.asarray(image), profile)


def orient_array(a, orientation):
    transforms = {
        2: lambda x: x[:, ::-1],
        3: lambda x: x[::-1, ::-1],
        4: lambda x: x[::-1],
        5: lambda x: np.swapaxes(x, 0, 1),
        6: lambda x: np.rot90(x, -1),
        7: lambda x: np.swapaxes(x, 0, 1)[::-1, ::-1],
        8: lambda x: np.rot90(x, 1),
    }
    return np.ascontiguousarray(transforms.get(orientation, lambda x: x)(a))


def color_grade(linear, color: Color, skin=None, *, legacy=False):
    if color == Color() or color.strength == 0:
        return linear.copy()
    if not legacy:
        # Interpolate parameters, not an already-clipped image with the original.
        # Blending with an over-white original prevents even negative exposure
        # from recovering highlights at partial style strength.
        color = color.model_copy(update={
            **{name: getattr(color, name) * color.strength for name in (
                "exposure", "contrast", "warmth", "tint", "shadows", "highlights",
                "black_point", "shadow_hue", "highlight_hue",
            )},
            "saturation": 1 + (color.saturation - 1) * color.strength,
            "strength": 1.0,
        })
    # Exposure is physical in linear light; artistic controls retain the wide working gamut.
    rgb = convert(linear * (2**color.exposure), icc_profile("linear-prophoto"), "prophoto")
    luma = rgb @ np.array([0.288, 0.712, 0.0001], dtype=np.float32)
    rgb = luma[..., None] + (rgb - luma[..., None]) * color.saturation
    rgb = (rgb - 0.5) * (1 + color.contrast) + 0.5
    dark = (1 - np.clip(luma, 0, 1)) ** 2
    bright = np.clip(luma, 0, 1) ** 2
    rgb += (color.shadows * dark + color.highlights * bright + color.black_point * dark)[..., None]
    shift = np.empty_like(rgb)
    shift[..., 0] = color.warmth + color.shadow_hue * dark + color.highlight_hue * bright
    shift[..., 1] = color.tint
    shift[..., 2] = -color.warmth - color.shadow_hue * dark - color.highlight_hue * bright
    if skin is not None and color.protect_skin:
        shift *= 1 - 0.75 * skin[..., None]
    rgb += shift
    encoded = np.clip(rgb, 0, 1) if legacy else np.maximum(rgb, 0)
    graded = convert(encoded.astype(np.float32), icc_profile("prophoto"))
    return np.asarray(linear * (1 - color.strength) + graded * color.strength, np.float32)


def brush_mask(shape, strokes):
    h, w = shape[:2]
    mask = np.zeros((h, w), np.float32)
    for stroke in strokes:
        radius = max(1, round(stroke.radius * min(h, w)))
        points = [(round(x * (w - 1)), round(y * (h - 1))) for x, y in stroke.points]
        for point in points:
            cv2.circle(mask, point, radius, 1, -1)
        for start, end in zip(points, points[1:]):
            cv2.line(mask, start, end, 1, radius * 2)
    return mask


def face_skin_mask(shape, analysis, disabled=()):
    h, w = shape[:2]
    mask = np.zeros((h, w), np.float32)
    segmentation = analysis.get("skin_mask")
    if segmentation:
        small = np.asarray(segmentation, np.float32)
        mask = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        mask = np.clip((mask - 0.7) / 0.3, 0, 1)
    # Require actual face landmarks. An absent model must not activate a guessed skin retouch.
    face_union = np.zeros_like(mask)
    for index, face in enumerate(analysis.get("faces", [])):
        if index in disabled:
            continue
        polygon = face.get("oval", [])
        if not polygon:
            continue
        current = np.zeros_like(mask)
        points = np.int32([(x * (w - 1), y * (h - 1)) for x, y in polygon])
        cv2.fillPoly(current, [points], 1)
        for zone in face.get("protected", []):
            points = np.int32([(x * (w - 1), y * (h - 1)) for x, y in zone])
            cv2.fillPoly(current, [cv2.convexHull(points)], 0)
        margin = max(3, int(min(h, w) * 0.006))
        current = cv2.erode(current, np.ones((margin, margin), np.uint8))
        face_union = np.maximum(face_union, current)
    mask = mask * face_union if segmentation else face_union
    # Suppress strong boundaries instead of smoothing eyelashes, jewellery, hair or makeup edges.
    return np.clip(mask, 0, 1)


def retouch_image(linear, params: Retouch, mask):
    if not params.strength and not params.color_evenness and not params.healing:
        return linear.copy(), np.zeros(linear.shape[:2], np.float32)
    result = linear.copy()
    h, w = linear.shape[:2]
    protection = brush_mask(linear.shape, params.protected)
    valid = np.asarray(mask, np.float32) * (1 - protection)
    luma = linear.mean(axis=2)
    gradient = cv2.magnitude(cv2.Sobel(luma, cv2.CV_32F, 1, 0), cv2.Sobel(luma, cv2.CV_32F, 0, 1))
    valid *= np.clip(1 - gradient / 0.15, 0, 1)
    # Gaussian low frequencies retain original residual texture exactly.
    if valid.max() > 0 and (params.strength or params.color_evenness):
        scale = min(h, w)
        low = cv2.GaussianBlur(linear, (0, 0), max(1.0, scale * 0.006))
        broad = cv2.GaussianBlur(low, (0, 0), max(2.0, scale * 0.022))
        difference = broad - low
        luminance = difference @ np.array([0.288, 0.712, 0], np.float32)
        correction = params.strength * luminance[..., None]
        correction = correction + params.color_evenness * (difference - luminance[..., None])
        alpha = cv2.GaussianBlur(valid, (0, 0), max(0.5, scale * 0.0015)) * valid
        result += correction * alpha[..., None]
    changed = valid.copy() if params.strength or params.color_evenness else np.zeros_like(valid)
    for spot in params.healing:
        cx, cy = round(spot.x * (w - 1)), round(spot.y * (h - 1))
        r = max(2, round(spot.radius * min(w, h)))
        if cx - r < 0 or cy - r < 0 or cx + r >= w or cy + r >= h:
            continue
        target = result[cy - r : cy + r + 1, cx - r : cx + r + 1]
        choices = []
        if spot.source_x is not None and spot.source_y is not None:
            choices = [(round(spot.source_x * (w - 1)), round(spot.source_y * (h - 1)))]
        else:
            choices = [
                (cx + dx * r * 3, cy + dy * r * 3)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))
            ]
        patches = []
        for sx, sy in choices:
            if sx - r < 0 or sy - r < 0 or sx + r >= w or sy + r >= h:
                continue
            if spot.source_x is None and mask[sy - r : sy + r + 1, sx - r : sx + r + 1].mean() < 0.8:
                continue
            patch = linear[sy - r : sy + r + 1, sx - r : sx + r + 1]
            distance = float(np.mean((patch.mean((0, 1)) - target.mean((0, 1))) ** 2))
            patches.append((distance, patch))
        if not patches:
            continue
        source = min(patches, key=lambda item: item[0])[1]
        adjusted = source + target.mean((0, 1)) - source.mean((0, 1))
        yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
        alpha = np.clip(1 - (xx * xx + yy * yy) / (r * r), 0, 1).astype(np.float32)
        alpha *= 1 - protection[cy - r : cy + r + 1, cx - r : cx + r + 1]
        target[:] = target * (1 - alpha[..., None]) + adjusted * alpha[..., None]
        changed[cy - r : cy + r + 1, cx - r : cx + r + 1] = np.maximum(
            changed[cy - r : cy + r + 1, cx - r : cx + r + 1], alpha
        )
    return result, changed


def geometry(array, crop: Crop, rotation=0, version=1):
    if version == 2 and rotation:
        array = geometry(array, Crop(), rotation, version=1)
        rotation = 0
    h, w = array.shape[:2]
    # Crop is defined before rotation. Rotate within the cropped frame and inscribe to remove black corners.
    left, top = round(crop.x * w), round(crop.y * h)
    right, bottom = min(w, round((crop.x + crop.w) * w)), min(h, round((crop.y + crop.h) * h))
    result = array[top : max(top + 1, bottom), left : max(left + 1, right)]
    if rotation:
        h, w = result.shape[:2]
        angle = abs(np.deg2rad(rotation))
        scale = max((w * np.cos(angle) + h * np.sin(angle)) / w, (h * np.cos(angle) + w * np.sin(angle)) / h)
        matrix = cv2.getRotationMatrix2D(((w - 1) / 2, (h - 1) / 2), rotation, scale)
        result = cv2.warpAffine(
            result, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101
        )
    return result


def recipe_needs_masks(recipe: EditRecipe):
    retouch = recipe.retouch
    local = any(
        (
            retouch.strength,
            retouch.color_evenness,
            retouch.body_strength,
            retouch.body_color_evenness,
            retouch.healing,
        )
    )
    protected_color = recipe.color.protect_skin and recipe.color != Color() and recipe.color.strength > 0
    return bool(local or protected_color)


def apply_recipe(linear, recipe: EditRecipe, analysis=None, long_edge=0):
    analysis = analysis or {}
    if not recipe_needs_masks(recipe):
        # Identity local processing cannot affect pixels. Avoid full-resolution skin
        # masks and model work when there is no correction that consumes them.
        canvas = geometry_canvas(linear, recipe)
        result = color_grade(canvas, recipe.color, legacy=not extended_range(recipe))
        result = geometry(result, recipe.crop, recipe.rotation if recipe.version == 1 else 0)
        return resize(result, long_edge), np.zeros(canvas.shape[:2], np.float32)
    if recipe.version == 2:
        linear = geometry_canvas(linear, recipe)
        mask, body = skin_masks(linear, analysis, recipe.retouch.disabled_faces)
        result = color_grade(linear, recipe.color, np.maximum(mask, body), legacy=not extended_range(recipe))
        result, changed = retouch_tiled(result, recipe.retouch, mask, body)
        return resize(geometry(result, recipe.crop), long_edge), changed
    mask = face_skin_mask(linear.shape, analysis, recipe.retouch.disabled_faces)
    result = color_grade(linear, recipe.color, mask, legacy=True)
    result, changed = retouch_image(result, recipe.retouch, mask)
    result = resize(geometry(result, recipe.crop, recipe.rotation), long_edge)
    return result, changed


def geometry_canvas(linear, recipe):
    return geometry(linear, Crop(), recipe.rotation) if recipe.version == 2 and recipe.rotation else linear


def skin_masks(linear, analysis, disabled=()):
    face = face_skin_mask(linear.shape, analysis, disabled)
    body = np.zeros(linear.shape[:2], np.float32)
    values = analysis.get("body_skin_mask")
    if values is not None and analysis.get("poses"):
        probability = cv2.resize(np.asarray(values, np.float32), (linear.shape[1], linear.shape[0]))
        body = np.clip((probability - 0.8) / 0.2, 0, 1)
        # Exclude every face, including disabled faces, from the body pass.
        for item in analysis.get("faces", []):
            x1, y1, x2, y2 = item["box"]
            h, w = body.shape
            body[
                max(0, int(y1 * h)) : min(h, int(np.ceil(y2 * h))),
                max(0, int(x1 * w)) : min(w, int(np.ceil(x2 * w))),
            ] = 0
    # Refine on the actual canvas. Intersect with the original support to prevent mask expansion.
    guide = np.asarray(linear @ np.array([0.288, 0.712, 0], np.float32), np.float32)
    radius = max(2, round(min(guide.shape) * 0.002))
    for mask in (face, body):
        if mask.max() > 0:
            refined = cv2.ximgproc.guidedFilter(guide, mask, radius, 0.0004)
            mask *= np.clip(refined, 0, 1)
    return face, body


def retouch_tiled(linear, params, face, body, tile_size=768):
    """Same finite-support filters on overlapping tiles; full-image scale never changes."""
    if not any(
        (
            params.strength,
            params.color_evenness,
            params.body_strength,
            params.body_color_evenness,
            params.healing,
        )
    ):
        return linear.copy(), np.zeros(linear.shape[:2], np.float32)
    h, w = linear.shape[:2]
    scale = min(h, w)
    radius_low = max(1, int(np.ceil(4 * max(1.0, scale * 0.006))))
    radius_broad = max(1, int(np.ceil(4 * max(2.0, scale * 0.022))))
    radius_alpha = max(1, int(np.ceil(4 * max(0.5, scale * 0.0015))))
    halo = radius_low + radius_broad + radius_alpha + 2
    protection = brush_mask(linear.shape, params.protected)
    face = face * (1 - protection)
    body = body * (1 - protection)
    result = linear.copy()
    changed = np.zeros((h, w), np.float32)
    for top in range(0, h, tile_size):
        for left in range(0, w, tile_size):
            bottom, right = min(h, top + tile_size), min(w, left + tile_size)
            face_active = (params.strength or params.color_evenness) and np.any(face[top:bottom, left:right])
            body_active = (params.body_strength or params.body_color_evenness) and np.any(
                body[top:bottom, left:right]
            )
            if not face_active and not body_active:
                continue
            y1, y2, x1, x2 = (
                max(0, top - halo),
                min(h, bottom + halo),
                max(0, left - halo),
                min(w, right + halo),
            )
            part = linear[y1:y2, x1:x2]
            gray = part.mean(axis=2)
            gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
            boundary = np.clip(1 - gradient / 0.15, 0, 1)
            low = cv2.GaussianBlur(part, (2 * radius_low + 1,) * 2, max(1.0, scale * 0.006))
            broad = cv2.GaussianBlur(low, (2 * radius_broad + 1,) * 2, max(2.0, scale * 0.022))
            difference = broad - low
            luminance = difference @ np.array([0.288, 0.712, 0], np.float32)
            correction = np.zeros_like(part)
            affected = np.zeros(part.shape[:2], np.float32)
            for mask, strength, color in (
                (face, params.strength, params.color_evenness),
                (body, params.body_strength, params.body_color_evenness),
            ):
                if not strength and not color:
                    continue
                valid = mask[y1:y2, x1:x2] * boundary
                alpha = cv2.GaussianBlur(valid, (2 * radius_alpha + 1,) * 2, max(0.5, scale * 0.0015)) * valid
                correction += (
                    strength * luminance[..., None] + color * (difference - luminance[..., None])
                ) * alpha[..., None]
                affected = np.maximum(affected, alpha)
            ys, xs = slice(top - y1, bottom - y1), slice(left - x1, right - x1)
            result[top:bottom, left:right] += correction[ys, xs]
            changed[top:bottom, left:right] = affected[ys, xs]
    if params.healing:
        points = params.model_copy(update={"strength": 0, "color_evenness": 0})
        result, healed = retouch_image(result, points, np.maximum(face, body))
        changed = np.maximum(changed, healed)
    return result, changed


def write_image(path: Path, linear, format="jpeg", profile="srgb", quality=95, sharpen=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = linear
    if sharpen:
        blurred = cv2.GaussianBlur(linear, (0, 0), 0.7)
        rendered = linear + sharpen * (linear - blurred)
    output_profile = icc_profile("srgb" if format == "jpeg" else profile)
    output = imagecodecs.cms_transform(
        np.ascontiguousarray(rendered, dtype=np.float32),
        icc_profile("linear-prophoto"),
        output_profile,
        colorspace="RGB",
        outdtype="float32",
        outcolorspace="RGB",
        intent=1,
    )
    with image_temporary(path) as temporary:
        if format == "jpeg":
            Image.fromarray(np.uint8(np.clip(output, 0, 1) * 255 + 0.5)).save(
                temporary, format="JPEG", quality=quality, subsampling=0, icc_profile=output_profile
            )
        else:
            tifffile.imwrite(
                temporary,
                np.uint16(np.clip(output, 0, 1) * 65535 + 0.5),
                photometric="rgb",
                metadata=None,
                compression="deflate",
                extratags=[(34675, "B", len(output_profile), output_profile, False)],
            )


@contextmanager
def image_temporary(path):
    from .cache import protect

    handle, temporary = tempfile.mkstemp(prefix=".openphoto-", suffix=".tmp", dir=path.parent)
    os.close(handle)
    try:
        with protect(Path(temporary), path):
            yield temporary
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_preview(image, path, quality=94):
    with image_temporary(path) as temporary:
        image.save(temporary, format="JPEG", quality=quality, icc_profile=icc_profile("srgb"))


def cache_key(fingerprint_value, recipe, suffix=""):
    data = f"{PIPELINE_VERSION}:{fingerprint_value}:{recipe.model_dump_json()}:{suffix}"
    return hashlib.sha256(data.encode()).hexdigest()


class RawDeveloper:
    def __init__(self, executable: str | None, cache: Path, cache_budget=20 * 1024**3):
        self.executable = executable
        self.cache = cache
        self.cache_budget = cache_budget
        cache.mkdir(parents=True, exist_ok=True)
        self.environment = dict(
            os.environ,
            RT_SETTINGS=str((cache / "rt-settings").resolve()),
            RT_CACHE=str((cache / "rt-cache").resolve()),
            OMP_NUM_THREADS=str(min(4, max(1, int(os.environ.get("OMP_NUM_THREADS", "4"))))),
        )

    def develop(self, path: Path, fingerprint_value: str, recipe: EditRecipe, edge=0):
        expected = processing_environment(recipe.version)
        if recipe.runtime.get("pipeline") == "openphoto-float-v2" and recipe.version == 2:
            expected = {**expected, "pipeline": "openphoto-float-v2"}
        if recipe.runtime and recipe.runtime != expected:
            raise RuntimeError(
                "Рецепт закреплён за другой версией обработки. Восстановите прежнюю сборку или явно создайте новую версию рецепта."
            )
        if path.suffix.lower() not in RAW_EXTENSIONS:
            image = read_rgb(path)
            image *= 2**recipe.develop.exposure
            if recipe.develop.temperature is not None:
                warmth = np.clip((recipe.develop.temperature - 6500) / 20000, -0.2, 0.2)
                image = color_grade(image, Color(warmth=float(warmth)), legacy=not extended_range(recipe))
            return resize(image, edge)
        if not self.executable or not Path(self.executable).is_file():
            raise RuntimeError("Для проявки ARW нужен RawTherapee CLI 5.13. Укажите путь в настройках.")
        process = subprocess.run(
            [self.executable, "-v"],
            capture_output=True,
            text=True,
            timeout=20,
            env=self.environment,
            cwd=Path(self.executable).parent,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if "5.13" not in process.stdout + process.stderr:
            raise RuntimeError("Этот рецепт требует RawTherapee 5.13; смена версии должна быть явной.")
        develop_json = json.dumps(recipe.develop.model_dump(), sort_keys=True)
        profile_hash = hashlib.sha256(icc_profile("linear-prophoto")).hexdigest()
        hdr = extended_range(recipe)
        raw_pipeline = PIPELINE_VERSION if hdr else "openphoto-float-v2"
        key = hashlib.sha256(
            f"{raw_pipeline}:{fingerprint_value}:{develop_json}:5.13:{edge}:{profile_hash}".encode()
        ).hexdigest()
        target = self.cache / f"raw-{key}.tiff"
        from .cache import protect, reserve, trim

        temp_target = target.with_name(target.stem + ".partial.tif")
        pp3 = self.cache / f"raw-{key}.pp3"
        profile = self.cache / "linear-prophoto.icc"
        with protect(target, temp_target, pp3, profile, self.cache / "rt-cache", self.cache / "rt-settings"):
            try:
                if not target.exists():
                    import rawpy

                    with rawpy.imread(str(path)) as raw:
                        width, height = raw.sizes.width, raw.sizes.height
                    scale = min(1, edge / max(width, height)) if edge else 1
                    required = int(width * height * scale**2 * (12 if hdr else 6)) + 16 * 1024**2
                    reserve(self.cache, self.cache_budget, required)
                if not target.exists():
                    profile = self.cache / "linear-prophoto.icc"
                    if not profile.exists():
                        profile.write_bytes(icc_profile("linear-prophoto"))
                    pp3 = self.cache / f"raw-{key}.pp3"
                    develop = recipe.develop
                    pp3.write_text(
                        "[Version]\nAppVersion=5.13\nVersion=352\n"
                        f"[Exposure]\nAuto=false\nCompensation={develop.exposure}\n"
                        "Brightness=0\nContrast=0\nSaturation=0\nBlack=0\n"
                        "Curve=0;\nCurve2=0;\n"
                        + ("ClampOOG=false\n" if hdr else "")
                        + f"[HLRecovery]\nEnabled={str(develop.recover_highlights).lower()}\nMethod={'Luminance' if hdr else 'Color'}\n"
                        f"[White Balance]\nSetting={'Camera' if develop.temperature is None else 'Custom'}\n"
                        f"Temperature={develop.temperature or 6500}\nGreen={develop.tint}\n"
                        "[Color Management]\nInputProfile=(camera)\nWorkingProfile=ProPhoto\n"
                        f"OutputProfile=file:{profile.as_posix()}\nOutputProfileIntent=Relative\n"
                        "OutputBPC=true\nApplyLookTable=false\nApplyBaselineExposureOffset=true\n"
                        "[LensProfile]\nLcMode=lfauto\n"
                        f"UseDistortion={str(develop.lens_correction).lower()}\n"
                        f"UseVignette={str(develop.lens_correction).lower()}\nUseCA=false\n"
                        "[Directional Pyramid Denoising]\n"
                        f"Enabled={str(develop.denoise > 0).lower()}\nLuma={develop.denoise * 30}\n"
                        "[Sharpening]\nEnabled=false\n"
                        f"[Resize]\nEnabled={str(edge > 0).lower()}\nAppliesTo=Full image\n"
                        f"Method=Lanczos\nDataSpecified=3\nWidth={edge or 2048}\nHeight={edge or 2048}\nAllowUpscaling=false\n",
                        encoding="utf-8",
                    )
                    command = [
                        self.executable,
                        "-q",
                        "-Y",
                        "-o",
                        str(temp_target),
                        "-p",
                        str(pp3),
                        "-t",
                        "-b32" if hdr else "-b16",
                        "-c",
                        str(path),
                    ]
                    run = subprocess.run(
                        command,
                        capture_output=True,
                        timeout=600,
                        env=self.environment,
                        cwd=Path(self.executable).parent,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    if run.returncode or not temp_target.exists():
                        raise RuntimeError(
                            "Ошибка RawTherapee: " + (run.stdout + run.stderr).decode(errors="replace")[-1500:]
                        )
                    with tifffile.TiffFile(temp_target) as tf:
                        expected_dtype = np.dtype("float32" if hdr else "uint16")
                        if 34675 not in tf.pages[0].tags or tf.pages[0].dtype != expected_dtype:
                            raise RuntimeError("RawTherapee не сохранил ожидаемый промежуточный TIFF с ICC-профилем")
                    os.replace(temp_target, target)
                target.touch()
                image = read_rgb(target)
                trim(self.cache, self.cache_budget)
                return image
            finally:
                temp_target.unlink(missing_ok=True)
                pp3.unlink(missing_ok=True)
        # Caller boundaries also trim rendered previews and masks.



def color_statistics(linear, mask=None):
    rgb = to_srgb(resize(linear, 256))
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2Lab)
    pixels = lab.reshape(-1, 3)
    if mask is not None:
        resized = cv2.resize(mask, (lab.shape[1], lab.shape[0])) > 0.7
        if resized.sum() > 50:
            pixels = lab[resized]
    return np.concatenate(
        [
            np.quantile(pixels[:, 0] / 100, [0.1, 0.25, 0.5, 0.75, 0.9]),
            np.mean(pixels[:, 1:], axis=0) / 128,
            np.std(pixels[:, 1:], axis=0) / 128,
        ]
    ).tolist()


def match_color(linear, reference_stats, strength=0.6, skin=None, target_regions=None, region_masks=None, *, legacy=False):
    from scipy.optimize import least_squares

    image = resize(linear, 192)
    target = np.asarray(reference_stats, np.float64)
    names = ["exposure", "contrast", "saturation", "warmth", "tint", "shadows", "highlights"]
    neutral = np.array([0, 0, 1, 0, 0, 0, 0], float)
    lower = [-0.8 if legacy else -2, -0.3, 0.5, -0.1, -0.08, -0.15, -0.15]
    upper = [0.8 if legacy else 2, 0.3, 1.5, 0.1, 0.08, 0.15, 0.15]
    mask = cv2.resize(skin, (image.shape[1], image.shape[0])) if skin is not None else None
    skin_stats = (
        np.asarray(color_statistics(image, mask)) if mask is not None and (mask > 0.7).sum() > 50 else None
    )
    shared_regions = {
        name: np.asarray(values, np.float32)
        for name, values in (region_masks or {}).items()
        if target_regions and target_regions.get(name) and (np.asarray(values) > 0.7).sum() > 50
    }

    def residual(values):
        parameters = Color(**dict(zip(names, values)))
        output = color_grade(image, parameters, mask, legacy=legacy)
        stats = np.asarray(color_statistics(output))
        residuals = [stats - target, (values - neutral) * 0.14]
        if skin_stats is not None:
            # Preserve the person's own chroma; reference skin is not a target skin tone.
            changed_skin = np.asarray(color_statistics(output, mask))
            residuals.append((changed_skin[5:7] - skin_stats[5:7]) * 1.5)
        for name, region in shared_regions.items():
            residuals.append((np.asarray(color_statistics(output, region)) - target_regions[name]) * 0.4)
        return np.concatenate(residuals)

    def jacobian(values):
        base = residual(values)
        columns = []
        # Explicit finite steps exceed float32/ICC quantization, including parameters starting at zero.
        for i, step in enumerate((0.02, 0.01, 0.02, 0.005, 0.005, 0.01, 0.01)):
            shifted = values.copy()
            delta = step if values[i] + step <= upper[i] else -step
            shifted[i] += delta
            columns.append((residual(shifted) - base) / delta)
        return np.stack(columns, axis=1)

    fit = least_squares(residual, neutral, bounds=(lower, upper), jac=jacobian, max_nfev=32)
    return Color(**dict(zip(names, fit.x)), strength=strength)
