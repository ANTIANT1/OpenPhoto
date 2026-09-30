from pathlib import Path

import pytest
from PIL import Image

from conftest import import_all
from openphoto.locking import ProjectLock


def test_export_freezes_recipe_and_selection_at_enqueue(workspace):
    client, pipeline, source, project = workspace
    photos = import_all(client, pipeline, source)
    identifier = photos[0]['id']
    client.post('/api/decisions', json={'photo_ids': [identifier], 'action': 'keep'})
    job = client.post('/api/export', json={'directory': str(project / 'frozen')}).json()['job_id']
    recipe = client.get(f'/api/photos/{identifier}').json()['recipe']
    recipe['crop'] = {'x': .25, 'y': .25, 'w': .5, 'h': .5}
    edit = client.put(f'/api/photos/{identifier}/recipe', json={'recipe': recipe, 'expected_revision': 0}).json()
    pipeline.run(edit['job_id'])
    pipeline.run(job)
    assert Image.open(next((project / 'frozen').glob('*.jpg'))).size == (320, 240)


def test_modified_source_is_not_silently_rendered(workspace):
    client, pipeline, source, project = workspace
    identifier = import_all(client, pipeline, source)[0]['id']
    photo = client.get(f'/api/photos/{identifier}').json()
    (source / photo['name']).write_bytes(b'changed outside the application')
    job = client.post(f'/api/photos/{identifier}/render').json()['job_id']
    pipeline.run(job)
    state = next(j for j in client.get('/api/jobs').json() if j['id'] == job)
    assert state['state'] == 'completed_with_errors'
    assert not (project / 'cache' / f'render-{identifier}-0.jpg').exists()


def test_only_one_application_may_open_project(tmp_path):
    first, second = ProjectLock(tmp_path), ProjectLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_full_base_and_export_geometry_share_canvas(workspace):
    client, pipeline, source, project = workspace
    identifier = import_all(client, pipeline, source)[0]['id']
    recipe = client.get(f'/api/photos/{identifier}').json()['recipe']
    recipe['crop'] = {'x': .25, 'y': 0, 'w': .5, 'h': 1}
    client.put(f'/api/photos/{identifier}/recipe', json={'recipe': recipe, 'expected_revision': 0})
    job = client.post(f'/api/photos/{identifier}/render?full=true').json()['job_id']
    pipeline.run(job)
    assert Image.open(Path(project) / 'cache' / f'fullbase-{identifier}-1.jpg').size == (320, 240)
    assert Image.open(Path(project) / 'cache' / f'full-{identifier}-1.jpg').size == (160, 240)
