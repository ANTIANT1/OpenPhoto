/* Deterministic browser regressions: real React build, controlled response ordering. */
const {createRequire} = require('node:module');
const {chromium} = createRequire(require('node:path').join(__dirname,'../frontend/package.json'))('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve}; };
(async () => {
  const folder = path.resolve(process.argv[2]);
  const session = JSON.parse(fs.readFileSync(path.join(folder, 'launch-session.json'), 'utf8'));
  const seed = JSON.parse(fs.readFileSync(path.join(folder, 'ui-fixture.json'), 'utf8'));
  const image = fs.readFileSync(path.join(folder, 'fixture.jpg'));
  const browser = await chromium.launch({channel:'msedge', headless:true,
    args:['--disable-background-networking','--disable-component-update']});
  const report = {checks:{}, errors:[]};
  try {
    async function setup(count = 3) {
      const fixture = structuredClone(seed), saves = [], gates = {}, batches = [], pages = [], decisions = [], imageRequests = [], workflows = [];
      if (count > 3) {
        const original = fixture.photos[0], detail = fixture.details[original.id];
        fixture.photos = Array.from({length:count}, (_,i) => ({...structuredClone(original),id:`fixture-${i}`,name:`Frame-${String(i).padStart(4,'0')}.jpg`}));
        fixture.ids = fixture.photos.map(p => p.id);
        fixture.details = Object.fromEntries(fixture.photos.map(p => [p.id,{...structuredClone(detail),...p}]));
      }
      const [a,b,c] = fixture.ids;
      const context = await browser.newContext({viewport:{width:1440,height:960}});
      const page = await context.newPage();
      page.on('pageerror', e => report.errors.push(e.message));
      await page.route('**/api/**', async route => {
        const request = route.request(), url = new URL(request.url());
        const reply = (value,status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
        if (url.pathname === '/api/events') return route.fulfill({contentType:'text/event-stream',body:'event: jobs\ndata: []\n\n'});
        if (url.pathname === '/api/jobs') return reply([]);
        if (url.pathname === '/api/workflows') { workflows.push(request.postDataJSON()); return reply({job_id:'workflow-fixture',count:fixture.photos.length}); }
        if (url.pathname === '/api/shoots') return reply([{id:fixture.photos[0].shoot_id,name:'Browser fixture',count:fixture.photos.length}]);
        if (url.pathname === '/api/photos') {
          const offset=Number(url.searchParams.get('offset') || 0), limit=Number(url.searchParams.get('limit') || 250);
          pages.push(offset);
          const visible=fixture.photos.filter(p => url.searchParams.get('filter')==='removed' ? p.status==='removed' : p.status!=='removed');
          return reply({photos:visible.slice(offset,offset+limit),total:visible.length});
        }
        if (url.pathname === '/api/recipes/batch') { batches.push(request.postDataJSON()); return reply({updated:[b],skipped:[]}); }
        if (url.pathname === '/api/decisions') {
          gates.decision?.started.resolve();
          if (gates.decision) await gates.decision.release.promise;
          const body=request.postDataJSON(); decisions.push(body);
          for(const id of body.photo_ids) {
            const photo=fixture.photos.find(p=>p.id===id);
            if(body.action==='remove') { photo.previousStatus=photo.status; photo.status='removed'; }
            if(body.action==='restore_removed') photo.status=photo.previousStatus || 'unreviewed';
            if(['keep','reject'].includes(body.action)) photo.status=body.action;
            fixture.details[id].status=photo.status;
          }
          return reply({updated:body.photo_ids.length});
        }
        const id = url.pathname.split('/')[3];
        if (fixture.details[id]) {
          if (url.pathname.includes('/restore/')) {
            gates.restore?.started.resolve();
            if (gates.restore) await gates.restore.release.promise;
            fixture.details[id].recipe.develop.exposure = 2;
            fixture.details[id].revision++;
            return reply({revision:fixture.details[id].revision,job_id:'restore-fixture'});
          }
          if (url.pathname.endsWith('/image')) {
            imageRequests.push({id,variant:url.searchParams.get('variant')});
            if(id===b && gates.peer && url.searchParams.get('variant')==='render') {
              gates.peer.started.resolve(); await gates.peer.release.promise;
            }
            return route.fulfill({contentType:'image/jpeg',body:image});
          }
          if (url.pathname.endsWith('/render')) return reply({job_id:'render-fixture'});
          if (url.pathname.endsWith('/draft')) return reply({saved:true});
          if (url.pathname.endsWith('/recipe')) {
            const body = request.postDataJSON(); saves.push({id,body});
            gates.save?.started.resolve();
            if (gates.save) await gates.save.release.promise;
            if (gates.failSave) return reply({detail:'Контрольная ошибка сохранения'},503);
            assert.equal(body.expected_revision, fixture.details[id].revision);
            fixture.details[id].recipe = body.recipe;
            fixture.details[id].revision++;
            return reply({revision:fixture.details[id].revision});
          }
          if (gates.get?.id === id) {
            gates.get.started.resolve();
            await gates.get.release.promise;
          }
          return reply(fixture.details[id]);
        }
        return route.continue();
      });
      await page.goto(session.url+'/?token='+encodeURIComponent(session.token));
      await page.locator('.photo-card').first().waitFor();
      const open = async id => {
        await page.locator('.photo-card').filter({hasText:fixture.details[id].name}).click();
        await page.locator(`.editor-image[alt="${fixture.details[id].name}"]`).waitFor();
      };
      const current = async id => assert.equal(await page.locator('.editor-image').getAttribute('alt'),fixture.details[id].name);
      const slider = page.locator('.control-section input[type=range]').first();
      const next = () => page.getByRole('button',{name:'Следующий кадр',exact:true}).click();
      const gate = name => (gates[name] = {started:deferred(), release:deferred()});
      const rendered = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      return {context,page,fixture,saves,batches,gates,pages,decisions,imageRequests,workflows,a,b,c,open,current,slider,next,gate,rendered};
    }
    {
      const t = await setup(), gate = t.gate('decision');
      await t.open(t.a);
      await t.page.getByRole('button',{name:'В отбор',exact:true}).click();
      await gate.started.promise;
      await t.next();
      await t.page.locator(`.editor-image[alt="${t.fixture.details[t.b].name}"]`).waitFor();
      await t.slider.fill('1.25');
      const refreshed = t.page.waitForResponse(r => new URL(r.url()).pathname === `/api/photos/${t.a}`);
      gate.release.resolve();
      await refreshed; await t.rendered();
      await t.current(t.b);
      assert.equal(await t.slider.inputValue(),'1.25');
      await t.page.getByRole('button',{name:'Применить изменения',exact:true}).click();
      await t.page.waitForFunction(() => document.querySelector('.adjustment-title [role=status]')?.textContent?.includes('сохранено'));
      assert.deepEqual(t.saves.map(s=>[s.id,s.body.recipe.develop.exposure]),[[t.b,1.25]]);
      report.checks.delayed_decision_cannot_change_frame_or_submit_foreign_recipe = true;
      await t.page.screenshot({path:path.join(folder,'editor-after-delayed-decision.png')});
      await t.context.close();
    }
    {
      const t = await setup(), gate = t.gate('save');
      await t.open(t.a); await t.slider.fill('0.5');
      await t.next(); await gate.started.promise;
      await t.current(t.a);
      await t.slider.fill('1');
      gate.release.resolve();
      await t.page.locator(`.editor-image[alt="${t.fixture.details[t.b].name}"]`).waitFor();
      assert.deepEqual(t.saves.map(s=>[s.id,s.body.expected_revision,s.body.recipe.develop.exposure]),[[t.a,0,.5],[t.a,1,1]]);
      assert.equal(await t.slider.inputValue(),'0.75');
      report.checks.navigation_flushes_edits_made_during_inflight_save = true;
      await t.context.close();
    }
    {
      const t = await setup();
      await t.open(t.a); await t.slider.fill('0.5'); t.gates.failSave = true;
      await t.next();
      await t.page.getByText('Контрольная ошибка сохранения',{exact:false}).first().waitFor();
      await t.current(t.a); assert.equal(await t.slider.inputValue(),'0.5');
      assert.equal(await t.page.locator('.adjustment-title [role=status]').textContent(),'Ошибка сохранения');
      t.gates.failSave = false;
      await t.next(); await t.page.locator(`.editor-image[alt="${t.fixture.details[t.b].name}"]`).waitFor();
      assert.equal(t.fixture.details[t.a].recipe.develop.exposure,.5);
      report.checks.failed_save_keeps_draft_and_allows_retry = true;
      await t.context.close();
    }
    {
      const t = await setup();
      await t.open(t.a);
      const gate = t.gate('get'); gate.id = t.b;
      await t.next(); await gate.started.promise;
      await t.page.getByRole('button',{name:'К съёмке',exact:true}).click();
      await t.page.locator('.photo-card').first().waitFor();
      const response = t.page.waitForResponse(r => new URL(r.url()).pathname === `/api/photos/${t.b}`);
      gate.release.resolve(); await response; await t.rendered();
      assert.equal(await t.page.locator('.editor-image').count(),0);
      assert.equal(t.saves.length,0);
      report.checks.leaving_editor_invalidates_pending_navigation = true;
      await t.context.close();
    }
    {
      const t = await setup(), gate = t.gate('restore');
      await t.open(t.a);
      await t.page.locator('.history').getByText('Версия 0',{exact:true}).click();
      await gate.started.promise;
      await t.next();
      await t.current(t.a);
      gate.release.resolve();
      await t.page.locator(`.editor-image[alt="${t.fixture.details[t.b].name}"]`).waitFor();
      assert.equal(t.fixture.details[t.a].recipe.develop.exposure,2);
      assert.equal(t.saves.length,0);
      await t.slider.fill('1.25');
      await t.page.getByRole('button',{name:'Применить изменения',exact:true}).click();
      await t.page.waitForFunction(() => document.querySelector('.adjustment-title [role=status]')?.textContent?.includes('сохранено'));
      assert.deepEqual(t.saves.map(s=>[s.id,s.body.recipe.develop.exposure]),[[t.b,1.25]]);
      report.checks.delayed_restore_cannot_clear_next_frames_draft_or_overwrite_restored_recipe = true;
      await t.context.close();
    }
    {
      const t=await setup(); await t.open(t.a); await t.slider.fill('0.6');
      t.gates.failSave=true;
      assert.equal(await t.page.evaluate(()=>window.openPhotoFlush()),false);
      assert.equal(await t.slider.inputValue(),'0.6');
      t.gates.failSave=false;
      assert.equal(await t.page.evaluate(()=>window.openPhotoFlush()),true);
      assert.equal(t.fixture.details[t.a].recipe.develop.exposure,.6);
      report.checks.desktop_close_flush_retains_failed_edits=true;
      await t.context.close();
    }
    {
      const t=await setup(), gate=t.gate('peer');
      for(const id of [t.a,t.b]) await t.page.getByRole('button',{name:'Выделить '+t.fixture.details[id].name,exact:true}).click();
      await t.page.getByRole('button',{name:'Сравнить',exact:true}).click();
      await gate.started.promise;
      const variants=()=>t.page.locator('.editor-image, .compare-image img').evaluateAll(images=>images.map(i=>new URL(i.src).searchParams.get('variant')));
      assert.deepEqual(await variants(),['original','original']);
      gate.release.resolve();
      await t.page.waitForFunction(()=>[...document.querySelectorAll('.editor-image,.compare-image img')].every(i=>new URL(i.src).searchParams.get('variant')==='render'));
      await t.page.getByRole('button',{name:'До / После',exact:true}).click();
      await t.page.waitForFunction(()=>[...document.querySelectorAll('.editor-image,.compare-image img')].every(i=>new URL(i.src).searchParams.get('variant')==='base'));
      report.checks.comparison_sources_stay_aligned=true;
      await t.context.close();
    }
    {
      const t=await setup();
      for(const id of [t.a,t.b]) await t.page.getByRole('button',{name:'Выделить '+t.fixture.details[id].name,exact:true}).click();
      await t.open(t.a); await t.slider.fill('0.4');
      await t.page.locator('.adjustment-footer').getByRole('button',{name:'Применить к серии',exact:true}).click();
      await t.page.getByLabel('Проявка · экспозиция, баланс белого и RAW-параметры').check();
      await t.page.locator('.modal').getByRole('button',{name:'Применить к серии',exact:true}).click();
      await t.page.waitForFunction(()=>!document.querySelector('.modal h2')?.textContent?.includes('Настройки для серии'));
      assert.equal(t.batches.length,1); assert.deepEqual(t.batches[0].photo_ids,[t.b]);
      assert(t.batches[0].sections.includes('develop'));
      assert.equal(t.batches[0].recipe.develop.exposure,.4);
      assert.equal(t.fixture.details[t.a].recipe.develop.exposure,.4);
      report.checks.batch_flushes_draft_and_targets_selection=true;
      await t.context.close();
    }
    {
      const t=await setup(1007);
      await t.page.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='1007');
      // Initialization can cancel and repeat the first request when settings arrive.
      assert.deepEqual([...new Set(t.pages)],[0,250,500,750,1000]);
      await t.page.getByRole('button',{name:'Выделить Frame-0000.jpg',exact:true}).click();
      await t.page.locator('.gallery-scroll').evaluate(el=>{el.scrollTop=el.scrollHeight;});
      await t.page.getByRole('button',{name:'Выделить Frame-1006.jpg',exact:true}).click();
      assert.match(await t.page.locator('.selection-toolbar').innerText(),/Выбрано 2/);
      await t.open(t.fixture.ids[1006]);
      assert.match(await t.page.locator('.editor-nav').innerText(),/1007 \/ 1007/);
      await t.page.getByRole('button',{name:'Предыдущий кадр',exact:true}).click();
      await t.page.locator('.editor-image[alt="Frame-1005.jpg"]').waitFor();
      await t.page.getByRole('button',{name:'К съёмке',exact:true}).click();
      assert.match(await t.page.locator('.selection-toolbar').innerText(),/Выбрано 2/);
      assert((await t.page.locator('.photo-card').count()) < 100, 'Grid must stay virtualized');
      report.checks.catalog_over_1000_keeps_pagination_navigation_and_selection=true;
      await t.context.close();
    }
    {
      const t=await setup(1007);
      await t.page.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='1007');
      await t.page.keyboard.press('Control+a');
      assert.match(await t.page.locator('.selection-toolbar').innerText(),/Выбрано 1007/);
      await t.page.keyboard.press('Delete');
      await t.page.locator('.modal').getByRole('button',{name:'Удалить из каталога',exact:true}).click();
      await t.page.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='0');
      assert.equal(t.decisions[0].action,'remove');
      assert.equal(new Set(t.decisions[0].photo_ids).size,1007);
      await t.page.getByRole('button',{name:'Удалённые',exact:true}).click();
      await t.page.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='1007');
      await t.page.getByRole('button',{name:'Выделить все',exact:true}).click();
      await t.page.getByRole('button',{name:'Вернуть в каталог',exact:true}).click();
      await t.page.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='0');
      assert.equal(t.decisions[1].action,'restore_removed');
      await t.page.getByRole('button',{name:'Все кадры',exact:true}).click();
      await t.page.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='1007');
      await t.page.getByRole('button',{name:'Новая съёмка',exact:true}).click();
      const field=t.page.getByLabel('Название съёмки');
      await field.fill('Не удалять кадры при вводе'); await field.press('Control+a'); await field.press('Delete');
      assert.equal(await field.inputValue(),''); assert.equal(t.decisions.length,2);
      assert(await t.page.getByRole('button',{name:'Выбрать файлы ARW/JPEG',exact:true}).isVisible());
      report.checks.select_all_delete_restore_1007_and_text_field_shortcuts=true;
      await t.context.close();
    }
    {
      const t=await setup(); await t.open(t.a);
      await t.page.waitForFunction(()=>new URL(document.querySelector('.editor-image').src).searchParams.get('variant')==='render');
      assert(!t.imageRequests.some(r=>r.variant==='full' || r.variant==='fullbase'));
      await t.page.getByRole('button',{name:'Масштаб 1:1',exact:true}).click();
      await t.page.waitForFunction(()=>new URL(document.querySelector('.editor-image').src).searchParams.get('variant')==='full');
      assert(t.imageRequests.some(r=>r.variant==='full'));
      report.checks.full_resolution_is_requested_only_for_one_to_one=true;
      await t.context.close();
    }
    {
      const t=await setup();
      await t.page.getByRole('button',{name:'Обработать съёмку',exact:true}).click();
      await t.page.locator('.modal h2').filter({hasText:'Обработка и экспорт'}).waitFor();
      assert.equal(t.workflows.length,1);
      assert.equal(t.workflows[0].selection,'suggested');
      assert.equal(t.workflows[0].retouch_strength,.15);
      assert.equal(t.workflows[0].export_directory,null);
      report.checks.one_click_launches_whole_workflow=true;
      await t.context.close();
    }
    {
      const t=await setup();
      await t.page.getByRole('button',{name:'Обрабатывать вручную',exact:true}).click();
      await t.page.getByRole('button',{name:'Кадр',exact:true}).click();
      await t.page.locator('.crop-overlay').waitFor();
      await t.page.getByRole('button',{name:'1:1',exact:true}).click();
      const overlay=t.page.locator('.crop-overlay');
      const original=await overlay.boundingBox();
      const drag=async (target,dx,dy)=>{
        const box=await target.boundingBox();
        await t.page.mouse.move(box.x+box.width/2,box.y+box.height/2);
        await t.page.mouse.down();
        await t.page.mouse.move(box.x+box.width/2+dx,box.y+box.height/2+dy,{steps:6});
        await t.page.mouse.up(); await t.rendered();
      };
      await drag(t.page.locator('[data-crop-handle=e]'),-35,0);
      const resized=await overlay.boundingBox();
      assert(resized.width<original.width-25,'Edge must resize crop');
      await drag(t.page.locator('[data-crop-handle=se]'),-15,-30);
      const corner=await overlay.boundingBox();
      assert(corner.height<resized.height-20 && corner.width<resized.width-10,'Corner must resize both dimensions');
      await drag(overlay,15,12);
      const moved=await overlay.boundingBox();
      assert(Math.abs(moved.width-corner.width)<2 && moved.x>corner.x+10,'Inside must move crop without resizing');
      const image=t.page.locator('.editor-image'), before=await image.boundingBox();
      await t.page.mouse.move(before.x+before.width*.5,before.y+before.height*.5);
      await t.page.keyboard.down('Control'); await t.page.mouse.wheel(0,-300); await t.page.keyboard.up('Control');
      await t.page.waitForFunction(w=>document.querySelector('.editor-image').getBoundingClientRect().width>w*1.4,before.width);
      const deviceRatio=await t.page.evaluate(()=>window.devicePixelRatio);
      assert.equal(deviceRatio,1,'Ctrl+wheel must zoom image, not browser UI');
      await t.page.getByRole('button',{name:'По окну',exact:true}).click(); await t.rendered();
      assert(Math.abs((await image.boundingBox()).width-before.width)<3);
      await t.page.getByRole('button',{name:'Применить изменения',exact:true}).click();
      assert(t.saves[0].body.recipe.crop.w<1 && t.saves[0].body.recipe.lock_crop);
      await t.page.screenshot({path:path.join(folder,'crop-editor.png')});
      report.checks.crop_edges_corners_move_ctrl_wheel_and_fit=true;
      await t.context.close();
    }
    assert.deepEqual(report.errors,[]);
  } catch (error) { report.failure = error.stack; process.exitCode = 1; }
  finally {
    await browser.close();
    fs.writeFileSync(path.join(folder,'editor-races.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  }
})();
