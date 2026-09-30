"""Coordinate cancellation cleanup with the worker across process boundaries."""
from pathlib import Path

from . import exports
from .database import ProcessingJob, dumps, loads
from .locking import ProjectLock


def job_lock(catalog, identifier):
    directory = catalog.directory / "locks"
    directory.mkdir(exist_ok=True)
    # IDs originate in the catalog, never in a caller-supplied filesystem path.
    import hashlib

    return ProjectLock(directory, hashlib.sha256(identifier.encode()).hexdigest() + ".lock")


def cleanup_cancelled(catalog, identifier, locked=False):
    lock = None
    if not locked:
        lock = job_lock(catalog, identifier)
        try:
            lock.acquire()
        except RuntimeError:
            return  # The active worker performs cleanup in its finally block.
    try:
        with catalog.session() as session:
            job = session.get(ProcessingJob, identifier)
            if not job or job.kind != "export" or job.state != "cancelled":
                return
            result = loads(job.result, {})
            failures = []
            for record in result.get("files", {}).values():
                try:
                    exports.cleanup(record, rollback=record.get("state") != "committed")
                    if record.get("state") != "committed":
                        record["state"] = "cancelled"
                except OSError as error:
                    failures.append(str(error))
            result["cleanup_errors"] = failures
            job.result = dumps(result)
            if failures:
                job.error = "Не удалось убрать временные файлы; очистка будет повторена при открытии проекта."
    finally:
        if lock:
            lock.release()


def recover_exports(catalog):
    """Call only before workers start or after their process has terminated."""
    with catalog.session() as session:
        jobs = session.query(ProcessingJob).filter_by(kind="export").all()
    for job in jobs:
        cleanup_cancelled(catalog, job.id)
        payload, result = loads(job.payload, {}), loads(job.result, {})
        directory = Path(payload.get("directory", "__missing__")).expanduser().resolve()
        if not directory.is_dir():
            continue
        recorded = {record["owner"] for record in result.get("files", {}).values()}
        allowed = {job.id + "-" + identifier for identifier in payload.get("photo_ids", [])}
        # A process can die between the exclusive reservation and the DB commit.
        # Such a reservation has no published files: publication requires a journal.
        for marker in directory.glob(".*.openphoto-reservation"):
            try:
                owner = marker.read_text()
                if owner not in allowed:
                    continue
                if owner not in recorded:
                    exports.cleanup({"path": str(directory / "unused"), "owner": owner,
                                     "staging": str(directory / (".openphoto-" + owner)),
                                     "marker": str(marker)})
            except OSError:
                continue  # A missing external drive can be retried on the next start.
