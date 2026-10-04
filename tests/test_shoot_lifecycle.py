"""Tester-reported removal/re-import paths must preserve the same editing identity."""
import shutil

from conftest import import_all
from openphoto.database import PhotoAsset, ProcessingJob, Shoot, dumps, loads
from openphoto.imaging import fingerprint


def test_reimport_restores_history_rating_and_moved_source_without_duplicates(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    photo = photos[0]
    identifier, shoot_id = photo['id'], photo['shoot_id']
    before_hash = fingerprint(source / photo['name'])
    client.post('/api/decisions', json={'photo_ids':[identifier], 'action':'keep'})
    client.post('/api/decisions', json={'photo_ids':[identifier], 'action':'rating', 'value':5})
    with pipeline.catalog.session() as s:
        row = s.get(PhotoAsset, identifier)
        recipe = pipeline.catalog.recipe(row, s)
        recipe.develop.exposure = .7
        pipeline.catalog.save_recipe(s, row, recipe, row.revision)
    before = client.get('/api/photos/'+identifier).json()
    client.post('/api/decisions', json={'photo_ids':[identifier], 'action':'remove'})
    moved = source.parent / 'moved'
    moved.mkdir()
    shutil.move(str(source/photo['name']), str(moved/photo['name']))
    job = client.post('/api/import', json={'paths':[str(moved)],'shoot_name':'Re-import'}).json()['job_id']
    pipeline.run(job)
    current = client.get('/api/photos/'+identifier).json()
    for key in ['id','shoot_id','rating','status','recipe','history','revision']:
        assert current[key] == before[key]
    assert client.get('/api/photos').json()['total'] == 4
    assert len(client.get('/api/shoots').json()) == 1
    assert client.get('/api/shoots').json()[0]['id'] == shoot_id
    result = client.get('/api/jobs/'+job).json()['result']
    assert (result['restored'],result['imported'],result['duplicates']) == (1,0,0)
    with pipeline.catalog.session() as s:
        assert pipeline.catalog.photo_path(s.get(PhotoAsset, identifier), s) == moved/photo['name']
    assert fingerprint(moved/photo['name']) == before_hash
    # A second import remains a duplicate, not another card or shoot.
    job = client.post('/api/import', json={'paths':[str(moved)],'shoot_name':'Again'}).json()['job_id']
    pipeline.run(job)
    assert client.get('/api/jobs/'+job).json()['result']['duplicates'] == 1


def test_remove_shoot_restore_and_undo_preserve_files_and_hide_empty_shoot(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    shoot_id, first = photos[0]['shoot_id'], photos[0]['id']
    hashes = {p.name:fingerprint(p) for p in source.iterdir()}
    before = client.get('/api/photos/'+first).json()
    response = client.delete('/api/shoots/'+shoot_id)
    assert response.status_code == 200 and response.json()['removed'] == 4
    assert client.get('/api/shoots').json() == []
    assert client.get('/api/photos?filter=removed').json()['total'] == 4
    assert client.delete('/api/shoots/'+shoot_id).json()['removed'] == 0
    assert client.post('/api/decisions/undo').status_code == 200
    assert client.get('/api/shoots').json()[0]['count'] == 4
    assert client.delete('/api/shoots/'+shoot_id).status_code == 200
    client.post('/api/decisions', json={'photo_ids':[first], 'action':'restore_removed'})
    assert client.get('/api/shoots').json()[0]['count'] == 1
    current = client.get('/api/photos/'+first).json()
    assert current['recipe'] == before['recipe'] and current['history'] == before['history']
    client.post('/api/decisions', json={'photo_ids':[first], 'action':'remove'})
    assert client.get('/api/shoots').json()[0]['count'] == 0
    assert client.delete('/api/shoots/'+shoot_id).status_code == 200
    assert client.get('/api/shoots').json() == []
    import_all(client, pipeline, source)
    assert client.get('/api/shoots').json()[0]['count'] == 4
    assert {p.name:fingerprint(p) for p in source.iterdir()} == hashes
    with pipeline.catalog.session() as s:
        empty = Shoot(name='No photos ever')
        s.add(empty)
        s.flush()
        empty_id = empty.id
    assert client.delete('/api/shoots/'+empty_id).status_code == 200
    assert len(client.get('/api/shoots').json()) == 1
    assert client.delete('/api/shoots/missing').status_code == 404


def test_shoot_removal_rejects_pending_processing_without_partial_changes(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    shoot_id = photos[0]['shoot_id']
    job_id = client.post('/api/workflows', json={'shoot_id':shoot_id}).json()['job_id']
    assert client.delete('/api/shoots/'+shoot_id).status_code == 409
    assert client.get('/api/photos').json()['total'] == 4
    with pipeline.catalog.session() as s:
        assert 'archived_at' not in loads(s.get(Shoot, shoot_id).settings)
        s.get(ProcessingJob, job_id).state = 'cancelled'
        s.add(ProcessingJob(kind='analyze', state='queued', payload=dumps({'shoot_id':'unrelated'})))
    assert client.delete('/api/shoots/'+shoot_id).status_code == 200


def test_first_run_guide_preference_is_persistent(workspace):
    client, pipeline, _, _ = workspace
    response = client.patch('/api/settings', json={'onboarding_completed':True})
    assert response.status_code == 200
    assert client.get('/api/status').json()['settings']['onboarding_completed'] is True
    assert pipeline.catalog.settings()['onboarding_completed'] is True
