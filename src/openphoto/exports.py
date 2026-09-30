"""Recoverable export bundles with exclusive names and no final-file placeholders."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def identity(path):
    stat = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"device": stat.st_dev, "inode": stat.st_ino, "bytes": stat.st_size, "sha256": digest}


def owned(path, expected):
    try:
        return identity(path) == expected
    except OSError:
        return False


def reserve_bundle(directory, stem, extension, suffixes, owner):
    for number in range(100000):
        name = f"{stem}{'_' + str(number) if number else ''}{extension}"
        names = [name + suffix for suffix in suffixes]
        marker = directory / ("." + name + ".openphoto-reservation")
        if any((directory / item).exists() for item in names):
            continue
        try:
            descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "w") as stream:
            stream.write(owner)
        if any((directory / item).exists() for item in names):
            marker.unlink()
            continue
        staging = directory / (".openphoto-" + owner)
        staging.mkdir(exist_ok=True)
        return {
            "path": str(directory / name),
            "names": names,
            "marker": str(marker),
            "staging": str(staging),
            "owner": owner,
            "state": "reserved",
            "prepared": {},
        }
    raise RuntimeError("Не удалось подобрать свободное имя комплекта экспорта")


def prepare(record):
    staging = Path(record["staging"])
    prepared = {name: identity(staging / name) for name in record["names"]}
    if any(info["bytes"] == 0 for info in prepared.values()):
        raise ValueError("Экспорт создал пустой файл")
    record.update(prepared=prepared, state="prepared")


def publish(record):
    directory, staging = Path(record["path"]).parent, Path(record["staging"])
    for name in record["names"]:
        target, source = directory / name, staging / name
        if target.exists():
            if owned(target, record["prepared"][name]):
                continue  # Resume a rename completed before the database checkpoint.
            raise FileExistsError(f"Имя занято другим файлом: {name}")
        if not owned(source, record["prepared"][name]):
            raise ValueError("Временный файл экспорта изменён или недоступен")
        if os.name == "nt":
            os.rename(source, target)  # Windows rename fails if the destination exists.
        else:
            os.link(source, target)
            source.unlink()
    record["state"] = "committed"


def cleanup(record, rollback=False):
    if record.get("historical"):
        return  # A restored project may display, but never clean, the original's receipts.
    directory = Path(record["path"]).parent.resolve()
    if rollback:
        for name, expected in record.get("prepared", {}).items():
            target = directory / name
            if target.parent == directory and owned(target, expected):
                target.unlink()
    staging = Path(record["staging"]).resolve()
    marker = Path(record["marker"]).resolve()
    if staging.parent == directory and staging.name == ".openphoto-" + record["owner"] and staging.exists():
        shutil.rmtree(staging)
    if marker.parent == directory and marker.exists() and marker.read_text() == record["owner"]:
        marker.unlink()
