/* Real browser checks; Playwright is pinned in frontend/package-lock.json. */
const { createRequire } = require('node:module');
const { chromium } = createRequire(require('node:path').join(__dirname, '../frontend/package.json'))('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const folder = path.resolve(process.argv[2]);
  const session = JSON.parse(fs.readFileSync(path.join(folder, 'launch-session.json'), 'utf8'));
  const out = path.join(folder, 'ui'); fs.mkdirSync(out, {recursive:true});
  const browser = await chromium.launch({channel:'msedge',headless:true,args:['--disable-background-networking','--disable-component-update']});
  const report = {checks:{}, errors:[]};
  try {
    const context = await browser.newContext({viewport:{width:1440,height:960},deviceScaleFactor:1});
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    await page.goto(session.url+'/?token='+encodeURIComponent(session.token));
    await page.locator('.photo-card').first().waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('.photo-card img')].slice(0,4).every(i=>i.complete && i.naturalWidth));
    await page.screenshot({path:path.join(out,'library.png')});
    const names = await page.locator('.photo-card .photo-name').allTextContents();
    assert(names.length>=2);
    await page.getByRole('button',{name:'Выделить '+names[0],exact:true}).click();
    await page.getByRole('button',{name:'Выделить '+names[1],exact:true}).click();
    await page.getByRole('button',{name:'Сравнить',exact:true}).click();
    await page.locator('.compare-image img').waitFor();
    assert.equal(await page.locator('.editor-image').getAttribute('alt'),names[0]);
    assert.equal(await page.locator('.compare-image img').getAttribute('alt'),names[1]);
    const comparisonRequest = page.waitForRequest(r => r.url().endsWith('/api/decisions') && r.method()==='POST');
    await page.locator('.compare-image').getByRole('button',{name:'Этот лучше'}).click();
    const preference = (await comparisonRequest).postDataJSON();
    const leftURL = new URL(await page.locator('.editor-image').getAttribute('src'),session.url);
    const rightURL = new URL(await page.locator('.compare-image img').getAttribute('src'),session.url);
    assert.equal(preference.other_id,leftURL.pathname.split('/')[3]);
    assert.deepEqual(preference.photo_ids,[rightURL.pathname.split('/')[3]]);
    report.checks.explicit_comparison_pair = true;
    await page.getByRole('button',{name:'К съёмке',exact:true}).click();
    await page.locator('.photo-card').first().waitFor();
    // Camera view must use actual JPEG pixels, independent of full RAW readiness.
    const rawCard = page.locator('.photo-card').filter({hasText:'RAW + JPG'}).first();
    await rawCard.click();
    await page.getByRole('button',{name:'JPEG камеры',exact:true}).click();
    await page.getByRole('button',{name:'Масштаб 1:1',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('.editor-image')?.complete && document.querySelector('.editor-image')?.naturalWidth>3000);
    assert((await page.locator('.editor-image').getAttribute('src')).includes('camera-full'));
    assert.equal(await page.locator('.native-view').count(),1);
    report.checks.camera_jpeg_native_scale = true;
    await page.screenshot({path:path.join(out,'camera-1to1.png')});
    await page.getByRole('button',{name:'Масштаб 1:1',exact:true}).click();
    await page.getByRole('button',{name:'Вернуться к RAW',exact:true}).click();
    // A failed recipe save must leave the edited frame open and the draft available.
    await page.route('**/api/photos/*/recipe',async route => {
      if(route.request().method()==='PUT') await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Контрольная ошибка сохранения'})});
      else await route.continue();
    });
    const slider = page.locator('.control-section input[type=range]').first();
    const newValue = (Number(await slider.inputValue())===0.1) ? '0.2' : '0.1';
    await slider.fill(newValue);
    const editorName = await page.locator('.editor-image').getAttribute('alt');
    await page.getByRole('button',{name:'Следующий кадр',exact:true}).click();
    await page.getByText('Контрольная ошибка сохранения',{exact:false}).first().waitFor();
    assert.equal(await page.locator('.editor-image').getAttribute('alt'),editorName);
    assert.equal(await slider.inputValue(),newValue);
    report.checks.failed_save_preserves_draft = true;
    await page.unroute('**/api/photos/*/recipe');
    await page.getByRole('button',{name:'Следующий кадр',exact:true}).click();
    await page.waitForFunction(name => document.querySelector('.editor-image')?.alt !== name,editorName);
    report.checks.save_before_navigation = true;
    await page.getByRole('button',{name:'Настройки',exact:true}).click();
    const modelPath = page.getByLabel('Папка моделей',{exact:true});
    await modelPath.waitFor();
    const originalPath = await modelPath.inputValue();
    await modelPath.focus(); await page.keyboard.press('1');
    assert.equal((await modelPath.inputValue()).length, originalPath.length+1);
    report.checks.shortcuts_ignore_fields = true;
    await page.screenshot({path:path.join(out,'settings.png')});
    // Exercise the virtual library beyond its former first-1000 boundary using a
    // deterministic API fixture. This does not insert synthetic data into the project.
    const fixtureContext = await browser.newContext({viewport:{width:1440,height:960}});
    const fixture = await fixtureContext.newPage();
    const headers = {'X-OpenPhoto-Token':session.token};
    const initial = await (await context.request.get(session.url+'/api/photos?limit=1',{headers})).json();
    const seed = await (await context.request.get(session.url+'/api/photos/'+initial.photos[0].id,{headers})).json();
    const thumb = await (await context.request.get(session.url+'/api/photos/'+seed.id+'/image',{headers})).body();
    const rows = Array.from({length:1005},(_,index)=>({...initial.photos[0],id:'fixture-'+index,name:`Frame-${index+1}.JPG`,shoot_id:'fixture',group_id:'group',raw:false,paired:false,revision:0}));
    await fixture.route('**/api/**',async route => {
      const url = new URL(route.request().url());
      const reply = data => route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      if(url.pathname==='/api/events') return route.fulfill({contentType:'text/event-stream',body:'event: jobs\ndata: []\n\n'});
      if(url.pathname==='/api/shoots') return reply([{id:'fixture',name:'Pagination fixture',count:1005}]);
      if(url.pathname==='/api/photos') {const offset=Number(url.searchParams.get('offset')||0);return reply({total:rows.length,photos:rows.slice(offset,offset+250)});}
      if(url.pathname.endsWith('/image')) return route.fulfill({contentType:'image/jpeg',body:thumb});
      if(url.pathname.endsWith('/render')) return reply({job_id:'fixture-job'});
      const id=url.pathname.split('/')[3];
      if(id?.startsWith('fixture-')) return reply({...seed,...rows[Number(id.slice(8))],draft:null});
      await route.continue();
    });
    await fixture.goto(session.url+'/?token='+encodeURIComponent(session.token));
    await fixture.waitForFunction(()=>document.querySelector('.count-pill')?.textContent==='1005');
    await fixture.locator('.gallery-scroll').evaluate(element=>{element.scrollTop=element.scrollHeight;});
    await fixture.getByText('Frame-1005.JPG',{exact:true}).click();
    await fixture.locator('.editor-image[alt="Frame-1005.JPG"]').waitFor();
    assert.equal(await fixture.locator('.editor-nav span').innerText(),'1005 / 1005');
    await fixture.keyboard.press('ArrowLeft');
    await fixture.locator('.editor-image[alt="Frame-1004.JPG"]').waitFor();
    report.checks.paginated_navigation_1005 = true;
    await fixtureContext.close();
    assert.deepEqual(report.errors,[]);
    report.ok = true;
  } catch(error) {
    report.ok=false; report.failure=error.message; process.exitCode=1;
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  }
})().catch(error => {console.error(error.message);process.exitCode=1;});
