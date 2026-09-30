"""Bounded local analysis. Optional models are never downloaded during inference."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .imaging import color_statistics, convert, face_skin_mask, icc_profile
from .schemas import Crop

ANALYSIS_VERSION = "analysis-v2"
MODEL_FILES = {
    "clip": "clip-vit-b32.pt",
    "aesthetic": "aesthetic-b32.pth",
    "face": "face_landmarker.task",
    "pose": "pose_landmarker_full.task",
    "skin": "selfie_multiclass.tflite",
}


class LocalModels:
    def __init__(self, directory: Path):
        self.directory = directory
        self.clip = None
        self.aesthetic = None
        self.face = None
        self.pose = None
        self.skin = None
        self.device = "cpu"
        self.errors = {}
        self._loaded = set()
        self._verified = {}
        self.regions = {}

    def verified(self, name):
        if name in self._verified:
            return self._verified[name]
        path = self.directory / MODEL_FILES[name]
        manifest_path = Path(__file__).parent / "resources/models.lock.json"
        valid = False
        if path.is_file() and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = manifest.get(path.name, {}).get("sha256")
            with path.open("rb") as stream:
                valid = expected == hashlib.file_digest(stream, "sha256").hexdigest()
        self._verified[name] = valid
        if path.is_file() and not valid:
            self.errors[name] = "Контрольная сумма модели не совпадает с закреплённым манифестом OpenPhoto"
        return valid

    def availability(self):
        return {name: (self.directory / file).is_file() for name, file in MODEL_FILES.items()}

    def load_clip(self):
        if "clip" in self._loaded:
            return
        self._loaded.add("clip")
        if not self.verified("clip") or importlib.util.find_spec("open_clip") is None:
            return
        try:
            import open_clip
            import torch

            torch.set_num_threads(min(4, int(os.environ.get("OMP_NUM_THREADS", "4"))))

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            if self.device == "cuda":
                torch.cuda.set_per_process_memory_fraction(0.72)
            self.clip, _, self.preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained=None, force_quick_gelu=True, device="cpu"
            )
            # The official OpenAI file is TorchScript, not a pickled training checkpoint.
            archive = torch.jit.load(str(self.directory / MODEL_FILES["clip"]), map_location="cpu")
            state = archive.state_dict()
            for key in ("input_resolution", "context_length", "vocab_size"):
                state.pop(key, None)
            self.clip.load_state_dict(state)
            del archive, state
            try:
                self.clip.to(self.device)
            except torch.cuda.OutOfMemoryError:
                self.device = "cpu"
                self.clip.to("cpu")
                torch.cuda.empty_cache()
            self.clip.eval()
            if self.verified("aesthetic"):
                self.aesthetic = torch.nn.Linear(512, 1)
                self.aesthetic.load_state_dict(
                    torch.load(
                        self.directory / MODEL_FILES["aesthetic"], map_location="cpu", weights_only=True
                    )
                )
                self.aesthetic.eval()
        except Exception as error:
            self.errors["clip"] = str(error)
            self.clip = None

    def embedding(self, rgb):
        self.load_clip()
        if self.clip is None:
            return None, None
        import torch

        image = self.preprocess(Image.fromarray(rgb)).unsqueeze(0)
        try:
            with torch.inference_mode():
                vector = self.clip.encode_image(image.to(self.device)).float()
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            self.device = "cpu"
            self.clip.to("cpu")
            with torch.inference_mode():
                vector = self.clip.encode_image(image).float()
        vector = vector.cpu()
        # On CPU .cpu() can retain an inference tensor; avoid mutating it outside inference_mode.
        vector = vector / vector.norm(dim=-1, keepdim=True).clamp_min(1e-8)
        score = None
        if self.aesthetic is not None:
            with torch.inference_mode():
                score = float(self.aesthetic(vector).item())
        return vector.numpy()[0].tolist(), score

    def load_landmarks(self):
        if "landmarks" in self._loaded:
            return
        self._loaded.add("landmarks")
        if not any(self.verified(name) for name in ("face", "pose", "skin")):
            return
        if importlib.util.find_spec("mediapipe") is None:
            return
        try:
            os.environ.setdefault("MPLCONFIGDIR", str(self.directory.parent / ".cache" / "matplotlib"))
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            for name, filename in MODEL_FILES.items():
                path = self.directory / filename
                if name not in {"face", "pose", "skin"} or not self.verified(name):
                    continue
                try:
                    base = python.BaseOptions(model_asset_path=str(path))
                    if name == "face":
                        self.face = vision.FaceLandmarker.create_from_options(
                            vision.FaceLandmarkerOptions(
                                base_options=base, num_faces=8, output_face_blendshapes=True
                            )
                        )
                    elif name == "pose":
                        self.pose = vision.PoseLandmarker.create_from_options(
                            vision.PoseLandmarkerOptions(
                                base_options=base, num_poses=4, output_segmentation_masks=False
                            )
                        )
                    else:
                        self.skin = vision.ImageSegmenter.create_from_options(
                            vision.ImageSegmenterOptions(
                                base_options=base, output_category_mask=False, output_confidence_masks=True
                            )
                        )
                except Exception as error:
                    self.errors[name] = str(error)
        except Exception as error:
            self.errors["landmarks"] = str(error)

    def landmarks(self, rgb, legacy=False):
        self.load_landmarks()
        self.regions = {}
        faces, poses, skin = [], [], None
        if not any((self.face, self.pose, self.skin)):
            return faces, poses, skin
        import mediapipe as mp

        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        if self.face:
            result = self.face.detect(image)
            oval_indices = [
                10,
                338,
                297,
                332,
                284,
                251,
                389,
                356,
                454,
                323,
                361,
                288,
                397,
                365,
                379,
                378,
                400,
                377,
                152,
                148,
                176,
                149,
                150,
                136,
                172,
                58,
                132,
                93,
                234,
                127,
                162,
                21,
                54,
                103,
                67,
                109,
            ]
            zones = [
                [33, 160, 158, 133, 153, 144],
                [362, 385, 387, 263, 373, 380],
                [70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
                [300, 293, 334, 296, 336, 285, 295, 282, 283, 276],
                [61, 40, 37, 0, 267, 270, 291, 321, 314, 17, 84, 91],
            ]
            for index, points in enumerate(result.face_landmarks):
                coords = [(float(p.x), float(p.y)) for p in points]
                box = [
                    min(x for x, _ in coords),
                    min(y for _, y in coords),
                    max(x for x, _ in coords),
                    max(y for _, y in coords),
                ]
                blends = {c.category_name: float(c.score) for c in result.face_blendshapes[index]}
                inside = np.mean([0 <= x <= 1 and 0 <= y <= 1 for x, y in coords])
                face_pixels = min((box[2] - box[0]) * rgb.shape[1], (box[3] - box[1]) * rgb.shape[0])
                confidence = float(np.clip(inside * min(1, face_pixels / 80), 0, 1))
                face = {
                    "box": box,
                    "confidence": confidence,
                    "oval": [coords[i] for i in oval_indices],
                    "protected": [[coords[i] for i in zone] for zone in zones],
                    "eyes_closed": max(blends.get("eyeBlinkLeft", 0), blends.get("eyeBlinkRight", 0)),
                    "expression": {k: v for k, v in blends.items() if "Smile" in k or "Blink" in k},
                }
                eye_x = (coords[33][0] + coords[263][0]) / 2
                face["gaze_proxy"] = float(
                    np.clip((coords[1][0] - eye_x) / max(box[2] - box[0], 0.01), -1, 1)
                )
                faces.append(face)
        if self.pose:
            result = self.pose.detect(image)
            for pose in result.pose_landmarks:
                poses.append(
                    [{"x": float(p.x), "y": float(p.y), "visibility": float(p.visibility)} for p in pose]
                )
        if self.skin:
            result = self.skin.segment(image)
            edge = 96 if legacy else 256
            self.regions = {
                name: cv2.resize(
                    result.confidence_masks[index].numpy_view(), (edge, edge), interpolation=cv2.INTER_AREA
                )
                .round(3)
                .tolist()
                for name, index in (("background", 0), ("clothing", 4), ("body_skin", 2))
            }
            skin = (
                cv2.resize(
                    result.confidence_masks[3].numpy_view(), (edge, edge), interpolation=cv2.INTER_AREA
                )
                .round(3)
                .tolist()
            )
        return faces, poses, skin


def box_pixels(box, width, height):
    x1, y1, x2, y2 = box
    return (
        max(0, int(x1 * width)),
        max(0, int(y1 * height)),
        min(width, math.ceil(x2 * width)),
        min(height, math.ceil(y2 * height)),
    )


def sharpness(gray):
    if gray.size < 16:
        return None
    return float(np.log1p(cv2.Laplacian(gray, cv2.CV_32F).var()))


def subject_box(faces, poses):
    points = []
    for pose in poses:
        points.extend(
            [
                (p["x"], p["y"])
                for p in pose
                if p["visibility"] >= 0.65 and 0 <= p["x"] <= 1 and 0 <= p["y"] <= 1
            ]
        )
    for face in faces:
        x1, y1, x2, y2 = face["box"]
        points.extend([(x1, y1), (x2, y2)])
    if not points:
        return None
    return [
        max(0, min(x for x, _ in points)),
        max(0, min(y for _, y in points)),
        min(1, max(x for x, _ in points)),
        min(1, max(y for _, y in points)),
    ]


def composition(box, faces, crop=Crop(), edge_energy=0):
    if box is None:
        return {
            "score": 0.5,
            "placement": 0.5,
            "balance": 0.5,
            "confidence": 0,
            "reason": "Главный объект не определён — исходное кадрирование сохранено",
        }
    cx = ((box[0] + box[2]) / 2 - crop.x) / crop.w
    cy = ((box[1] + box[3]) / 2 - crop.y) / crop.h
    anchors = [(0.5, 0.5), (1 / 3, 1 / 3), (2 / 3, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 2 / 3)]
    placement = max(math.exp(-5 * ((cx - x) ** 2 + (cy - y) ** 2)) for x, y in anchors)
    balance = max(0, 1 - abs(cx - 0.5))
    gaze_room = 0.5
    if faces:
        face = max(faces, key=lambda f: (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1]))
        direction = face.get("gaze_proxy", 0)
        if abs(direction) > 0.07:
            gaze_room = 1 - cx if direction > 0 else cx
    score = 0.5 * placement + 0.25 * balance + 0.15 * gaze_room + 0.1 * (1 - min(edge_energy, 1))
    return {
        "score": round(score, 4),
        "placement": round(placement, 4),
        "balance": round(balance, 4),
        "gaze_room": round(gaze_room, 4),
        "confidence": min((f.get("confidence", 0) for f in faces), default=0),
        "subject_box": box,
    }


def crop_is_safe(crop: Crop, faces, poses, minimum_area=0.8):
    if crop.w * crop.h < minimum_area - 1e-7:
        return False
    for face in faces:
        x1, y1, x2, y2 = face["box"]
        pad = 0.015
        if crop.x > max(0, x1 - pad) or crop.y > max(0, y1 - pad):
            return False
        if crop.x + crop.w < min(1, x2 + pad) or crop.y + crop.h < min(1, y2 + pad):
            return False
    for pose in poses:
        for index in (13, 14, 15, 16, 25, 26, 27, 28, 29, 30, 31, 32):
            point = pose[index]
            x, y = point["x"], point["y"]
            if point["visibility"] >= 0.65 and 0 <= x <= 1 and 0 <= y <= 1:
                pad = 0.012
                if (
                    crop.x > max(0, x - pad)
                    or crop.y > max(0, y - pad)
                    or crop.x + crop.w < min(1, x + pad)
                    or crop.y + crop.h < min(1, y + pad)
                ):
                    return False
    return True


def crop_descriptor(box, crop):
    if box is None:
        return None
    return [
        ((box[0] + box[2]) / 2 - crop.x) / crop.w,
        ((box[1] + box[3]) / 2 - crop.y) / crop.h,
        (box[2] - box[0]) / crop.w,
        (box[3] - box[1]) / crop.h,
    ]


def propose_crops(width, height, faces, poses, ratio=None, min_area=0.8, preferences=()):
    subject = subject_box(faces, poses)
    original = composition(subject, faces)
    if subject is None:
        return []
    ratio = ratio or width / height
    scale_ratio = ratio / (width / height)
    candidates = []
    for scale in (1.0, 0.97, 0.94, 0.90, 0.82, 0.72):
        cw = scale * min(1, scale_ratio)
        ch = scale * min(1, 1 / scale_ratio)
        for ax in (0, 0.5, 1):
            for ay in (0, 0.5, 1):
                crop = Crop(x=(1 - cw) * ax, y=(1 - ch) * ay, w=cw, h=ch)
                if cw * ch > 0.999:
                    continue
                score = composition(subject, faces, crop)["score"] - 0.12 * (1 - cw * ch)
                if preferences:
                    descriptor = np.asarray(crop_descriptor(subject, crop))
                    distances = [np.linalg.norm(descriptor - np.asarray(p)) for p in preferences[-100:]]
                    # Separate accepted examples; retain multiple composition directions.
                    score += 0.02 * np.exp(-8 * min(distances))
                safe = crop_is_safe(crop, faces, poses, min_area)
                gain = score - original["score"]
                candidates.append(
                    {
                        "crop": crop.model_dump(),
                        "score": round(score, 4),
                        "gain": round(gain, 4),
                        "safe": safe,
                        "retained": round(cw * ch, 4),
                        "auto_eligible": safe
                        and gain > 0.025
                        and original["confidence"] >= 0.8
                        and abs(scale_ratio - 1) < 0.001,
                        "reason": "Положение объекта и свободное пространство"
                        if safe
                        else "Нужна проверка границ и потери площади",
                    }
                )
    candidates.sort(key=lambda c: (c["safe"], c["score"]), reverse=True)
    selected = []
    for candidate in candidates:
        rect = candidate["crop"]
        if all(sum(abs(rect[k] - c["crop"][k]) for k in rect) > 0.055 for c in selected):
            selected.append(candidate)
        if len(selected) == 3:
            break
    return selected


def horizon_candidate(gray):
    h, w = gray.shape
    edges = cv2.Canny(gray, 60, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 1800, threshold=max(35, w // 5), minLineLength=w * 0.45, maxLineGap=w * 0.025
    )
    votes = []
    if lines is not None:
        for ((x1, y1, x2, y2),) in lines:
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angle) < 8 and min(y1, y2) > h * 0.1 and max(y1, y2) < h * 0.85:
                votes.append(float(angle))
    if len(votes) < 3 or np.std(votes) > 0.6:
        return None
    confidence = float(min(1, len(votes) / 8) * np.exp(-np.std(votes) / 0.6))
    return {
        "degrees": round(float(np.median(votes)), 2),
        "confidence": round(confidence, 3),
        "reason": "Согласованные длинные линии; проверьте, что это горизонт",
    }


def spot_candidates(gray, mask):
    """Visual anomalies only: never infer that a mark is a temporary blemish."""
    radius = max(2, round(min(gray.shape) * 0.004))
    dark = cv2.morphologyEx(
        gray,
        cv2.MORPH_BLACKHAT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)),
    )
    binary = np.uint8((dark > 18) & (mask > 0.8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(binary)
    result = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if 3 <= area <= radius * radius * 2 and max(w, h) <= radius * 3:
            cx, cy = centers[i]
            result.append(
                {
                    "x": float(cx / gray.shape[1]),
                    "y": float(cy / gray.shape[0]),
                    "radius": float(min(0.025, max(w, h) / min(gray.shape))),
                    "contrast": float(dark[labels == i].mean() / 255),
                }
            )
    return sorted(result, key=lambda r: r["contrast"], reverse=True)[:8]


def analyze(rgb, models: LocalModels | None = None, *, source="embedded", min_area=0.8, legacy=False):
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    faces, poses, skin = models.landmarks(rgb, legacy=legacy) if models else ([], [], None)
    embedding, aesthetic = models.embedding(rgb) if models else (None, None)
    face_sharpness = []
    for face in faces:
        x1, y1, x2, y2 = box_pixels(face["box"], w, h)
        value = sharpness(gray[y1:y2, x1:x2])
        face["sharpness"] = value
        face_sharpness.append(value or 0)
        face["eye_sharpness"] = []
        for points in face.get("protected", [])[:2]:
            xs, ys = zip(*points)
            xx1, yy1, xx2, yy2 = box_pixels([min(xs), min(ys), max(xs), max(ys)], w, h)
            face["eye_sharpness"].append(sharpness(gray[yy1:yy2, xx1:xx2]))
    box = subject_box(faces, poses)
    sharp = sharpness(gray) or 0
    clipped_light = float(np.mean(np.max(rgb, axis=-1) >= 253))
    clipped_dark = float(np.mean(np.max(rgb, axis=-1) <= 3))
    residual = gray.astype(np.float32) - cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1)
    noise = float(np.median(np.abs(residual)) / 255)
    edge_band = max(1, min(w, h) // 30)
    edges = np.abs(cv2.Laplacian(gray, cv2.CV_32F)) / 255
    edge_energy = float(
        np.mean(
            np.r_[
                edges[:edge_band].ravel(),
                edges[-edge_band:].ravel(),
                edges[:, :edge_band].ravel(),
                edges[:, -edge_band:].ravel(),
            ]
        )
    )
    comp = composition(box, faces, edge_energy=edge_energy)
    primary = (
        max(faces, key=lambda f: (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1])) if faces else None
    )
    technical = float(
        np.clip((0.7 * (primary["sharpness"] or 0) + 0.3 * sharp if primary else sharp) / 9, 0, 1)
    )
    # No absolute exposure / blink veto: each remains an independent review signal.
    quality = (
        technical * 0.5
        + comp["score"] * 0.35
        + (np.clip(aesthetic / 10, 0, 1) if aesthetic is not None else 0.5) * 0.15
    )
    notes = []
    if technical < 0.35:
        notes.append("Проверьте резкость в масштабе 1:1")
    if clipped_light > 0.03:
        notes.append(
            "Возможна потеря деталей в светах"
            if source == "developed"
            else "Света оценены по превью; требуется проявка"
        )
    if any(f.get("eyes_closed", 0) > 0.65 for f in faces):
        notes.append("Возможно закрыты глаза; художественный замысел сохраняется")
    if not faces:
        notes.append("Лицевые ориентиры не найдены; автоматическая ретушь кожи не применяется")
    if models and models.errors:
        notes.append("Некоторые модели недоступны; подробности в диагностике")
    small = cv2.resize(gray, (32, 32)).astype(np.float32)
    dct = cv2.dct(small)[:8, :8]
    bits = (dct > np.median(dct[1:])).reshape(-1)
    phash = "".join("1" if x else "0" for x in bits)
    linear = convert(rgb, icc_profile("srgb"))
    statistics = color_statistics(linear)
    regions = {}
    spots = []
    if skin and faces:
        mask = face_skin_mask(linear.shape, {"skin_mask": skin, "faces": faces})
        if (mask > 0.7).sum() > 50:
            regions = {
                "skin": color_statistics(linear, mask),
                "background": color_statistics(linear, 1 - mask),
            }
            spots = spot_candidates(gray, mask)
    if models:
        for name, values in models.regions.items():
            mask = np.asarray(values, np.float32)
            if (mask > 0.7).sum() > 50:
                regions[name] = color_statistics(linear, mask)
    features = [
        technical,
        comp["score"],
        clipped_light,
        clipped_dark,
        noise,
        (aesthetic or 5) / 10,
        max(face_sharpness, default=0) / 9,
        comp["placement"],
        comp["balance"],
    ]
    return {
        "version": ANALYSIS_VERSION,
        "source": source,
        "width": w,
        "height": h,
        "sharpness": sharp,
        "technical": technical,
        "highlight_clipping": clipped_light,
        "shadow_clipping": clipped_dark,
        "noise": noise,
        "faces": faces,
        "poses": poses,
        "skin_mask": skin,
        "body_skin_mask": models.regions.get("body_skin") if models and not legacy else None,
        "embedding": embedding,
        "aesthetic": aesthetic,
        "composition": comp,
        "horizon": horizon_candidate(gray),
        "edge_energy": edge_energy,
        "crops": propose_crops(w, h, faces, poses, min_area=min_area),
        "color_stats": statistics,
        "region_stats": regions,
        "spot_candidates": spots,
        "features": features,
        "phash": phash,
        "score": float(quality),
        "review": bool(notes),
        "notes": notes,
        "models": models.availability() if models else {},
        "device": models.device if models else "cpu",
        "model_errors": models.errors if models else {},
    }


def reference_similarity(analysis, references):
    vector = analysis.get("embedding")
    distances = []
    spatial = []
    for ref in references:
        if ref.get("roles") and not set(ref["roles"]) & {"composition", "mood"}:
            continue
        if vector is not None and ref.get("embedding") is not None:
            value = float(np.dot(vector, ref["embedding"]))
            distances.append((value, ref["id"]))
        a = analysis.get("composition", {}).get("subject_box")
        b = ref.get("composition", {}).get("subject_box")
        if a and b and "composition" in ref.get("roles", []):
            delta = np.asarray(crop_descriptor(a, Crop())) - np.asarray(crop_descriptor(b, Crop()))
            spatial.append((float(np.exp(-3 * np.linalg.norm(delta))), ref["id"]))
    distances.sort(reverse=True)
    spatial.sort(reverse=True)
    mood = float(np.mean([v for v, _ in distances[:3]])) if distances else None
    layout = float(np.mean([v for v, _ in spatial[:3]])) if spatial else None
    similarity = (
        0.75 * mood + 0.25 * layout
        if mood is not None and layout is not None
        else mood
        if mood is not None
        else layout
    )
    return {
        "similarity": similarity,
        "visual_similarity": mood,
        "composition_similarity": layout,
        "reference_ids": [i for _, i in distances[:3]],
        "composition_reference_ids": [i for _, i in spatial[:3]],
    }
