"""Small progress events and paged access to durable job results."""
import base64
import json
import os
from pathlib import Path

from fastapi import HTTPException, Query
from sqlalchemy import and_, or_

from .database import ProcessingJob, loads

ACTIVE = {"queued", "running", "paused"}


def public_job(job, compact=False):
    payload, result = loads(job.payload, {}), loads(job.result, {})
    if compact:
        errors = result.get("errors", [])
        result = {**{k: result[k] for k in ("prepared_count", "selected_count", "skipped_count", "warning_count",
                                           "export_job_id", "restored", "imported", "duplicates") if k in result},
                  "message": result.get("message"), "errors": errors[:3], "error_count": len(errors),
                  "output_count": sum(r.get("state") == "committed" for r in result.get("files", {}).values())}
    return {"id": job.id, "kind": job.kind, "state": job.state, "total": job.total,
            "completed": job.completed, "photo_ids": payload.get("photo_ids", []),
            "shoot_id": payload.get("shoot_id"),
            "full": payload.get("full", False), "result": result, "error": job.error,
            "created": job.created, "updated": job.updated}


def register_job_views(app, catalog):
    def get_job(session, identifier):
        job = session.get(ProcessingJob, identifier)
        if job is None:
            raise HTTPException(404, "Задание не найдено")
        return job

    def job_list(compact=False, history_limit=100):
        with catalog.session() as session:
            query = session.query(ProcessingJob)
            active = query.filter(ProcessingJob.state.in_(ACTIVE)).order_by(ProcessingJob.created.desc(), ProcessingJob.id.desc()).all()
            history = query.filter(~ProcessingJob.state.in_(ACTIVE)).order_by(ProcessingJob.created.desc(), ProcessingJob.id.desc()).limit(history_limit).all()
            return [public_job(j, compact) for j in active + history]

    @app.get("/api/jobs")
    def jobs(compact: bool = False):
        return job_list(compact)

    @app.get("/api/jobs/history")
    def history(cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
        with catalog.session() as session:
            query = session.query(ProcessingJob).filter(~ProcessingJob.state.in_(ACTIVE))
            total = query.count()
            if cursor:
                try:
                    created, identifier = json.loads(base64.urlsafe_b64decode(cursor))
                    if not isinstance(created, str) or not isinstance(identifier, str):
                        raise ValueError()
                except (ValueError, TypeError, UnicodeError):
                    raise HTTPException(400, "Некорректная страница истории") from None
                query = query.filter(or_(ProcessingJob.created < created,
                                         and_(ProcessingJob.created == created, ProcessingJob.id < identifier)))
            rows = query.order_by(ProcessingJob.created.desc(), ProcessingJob.id.desc()).limit(limit + 1).all()
            page = rows[:limit]
            next_cursor = base64.urlsafe_b64encode(json.dumps([page[-1].created, page[-1].id]).encode()).decode() if len(rows) > limit else None
            return {"jobs": [public_job(j, True) for j in page], "total": total, "next_cursor": next_cursor}

    @app.get("/api/jobs/{identifier}")
    def detail(identifier: str):
        with catalog.session() as session:
            return public_job(get_job(session, identifier))

    @app.get("/api/jobs/{identifier}/outputs")
    def outputs(identifier: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        with catalog.session() as session:
            job = get_job(session, identifier)
            if job.kind != "export":
                raise HTTPException(400, "У задания нет экспортированных файлов")
            records = [r for r in loads(job.result, {}).get("files", {}).values() if r.get("state") == "committed"]
            return {"directory": loads(job.payload, {}).get("directory"), "total": len(records),
                    "files": [{"path": r["path"], "available": Path(r["path"]).is_file()} for r in records[offset:offset + limit]]}

    @app.post("/api/jobs/{identifier}/open-folder")
    def open_folder(identifier: str):
        with catalog.session() as session:
            job = get_job(session, identifier)
            if job.kind != "export":
                raise HTTPException(400, "Выберите задание экспорта")
            destination = Path(loads(job.payload, {}).get("directory", "__missing__")).expanduser().resolve()
        if not destination.is_dir():
            raise HTTPException(404, "Папка результата недоступна. Подключите диск.")
        if os.name != "nt":
            raise HTTPException(400, "Открытие папки поддерживается в Windows")
        os.startfile(destination)
        return {"opened": True}

    return lambda: job_list(compact=True, history_limit=20)
