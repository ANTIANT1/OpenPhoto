import json
import os
from pathlib import Path

import pytest

from conftest import import_all
from openphoto import cache


def test_busy_release_is_deferred_and_does_not_mask_processing_error(tmp_path, monkeypatch):
    image = tmp_path / 'image.jpg'
    image.write_bytes(b'pixels')
    unlink = Path.unlink
    blocked = True

    def sharing_conflict(path, *args, **kwargs):
        if path.name.startswith('.lease-') and blocked:
            error = PermissionError('Windows sharing violation')
            error.winerror = 32
            raise error
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', sharing_conflict)
    with pytest.raises(ValueError, match='processing error'):
        with cache.protect(image):
            raise ValueError('processing error')
    assert list(tmp_path.glob('.lease-*'))
    assert cache.trim(tmp_path, 0) == len(b'pixels')
    assert image.exists()
    blocked = False
    assert cache.trim(tmp_path, 0) == 0
    assert not list(tmp_path.glob('.lease-*')) and not image.exists()


def test_incomplete_live_lease_never_exposes_image_to_eviction(tmp_path):
    image = tmp_path / 'image.jpg'
    image.write_bytes(b'pixels')
    marker = tmp_path / f'.lease-{os.getpid()}-incomplete'
    marker.write_text('{"path":')
    assert cache.trim(tmp_path, 0) == len(b'pixels')
    assert marker.exists() and image.exists()
    cache.release_lease(marker)
    assert cache.trim(tmp_path, 0) == 0


def test_image_response_survives_concurrent_lease_reader(workspace, monkeypatch):
    client, pipeline, source, project = workspace
    photo = import_all(client, pipeline, source)[0]
    unlink = Path.unlink
    conflicts = []

    def sharing_conflict(path, *args, **kwargs):
        if path.name.startswith('.lease-') and path not in conflicts:
            conflicts.append(path)
            error = PermissionError('Windows sharing violation')
            error.winerror = 32
            raise error
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', sharing_conflict)
    response = client.get(f'/api/photos/{photo["id"]}/image?variant=original')
    assert response.status_code == 200 and response.content.startswith(b'\xff\xd8')
    assert conflicts and not list((project / 'cache').rglob('.lease-*'))


def test_orphaned_partial_lease_is_reclaimed(tmp_path, monkeypatch):
    image = tmp_path / 'image.jpg'
    image.write_bytes(b'pixels')
    marker = tmp_path / '.lease-123456789-orphan'
    marker.write_text(json.dumps({'path':'image.jpg'})[:-1])
    monkeypatch.setattr(cache.psutil, 'pid_exists', lambda _: False)
    assert cache.trim(tmp_path, 0) == 0
    assert not marker.exists() and not image.exists()
