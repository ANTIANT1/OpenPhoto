from __future__ import annotations

import asyncio
import importlib.metadata
import json
import secrets
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from . import __version__
from .analysis import MODEL_FILES, propose_crops
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
)
from .schemas import (
    BatchRecipeRequest,
    Crop,
    DecisionRequest,
    EditRecipe,
    ExportRequest,
    GroupRequest,
    ImportRequest,
    JobRequest,
    ProfileRequest,
    RecipeRequest,
    RecipeFileRequest,
    ReferenceRolesRequest,
    SettingsPatch,
)
from .service import cached_render, enqueue, public_photo


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def create_app(directory: str | Path, token: str | None = None, start_worker=True):
    catalog = Catalog(directory)
    from .locking import ProjectLock
    from .dependencies import resolve_dependencies

    lock = ProjectLock(catalog.directory)
    lock.acquire()
    token = token or secrets.token_urlsafe(32)
    root = resource_root()
    try:
        catalog.initialize()
        resolve_dependencies(catalog, root)
    except Exception:
        catalog.engine.dispose()
        lock.release()
        raise

    @asynccontextmanager
    async def lifespan(app):
        # Unfinished work is resumable, not silently started on next launch.
        with catalog.session() as s:
            for job in s.query(ProcessingJob).filter_by(state="running"):
                job.state = "paused"
                job.error = "Обработка была прервана. Можно продолжить с сохранённого этапа."
        from .job_lifecycle import recover_exports

        recover_exports(catalog)
        supervisor = None
        if start_worker:
            from .processes import WorkerSupervisor

            supervisor = WorkerSupervisor(catalog)
            supervisor.start()
        app.state.supervisor = supervisor
        try:
            yield
        finally:
            if supervisor:
                supervisor.close()
            catalog.engine.dispose()
            lock.release()

    app = FastAPI(
        title="OpenPhoto local API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.catalog, app.state.token = catalog, token
    from .projects import register_project_routes

    register_project_routes(app, catalog)
    from .workflows import register_workflows

    register_workflows(app, catalog)
    import threading

    preview_slots = threading.BoundedSemaphore(2)
    import weakref

    weakref.finalize(app, lock.release)

    @app.middleware("http")
    async def security(request: Request, call_next):
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "testserver"}:
            return JSONResponse({"detail": "Invalid local host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Cross-origin request denied"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-openphoto-token", "")
            if request.method in {"GET", "HEAD"}:
                supplied = supplied or request.cookies.get("openphoto_session", "")
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"detail": "Session token required"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409 if "Revision" in str(error) else 400)

    @app.exception_handler(IntegrityError)
    async def conflicting_write(request, error):
        return JSONResponse(
            {"detail": "Конфликт изменений. Обновите данные и повторите действие."}, status_code=409
        )

    def get_photo(s, identifier):
        photo = s.get(PhotoAsset, identifier)
        if not photo:
            raise HTTPException(404, "Фотография не найдена")
        return photo

    @app.get("/api/status")
    def status():
        settings = catalog.settings()
        models_dir = Path(settings.get("models_directory", catalog.directory / "models"))
        packages = {}
        for name in ("torch", "mediapipe", "rawpy", "open-clip-torch", "imagecodecs"):
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
        return {
            "version": __version__,
            "project": str(catalog.directory),
            "export_directory": settings.get("last_export_directory", str(Path.home() / "Pictures" / "OpenPhoto" / "Exports")),
            "settings": settings,
            "resources": app.state.supervisor.status()
            if getattr(app.state, "supervisor", None)
            else {"worker_pid": None},
            "models": {name: (models_dir / file).is_file() for name, file in MODEL_FILES.items()},
            "packages": packages,
            "raw_ready": Path(settings.get("rawtherapee", "__missing__")).is_file(),
            "disk_free": shutil.disk_usage(catalog.directory).free,
            "auto_crop_active": bool(
                settings.get("auto_crop", True) and settings.get("crop_validated", False)
            ),
        }

    @app.patch("/api/settings")
    def update_settings(body: SettingsPatch):
        for key, value in body.model_dump(exclude_none=True).items():
            if key in {"rawtherapee", "exiftool"} and value and not Path(value).is_file():
                raise HTTPException(400, f"Файл не найден: {value}")
            if key == "models_directory" and value and not Path(value).is_dir():
                raise HTTPException(400, "Папка моделей не найдена")
            catalog.set_setting(key, value)
            if key in {"rawtherapee", "exiftool", "models_directory"}:
                catalog.set_setting(key + "_source", "custom" if value else "bundled")
        resolve_dependencies(catalog, root)
        if body.keeper_fraction is not None:
            from .selection import recompute_selection

            recompute_selection(catalog)
        return catalog.settings()

    @app.get("/api/shoots")
    def shoots():
        with catalog.session() as s:
            return [
                {
                    "id": shoot.id,
                    "name": shoot.name,
                    "created": shoot.created,
                    "count": s.query(PhotoAsset).filter_by(shoot_id=shoot.id).filter(PhotoAsset.status != "removed").count(),
                }
                for shoot in s.query(Shoot).order_by(Shoot.created.desc())
            ]

    @app.get("/api/photos")
    def photos(
        shoot_id: str | None = None,
        filter: str = "all",
        sort: str = "time",
        offset: int = 0,
        limit: int = 1000,
    ):
        with catalog.session() as s:
            query = s.query(PhotoAsset)
            query = query.filter(PhotoAsset.status == "removed" if filter == "removed" else PhotoAsset.status != "removed")
            if shoot_id:
                query = query.filter_by(shoot_id=shoot_id)
            if filter == "keep":
                query = query.filter_by(status="keep")
            elif filter == "suggested":
                query = query.filter(PhotoAsset.suggested, PhotoAsset.status != "reject")
            elif filter == "review":
                query = query.filter_by(review=True)
            elif filter == "reject":
                query = query.filter_by(status="reject")
            total = query.count()
            order = {
                "time": PhotoAsset.captured,
                "score": PhotoAsset.score.desc(),
                "taste": PhotoAsset.learned_score.desc(),
                "rating": PhotoAsset.rating.desc(),
            }.get(sort, PhotoAsset.captured)
            items = (
                query.order_by(order, PhotoAsset.id)
                .offset(max(0, offset))
                .limit(min(2000, max(1, limit)))
                .all()
            )
            return {"total": total, "photos": [public_photo(p) for p in items]}

    @app.get("/api/photos/{identifier}")
    def detail(identifier: str):
        with catalog.session() as s:
            photo = get_photo(s, identifier)
            row = s.get(AnalysisResult, identifier)
            result = public_photo(photo, loads(row.data) if row else None)
            result["recipe"] = catalog.recipe(photo, s).model_dump()
            draft = s.get(RecipeDraft, identifier)
            result["draft"] = loads(draft.recipe) if draft and draft.revision == photo.revision else None
            result["manual_sections"] = loads(photo.manual_sections, [])
            result["history"] = [
                {"revision": r.revision, "source": r.source, "created": r.created}
                for r in s.query(RecipeRevision)
                .filter_by(photo_id=identifier)
                .order_by(RecipeRevision.revision.desc())
            ]
            return result

    @app.put("/api/photos/{identifier}/draft")
    def save_draft(identifier: str, body: RecipeRequest):
        with catalog.session() as s:
            photo = get_photo(s, identifier)
            if body.expected_revision != photo.revision:
                raise HTTPException(409, "Черновик относится к предыдущей версии")
            s.merge(
                RecipeDraft(
                    photo_id=identifier, revision=photo.revision, recipe=body.recipe.model_dump_json()
                )
            )
        return {"saved": True}

    @app.get("/api/photos/{identifier}/image")
    def image(identifier: str, variant: str = "thumb", revision: int = 0):
        if variant not in {
            "thumb",
            "original",
            "camera",
            "camera-full",
            "render",
            "mask",
            "base",
            "full",
            "fullbase",
            "style-soft",
            "style-medium",
            "style-strong",
            "geometry-new",
        }:
            raise HTTPException(400, "Unknown image variant")
        with catalog.session() as s:
            photo = get_photo(s, identifier)
            if variant.startswith("camera") and not photo.jpeg_path:
                raise HTTPException(404, "У кадра нет JPEG камеры")
            source = catalog.photo_path(
                photo, s, jpeg=variant in {"thumb", "original", "camera", "camera-full"}
            )
        extension = "png" if variant == "mask" else "jpg"
        name = f"{variant}-{identifier}{'-' + str(revision) if variant not in {'thumb', 'original', 'camera'} else ''}.{extension}"
        path = catalog.directory / "cache" / name
        from .cache import lease, release_lease, trim

        budget = catalog.settings().get("cache_gb", 20) * 1024**3
        marker = lease(path, seconds=120)
        stream = None
        try:
            if not path.is_file() and variant in {"thumb", "original", "camera", "camera-full"}:
                from .imaging import oriented_preview, write_preview

                try:
                    with preview_slots:
                        preview = oriented_preview(
                            source, 420 if variant == "thumb" else max(photo.width, photo.height)
                            if variant == "camera-full" else 2048,
                        )
                        write_preview(preview, path)
                except Exception as error:
                    raise HTTPException(404, f"Превью недоступно: {error}") from error
            if not path.is_file():
                raise HTTPException(404, "Превью ещё не готово")
            stream = path.open("rb")
            trim(catalog.directory / "cache", budget)
        except BaseException:
            if stream:
                stream.close()
            release_lease(marker)
            raise

        def release_image():
            stream.close()
            release_lease(marker)

        def chunks():
            try:
                while chunk := stream.read(1024 * 1024):
                    yield chunk
            finally:
                release_image()
                trim(catalog.directory / "cache", budget)

        from starlette.background import BackgroundTask
        response = StreamingResponse(chunks(), media_type=f"image/{'png' if extension == 'png' else 'jpeg'}",
                                     background=BackgroundTask(release_image))
        weakref.finalize(response, release_image)
        return response

    @app.post("/api/import")
    def import_photos(body: ImportRequest):
        return {"job_id": enqueue(catalog, "import", body.model_dump())}

    @app.post("/api/analyze")
    def analysis(body: JobRequest):
        return {"job_id": enqueue(catalog, "analyze", body.model_dump(), 20)}

    @app.post("/api/style/propose")
    def style(body: JobRequest):
        if not body.profile_id:
            raise HTTPException(400, "Выберите профиль референсов")
        return {"job_id": enqueue(catalog, "style", body.model_dump(), 10)}

    @app.post("/api/photos/{identifier}/render")
    def render(identifier: str, full: bool = False):
        with catalog.session() as s:
            photo = get_photo(s, identifier)
            revision = photo.revision
            row = s.get(AnalysisResult, identifier)
            if cached_render(catalog, photo, loads(row.data, {}) if row else {}, full):
                return {"job_id": None, "revision": revision, "cached": True}
            for j in s.query(ProcessingJob).filter(
                ProcessingJob.kind == "render", ProcessingJob.state.in_(["queued", "running"])
            ):
                p = loads(j.payload)
                if (
                    p.get("photo_ids") == [identifier]
                    and p.get("revision") == revision
                    and p.get("full", False) == full
                ):
                    return {"job_id": j.id, "revision": revision}
        return {
            "job_id": enqueue(
                catalog, "render", {"photo_ids": [identifier], "revision": revision, "full": full}, 0
            ),
            "revision": revision,
        }

    @app.put("/api/photos/{identifier}/recipe")
    def save_recipe(identifier: str, body: RecipeRequest):
        with catalog.session() as s:
            photo = get_photo(s, identifier)
            previous = catalog.recipe(photo, s).model_dump()
            current = body.recipe.model_dump()
            sections = [k for k in ("develop", "color", "retouch", "crop") if previous[k] != current[k]]
            if previous["rotation"] != current["rotation"] or previous["lock_crop"] != current["lock_crop"]:
                sections.append("crop")
            revision = catalog.save_recipe(
                s, photo, body.recipe, body.expected_revision, body.source, sections
            )
            if "crop" in sections:
                from .analysis import crop_descriptor, subject_box

                row = s.get(AnalysisResult, identifier)
                data = loads(row.data, {}) if row else {}
                descriptor = crop_descriptor(
                    subject_box(data.get("faces", []), data.get("poses", [])), body.recipe.crop
                )
                s.add(
                    UserDecision(
                        photo_id=identifier,
                        action="accept_crop",
                        value=dumps({"crop": current["crop"], "descriptor": descriptor}),
                        previous=dumps(previous["crop"]),
                    )
                )
        return {
            "revision": revision,
            "job_id": enqueue(catalog, "render", {"photo_ids": [identifier], "revision": revision}, 0),
        }

    @app.post("/api/photos/{identifier}/restore/{revision}")
    def restore(identifier: str, revision: int):
        with catalog.session() as s:
            photo = get_photo(s, identifier)
            row = s.get(RecipeRevision, (identifier, revision))
            if not row:
                raise HTTPException(404, "Версия не найдена")
            new_revision = catalog.save_recipe(
                s, photo, EditRecipe.model_validate_json(row.recipe), photo.revision, "restore"
            )
        return {
            "revision": new_revision,
            "job_id": enqueue(catalog, "render", {"photo_ids": [identifier], "revision": new_revision}, 0),
        }

    @app.post("/api/photos/{identifier}/migrate-runtime")
    def migrate_runtime(identifier: str):
        from .imaging import processing_environment

        with catalog.session() as s:
            photo = get_photo(s, identifier)
            recipe = catalog.recipe(photo, s)
            recipe.runtime = processing_environment(recipe.version)
            revision = catalog.save_recipe(s, photo, recipe, photo.revision, "engine_migration")
        return {
            "revision": revision,
            "job_id": enqueue(catalog, "render", {"photo_ids": [identifier], "revision": revision}, 0),
        }

    @app.post("/api/recipes/batch")
    def batch(body: BatchRecipeRequest):
        updated, skipped = [], []
        with catalog.session() as s:
            intention = None
            source_data = {}
            source_photo = None
            if body.source_photo_id:
                from .analysis import crop_descriptor, subject_box

                source_photo = get_photo(s, body.source_photo_id)
                source_analysis = s.get(AnalysisResult, body.source_photo_id)
                source_data = loads(source_analysis.data, {}) if source_analysis else {}
                intention = crop_descriptor(
                    subject_box(source_data.get("faces", []), source_data.get("poses", [])), body.recipe.crop
                )
            targets = body.photo_ids
            if body.scope != "selection":
                if not source_photo:
                    raise HTTPException(400, "Для настроек группы или съёмки нужен исходный кадр")
                shoot = s.get(Shoot, source_photo.shoot_id)
                settings = loads(shoot.settings, {})
                layer = (
                    settings.setdefault("recipe", {})
                    if body.scope == "shoot"
                    else settings.setdefault("groups", {}).setdefault(source_photo.group_id, {})
                )
                for section in body.sections:
                    if section != "crop":
                        layer[section] = body.recipe.model_dump()[section]
                shoot.settings = dumps(settings)
                query = s.query(PhotoAsset).filter_by(shoot_id=source_photo.shoot_id)
                if body.scope == "group":
                    query = query.filter_by(group_id=source_photo.group_id)
                targets = [p.id for p in query if p.id != source_photo.id]
            for identifier in targets:
                photo = get_photo(s, identifier)
                recipe = catalog.recipe(photo, s)
                settings = loads(s.get(Shoot, photo.shoot_id).settings, {})
                group_layer = settings.get("groups", {}).get(photo.group_id, {})
                manual = loads(photo.manual_sections, [])
                changed = []
                for section in body.sections:
                    if body.preserve_manual and section in manual:
                        continue
                    if body.scope == "shoot" and section in group_layer:
                        continue
                    if section == "crop":
                        row = s.get(AnalysisResult, identifier)
                        data = loads(row.data, {}) if row else {}
                        ratio_source = source_photo or photo
                        source_data = (
                            loads(source_analysis.data, {}) if source_photo and source_analysis else data
                        )
                        ratio = (
                            source_data.get("canvas_width", ratio_source.width)
                            / max(source_data.get("canvas_height", ratio_source.height), 1)
                            * body.recipe.crop.w
                            / body.recipe.crop.h
                        )
                        options = propose_crops(
                            data.get("canvas_width", photo.width),
                            data.get("canvas_height", photo.height),
                            data.get("faces", []),
                            data.get("poses", []),
                            ratio,
                            preferences=[intention] if intention else [],
                        )
                        safe = [o for o in options if o["safe"]]
                        if not safe:
                            photo.review_flags = dumps(sorted(set(loads(photo.review_flags, [])) | {"crop_transfer"}))
                            photo.review = True
                            continue
                        recipe.crop = Crop(**safe[0]["crop"])
                        photo.review_flags = dumps([f for f in loads(photo.review_flags, []) if f != "crop_transfer"])
                    elif section == "retouch":
                        # Strength transfers; source patches, brush strokes and disabled face IDs do not.
                        recipe.retouch.strength = body.recipe.retouch.strength
                        recipe.retouch.color_evenness = body.recipe.retouch.color_evenness
                        recipe.retouch.body_strength = body.recipe.retouch.body_strength
                        recipe.retouch.body_color_evenness = body.recipe.retouch.body_color_evenness
                    elif section == "develop":
                        from .imaging import RAW_EXTENSIONS

                        if Path(photo.relative_path).suffix.lower() in RAW_EXTENSIONS:
                            recipe.develop = body.recipe.develop.model_copy(deep=True)
                        else:
                            recipe.develop.exposure = body.recipe.develop.exposure
                    else:
                        setattr(recipe, section, getattr(body.recipe, section).model_copy(deep=True))
                    changed.append(section)
                if changed:
                    catalog.save_recipe(s, photo, recipe, photo.revision, "batch_" + body.scope, changed)
                    updated.append(identifier)
                else:
                    skipped.append(identifier)
        return {
            "updated": updated,
            "skipped": skipped,
            "job_id": enqueue(
                catalog,
                "render",
                {
                    "photo_ids": updated,
                    "harmonize_exposure": body.harmonize_exposure,
                    "source_photo_id": body.source_photo_id,
                },
                10,
            )
            if updated
            else None,
        }

    @app.post("/api/recipes/restore-file")
    def restore_file(body: RecipeFileRequest):
        path = Path(body.path).expanduser().resolve()
        if not path.is_file() or path.stat().st_size > 10 * 1024**2:
            raise HTTPException(400, "Файл рецепта недоступен или слишком большой")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        recipe = EditRecipe.model_validate(manifest.get("recipe"))
        with catalog.session() as s:
            photo = get_photo(s, body.photo_id)
            if photo.fingerprint != manifest.get("source_sha256"):
                raise HTTPException(409, "Рецепт относится к другому исходнику")
            installed = Path(__file__).parent / "resources" / "models.lock.json"
            models = json.loads(installed.read_text(encoding="utf-8")) if installed.is_file() else {}
            for name, model in manifest.get("models", {}).items():
                if models.get(name, {}).get("sha256") != model.get("sha256"):
                    raise HTTPException(409, f"Для точного повторения нужна исходная версия модели {name}")
            revision = catalog.save_recipe(s, photo, recipe, body.expected_revision, "restore")
        return {
            "revision": revision,
            "job_id": enqueue(catalog, "render", {"photo_ids": [body.photo_id], "revision": revision}, 0),
        }

    @app.post("/api/decisions")
    def decision(body: DecisionRequest):
        from .database import uid

        if body.action == "rating" and (not isinstance(body.value, int) or not 0 <= body.value <= 5):
            raise HTTPException(400, "Rating must be 0–5")
        identifiers, operation = list(dict.fromkeys(body.photo_ids)), uid()
        with catalog.session() as s:
            for identifier in identifiers:
                photo = get_photo(s, identifier)
                old = {"status": photo.status, "rating": photo.rating}
                if body.action == "remove":
                    if photo.status == "removed":
                        continue
                    photo.status = "removed"
                elif body.action == "restore_removed":
                    if photo.status != "removed":
                        continue
                    removal = s.query(UserDecision).filter_by(photo_id=identifier, action="remove", undone=False).order_by(UserDecision.created.desc(), UserDecision.id.desc()).first()
                    previous = loads(removal.previous, {}) if removal else {}
                    photo.status = previous.get("status", "unreviewed")
                elif photo.status == "removed":
                    raise HTTPException(409, "Сначала верните кадр из удалённых")
                elif body.action in {"keep", "reject", "clear"}:
                    photo.status = "unreviewed" if body.action == "clear" else body.action
                elif body.action == "rating":
                    photo.rating = body.value
                elif body.action == "compare":
                    other = get_photo(s, body.other_id)
                    if identifier == other.id or photo.shoot_id != other.shoot_id or other.status == "removed":
                        raise HTTPException(400, "Сравнивайте разные кадры одной съёмки")
                    photo.status = "keep"
                s.add(
                    UserDecision(
                        operation_id=operation,
                        photo_id=identifier,
                        other_id=body.other_id,
                        action=body.action,
                        value=dumps(body.value),
                        previous=dumps(old),
                    )
                )
            if body.action in {"remove", "restore_removed"}:
                from .selection import recompute_selection

                s.flush()
                recompute_selection(catalog, identifiers, s)
        return {"updated": len(identifiers)}

    @app.post("/api/decisions/undo")
    def undo():
        with catalog.session() as s:
            row = (
                s.query(UserDecision)
                .filter_by(undone=False)
                .filter(UserDecision.action != "accept_crop")
                .order_by(UserDecision.created.desc())
                .first()
            )
            if not row:
                return {"undone": False}
            rows = s.query(UserDecision).filter_by(operation_id=row.operation_id, undone=False).order_by(
                UserDecision.created.desc(), UserDecision.id.desc()
            ).all() if row.operation_id else [row]
            ids = []
            for item in rows:
                photo = get_photo(s, item.photo_id)
                old = loads(item.previous, {})
                photo.status, photo.rating = old.get("status", photo.status), old.get("rating", photo.rating)
                item.undone = True
                ids.append(photo.id)
            if any(item.action in {"remove", "restore_removed"} for item in rows):
                from .selection import recompute_selection

                s.flush()
                recompute_selection(catalog, ids, s)
            return {"undone": True, "photo_id": row.photo_id, "photo_ids": ids}

    @app.post("/api/groups")
    def groups(body: GroupRequest):
        from .database import uid

        group = uid()
        with catalog.session() as s:
            for identifier in body.photo_ids:
                photo = get_photo(s, identifier)
                photo.group_id = group if body.action == "merge" else uid()
                photo.group_locked = True
            from .selection import recompute_selection

            s.flush()
            recompute_selection(catalog, body.photo_ids, s)
        return {"updated": len(body.photo_ids)}

    @app.get("/api/profiles")
    def profiles():
        with catalog.session() as s:
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "references": [
                        {k: v for k, v in r.items() if k != "embedding"}
                        for r in loads(p.data).get("references", [])
                    ],
                }
                for p in s.query(StyleProfile).order_by(StyleProfile.created.desc())
            ]

    @app.post("/api/profiles")
    def create_profile(body: ProfileRequest):
        return {"job_id": enqueue(catalog, "profile", body.model_dump(), 15)}

    @app.patch("/api/profiles/{profile_id}/references/{reference_id}")
    def reference_roles(profile_id: str, reference_id: str, body: ReferenceRolesRequest):
        with catalog.session() as s:
            profile = s.get(StyleProfile, profile_id)
            if not profile:
                raise HTTPException(404)
            data = loads(profile.data)
            reference = next((r for r in data["references"] if r["id"] == reference_id), None)
            if not reference:
                raise HTTPException(404)
            reference["roles"] = list(dict.fromkeys(body.roles))
            profile.data = dumps(data)
        return {"updated": True}

    @app.get("/api/references/{identifier}")
    def reference_image(identifier: str):
        if len(identifier) != 32 or not all(c in "0123456789abcdef" for c in identifier):
            raise HTTPException(404)
        path = catalog.directory / "references" / f"{identifier}.jpg"
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/ranker/train")
    def train():
        return {"job_id": enqueue(catalog, "train", {}, 30)}

    @app.post("/api/export")
    def export(body: ExportRequest):
        job_id = enqueue(catalog, "export", body.model_dump(), 40)
        catalog.set_setting("last_export_directory", str(Path(body.directory).expanduser().resolve()))
        return {"job_id": job_id}

    @app.get("/api/roots")
    def roots():
        with catalog.session() as s:
            return [{"id": r.id, "path": r.path, "available": Path(r.path).is_dir()} for r in s.query(Root)]

    @app.post("/api/roots/{identifier}/relink")
    def relink(identifier: str, body: dict):
        path = Path(body.get("path", "")).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(400, "Папка недоступна")
        with catalog.session() as s:
            root_row = s.get(Root, identifier)
            if root_row is None:
                raise HTTPException(404)
            photos = s.query(PhotoAsset).filter_by(root_id=identifier).all()
            mismatched = []
            from .imaging import fingerprint

            for photo in photos:
                source = (path / photo.relative_path).resolve()
                if (
                    not source.is_relative_to(path)
                    or not source.is_file()
                    or fingerprint(source) != photo.fingerprint
                ):
                    mismatched.append(photo.name)
            if mismatched:
                raise HTTPException(400, f"Исходники не совпадают: {', '.join(mismatched[:5])}")
            root_row.path = str(path)
        return {"updated": True}

    from .job_views import register_job_views

    job_list = register_job_views(app, catalog)

    @app.post("/api/jobs/{identifier}/{action}")
    def control_job(identifier: str, action: str):
        with catalog.session() as s:
            job = s.get(ProcessingJob, identifier)
            if not job:
                raise HTTPException(404)
            if action == "pause" and job.state in {"queued", "running"}:
                job.state = "paused"
            elif action == "cancel" and job.state in {"queued", "running", "paused"}:
                job.state = "cancelled"
            elif action in {"resume", "retry"} and job.state in {"paused", "failed", "completed_with_errors"}:
                if action == "retry":
                    failed = {e["item"] for e in loads(job.result, {}).get("errors", []) if "item" in e}
                    job.checkpoint = dumps([i for i in loads(job.checkpoint, []) if i not in failed])
                    result = loads(job.result, {})
                    result["errors"] = []
                    job.result = dumps(result)
                job.state, job.error = "queued", None
            else:
                raise HTTPException(409, "Действие не подходит для текущего состояния задания")
            job.updated = now()
        if action == "cancel":
            from .job_lifecycle import cleanup_cancelled

            cleanup_cancelled(catalog, identifier)
        return {"state": job.state}

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                data = json.dumps(await asyncio.to_thread(job_list), ensure_ascii=False)
                if data != previous:
                    yield f"event: jobs\ndata: {data}\n\n"
                    previous = data
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    dist = root / "frontend" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index(request: Request):
        supplied = request.query_params.get("token", "") or request.cookies.get("openphoto_session", "")
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(401, "Откройте приложение через локальный запуск OpenPhoto")
        if not (dist / "index.html").exists():
            return JSONResponse(
                {"detail": "Сначала соберите интерфейс: cd frontend; npm install; npm run build"},
                status_code=503,
            )
        from fastapi.responses import HTMLResponse

        html = (dist / "index.html").read_text(encoding="utf-8")
        html = html.replace("</head>", f'<meta name="openphoto-token" content="{token}"></head>')
        response = HTMLResponse(html)
        response.set_cookie("openphoto_session", token, httponly=True, samesite="strict")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/photos/{identifier}/geometry-preview")
    def geometry_preview(identifier: str):
        from .imaging import processing_environment
        from .schemas import Crop

        with catalog.session() as s:
            photo = get_photo(s, identifier)
            recipe = catalog.recipe(photo, s)
            if recipe.version == 2:
                raise HTTPException(409, "Кадр уже использует новую геометрию")
            recipe.version = 2
            recipe.runtime = processing_environment(2)
            if recipe.rotation:
                # A rotated cropped rectangle cannot generally become an axis-aligned crop
                # on a differently rotated full canvas. Preview the complete new canvas.
                recipe.crop = Crop()
                recipe.retouch.protected = []
                recipe.retouch.healing = []
                recipe.retouch.strength = recipe.retouch.color_evenness = 0
                recipe.retouch.body_strength = recipe.retouch.body_color_evenness = 0
            payload = {"photo_ids": [identifier], "revision": photo.revision, "recipe": recipe.model_dump()}
        return {
            "recipe": recipe.model_dump(),
            "job_id": enqueue(catalog, "geometry_preview", payload, 0),
            "note": "При повороте исходная обрезка и локальные отметки остаются в прежней версии; новая версия начинается с полного кадра и отключённой ретуши.",
        }

    return app
