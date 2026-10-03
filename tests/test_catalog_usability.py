from conftest import import_all
from openphoto.database import AnalysisResult, PhotoAsset, ProcessingJob, dumps, loads
from openphoto.imaging import fingerprint
from openphoto.selection import recompute_selection


def test_remove_restore_and_undo_preserve_originals_recipes_and_ratings(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    ids = [p['id'] for p in photos[:2]]
    hashes = {p.name:fingerprint(p) for p in source.iterdir()}
    client.post('/api/decisions', json={'photo_ids':ids, 'action':'keep'})
    client.post('/api/decisions', json={'photo_ids':ids, 'action':'rating', 'value':4})
    before = {i:client.get(f'/api/photos/{i}').json() for i in ids}
    response = client.post('/api/decisions', json={'photo_ids':ids, 'action':'remove'})
    assert response.status_code == 200
    for filter_name in ('all', 'keep', 'suggested', 'review', 'reject'):
        assert not set(ids) & {p['id'] for p in client.get('/api/photos', params={'filter':filter_name}).json()['photos']}
    assert client.get('/api/photos?filter=removed').json()['total'] == 2
    assert sum(s['count'] for s in client.get('/api/shoots').json()) == 2
    assert client.post('/api/decisions', json={'photo_ids':ids, 'action':'keep'}).status_code == 409
    # Removing again is idempotent and must not replace the original restore state.
    client.post('/api/decisions', json={'photo_ids':ids, 'action':'remove'})
    recompute_selection(pipeline.catalog)
    export = client.post('/api/export', json={'photo_ids':ids,'directory':str(source.parent/'output')})
    assert export.status_code == 200
    with pipeline.catalog.session() as s:
        assert loads(s.get(ProcessingJob, export.json()['job_id']).payload)['photo_ids'] == []
    assert client.post('/api/decisions', json={'photo_ids':ids, 'action':'restore_removed'}).status_code == 200
    for identifier in ids:
        current = client.get(f'/api/photos/{identifier}').json()
        assert current['status'] == 'keep' and current['rating'] == 4
        assert current['recipe'] == before[identifier]['recipe']
        assert current['history'] == before[identifier]['history']
    client.post('/api/decisions/undo')  # Undo restore, then undo the whole removal.
    assert client.get('/api/photos?filter=removed').json()['total'] == 2
    response = client.post('/api/decisions/undo')
    assert set(response.json()['photo_ids']) == set(ids)
    assert client.get('/api/photos').json()['total'] == 4
    assert {p.name:fingerprint(p) for p in source.iterdir()} == hashes


def test_remove_batch_rolls_back_on_unknown_photo(workspace):
    client, pipeline, source, _ = workspace
    identifier = import_all(client, pipeline, source)[0]['id']
    response = client.post('/api/decisions', json={'photo_ids':[identifier,'missing'], 'action':'remove'})
    assert response.status_code == 404
    assert client.get('/api/photos?filter=removed').json()['total'] == 0


def test_cached_open_does_not_queue_or_run_models_and_missing_cache_rebuilds(workspace, monkeypatch):
    client, pipeline, source, project = workspace
    photo = import_all(client, pipeline, source)[0]
    identifier = photo['id']
    # A complete render is published together with revision-tagged analysis.
    with pipeline.catalog.session() as s:
        s.add(AnalysisResult(photo_id=identifier, data=dumps({'input_revision':0,'source':'developed'})))
    for variant, suffix in (('render','jpg'),('base','jpg'),('mask','png')):
        (project/'cache'/f'{variant}-{identifier}-0.{suffix}').write_bytes(b'cached-image')
    with pipeline.catalog.session() as s:
        previous_jobs = s.query(ProcessingJob).count()
    for _ in range(10):
        response = client.post(f'/api/photos/{identifier}/render').json()
        assert response == {'job_id':None,'revision':0,'cached':True}
    monkeypatch.setattr(pipeline, 'developer', lambda: (_ for _ in ()).throw(AssertionError('Unnecessary RAW decode')))
    pipeline.render_photo(identifier)
    with pipeline.catalog.session() as s:
        assert s.query(ProcessingJob).count() == previous_jobs
    full = client.post(f'/api/photos/{identifier}/render?full=true').json()
    assert full['job_id']
    (project/'cache'/f'base-{identifier}-0.jpg').unlink()
    pending = client.post(f'/api/photos/{identifier}/render').json()
    assert pending['job_id']
    assert client.post(f'/api/photos/{identifier}/render').json()['job_id'] == pending['job_id']
    with pipeline.catalog.session() as s:
        s.get(PhotoAsset, identifier).revision = 1
    newer = client.post(f'/api/photos/{identifier}/render').json()
    assert newer['revision'] == 1 and newer['job_id'] != pending['job_id']
