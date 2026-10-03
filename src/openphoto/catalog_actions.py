"""Reversible removal of shoots; originals and editing history stay intact."""
from fastapi import HTTPException

from .database import PhotoAsset, ProcessingJob, Shoot, UserDecision, dumps, loads, now, uid


def reveal_shoot(session, identifier):
    shoot = session.get(Shoot, identifier)
    if shoot:
        settings = loads(shoot.settings, {})
        settings.pop("archived_at", None)
        shoot.settings = dumps(settings)


def restore_photo(session, photo):
    removal = session.query(UserDecision).filter_by(
        photo_id=photo.id, action="remove", undone=False,
    ).order_by(UserDecision.created.desc(), UserDecision.id.desc()).first()
    previous = loads(removal.previous, {}) if removal else {}
    photo.status = previous.get("status", "unreviewed")
    if photo.status == "removed":
        photo.status = "unreviewed"
    reveal_shoot(session, photo.shoot_id)


def register_catalog_actions(app, catalog):
    @app.delete("/api/shoots/{identifier}")
    def remove_shoot(identifier: str):
        with catalog.session() as session:
            shoot = session.get(Shoot, identifier)
            if not shoot:
                raise HTTPException(404, "Съёмка не найдена")
            photos = session.query(PhotoAsset).filter_by(shoot_id=identifier).all()
            ids = {p.id for p in photos}
            for job in session.query(ProcessingJob).filter(ProcessingJob.state.in_(["queued", "running", "paused"])):
                payload = loads(job.payload, {})
                if (job.kind == "import" or payload.get("shoot_id") == identifier
                        or ids.intersection(payload.get("photo_ids", []))
                        or (ids and job.kind in {"analyze", "render", "style"}
                            and not payload.get("photo_ids") and not payload.get("shoot_id"))):
                    raise HTTPException(409, "Сначала завершите или отмените задания этой съёмки в «Обработка и экспорт».")
            operation, removed = uid(), 0
            for photo in photos:
                if photo.status == "removed":
                    continue
                session.add(UserDecision(operation_id=operation, photo_id=photo.id, action="remove",
                                         previous=dumps({"status": photo.status, "rating": photo.rating})))
                photo.status = "removed"
                removed += 1
            shoot.settings = dumps({**loads(shoot.settings, {}), "archived_at": now()})
        return {"removed": removed, "shoot_id": identifier}
