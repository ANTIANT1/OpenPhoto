"""Budget all disposable cache files; short file leases protect active responses."""

from __future__ import annotations

import os
import json
import shutil
import time
import uuid
import threading
from contextlib import contextmanager

import psutil

_pending_release = set()
_release_lock = threading.Lock()


def release_lease(marker):
    """Windows readers can briefly deny deletion; cleanup must not fail a response."""
    for attempt in range(5):
        try:
            marker.unlink(missing_ok=True)
            with _release_lock:
                _pending_release.discard(marker)
            return True
        except OSError as error:
            if getattr(error, "winerror", None) not in (32, 33) or attempt == 4:
                break
            time.sleep(0.01 * (attempt + 1))
    # Retry at the next cache boundary. Keep the lease in place meanwhile so a
    # transient sharing conflict cannot cause deletion of an active image.
    with _release_lock:
        _pending_release.add(marker)
    return False


def lease(path, seconds=None):
    marker = path.parent / f".lease-{os.getpid()}-{uuid.uuid4().hex}"
    marker.write_text(json.dumps({"path": path.name, "pid": os.getpid(),
                                 "created": psutil.Process().create_time(),
                                 "expires": time.time() + seconds if seconds else None}), encoding="utf-8")
    try:
        os.utime(path, None)
    except FileNotFoundError:
        pass
    return marker


@contextmanager
def protect(*paths):
    markers = []
    try:
        for path in paths:
            markers.append(lease(path))
        yield
    finally:
        for marker in markers:
            release_lease(marker)


def protect_photo(directory, identifier, revision):
    paths = [directory / f"{variant}-{identifier}.jpg" for variant in ("thumb", "original", "camera")]
    paths += [directory / f"{variant}-{identifier}-{revision}.jpg" for variant in
              ("base", "render", "fullbase", "full", "camera-full", "style-soft", "style-medium",
               "style-strong", "geometry-new")]
    paths.append(directory / f"mask-{identifier}-{revision}.png")
    return protect(*paths)


def trim(directory, budget):
    with _release_lock:
        pending = tuple(_pending_release)
    for marker in pending:
        if marker.resolve().is_relative_to(directory.resolve()):
            release_lease(marker)
    pinned = set()
    for marker in directory.rglob(".lease-*"):
        try:
            text = marker.read_text(encoding="utf-8")
            if text.startswith("{"):
                info = json.loads(text)
                alive = psutil.Process(info["pid"]).create_time() == info["created"]
                if info.get("expires") and time.time() > info["expires"]:
                    alive = False
                name = info["path"]
            else:  # Leases from earlier builds expire as before.
                alive, name = time.time() - marker.stat().st_mtime < 120, text
            if alive:
                pinned.add((marker.parent / name).resolve())
            else:
                release_lease(marker)
        except FileNotFoundError:
            continue  # Another response has already released this lease.
        except (OSError, ValueError, KeyError, psutil.Error):
            # A concurrent writer may not yet have finished its JSON, or a
            # Windows reader can deny access. Never interpret that as unleased.
            try:
                owner_alive = psutil.pid_exists(int(marker.name.split("-", 2)[1]))
            except (ValueError, IndexError):
                owner_alive = True
            if owner_alive:
                pinned.add(marker.parent.resolve())
            else:
                release_lease(marker)
    candidates = []
    for path in directory.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink() and not path.name.startswith(".lease-"):
                stat = path.stat()
                candidates.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            pass
    total = sum(size for _, size, _ in candidates)
    for _, size, path in sorted(candidates):
        if total <= budget:
            break
        if any(path.resolve().is_relative_to(pin) for pin in pinned):
            continue
        try:
            path.unlink(missing_ok=True)
            total -= size
        except OSError:
            pass  # A native decoder may still own this file; try at the next boundary.
    return total


def reserve(directory, budget, required):
    """Admit a bounded intermediate before starting an expensive RAW decode."""
    if required > budget:
        raise RuntimeError("Лимит кэша слишком мал для этого RAW. Увеличьте его в настройках.")
    total = trim(directory, budget - required)
    if total + required > budget:
        raise RuntimeError("Кэш занят открытыми изображениями. Закройте сравнение и повторите обработку.")
    if shutil.disk_usage(directory).free < required + 64 * 1024**2:
        raise RuntimeError("На диске недостаточно места для промежуточного RAW-файла.")
