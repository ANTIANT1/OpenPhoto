from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageOps

from .analysis import LocalModels, analyze, propose_crops, reference_similarity
from .cache import protect_photo
from .database import (
    AnalysisResult,
    Catalog,
    PhotoAsset,
    ProcessingJob,
    RecipeDraft,
    RecipeRevision,
    Root,
    Shoot,
    StyleProfile,
    UserDecision,
    dumps,
    loads,
    now,
    uid,
)
from .imaging import (
    IMAGE_EXTENSIONS,
    RAW_EXTENSIONS,
    RawDeveloper,
    apply_recipe,
    cache_key,
    color_statistics,
    extended_range,
    face_skin_mask,
    fingerprint,
    match_color,
    oriented_preview,
    processing_environment,
    resize,
    to_srgb,
    write_image,
)
from .imaging import geometry_canvas
from .learning import fit_ranker, score as learned_score
from .schemas import Crop, EditRecipe, ExportRequest


def cached_render(catalog, photo, analysis, full=False):
    """Only a complete render of this exact revision can skip expensive work."""
    if analysis.get("input_revision") != photo.revision:
        return False
    cache = catalog.directory / "cache"
    variants = ("full", "fullbase") if full else ("render", "base")
    paths = [cache / f"{variant}-{photo.id}-{photo.revision}.jpg" for variant in variants]
    paths.append(cache / f"mask-{photo.id}-{photo.revision}.png")
    try:
        return all(path.is_file() and path.stat().st_size > 0 for path in paths)
    except OSError:
        return False


def geometry_analysis_key(fingerprint_value, recipe, shape):
    geometry = recipe.model_copy(deep=True)
    defaults = EditRecipe()
    geometry.color = defaults.color
    geometry.retouch = defaults.retouch
    geometry.crop = defaults.crop
    geometry.lock_crop = False
    return cache_key(fingerprint_value, geometry, str(tuple(shape)))


def enqueue(catalog, kind, payload, priority=20, identifier=None):
    with catalog.session() as session:
        if identifier and session.get(ProcessingJob, identifier):
            return identifier
        job = ProcessingJob(kind=kind, payload=dumps(payload), priority=priority)
        if identifier:
            job.id = identifier
        if kind == "export":
            query = session.query(PhotoAsset).filter(PhotoAsset.status != "removed")
            if payload.get("photo_ids"):
                query = query.filter(PhotoAsset.id.in_(payload["photo_ids"]))
            else:
                if payload.get("shoot_id"):
                    query = query.filter_by(shoot_id=payload["shoot_id"])
                query = query.filter(
                    (PhotoAsset.status == "keep")
                    | (
                        (PhotoAsset.status == "unreviewed") & PhotoAsset.suggested
                        if payload.get("include_proposed")
                        else PhotoAsset.status == "keep"
                    )
                )
            scope = list(query.order_by(PhotoAsset.captured))
            payload = {**payload, "photo_ids": [p.id for p in scope]}
            job.payload = dumps(payload)
            job.result = dumps(
                {
                    "snapshots": {
                        p.id: {
                            "revision": p.revision,
                            "recipe": catalog.recipe(p, session).model_dump(),
                            "rating": p.rating,
                            "status": p.status,
                            "source": {"root_id": p.root_id, "relative_path": p.relative_path,
                                       "fingerprint": p.fingerprint, "name": p.name},
                        }
                        for p in scope
                    },
                    "scope_frozen": True,
                }
            )
        session.add(job)
        session.flush()
        return job.id


def discover(paths, recursive=True, references=False):
    found = {}
    errors = []
    for supplied in paths:
        root = Path(supplied).expanduser().resolve()
        if not root.exists():
            errors.append({"path": str(root), "error": "Файл или папка недоступны"})
            continue
        entries = (
            root.rglob("*") if root.is_dir() and recursive else root.glob("*") if root.is_dir() else [root]
        )
        try:
            for path in entries:
                if path.is_file() and path.suffix.lower() in (IMAGE_EXTENSIONS | ({".psd"} if references else set())):
                    found[str(path.resolve()).casefold()] = (
                        path.resolve(),
                        root if root.is_dir() else root.parent,
                    )
        except OSError as error:
            errors.append({"path": str(root), "error": str(error)})
    paired = {}
    for path, root in found.values():
        key = str(path.parent / path.stem).casefold()
        paired.setdefault(key, []).append((path, root))
    result = []
    for files in paired.values():
        raws = [p for p in files if p[0].suffix.lower() in RAW_EXTENSIONS]
        jpegs = [p for p in files if p[0].suffix.lower() in {".jpg", ".jpeg"}]
        if len(raws) == 1 and len(jpegs) == 1:
            result.append((raws[0][0], raws[0][1], jpegs[0][0]))
            result.extend((p, r, None) for p, r in files if p not in {raws[0][0], jpegs[0][0]})
        else:
            result.extend((p, r, None) for p, r in files)
    return sorted(result, key=lambda row: str(row[0]).casefold()), errors


def metadata(path, exiftool=None):
    result = {}
    if exiftool and Path(exiftool).is_file():
        run = subprocess.run(
            [
                exiftool,
                "-json",
                "-n",
                "-DateTimeOriginal",
                "-Make",
                "-Model",
                "-LensModel",
                "-ISO",
                "-FNumber",
                "-ExposureTime",
                "-FocalLength",
                "-Orientation",
                "-ImageWidth",
                "-ImageHeight",
                str(path),
            ],
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if run.returncode == 0:
            result = json.loads(run.stdout)[0]
            result.pop("SourceFile", None)
    else:
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                for key, tag in {
                    "Make": 271,
                    "Model": 272,
                    "Orientation": 274,
                    "DateTimeOriginal": 36867,
                }.items():
                    value = exif.get(tag)
                    if value is not None:
                        result[key] = str(value)
                if 34665 in exif:
                    sub = exif.get_ifd(34665)
                    for key, tag in {
                        "DateTimeOriginal": 36867,
                        "ISO": 34855,
                        "FNumber": 33437,
                        "ExposureTime": 33434,
                        "FocalLength": 37386,
                        "LensModel": 42036,
                    }.items():
                        value = sub.get(tag)
                        if value is not None:
                            result[key] = str(value)
        except Exception:
            pass
    result["file_bytes"] = path.stat().st_size
    captured = path.stat().st_mtime
    try:
        captured = datetime.strptime(str(result["DateTimeOriginal"])[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except (KeyError, ValueError):
        pass
    return result, captured


def public_photo(photo, analysis=None):
    return {
        "id": photo.id,
        "shoot_id": photo.shoot_id,
        "name": photo.name,
        "raw": Path(photo.relative_path).suffix.lower() in RAW_EXTENSIONS,
        "paired": bool(photo.jpeg_path),
        "width": photo.width,
        "height": photo.height,
        "group_id": photo.group_id,
        "status": photo.status,
        "rating": photo.rating,
        "suggested": photo.suggested,
        "review": photo.review,
        "revision": photo.revision,
        "score": photo.score,
        "learned_score": photo.learned_score,
        "error": photo.error,
        "captured": photo.captured,
        "metadata": loads(photo.metadata_json, {}),
        "analysis": analysis,
    }


class Pipeline:
    def __init__(self, directory, lane=None):
        self.catalog = Catalog(directory)
        settings = self.catalog.settings()
        models_dir = Path(settings.get("models_directory", self.catalog.directory / "models"))
        self.models = LocalModels(models_dir)
        if lane in {"render", "import"}:
            self.models._loaded.add("clip")
        self.stop_event = None
        self.kinds = {
            "analysis": ["analyze", "profile", "train"],
            "render": ["render", "style", "export"],
            "import": ["import"],
        }.get(lane)

    def stopped(self, job_id):
        if self.stop_event is not None and self.stop_event.is_set():
            with self.catalog.session() as s:
                job = s.get(ProcessingJob, job_id)
                if job and job.state in {"queued", "running"}:
                    job.state = "paused"
            return True
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            return not job or job.state in {"paused", "cancelled"}

    def update(self, job_id, **fields):
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            for name, value in fields.items():
                setattr(job, name, value)
            job.updated = now()

    def item_done(self, job_id, item, error=None):
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            checkpoint = loads(job.checkpoint, [])
            if item not in checkpoint:
                checkpoint.append(item)
            job.checkpoint = dumps(checkpoint)
            job.completed = len(checkpoint)
            if error:
                result = loads(job.result, {})
                result.setdefault("errors", []).append({"item": item, "error": str(error)})
                job.result = dumps(result)
            job.updated = now()
        self.trim_cache()

    def yield_to_interactive(self, job_id):
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            query = s.query(ProcessingJob).filter(
                ProcessingJob.state == "queued", ProcessingJob.priority < job.priority,
                ProcessingJob.kind.in_(["render", "geometry_preview", "style"]),
            )
            if self.kinds:
                query = query.filter(ProcessingJob.kind.in_(self.kinds))
            if query.first():
                job.state = "queued"
                return True
        return False

    def run(self, job_id):
        from .job_lifecycle import cleanup_cancelled, job_lock

        lock = job_lock(self.catalog, job_id)
        lock.acquire()
        try:
            if not self.stopped(job_id):
                self._run(job_id)
        finally:
            try:
                try:
                    with self.catalog.session() as s:
                        job = s.get(ProcessingJob, job_id)
                        selection_ids = loads(job.payload, {}).get("photo_ids", []) if job and job.kind == "analyze" else None
                    if selection_ids is not None:
                        self.group_and_select(selection_ids)
                finally:
                    try:
                        cleanup_cancelled(self.catalog, job_id, locked=True)
                    finally:
                        self.trim_cache()
            finally:
                lock.release()

    def _run(self, job_id):
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            payload, kind = loads(job.payload), job.kind
            checkpoint = set(loads(job.checkpoint, []))
        if kind == "import":
            self.import_photos(job_id, payload, checkpoint)
        elif kind == "profile":
            self.import_profile(job_id, payload, checkpoint)
        elif kind == "train":
            self.train(job_id)
        elif kind == "workflow":
            from .workflows import run_workflow

            run_workflow(self, job_id, payload)
            return
        else:
            ids = payload.get("photo_ids", [])
            with self.catalog.session() as s:
                if not ids and not loads(job.result, {}).get("scope_frozen"):
                    q = s.query(PhotoAsset).filter(PhotoAsset.status != "removed")
                    if payload.get("shoot_id"):
                        q = q.filter(PhotoAsset.shoot_id == payload["shoot_id"])
                    if kind == "export":
                        q = q.filter(
                            (PhotoAsset.status == "keep")
                            | (
                                (PhotoAsset.status == "unreviewed") & PhotoAsset.suggested
                                if payload.get("include_proposed")
                                else (PhotoAsset.status == "keep")
                            )
                        )
                    ids = [p.id for p in q.order_by(PhotoAsset.captured)]
                # Persist the frozen scope, so adding/importing photos during a resumed job cannot change it.
                job = s.get(ProcessingJob, job_id)
                payload["photo_ids"] = ids
                job.payload = dumps(payload)
                job.total = len(ids)
            for photo_id in ids:
                if self.stopped(job_id):
                    return
                if photo_id in checkpoint:
                    continue
                if self.yield_to_interactive(job_id):
                    return
                try:
                    if kind == "analyze":
                        self.analyze_photo(photo_id, payload)
                    elif kind == "render":
                        if payload.get("harmonize_exposure"):
                            self.harmonize_photo(photo_id, payload.get("source_photo_id"))
                        self.render_photo(photo_id, payload.get("revision"), payload.get("full", False))
                    elif kind == "geometry_preview":
                        self.preview_geometry(photo_id, payload)
                    elif kind == "style":
                        self.propose_style(photo_id, payload)
                    elif kind == "export":
                        self.export_photo(job_id, photo_id, ExportRequest.model_validate(payload))
                    else:
                        raise ValueError(f"Unknown job kind: {kind}")
                    self.item_done(job_id, photo_id)
                except InterruptedError:
                    return
                except Exception as error:
                    self.item_done(job_id, photo_id, error)
        if not self.stopped(job_id):
            with self.catalog.session() as s:
                job = s.get(ProcessingJob, job_id)
                if job.state in {"queued", "running"}:
                    job.state = "completed_with_errors" if loads(job.result, {}).get("errors") else "completed"
                job.updated = now()
        self.trim_cache()

    def import_photos(self, job_id, payload, checkpoint):
        settings = self.catalog.settings()
        files, errors = discover(payload["paths"], payload.get("recursive", True))
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            result = loads(job.result, {})
            shoot_id = result.get("shoot_id")
            result.setdefault("duplicates", 0)
            result.setdefault("restored", 0)
            result.setdefault("imported", 0)
            result.setdefault("errors", []).extend(e for e in errors if e not in result.get("errors", []))
            job.result = dumps(result)
            job.total = len(files)
        for index, (path, root_path, jpeg) in enumerate(files):
            key = str(path)
            if key in checkpoint:
                continue
            if self.stopped(job_id):
                return
            if index and self.yield_to_interactive(job_id):
                return
            try:
                digest = fingerprint(path)
                item_error = None
                with self.catalog.session() as s:
                    existing = s.query(PhotoAsset).filter_by(fingerprint=digest).first()
                    if not existing and jpeg:
                        existing = next((p for p in s.query(PhotoAsset).filter(PhotoAsset.name.ilike(jpeg.name))
                                         if str(self.catalog.photo_path(p, s)).casefold() == str(jpeg).casefold()), None)
                        if existing:
                            # Freeze sources for pre-migration queued exports before promoting
                            # the same card from a JPEG to its newly discovered RAW pair.
                            for export in s.query(ProcessingJob).filter(ProcessingJob.kind == "export",
                                                                      ProcessingJob.state.in_(["queued", "paused", "running"])):
                                state = loads(export.result, {})
                                frozen = state.get("snapshots", {}).get(existing.id)
                                if frozen and "source" not in frozen:
                                    frozen["source"] = {key: getattr(existing, key) for key in
                                                        ("root_id", "relative_path", "fingerprint", "name")}
                                    export.result = dumps(state)
                            registered_root = Path(s.get(Root, existing.root_id).path)
                            recipe = self.catalog.recipe(existing, s)
                            existing.relative_path = str(path.relative_to(registered_root))
                            existing.jpeg_path = str(jpeg.relative_to(registered_root))
                            existing.fingerprint, existing.name = digest, path.name
                            meta, existing.captured = metadata(path, settings.get("exiftool"))
                            existing.metadata_json = dumps(meta)
                            existing.score = existing.learned_score = None
                            existing.review_flags = dumps(sorted(set(loads(existing.review_flags, [])) | {"raw_pair_added"}))
                            existing.review = True
                            s.query(AnalysisResult).filter_by(photo_id=existing.id).delete()
                            draft = s.get(RecipeDraft, existing.id)
                            draft_recipe = draft.recipe if draft and draft.revision == existing.revision else None
                            self.catalog.save_recipe(s, existing, recipe, existing.revision, "paired_raw")
                            if draft_recipe:
                                s.flush()
                                s.add(RecipeDraft(photo_id=existing.id, revision=existing.revision, recipe=draft_recipe))
                            item_error = self.prepare_preview(existing, path, jpeg)
                    if not existing:
                        existing = (
                            s.query(PhotoAsset)
                            .join(Root)
                            .filter(
                                Root.path == str(root_path),
                                PhotoAsset.relative_path == str(path.relative_to(root_path)),
                                PhotoAsset.error.is_not(None),
                            )
                            .first()
                        )
                    if existing:
                        if self.catalog.photo_path(existing, s) == path:
                            if jpeg:
                                registered_root = Path(s.get(Root, existing.root_id).path)
                                existing.jpeg_path = str(jpeg.relative_to(registered_root))
                            if existing.error:
                                existing.fingerprint = digest
                                item_error = self.prepare_preview(existing, path, jpeg)
                        job = s.get(ProcessingJob, job_id)
                        result = loads(job.result)
                        if existing.status == "removed":
                            from .catalog_actions import restore_photo

                            # An explicit re-import restores the card, its ratings and recipes.
                            # Bind it to the selected file, including a moved copy of the original.
                            root = s.query(Root).filter_by(path=str(root_path)).first()
                            if root is None:
                                root = Root(path=str(root_path))
                                s.add(root)
                                s.flush()
                            existing.root_id = root.id
                            existing.relative_path = str(path.relative_to(root_path))
                            existing.jpeg_path = str(jpeg.relative_to(root_path)) if jpeg else None
                            s.add(UserDecision(operation_id=job_id, photo_id=existing.id, action="restore_removed",
                                               previous=dumps({"status": "removed", "rating": existing.rating})))
                            restore_photo(s, existing)
                            result["restored"] += 1
                        else:
                            result["duplicates"] += 1
                        result["message"] = (f'Добавлено: {result["imported"]}. Восстановлено из удалённых: '
                                             f'{result["restored"]}. Уже в каталоге: {result["duplicates"]}.')
                        job.result = dumps(result)
                    else:
                        if not shoot_id or s.get(Shoot, shoot_id) is None:
                            shoot = Shoot(name=payload["shoot_name"])
                            s.add(shoot)
                            s.flush()
                            shoot_id = shoot.id
                            job = s.get(ProcessingJob, job_id)
                            result = loads(job.result, {})
                            result["shoot_id"] = shoot_id
                            job.result = dumps(result)
                        root = s.query(Root).filter_by(path=str(root_path)).first()
                        if root is None:
                            root = Root(path=str(root_path))
                            s.add(root)
                            s.flush()
                        meta, captured = metadata(path, settings.get("exiftool"))
                        photo = PhotoAsset(
                            shoot_id=shoot_id,
                            root_id=root.id,
                            relative_path=str(path.relative_to(root_path)),
                            jpeg_path=str(jpeg.relative_to(root_path)) if jpeg else None,
                            fingerprint=digest,
                            name=path.name,
                            metadata_json=dumps(meta),
                            captured=captured,
                        )
                        s.add(photo)
                        s.flush()
                        job = s.get(ProcessingJob, job_id)
                        result = loads(job.result)
                        result["imported"] += 1
                        result["message"] = (f'Добавлено: {result["imported"]}. Восстановлено из удалённых: '
                                             f'{result["restored"]}. Уже в каталоге: {result["duplicates"]}.')
                        job.result = dumps(result)
                        item_error = self.prepare_preview(photo, path, jpeg)
                        s.add(
                            RecipeRevision(
                                photo_id=photo.id,
                                revision=0,
                                recipe=EditRecipe(runtime=processing_environment()).model_dump_json(),
                                source="default",
                            )
                        )
                self.item_done(job_id, key, item_error)
            except Exception as error:
                self.item_done(job_id, key, error)

    def prepare_preview(self, photo, path, jpeg=None):
        with protect_photo(self.catalog.directory / "cache", photo.id, photo.revision):
            try:
                preview = oriented_preview(jpeg or path)
                if path.suffix.lower() in RAW_EXTENSIONS:
                    import rawpy

                    with rawpy.imread(str(path)) as raw:
                        photo.width, photo.height = raw.sizes.width, raw.sizes.height
                        if raw.sizes.flip in (5, 6):
                            photo.width, photo.height = photo.height, photo.width
                else:
                    with Image.open(path) as original:
                        photo.width, photo.height = ImageOps.exif_transpose(original).size
                from .imaging import icc_profile

                cache = self.catalog.directory / "cache"
                preview.save(cache / f"original-{photo.id}.jpg", quality=94, icc_profile=icc_profile("srgb"))
                preview.thumbnail((420, 420))
                preview.save(cache / f"thumb-{photo.id}.jpg", quality=85, icc_profile=icc_profile("srgb"))
                photo.error = None
            except Exception as error:
                photo.error = str(error)
            return photo.error

    def snapshot(self, photo_id, source=None):
        with self.catalog.session() as s:
            photo = s.get(PhotoAsset, photo_id)
            if photo is None:
                raise ValueError("Photo not found")
            recipe = self.catalog.recipe(photo, s)
            row = s.get(AnalysisResult, photo_id)
            analysis = loads(row.data, {}) if row else {}
            s.expunge(photo)
            if source:
                for key in ("root_id", "relative_path", "fingerprint", "name"):
                    setattr(photo, key, source[key])
            path = self.catalog.photo_path(photo, s)
            if not path.is_file():
                raise ValueError("Исходник недоступен. Подключите диск или перепривяжите папку.")
            if fingerprint(path) != photo.fingerprint:
                raise ValueError(
                    "Исходник изменён вне OpenPhoto. Результат по старому рецепту не воспроизводим."
                )
            return photo, path, recipe, analysis

    def developer(self):
        settings = self.catalog.settings()
        return RawDeveloper(settings.get("rawtherapee"), self.catalog.directory / "cache",
                            cache_budget=settings.get("cache_gb", 20) * 1024**3)

    def analyze_photo(self, photo_id, payload):
        photo, path, recipe, previous = self.snapshot(photo_id)
        with protect_photo(self.catalog.directory / "cache", photo_id, photo.revision):
            settings = self.catalog.settings()
            base = self.catalog.directory / "cache" / f"base-{photo_id}-{photo.revision}.jpg"
            image = oriented_preview(base if base.exists() else path)
            if not base.exists() and recipe.version == 2 and recipe.rotation:
                image = Image.fromarray(
                    np.uint8(
                        np.clip(geometry_canvas(np.asarray(image, dtype=np.float32) / 255, recipe), 0, 1) * 255
                        + 0.5
                    )
                )
            result = analyze(
                np.asarray(image),
                self.models,
                source="developed" if base.exists() else "embedded",
                min_area=settings.get("crop_min_area", 0.8),
                legacy=recipe.version == 1,
            )
            result["input_revision"] = photo.revision
            result["canvas_width"], result["canvas_height"] = image.size
            with self.catalog.session() as s:
                accepted = [
                    loads(d.value).get("descriptor")
                    for d in s.query(UserDecision).filter_by(action="accept_crop", undone=False)
                ]
                accepted = [d for d in accepted if d]
            if len(accepted) >= 8:
                result["crops"] = propose_crops(
                    result["width"],
                    result["height"],
                    result["faces"],
                    result["poses"],
                    min_area=settings.get("crop_min_area", 0.8),
                    preferences=accepted,
                )
            if payload.get("profile_id"):
                with self.catalog.session() as s:
                    profile = s.get(StyleProfile, payload["profile_id"])
                    if profile:
                        similarity = reference_similarity(result, loads(profile.data).get("references", []))
                        result["reference_match"] = similarity
                        if similarity["similarity"] is not None:
                            result["score"] = float(
                                np.clip(result["score"] + 0.1 * (similarity["similarity"] - 0.3), 0, 1)
                            )
            model = settings.get("ranker_model")
            with self.catalog.session() as s:
                current = s.get(PhotoAsset, photo_id)
                if current.revision != photo.revision:
                    return
                s.merge(AnalysisResult(photo_id=photo_id, data=dumps(result), updated=now()))
                current.score = result["score"]
                current.learned_score = learned_score(result, model) if model else None
                current.review = result["review"]
                current.error = None
                # Auto crop is gated by measured validation, and never overrides a manual edit.
                eligible = [c for c in result["crops"] if c["auto_eligible"]]
                if (
                    settings.get("auto_crop", True)
                    and settings.get("crop_validated", False)
                    and base.exists()
                    and eligible
                    and current.revision == photo.revision
                    and not recipe.lock_crop
                    and "crop" not in loads(current.manual_sections, [])
                ):
                    recipe.crop = Crop(**eligible[0]["crop"])
                    self.catalog.save_recipe(s, current, recipe, photo.revision, "automatic_crop")

    def group_and_select(self, ids):
        from .selection import recompute_selection
        recompute_selection(self.catalog, ids)

    def render_photo(self, photo_id, expected=None, full=False):
        photo, path, recipe, data = self.snapshot(photo_id)
        with protect_photo(self.catalog.directory / "cache", photo_id, photo.revision):
            if expected is not None and expected != photo.revision:
                return
            if cached_render(self.catalog, photo, data, full):
                return
            linear = self.developer().develop(path, photo.fingerprint, recipe, 0 if full else 2048)
            canvas = geometry_canvas(linear, recipe)
            geometry_key = geometry_analysis_key(photo.fingerprint, recipe, canvas.shape)
            # Colour, retouch strength and crop do not change the pre-crop canvas.
            # Reuse its detections, but never across development or rotation changes.
            if data.get("geometry_key") == geometry_key:
                developed = dict(data)
            else:
                developed = analyze(
                    np.uint8(to_srgb(resize(canvas, 2048)) * 255 + 0.5),
                    self.models,
                    source="developed",
                    legacy=recipe.version == 1,
                )
            developed["geometry_key"] = geometry_key
            developed["input_revision"] = photo.revision
            base_variant = "fullbase" if full else "base"
            write_image(
                self.catalog.directory / "cache" / f"{base_variant}-{photo_id}-{photo.revision}.jpg", canvas
            )
            output, changed = apply_recipe(linear, recipe, developed, 0 if full else 2048)
            variant = "full" if full else "render"
            target = self.catalog.directory / "cache" / f"{variant}-{photo_id}-{photo.revision}.jpg"
            write_image(target, output)
            mask = Image.fromarray(np.uint8(np.clip(changed, 0, 1) * 255))
            mask.thumbnail((2048, 2048))
            mask.save(self.catalog.directory / "cache" / f"mask-{photo_id}-{photo.revision}.png")
            with self.catalog.session() as s:
                current = s.get(PhotoAsset, photo_id)
                if current.revision == photo.revision:
                    # Preserve source analysis as a separate property for transparent comparison.
                    developed["embedded_score"] = data.get("embedded_score", data.get("score"))
                    if not developed.get("embedding") and data.get("embedding"):
                        for key in ("embedding", "aesthetic", "reference_match"):
                            if key in data:
                                developed[key] = data[key]
                        developed["features"][5] = (data.get("aesthetic") or 5) / 10
                        developed["score"] += 0.15 * ((data.get("aesthetic") or 5) / 10 - 0.5)
                        match = data.get("reference_match", {}).get("similarity")
                        if match is not None:
                            developed["score"] = float(np.clip(developed["score"] + 0.1 * (match - 0.3), 0, 1))
                    developed["canvas_width"], developed["canvas_height"] = canvas.shape[1], canvas.shape[0]
                    if data.get("style_proposal", {}).get("input_revision") == photo.revision:
                        developed["style_proposal"] = data["style_proposal"]
                    s.merge(AnalysisResult(photo_id=photo_id, data=dumps(developed), updated=now()))
                    current.review = developed["review"]
                    current.score = developed["score"]
                    model = self.catalog.settings().get("ranker_model")
                    current.learned_score = learned_score(developed, model) if model else None
                    current.error = None
            self.group_and_select([photo_id])

    def preview_geometry(self, photo_id, payload):
        photo, path, _, _ = self.snapshot(photo_id)
        with protect_photo(self.catalog.directory / "cache", photo_id, photo.revision):
            if payload["revision"] != photo.revision:
                return
            recipe = EditRecipe.model_validate(payload["recipe"])
            image = self.developer().develop(path, photo.fingerprint, recipe, 2048)
            aligned = analyze(
                np.uint8(to_srgb(geometry_canvas(image, recipe)) * 255 + 0.5), self.models, source="developed"
            )
            output, _ = apply_recipe(image, recipe, aligned, 2048)
            write_image(
                self.catalog.directory / "cache" / f"geometry-new-{photo_id}-{photo.revision}.jpg", output
            )

    def harmonize_photo(self, photo_id, source_id):
        from .imaging import skin_masks

        photo, path, recipe, _ = self.snapshot(photo_id)
        if {"develop", "color"}.intersection(loads(photo.manual_sections, [])):
            return
        with self.catalog.session() as session:
            anchor = session.get(PhotoAsset, source_id) if source_id else None
            if not anchor or anchor.group_id != photo.group_id:
                anchor = (
                    session.query(PhotoAsset)
                    .filter_by(group_id=photo.group_id)
                    .order_by(PhotoAsset.score.desc(), PhotoAsset.id)
                    .first()
                )
            if not anchor or anchor.id == photo_id:
                return
            anchor_id = anchor.id
        reference, ref_path, ref_recipe, _ = self.snapshot(anchor_id)

        def luminance(p, filename, r):
            canvas = geometry_canvas(self.developer().develop(filename, p.fingerprint, r, 1024), r)
            aligned = analyze(
                np.uint8(to_srgb(canvas) * 255 + 0.5), self.models, source="developed", legacy=r.version == 1
            )
            mask, _ = skin_masks(canvas, aligned)
            if (mask > 0.5).sum() < 100:
                return None
            return float(np.median((canvas @ np.array([0.288, 0.712, 0], np.float32))[mask > 0.5]))

        a, b = luminance(reference, ref_path, ref_recipe), luminance(photo, path, recipe)
        if a is None or b is None or min(a, b) < 0.005:
            return
        adjustment = float(np.clip(np.log2(a / b), -0.5, 0.5))
        recipe.color.exposure = float(np.clip(ref_recipe.color.exposure + adjustment, -2, 2))
        with self.catalog.session() as session:
            current = session.get(PhotoAsset, photo_id)
            current_anchor = session.get(PhotoAsset, anchor_id)
            if (
                current.revision == photo.revision
                and current_anchor.revision == reference.revision
                and not {"develop", "color"}.intersection(loads(current.manual_sections, []))
            ):
                self.catalog.save_recipe(
                    session, current, recipe, photo.revision, "exposure_harmonize", ["color"]
                )

    def propose_style(self, photo_id, payload):
        photo, path, recipe, analysis = self.snapshot(photo_id)
        with protect_photo(self.catalog.directory / "cache", photo_id, photo.revision):
            with self.catalog.session() as s:
                profile = s.get(StyleProfile, payload["profile_id"])
                if not profile:
                    raise ValueError("Профиль не найден")
                references = [r for r in loads(profile.data).get("references", []) if "color" in r["roles"]]
            if not references:
                raise ValueError("В профиле нет цветовых референсов")
            image = self.developer().develop(path, photo.fingerprint, recipe, 1024)
            stats = np.asarray(color_statistics(image))
            # Select an exemplar; do not average unrelated looks.
            reference = min(
                references, key=lambda r: np.linalg.norm(stats[:5] - np.asarray(r["color_stats"])[:5])
            )
            canvas = geometry_canvas(image, recipe)
            aligned = analyze(
                np.uint8(to_srgb(resize(canvas, 1024)) * 255 + 0.5),
                self.models,
                source="developed",
                legacy=recipe.version == 1,
            )
            mask = face_skin_mask(canvas.shape, aligned)
            suggestion = match_color(
                canvas,
                reference["color_stats"],
                payload.get("strength", 0.6),
                mask,
                reference.get("region_stats"),
                self.models.regions,
                legacy=not extended_range(recipe),
            )
            variants = []
            for name, strength in ((("soft", 0.35), ("medium", 0.65), ("strong", 1.0)) if payload.get("variants", True) else ()):
                variant_recipe = recipe.model_copy(deep=True)
                variant_recipe.color = suggestion.model_copy(update={"strength": strength})
                output, _ = apply_recipe(image, variant_recipe, aligned, 1024)
                write_image(
                    self.catalog.directory / "cache" / f"style-{name}-{photo_id}-{photo.revision}.jpg", output
                )
                variants.append({"name": name, "color": variant_recipe.color.model_dump()})
            analysis["style_proposal"] = {
                "color": suggestion.model_dump(),
                "reference_id": reference["id"],
                "profile_id": payload["profile_id"],
                "input_revision": photo.revision,
                "variants": variants,
            }
            with self.catalog.session() as s:
                current = s.get(PhotoAsset, photo_id)
                if current.revision == photo.revision:
                    s.merge(AnalysisResult(photo_id=photo_id, data=dumps(analysis), updated=now()))

    def import_profile(self, job_id, payload, checkpoint):
        from .imaging import icc_profile

        files, errors = discover(payload["paths"], references=True)
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            result = loads(job.result, {})
            profile_id = result.get("profile_id")
            if not profile_id:
                profile = StyleProfile(name=payload["name"], data=dumps({"references": [], "version": 1}))
                s.add(profile)
                s.flush()
                profile_id = profile.id
                job.result = dumps({"profile_id": profile_id, "errors": errors})
            job.total = len(files)
        for path, _, _ in files:
            if self.stopped(job_id):
                return
            if self.yield_to_interactive(job_id):
                return
            if str(path) in checkpoint:
                continue
            try:
                im = oriented_preview(path, 2048)
                data = analyze(np.asarray(im), self.models, source="reference")
                reference_id = uid()
                im.save(self.catalog.directory / "references" / f"{reference_id}.jpg", quality=96,
                        icc_profile=icc_profile("srgb"))
                ref = {
                    "id": reference_id,
                    "name": path.name,
                    "roles": payload["roles"],
                    "color_stats": data["color_stats"],
                    "region_stats": data.get("region_stats", {}),
                    "embedding": data["embedding"],
                    "composition": data["composition"],
                    "fingerprint": fingerprint(path),
                }
                with self.catalog.session() as s:
                    profile = s.get(StyleProfile, profile_id)
                    profile_data = loads(profile.data)
                    if not any(r["fingerprint"] == ref["fingerprint"] for r in profile_data["references"]):
                        profile_data["references"].append(ref)
                    profile.data = dumps(profile_data)
                self.item_done(job_id, str(path))
            except Exception as error:
                self.item_done(job_id, str(path), error)

    def export_photo(self, job_id, photo_id, request: ExportRequest):
        from . import exports

        with self.catalog.session() as s:
            frozen = loads(s.get(ProcessingJob, job_id).result, {}).get("snapshots", {}).get(photo_id, {})
        photo, path, recipe, analysis = self.snapshot(photo_id, frozen.get("source"))
        directory = Path(request.directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        with self.catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            result = loads(job.result, {})
            snapshot = result.get("snapshots", {}).get(photo_id)
            if snapshot:
                recipe = EditRecipe.model_validate(snapshot["recipe"])
                photo.revision, photo.rating, photo.status = (
                    snapshot["revision"],
                    snapshot["rating"],
                    snapshot["status"],
                )
            records = result.setdefault("files", {})
            record = records.get(photo_id)
            if record and record.get("state") == "committed":
                if all(
                    exports.owned(directory / name, expected) for name, expected in record["prepared"].items()
                ):
                    exports.cleanup(record)
                    return
                raise ValueError("Завершённый экспорт изменён или перемещён. Создайте новое задание.")
            if record and record.get("state") in {"reserved", "prepared"}:
                recipe = EditRecipe.model_validate(record["recipe"])
            else:
                extension = ".jpg" if request.format == "jpeg" else ".tiff"
                suffixes = (
                    [""]
                    + ([".xmp"] if request.xmp else [])
                    + ([".openphoto.json"] if request.recipes else [])
                )
                record = exports.reserve_bundle(
                    directory,
                    Path(photo.name).stem + "_openphoto",
                    extension,
                    suffixes,
                    job_id + "-" + photo_id,
                )
                record.update(revision=photo.revision, recipe=recipe.model_dump())
                records[photo_id] = record
                job.result = dumps(result)

        def checkpoint():
            with self.catalog.session() as session:
                job = session.get(ProcessingJob, job_id)
                result = loads(job.result, {})
                result.setdefault("files", {})[photo_id] = record
                job.result = dumps(result)

        try:
            if record["state"] != "prepared":
                target = Path(record["staging"]) / Path(record["path"]).name
                linear = self.developer().develop(path, photo.fingerprint, recipe)
                from .analysis import ANALYSIS_VERSION
                from .imaging import recipe_needs_masks

                aligned = {"version": ANALYSIS_VERSION, "source": "not_required", "faces": []}
                if recipe_needs_masks(recipe):
                    preview = resize(geometry_canvas(linear, recipe), 2048)
                    aligned = analyze(
                        np.uint8(to_srgb(preview) * 255 + 0.5),
                        self.models,
                        source="developed",
                        legacy=recipe.version == 1,
                    )
                output, _ = apply_recipe(linear, recipe, aligned, request.long_edge)
                write_image(target, output, request.format, request.profile, request.quality, request.sharpen)
                if request.recipes:
                    manifest = {
                        "schema": 1,
                        "source_name": photo.name,
                        "source_sha256": photo.fingerprint,
                        "revision": record["revision"],
                        "recipe": recipe.model_dump(),
                        "output": {
                            "format": request.format,
                            "profile": request.profile,
                            "long_edge": request.long_edge,
                            "sharpen": request.sharpen,
                        },
                        "analysis_version": aligned["version"],
                        "analysis": aligned,
                        "models": json.loads(
                            (Path(__file__).parent / "resources/models.lock.json").read_text(encoding="utf-8")
                        ),
                    }
                    atomic_text(target.with_suffix(target.suffix + ".openphoto.json"), dumps(manifest))
                if request.xmp:
                    write_xmp(target.with_suffix(target.suffix + ".xmp"), photo.rating, photo.status)
                exports.prepare(record)
                checkpoint()
            if self.stopped(job_id):
                raise InterruptedError("Экспорт приостановлен или отменён")
            exports.publish(record)
            checkpoint()
            exports.cleanup(record)
        except Exception:
            if record["state"] != "committed":
                exports.cleanup(record, rollback=True)
                record["state"] = "failed"
                checkpoint()
            raise

    def train(self, job_id):
        analyses, shoots, pairs = {}, {}, []
        with self.catalog.session() as s:
            for photo, row in s.query(PhotoAsset, AnalysisResult).join(
                AnalysisResult, PhotoAsset.id == AnalysisResult.photo_id
            ):
                data = loads(row.data)
                if data.get("features"):
                    analyses[photo.id], shoots[photo.id] = data, photo.shoot_id
            for decision in s.query(UserDecision).filter_by(action="compare", undone=False):
                if decision.other_id:
                    pairs.append((decision.photo_id, decision.other_id))
            # Only pairs of explicit ratings from the SAME burst contribute; unreviewed != negative.
            photos = s.query(PhotoAsset).filter(PhotoAsset.rating > 0).all()
            groups = {}
            for p in photos:
                groups.setdefault(p.group_id, []).append(p)
            for group in groups.values():
                for a in group:
                    for b in group:
                        if a.rating >= b.rating + 2:
                            pairs.append((a.id, b.id))
        model, status = fit_ranker(
            list(set(pairs)), analyses, shoots, self.catalog.settings().get("ranker_model")
        )
        if model:
            self.catalog.set_setting("ranker_model", model)
            with self.catalog.session() as s:
                for photo in s.query(PhotoAsset):
                    if photo.id in analyses:
                        photo.learned_score = learned_score(analyses[photo.id], model)
        self.group_and_select(list(analyses))
        self.catalog.set_setting("ranker_status", status)
        self.update(job_id, total=1, completed=1, result=dumps(status))

    def trim_cache(self):
        from .cache import trim

        budget = self.catalog.settings().get("cache_gb", 20) * 1024**3
        trim(self.catalog.directory / "cache", budget)


def reserve_path(directory, stem, extension):
    for number in range(100000):
        path = directory / f"{stem}{'' if number == 0 else '_' + str(number)}{extension}"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return path
        except FileExistsError:
            continue
    raise RuntimeError("Не удалось подобрать свободное имя файла")


def atomic_text(path, text):
    import tempfile

    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".openphoto-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_xmp(path, rating, status):
    xmp = "http://ns.adobe.com/xap/1.0/"
    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    ET.register_namespace("x", "adobe:ns:meta/")
    ET.register_namespace("rdf", rdf)
    ET.register_namespace("xmp", xmp)
    root = ET.Element("{adobe:ns:meta/}xmpmeta")
    element = ET.SubElement(root, f"{{{rdf}}}RDF")
    ET.SubElement(
        element,
        f"{{{rdf}}}Description",
        {
            f"{{{rdf}}}about": "",
            f"{{{xmp}}}Rating": str(-1 if status == "reject" else rating),
            f"{{{xmp}}}Label": "Selected" if status == "keep" else "",
        },
    )
    atomic_text(path, ET.tostring(root, encoding="unicode"))


def worker_loop(directory, stop_event, lane=None, idle_seconds=120):
    import traceback
    import time

    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    pipeline = Pipeline(directory, lane)
    pipeline.stop_event = stop_event
    kinds = {
        "analysis": ["analyze", "profile", "train"],
        "render": ["render", "style", "export"],
        "import": ["import"],
    }.get(lane)
    idle_since = time.monotonic()
    while not stop_event.is_set():
        job_id = None
        with pipeline.catalog.session() as s:
            query = s.query(ProcessingJob).filter_by(state="queued")
            if kinds:
                query = query.filter(ProcessingJob.kind.in_(kinds))
            job = query.order_by(ProcessingJob.priority, ProcessingJob.created).first()
            if job:
                job.state = "running"
                job.updated = now()
                job_id = job.id
        if job_id is None:
            if time.monotonic() - idle_since >= idle_seconds:
                break
            stop_event.wait(0.3)
            continue
        try:
            pipeline.run(job_id)
        except Exception as error:
            with pipeline.catalog.session() as s:
                job = s.get(ProcessingJob, job_id)
                if job and job.state not in {"cancelled", "paused"}:
                    job.state, job.error, job.updated = "failed", str(error), now()
            log = Path(directory) / "logs" / "worker.log"
            with log.open("a", encoding="utf-8") as stream:
                stream.write(f"\n{now()} {job_id}\n{traceback.format_exc()}")
        idle_since = time.monotonic()
    pipeline.catalog.engine.dispose()
