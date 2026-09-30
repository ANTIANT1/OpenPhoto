"""A durable, resumable shoot workflow using the existing single worker."""
from threading import Lock

from fastapi import HTTPException

from .database import AnalysisResult, PhotoAsset, ProcessingJob, RecipeDraft, RecipeRevision, StyleProfile, dumps, loads, now
from .schemas import WorkflowRequest


def register_workflows(app, catalog):
    admission = Lock()

    @app.post('/api/workflows')
    def start(body: WorkflowRequest):
        with admission:
            return admit(body)

    def admit(body):
        from .service import enqueue

        with catalog.session() as s:
            if s.query(ProcessingJob).filter_by(kind='import').filter(ProcessingJob.state.in_(['queued','running','paused'])).first():
                raise HTTPException(409, 'Дождитесь завершения импорта, чтобы обработать всю съёмку.')
            query = s.query(PhotoAsset).filter(~PhotoAsset.status.in_(['removed', 'reject']))
            if body.photo_ids:
                query = query.filter(PhotoAsset.id.in_(body.photo_ids))
            elif body.shoot_id:
                query = query.filter_by(shoot_id=body.shoot_id)
            identifiers = [p.id for p in query.order_by(PhotoAsset.captured, PhotoAsset.id)]
            if not identifiers:
                raise HTTPException(400, 'Добавьте фотографии или выделите кадры для обработки')
            if body.profile_id:
                profile = s.get(StyleProfile, body.profile_id)
                if not profile or not any('color' in r.get('roles', []) for r in loads(profile.data, {}).get('references', [])):
                    raise HTTPException(400, 'В выбранном стиле ещё нет готовых цветовых референсов')
            for job in s.query(ProcessingJob).filter_by(kind='workflow').filter(ProcessingJob.state.in_(['queued','running','paused'])):
                if set(loads(job.payload, {}).get('photo_ids', [])) & set(identifiers):
                    raise HTTPException(409, 'Эти кадры уже обрабатываются. Откройте текущую задачу.')
        values = body.model_dump()
        values['photo_ids'] = identifiers
        job_id = enqueue(catalog, 'workflow', values, 25)
        catalog.set_setting('workflow_defaults', {k:values[k] for k in ('profile_id','strength','selection','retouch_strength')})
        return {'job_id':job_id, 'count':len(identifiers)}


def prepare_recipe(pipeline, identifier, job_id, payload):
    catalog = pipeline.catalog
    marker = 'workflow:' + job_id
    with catalog.session() as s:
        if s.query(RecipeRevision).filter_by(photo_id=identifier, source=marker).first():
            return  # Recipe commit survived a crash before its render checkpoint.
        photo = s.get(PhotoAsset, identifier)
        if not photo or photo.status in {'removed', 'reject'}:
            return
        if s.get(RecipeDraft, identifier):
            raise RuntimeError('Есть несохранённая ручная правка. Откройте кадр, примените её и повторите этап.')
        expected = photo.revision
        manual = loads(photo.manual_sections, [])
    if payload.get('profile_id') and 'color' not in manual:
        pipeline.propose_style(identifier, {**payload, 'variants':False})
    with catalog.session() as s:
        photo = s.get(PhotoAsset, identifier)
        if s.get(RecipeDraft, identifier):
            raise RuntimeError('Есть несохранённая ручная правка. Примените её и повторите этап.')
        if not photo or photo.revision != expected or photo.status in {'removed', 'reject'}:
            return  # A newer manual edit always wins.
        recipe = catalog.recipe(photo, s)
        before = recipe.model_dump()
        if payload.get('profile_id') and 'color' not in manual:
            row = s.get(AnalysisResult, identifier)
            proposal = loads(row.data, {}).get('style_proposal', {}) if row else {}
            if proposal.get('input_revision') != expected:
                raise RuntimeError('Цветовой вариант устарел. Повторите обработку этого кадра.')
            recipe.color = type(recipe.color).model_validate(proposal['color'])
        strength = payload.get('retouch_strength', 0.15)
        if 'retouch' not in manual:
            recipe.retouch.strength = strength
            recipe.retouch.color_evenness = strength * .6
            recipe.retouch.body_strength = strength * .6
            recipe.retouch.body_color_evenness = strength * .4
        if before != recipe.model_dump():
            catalog.save_recipe(s, photo, recipe, expected, marker)


def run_workflow(pipeline, job_id, payload):
    from .service import enqueue

    catalog = pipeline.catalog
    identifiers = payload['photo_ids']

    def state():
        with catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            return set(loads(job.checkpoint, [])), loads(job.result, {})

    def message(text, **values):
        with catalog.session() as s:
            job = s.get(ProcessingJob, job_id)
            result = loads(job.result, {})
            result.update(message=text, **values)
            job.result, job.updated = dumps(result), now()

    def yielded():
        return pipeline.stopped(job_id) or pipeline.yield_to_interactive(job_id)

    pipeline.update(job_id, total=len(identifiers)*2)
    for identifier in identifiers:
        if yielded():
            return
        done, _ = state()
        item = 'analyze:' + identifier
        if item in done:
            continue
        message(f'Отбор: анализ {sum(i.startswith("analyze:") for i in done)+1} / {len(identifiers)}')
        try:
            with catalog.session() as s:
                photo = s.get(PhotoAsset, identifier)
                row = s.get(AnalysisResult, identifier)
                needs_analysis = photo and photo.status not in {'removed','reject'} and row is None
            if needs_analysis:
                pipeline.analyze_photo(identifier, payload)
            pipeline.item_done(job_id, item)
        except Exception as error:
            pipeline.item_done(job_id, item, error)
    pipeline.group_and_select(identifiers)
    _, result = state()
    with catalog.session() as s:
        selected = [p.id for p in s.query(PhotoAsset).filter(PhotoAsset.id.in_(identifiers), ~PhotoAsset.status.in_(['removed','reject']))
                    if payload.get('selection') == 'all' or p.status == 'keep' or p.suggested or p.review]
    done, _ = state()
    prior_processed = {i[8:] for i in done if i.startswith('process:')}
    pipeline.update(job_id, total=len(identifiers)+len(set(selected) | prior_processed))
    failed_analysis = {r['item'][8:] for r in result.get('errors', []) if r.get('item','').startswith('analyze:')}
    for number, identifier in enumerate(selected, 1):
        if yielded():
            return
        done, _ = state()
        item = 'process:' + identifier
        if item in done:
            continue
        message(f'Цвет и проявка: {number} / {len(selected)}', photo_ids=selected)
        try:
            if identifier in failed_analysis:
                raise RuntimeError('Сначала необходимо повторить неудачный анализ этого кадра')
            prepare_recipe(pipeline, identifier, job_id, payload)
            pipeline.render_photo(identifier)
            pipeline.item_done(job_id, item)
        except Exception as error:
            pipeline.item_done(job_id, item, error)
    if pipeline.stopped(job_id):
        return
    _, result = state()
    errors = result.get('errors', [])
    export_id = None
    if not errors and selected and payload.get('export_directory'):
        export_id = enqueue(catalog, 'export', {'photo_ids':selected,'directory':payload['export_directory'],
                            'format':'jpeg','profile':'srgb'}, 40, identifier=job_id+'-export')
    message('Есть ошибки. Готовые кадры сохранены; можно повторить неудачные этапы.' if errors else
            'Кадры готовы к проверке.' + (' JPEG-экспорт добавлен в очередь.' if export_id else ''),
            prepared_count=len(selected)-sum(r.get('item','').startswith('process:') for r in errors), export_job_id=export_id, photo_ids=selected)
    with catalog.session() as s:
        job = s.get(ProcessingJob, job_id)
        if job.state in {'paused', 'cancelled'}:
            if export_id:
                child = s.get(ProcessingJob, export_id)
                if child and child.state == 'queued':
                    # The single worker cannot start the child before this parent returns.
                    # Delete only the unstarted queue entry so resume can recreate it.
                    s.delete(child)
            return
        job.state = 'completed_with_errors' if errors else 'completed'
        job.updated = now()
