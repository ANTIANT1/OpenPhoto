"""Project switching and consistent, non-destructive catalog recovery."""
import json
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .database import ProcessingJob, Shoot, StyleProfile, loads
from .locking import ProjectLock


class NameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Введите название")
        return value.strip()


def preferences_path():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "OpenPhoto" / "preferences.json"


def recent_projects():
    path = preferences_path()
    try:
        if path.stat().st_size > 65536:
            return []
        items = json.loads(path.read_text(encoding="utf-8")).get("projects", [])
        return [item for item in items[:10] if isinstance(item, str)]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def remember_project(directory):
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = str(Path(directory).resolve())
    values = [current] + [p for p in recent_projects() if p.casefold() != current.casefold()]
    from .service import atomic_text

    atomic_text(path, json.dumps({"projects": values[:10]}, ensure_ascii=False))


def default_project():
    return next((Path(p) for p in recent_projects() if (Path(p) / "catalog.sqlite").is_file()),
                Path.home() / "Documents" / "OpenPhoto" / "Library")


def validate_project(directory, create=False):
    target = Path(directory).expanduser().resolve()
    if not (target / "catalog.sqlite").is_file():
        if not create:
            raise ValueError("В выбранной папке нет проекта OpenPhoto")
        if target.exists() and any(target.iterdir()):
            raise ValueError("Для нового проекта выберите пустую папку; фотографии импортируются отдельно")
    target.mkdir(parents=True, exist_ok=True)
    lock = ProjectLock(target)
    lock.acquire()
    lock.release()
    return target


def backup_project(catalog):
    directory = catalog.directory / "backups"
    directory.mkdir(exist_ok=True)
    name = f"catalog-manual-{time.time_ns()}.sqlite"
    target, temporary = directory / name, directory / (name + ".partial")
    try:
        with closing(sqlite3.connect(catalog.directory / "catalog.sqlite")) as source, closing(sqlite3.connect(temporary)) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Проверка резервной копии не пройдена")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def restore_copy(catalog, name):
    backups = (catalog.directory / "backups").resolve()
    source = (backups / name).resolve()
    if source.parent != backups or source.suffix != ".sqlite" or not source.is_file():
        raise ValueError("Резервная копия не найдена")
    parent = catalog.directory.parent.resolve()
    destination = parent / (catalog.directory.name + "-restored-" + uuid.uuid4().hex[:8])
    temporary = destination.with_name(destination.name + ".partial")
    created = False
    try:
        # Read-only validation before creating a destination; never replace the active project.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Резервная копия повреждена")
            if not {"photos", "recipes", "roots", "jobs"}.issubset({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}):
                raise ValueError("Файл не является каталогом OpenPhoto")
            temporary.mkdir(exist_ok=False)
            created = True
            with closing(sqlite3.connect(temporary / "catalog.sqlite")) as copy, copy:
                db.backup(copy)
                # A clone must have independent job owners. Otherwise its recovery could
                # mistake an active original export's reservation for its own orphan.
                for old_id, kind, result, checkpoint in copy.execute("SELECT id,kind,result,checkpoint FROM jobs").fetchall():
                    state = loads(result, {})
                    state["restored_job_id"] = old_id
                    if kind == "export":
                        state["files"] = {key: {**record, "historical": True} for key, record in state.get("files", {}).items()
                                          if record.get("state") == "committed"}
                        checkpoint = json.dumps([key for key in loads(checkpoint, []) if key in state["files"]])
                    copy.execute("UPDATE jobs SET id=?,result=?,checkpoint=? WHERE id=?",
                                 (uuid.uuid4().hex, json.dumps(state), checkpoint, old_id))
                copy.execute("UPDATE jobs SET state='paused' WHERE state IN ('queued','running')")
        references = catalog.directory / "references"
        if references.exists():
            shutil.copytree(references, temporary / "references")
        os.replace(temporary, destination)
        return destination
    except sqlite3.DatabaseError as error:
        raise ValueError("Резервная копия повреждена или имеет неподдерживаемую структуру") from error
    finally:
        if created and temporary.exists() and temporary.resolve().parent == parent:
            shutil.rmtree(temporary)


def register_project_routes(app, catalog):
    @app.get("/api/project")
    def project():
        return {"directory": str(catalog.directory), "recent": recent_projects()}

    @app.get("/api/project/backups")
    def backups():
        return [{"name": p.name, "bytes": p.stat().st_size, "modified": p.stat().st_mtime}
                for p in sorted((catalog.directory / "backups").glob("*.sqlite"), reverse=True)]

    @app.post("/api/project/backups")
    def backup():
        return {"name": backup_project(catalog).name}

    @app.post("/api/project/backups/{name}/restore")
    def restore(name: str):
        return {"directory": str(restore_copy(catalog, name))}

    def get(session, model, identifier):
        row = session.get(model, identifier)
        if row is None:
            raise HTTPException(404, "Запись не найдена")
        return row

    @app.patch("/api/shoots/{identifier}")
    def rename_shoot(identifier: str, body: NameRequest):
        with catalog.session() as session:
            get(session, Shoot, identifier).name = body.name
        return {"updated": True}

    @app.patch("/api/profiles/{identifier}")
    def rename_profile(identifier: str, body: NameRequest):
        with catalog.session() as session:
            get(session, StyleProfile, identifier).name = body.name
        return {"updated": True}

    @app.delete("/api/profiles/{identifier}")
    def delete_profile(identifier: str):
        with catalog.session() as session:
            row = get(session, StyleProfile, identifier)
            for job in session.query(ProcessingJob).filter(ProcessingJob.state.in_(["queued", "running", "paused"])):
                if loads(job.payload, {}).get("profile_id") == identifier or loads(job.result, {}).get("profile_id") == identifier:
                    raise HTTPException(409, "Сначала завершите или отмените обработку с этим профилем")
            backup_project(catalog)
            session.delete(row)
        # Keep reference images for catalog backups. Original reference files are never removed.
        return {"deleted": True}
