from __future__ import annotations

import json
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def loads(value, default=None):
    return json.loads(value) if value else default


class Base(DeclarativeBase):
    pass


class Root(Base):
    __tablename__ = "roots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    path: Mapped[str] = mapped_column(Text, unique=True)


class Shoot(Base):
    __tablename__ = "shoots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(Text)
    created: Mapped[str] = mapped_column(String, default=now)
    settings: Mapped[str] = mapped_column(Text, default="{}")


class PhotoAsset(Base):
    __tablename__ = "photos"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    shoot_id: Mapped[str] = mapped_column(ForeignKey("shoots.id"), index=True)
    root_id: Mapped[str] = mapped_column(ForeignKey("roots.id"))
    relative_path: Mapped[str] = mapped_column(Text)
    jpeg_path: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    captured: Mapped[float] = mapped_column(Float, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    group_id: Mapped[str] = mapped_column(String, index=True, default=uid)
    group_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="unreviewed")
    rating: Mapped[int] = mapped_column(Integer, default=0)
    suggested: Mapped[bool] = mapped_column(Boolean, default=True)
    review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_flags: Mapped[str] = mapped_column(Text, default="[]")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    manual_sections: Mapped[str] = mapped_column(Text, default="[]")
    score: Mapped[float | None] = mapped_column(Float)
    learned_score: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created: Mapped[str] = mapped_column(String, default=now)


class AnalysisResult(Base):
    __tablename__ = "analyses"
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id"), primary_key=True)
    data: Mapped[str] = mapped_column(Text)
    updated: Mapped[str] = mapped_column(String, default=now)


class RecipeRevision(Base):
    __tablename__ = "recipes"
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    created: Mapped[str] = mapped_column(String, default=now)


class UserDecision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    operation_id: Mapped[str | None] = mapped_column(String, index=True)
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id"), index=True)
    other_id: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(Text, default="null")
    previous: Mapped[str] = mapped_column(Text, default="{}")
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[str] = mapped_column(String, default=now)


class RecipeDraft(Base):
    __tablename__ = "recipe_drafts"
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    recipe: Mapped[str] = mapped_column(Text)


class StyleProfile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(Text)
    data: Mapped[str] = mapped_column(Text, default="{}")
    created: Mapped[str] = mapped_column(String, default=now)


class ProcessingJob(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String, default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=20)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[str] = mapped_column(Text, default="[]")
    result: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    created: Mapped[str] = mapped_column(String, default=now)
    updated: Mapped[str] = mapped_column(String, default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Catalog:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        for child in ("cache", "references", "models", "logs"):
            (self.directory / child).mkdir(exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.directory / 'catalog.sqlite'}", connect_args={"timeout": 30}
        )

        @event.listens_for(self.engine, "connect")
        def configure(dbapi, _):
            dbapi.execute("PRAGMA journal_mode=WAL")
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA busy_timeout=30000")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        import sqlite3
        import time

        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        database = self.directory / "catalog.sqlite"
        if database.exists():
            with closing(sqlite3.connect(database)) as source:
                tables = {
                    row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                revision = (
                    source.execute("SELECT version_num FROM alembic_version").fetchone()
                    if "alembic_version" in tables
                    else None
                )
                if tables and (
                    not revision or revision[0] != ScriptDirectory.from_config(config).get_current_head()
                ):
                    backups = self.directory / "backups"
                    backups.mkdir(exist_ok=True)
                    with closing(sqlite3.connect(
                        backups / f"catalog-before-migration-{time.time_ns()}.sqlite"
                    )) as destination:
                        source.backup(destination)
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    @contextmanager
    def session(self):
        with self.sessions.begin() as session:
            yield session

    def settings(self):
        with self.session() as s:
            return {row.key: loads(row.value) for row in s.query(Setting)}

    def set_setting(self, key, value):
        with self.session() as s:
            s.merge(Setting(key=key, value=dumps(value)))

    def photo_path(self, photo, session, jpeg=False):
        root = session.get(Root, photo.root_id)
        relative = photo.jpeg_path if jpeg and photo.jpeg_path else photo.relative_path
        base = Path(root.path).resolve()
        path = (base / relative).resolve()
        if not path.is_relative_to(base):
            raise ValueError("Photo path escapes its registered root")
        return path

    def recipe(self, photo, session):
        from .schemas import EditRecipe

        row = session.get(RecipeRevision, (photo.id, photo.revision))
        return EditRecipe.model_validate_json(row.recipe) if row else EditRecipe()

    def save_recipe(self, session, photo, recipe, expected, source="manual", sections=None):
        if photo.revision != expected:
            raise ValueError("Revision conflict: reload the current recipe")
        photo.revision += 1
        draft = session.get(RecipeDraft, photo.id)
        if draft:
            session.delete(draft)
        session.add(
            RecipeRevision(
                photo_id=photo.id, revision=photo.revision, recipe=recipe.model_dump_json(), source=source
            )
        )
        if source in ("manual", "crop_accept", "style_accept", "restore", "geometry_migration"):
            locked = set(loads(photo.manual_sections, []))
            locked.update(sections or ["develop", "color", "retouch", "crop"])
            photo.manual_sections = dumps(sorted(locked))
        return photo.revision
