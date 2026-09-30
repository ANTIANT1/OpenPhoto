"""Rebuild derived groups and recommendations from current evidence, atomically."""
from contextlib import nullcontext

import numpy as np

from .database import AnalysisResult, PhotoAsset, Shoot, dumps, loads


def recompute_selection(catalog, ids=None, session=None):
    fraction = catalog.settings().get("keeper_fraction", 0.35)
    with nullcontext(session) if session is not None else catalog.session() as s:
        query = s.query(PhotoAsset).filter(PhotoAsset.status != "removed")
        if ids is not None:
            shoots = {p.shoot_id for p in s.query(PhotoAsset).filter(PhotoAsset.id.in_(ids))}
            query = query.filter(PhotoAsset.shoot_id.in_(shoots))
        photos = query.order_by(PhotoAsset.shoot_id, PhotoAsset.captured, PhotoAsset.id).all()
        previous, previous_data = None, {}
        claimed = {p.group_id for p in photos if p.group_locked}
        layers = {}
        for photo in photos:
            if photo.shoot_id not in layers:
                shoot = s.get(Shoot, photo.shoot_id)
                layers[photo.shoot_id] = (shoot, loads(shoot.settings, {}))
            row = s.get(AnalysisResult, photo.id)
            data = loads(row.data, {}) if row else {}
            # Technical and explicit review reasons survive; old group ambiguity does not.
            photo.review = bool(photo.error or loads(photo.review_flags, []) or not data or data.get("review"))
            old_group = photo.group_id
            joins = False
            if previous and not photo.group_locked and not previous.group_locked and photo.shoot_id == previous.shoot_id:
                gap = photo.captured - previous.captured
                a, b = data.get("phash"), previous_data.get("phash")
                distance = sum(x != y for x, y in zip(a, b)) if a and b else 64
                similarity = None
                if data.get("embedding") and previous_data.get("embedding"):
                    similarity = float(np.dot(data["embedding"], previous_data["embedding"]))
                poses_a, poses_b = data.get("poses"), previous_data.get("poses")
                pose_distance = 1.0
                if poses_a and poses_b:
                    pairs = [(a, b) for a, b in zip(poses_a[0], poses_b[0]) if min(a["visibility"], b["visibility"]) > .7]
                    if pairs:
                        pose_distance = float(np.mean([np.hypot(a["x"] - b["x"], a["y"] - b["y"]) for a, b in pairs]))
                joins = 0 <= gap <= 8 and (distance <= 14 or (similarity is not None and similarity > .94 and pose_distance < .08))
            if not photo.group_locked:
                # Retain existing anchor IDs and their layer settings; split former members
                # into stable new anchors instead of perpetuating a stale merge.
                photo.group_id = previous.group_id if joins else old_group if old_group not in claimed else "auto-" + photo.id
                claimed.add(photo.group_id)
                settings = layers[photo.shoot_id][1]
                group_layers = settings.get("groups", {})
                if old_group != photo.group_id and old_group in group_layers and photo.group_id not in group_layers:
                    group_layers[photo.group_id] = dict(group_layers[old_group])
            previous, previous_data = photo, data
        for shoot, settings in layers.values():
            shoot.settings = dumps(settings)
        groups = {}
        for photo in photos:
            groups.setdefault((photo.shoot_id, photo.group_id), []).append(photo)
        winners = {}
        def effective(p):
            return p.learned_score if p.learned_score is not None else p.score or 0
        for group in groups.values():
            ranked = sorted(group, key=lambda p: (-effective(p), p.id))
            for index, photo in enumerate(ranked):
                photo.suggested = index == 0
                if len(group) == 1:
                    photo.review = True
            winners.setdefault(ranked[0].shoot_id, []).append(ranked[0])
            if len(ranked) > 1 and abs(effective(ranked[0]) - effective(ranked[1])) < .035:
                ranked[1].review = True
        # A global settings refresh must not allocate one shoot's quota to another.
        for shoot_id, selected in winners.items():
            members = [p for p in photos if p.shoot_id == shoot_id]
            budget = max(len(selected), round(len(members) * fraction))
            others = sorted((p for p in members if not p.suggested), key=lambda p: (-effective(p), p.id))
            for photo in others[:max(0, budget - len(selected))]:
                photo.suggested = True
