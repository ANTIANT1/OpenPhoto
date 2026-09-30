"""Automatic shoot processing and cache reuse regressions."""
from collections import Counter

from conftest import import_all
from openphoto.database import PhotoAsset, ProcessingJob, RecipeDraft, RecipeRevision, loads
from openphoto.imaging import fingerprint
from openphoto.workflows import prepare_recipe


def test_workflow_one_request_renders_exports_and_replays_without_duplicates(workspace):
    client, pipeline, source, project = workspace
    photos = import_all(client, pipeline, source)
    hashes = {p.name: fingerprint(p) for p in source.iterdir()}
    removed, rejected = [p['id'] for p in photos[:2]]
    client.post('/api/decisions', json={'photo_ids':[removed], 'action':'remove'})
    client.post('/api/decisions', json={'photo_ids':[rejected], 'action':'reject'})
    response = client.post('/api/workflows', json={'selection':'all', 'export_directory':str(project/'outputs')})
    assert response.status_code == 200, response.text
    job_id = response.json()['job_id']
    assert response.json()['count'] == 2
    assert client.post('/api/workflows', json={}).status_code == 409
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        job = s.get(ProcessingJob, job_id)
        assert job.state == 'completed', job.result
        assert job.completed == job.total == 4
        export_id = loads(job.result)['export_job_id']
        revisions = {p.id:p.revision for p in s.query(PhotoAsset)}
    pipeline.run(export_id)
    outputs = list((project/'outputs').glob('*.jpg'))
    assert len(outputs) == 2
    pipeline.run(job_id)  # Simulate recovery after the final checkpoint, before acknowledgement.
    with pipeline.catalog.session() as s:
        assert {p.id:p.revision for p in s.query(PhotoAsset)} == revisions
        assert s.query(ProcessingJob).filter_by(kind='export').count() == 1
    assert {p.name:fingerprint(p) for p in source.iterdir()} == hashes


def test_workflow_retry_only_failed_render_and_keep_committed_recipe(workspace, monkeypatch):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    bad = photos[0]['id']
    calls = Counter()
    original = pipeline.render_photo
    def render(identifier):
        calls[identifier] += 1
        if identifier == bad and calls[identifier] == 1:
            raise RuntimeError('simulated render interruption')
        return original(identifier)
    monkeypatch.setattr(pipeline, 'render_photo', render)
    job_id = client.post('/api/workflows', json={'selection':'all'}).json()['job_id']
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        assert s.get(ProcessingJob, job_id).state == 'completed_with_errors'
        revision = s.get(PhotoAsset, bad).revision
    assert client.post(f'/api/jobs/{job_id}/retry').status_code == 200
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        assert s.get(ProcessingJob, job_id).state == 'completed'
        assert s.get(PhotoAsset, bad).revision == revision
        assert s.query(RecipeRevision).filter_by(photo_id=bad, source='workflow:'+job_id).count() == 1
    assert calls[bad] == 2
    assert all(calls[p['id']] == 1 for p in photos[1:])


def test_workflow_preserves_manual_edits_drafts_and_cancelled_job(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    a, b = [p['id'] for p in photos[:2]]
    detail = client.get('/api/photos/'+a).json()
    detail['recipe']['retouch']['strength'] = .31
    saved = client.put(f'/api/photos/{a}/recipe', json={'recipe':detail['recipe'], 'expected_revision':0})
    assert saved.status_code == 200
    with pipeline.catalog.session() as s:
        pending = [j.id for j in s.query(ProcessingJob).filter_by(state='queued')]
    for identifier in pending:
        pipeline.run(identifier)
    prepare_recipe(pipeline, a, 'manual-preserved', {'retouch_strength':.15})
    assert client.get('/api/photos/'+a).json()['recipe']['retouch']['strength'] == .31
    detail = client.get('/api/photos/'+b).json()
    detail['recipe']['color']['exposure'] = .7
    client.put(f'/api/photos/{b}/draft', json={'recipe':detail['recipe'],'expected_revision':0})
    job_id = client.post('/api/workflows', json={'photo_ids':[b], 'selection':'all'}).json()['job_id']
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        assert s.get(RecipeDraft, b)
        assert s.get(PhotoAsset, b).revision == 0
        assert s.get(ProcessingJob, job_id).state == 'completed_with_errors'
    job_id = client.post('/api/workflows', json={'photo_ids':[b], 'selection':'all'}).json()['job_id']
    client.post(f'/api/jobs/{job_id}/cancel')
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        assert s.get(ProcessingJob, job_id).state == 'cancelled'
        assert s.get(ProcessingJob, job_id).completed == 0


def test_colour_retouch_crop_reuse_detection_but_geometry_invalidates(workspace, monkeypatch):
    import openphoto.service as service
    from openphoto.schemas import EditRecipe

    client, pipeline, source, _ = workspace
    identifier = import_all(client, pipeline, source)[0]['id']
    calls = []
    original = service.analyze
    def analyze(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'analyze', analyze)
    pipeline.render_photo(identifier)
    assert len(calls) == 1
    for section, key, value in [('color','exposure',.3), ('retouch','strength',.1), ('crop','w',.9)]:
        with pipeline.catalog.session() as s:
            photo = s.get(PhotoAsset, identifier)
            recipe = pipeline.catalog.recipe(photo, s)
            setattr(getattr(recipe, section), key, value)
            pipeline.catalog.save_recipe(s, photo, recipe, photo.revision)
        pipeline.render_photo(identifier)
        assert len(calls) == 1
    with pipeline.catalog.session() as s:
        photo = s.get(PhotoAsset, identifier)
        recipe = pipeline.catalog.recipe(photo, s)
        recipe.rotation = 1.5
        pipeline.catalog.save_recipe(s, photo, recipe, photo.revision)
    pipeline.render_photo(identifier)
    assert len(calls) == 2
    recipe = EditRecipe()
    key = service.geometry_analysis_key('a', recipe, (100,200,3))
    recipe.develop.exposure = 1
    assert key != service.geometry_analysis_key('a', recipe, (100,200,3))
    assert key != service.geometry_analysis_key('b', EditRecipe(), (100,200,3))


def test_workflow_pause_resume_keeps_analysis_checkpoint(workspace, monkeypatch):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    job_id = client.post('/api/workflows', json={'selection':'all'}).json()['job_id']
    calls = []
    original = pipeline.analyze_photo
    def analyze(identifier, payload):
        calls.append(identifier)
        original(identifier, payload)
        if len(calls) == 1:
            assert client.post(f'/api/jobs/{job_id}/pause').status_code == 200
    monkeypatch.setattr(pipeline, 'analyze_photo', analyze)
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        job = s.get(ProcessingJob, job_id)
        assert job.state == 'paused' and job.completed == 1
    assert client.post(f'/api/jobs/{job_id}/resume').status_code == 200
    pipeline.run(job_id)
    with pipeline.catalog.session() as s:
        assert s.get(ProcessingJob, job_id).state == 'completed'
    assert len(calls) == len(set(calls)) == len(photos)
