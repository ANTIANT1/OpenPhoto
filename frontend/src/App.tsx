import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { IconButton, Slider, Modal } from './controls';
import { loadPhotos, comparisonPair } from './library';
import { ProjectsPanel } from './ProjectsPanel';
import { BatchPanel } from './BatchPanel';
import { JobsPanel, jobNames } from './JobsPanel';
import { usePhotoEditor } from './usePhotoEditor';
import { useImageViewport } from './useImageViewport';
import { GettingStarted } from './GettingStarted';
import { Histogram } from './Histogram';
import { EngineSettings } from './EngineSettings';
import { AnalysisPanel } from './AnalysisPanel';
import { WorkflowLauncher } from './WorkflowLauncher';
import { CropOverlay, dragCrop } from './CropOverlay';
import type { CropDrag, CropHandle } from './CropOverlay';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Aperture, ArrowDownToLine, ArrowLeft, ArrowRight, Check, ChevronDown, CircleHelp, Columns2, Crop as CropIcon, Folder, FolderPlus, Grid2X2, Hand, Heart, ImagePlus, Layers, Loader2, Maximize2, Minus, Palette, Plus, RefreshCw, RotateCcw, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Star, Trash2, WandSparkles, X } from 'lucide-react';
import { api, imageUrl, post } from './api';
import type { Crop, Detail, Job, Photo, Profile, Recipe, Shoot, Status } from './types';

const historyNames: Record<string,string> = {paired_raw:'Добавлен исходный RAW',geometry_migration:'Новая геометрия',exposure_harmonize:'Согласование экспозиции',manual:'Ваша правка',default:'Исходный рецепт',crop_accept:'Принятое кадрирование',style_accept:'Принятый стиль',restore:'Восстановленная версия',engine_migration:'Новая версия движка',batch_group:'Настройки группы',batch_shoot:'Настройки съёмки',batch_selection:'Пакетная правка',auto_crop:'Автоматическое кадрирование'};

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [shoots, setShoots] = useState<Shoot[]>([]);
  const [shootId, setShootId] = useState('');
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('time');
  const [selected, updateSelected] = useState<Set<string>>(new Set());
  const allSelectedQuery = useRef<string | null>(null);
  const setSelected: typeof updateSelected = value => { allSelectedQuery.current = null; updateSelected(value); };
  const [removalIds, setRemovalIds] = useState<string[]>([]);
  const {detail, draft, editorRef, activate, clear, setDraft, updateDetail, syncRemote, persistDraft, replaceRecipe, saveState, setSaveState} = usePhotoEditor();
  const [tab, setTab] = useState('color');
  const [modal, setModal] = useState<string | null>(null);
  const [workflowModal, setWorkflowModal] = useState(false);
  const [toast, setToast] = useState('');
  const [busy, setBusy] = useState(false);
  const [before, setBefore] = useState(false);
  const [renderReady, setRenderReady] = useState(false);
  const [fullReady, setFullReady] = useState(false);
  const [imageAspect, setImageAspect] = useState(1);
  const [fitWidth, setFitWidth] = useState(0);
  const [showMask, setShowMask] = useState(false);
  const [shootToRemove, setShootToRemove] = useState<Shoot | null>(null);
  const [showGuide, setShowGuide] = useState(false);
  const [compare, setCompare] = useState(false);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [cameraView, setCameraView] = useState(false);
  const navigationEpoch = useRef(0);
  const refreshAbort = useRef<AbortController | null>(null);
  const loadedQuery = useRef('');
  const selectAll = () => { allSelectedQuery.current = loadedQuery.current; updateSelected(new Set(photos.map(p => p.id))); };
  useEffect(() => {
    if (allSelectedQuery.current !== null && allSelectedQuery.current === loadedQuery.current)
      updateSelected(new Set(photos.map(p => p.id)));
  }, [photos]);
  const [geometryReady, setGeometryReady] = useState(false);
  const [brush, setBrush] = useState<'none' | 'protect' | 'heal'>('none');
  const [brushRadius, setBrushRadius] = useState(0.02);
  const [formPath, setFormPath] = useState('');
  const [formName, setFormName] = useState('');
  const [exportFormat, setExportFormat] = useState('jpeg');
  const [exportProfile, setExportProfile] = useState('srgb');
  const [exportEdge, setExportEdge] = useState(0);
  const [includeProposed, setIncludeProposed] = useState(false);
  const [geometryProposal, setGeometryProposal] = useState<{recipe: Recipe; note: string} | null>(null);
  const [roots, setRoots] = useState<{id: string; path: string; available: boolean}[]>([]);
  const [cropDrag, setCropDrag] = useState<CropDrag | null>(null);
  const [brushPoints, setBrushPoints] = useState<[number, number][]>([]);
  const gridRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [columns, setColumns] = useState(4);
  const mainViewportRef = useRef<HTMLDivElement>(null);
  const peerViewportRef = useRef<HTMLDivElement>(null);
  const viewport = useImageViewport(mainViewportRef, imageRef, detail?.id, tab === 'crop' || brush !== 'none', !!modal || workflowModal);
  const {zoom, fullResolution} = viewport;
  const [peerWidth, setPeerWidth] = useState(0);
  const [peerReady, setPeerReady] = useState<string | null>(null);
  useEffect(() => {
    const view=mainViewportRef.current;
    if(!view) return;
    const measure=()=>setFitWidth(Math.max(1,Math.min(view.clientWidth,Math.min(view.clientHeight,window.innerHeight-345)*imageAspect)));
    const observer=new ResizeObserver(measure); observer.observe(view); measure();
    return ()=>observer.disconnect();
  },[detail?.id,imageAspect,compare]);
  useEffect(()=>{
    if(fullResolution && detail && !cameraView) {
      void post(`/photos/${detail.id}/render?full=true`).catch(e=>notify(String(e)));
      if(compare) for(const id of comparisonIds.filter(id=>id!==detail.id)) void post(`/photos/${id}/render?full=true`).catch(e=>notify(String(e)));
    }
  },[fullResolution,detail?.id,cameraView,compare]);
  const leaveEditor = async (after?: () => void) => {
    const epoch = ++navigationEpoch.current;
    try { await persistDraft(); if (epoch !== navigationEpoch.current) return; clear(); setCompare(false); after?.(); }
    catch (e) { setToast(String(e)); }
  };
  useEffect(() => { setRenderReady(false); setFullReady(false); }, [detail?.id, detail?.revision]);
  const syncScroll = (source: HTMLDivElement, target: HTMLDivElement | null) => {
    if (!target) return;
    const x = source.scrollLeft / Math.max(1, source.scrollWidth-source.clientWidth) * Math.max(0,target.scrollWidth-target.clientWidth);
    const y = source.scrollTop / Math.max(1, source.scrollHeight-source.clientHeight) * Math.max(0,target.scrollHeight-target.clientHeight);
    if (Math.abs(target.scrollLeft-x) > .5) target.scrollLeft=x;
    if (Math.abs(target.scrollTop-y) > .5) target.scrollTop=y;
  };
  const notify = (message: string) => { setToast(message); };
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 6000); return () => clearTimeout(timer); }, [toast]);

  const refresh = useCallback(async () => {
    refreshAbort.current?.abort();
    const controller = new AbortController(); refreshAbort.current = controller;
    try {
      const query = `shoot_id=${shootId}&filter=${filter}&sort=${sort}`;
      const incremental = loadedQuery.current !== query;
      loadedQuery.current = query;
      await Promise.all([
        loadPhotos(query, controller.signal, setPhotos, incremental),
        api<Shoot[]>('/shoots', {signal:controller.signal}).then(setShoots),
        api<Profile[]>('/profiles', {signal:controller.signal}).then(setProfiles),
        api<Status>('/status', {signal:controller.signal}).then(setStatus)
      ]);
    } catch (error) { if (!controller.signal.aborted) notify(String(error)); }
  }, [shootId, filter, sort]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const events = new EventSource('/api/events');
    events.addEventListener('jobs', event => { setJobs(JSON.parse((event as MessageEvent).data)); });
    events.onerror = () => { /* EventSource reconnects; existing work remains in SQLite. */ };
    return () => events.close();
  }, []);
  const catalogUpdate = jobs.map(j => `${j.id}:${j.state}:${j.kind === 'import' ? Math.floor(j.completed / 20) : 0}`).join('|');
  useEffect(() => { void refresh(); }, [catalogUpdate, refresh]);
  const latestUpdate = jobs.map(j => `${j.id}:${j.completed}:${j.state}`).join('|');
  const frameUpdate = jobs.filter(j => j.photo_ids.includes(detail?.id || '') && ['completed','completed_with_errors'].includes(j.state)).map(j => `${j.id}:${j.state}`).join('|');
  useEffect(() => {
    const session = editorRef.current;
    const current = session?.detail;
    if (current) {
      const pendingImages: HTMLImageElement[] = [];
      for (const variant of fullResolution ? ['render', 'full'] : ['render']) {
        const img = new Image();
        pendingImages.push(img);
        img.onload = () => { if (editorRef.current?.detail.id === current.id && editorRef.current.detail.revision === current.revision) {
          if (variant === 'render') setRenderReady(true); else setFullReady(true);
        } };
        img.src = imageUrl(current.id, variant, current.revision);
      }
      void api<Detail>(`/photos/${current.id}`).then(updated => {
        if (session) syncRemote(session.key, current.revision, updated);
      }).catch(e => notify(String(e)));
      return () => { for (const img of pendingImages) { img.onload = null; img.onerror = null; } };
    }
  }, [detail?.id, detail?.revision, frameUpdate, fullResolution]);
  useEffect(() => {
    if (!gridRef.current) return;
    const observer = new ResizeObserver(entries => setColumns(Math.max(2, Math.floor(entries[0].contentRect.width / 240))));
    observer.observe(gridRef.current); return () => observer.disconnect();
  }, [detail, photos.length]);
  const rowHeight = 310;
  const virtualizer = useVirtualizer({ count: Math.ceil(photos.length / columns), getScrollElement: () => gridRef.current, estimateSize: () => rowHeight, overscan: 3 });

  const act = async (fn: () => Promise<unknown>, message?: string) => {
    setBusy(true);
    try { await fn(); if (message) notify(message); await refresh(); }
    catch (error) { notify(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const openPhoto = useCallback(async (id: string) => {
    const epoch = ++navigationEpoch.current;
    try {
      await persistDraft();
      const data = await api<Detail>(`/photos/${id}`);
      await persistDraft();
      if (epoch !== navigationEpoch.current) return;
      activate(data); setCameraView(false); setRenderReady(false); setFullReady(false); setBefore(false); setBrush('none'); setShowMask(false);
      void post(`/photos/${id}/render`).catch(e => notify(String(e)));
    } catch (e) { notify(String(e)); }
  }, []);
  const decision = async (action: string, value?: number, ids?: string[]) => {
    const session = editorRef.current;
    const targets = ids || (session ? [session.detail.id] : [...selected]);
    if (!targets.length) return;
    await act(async () => {
      await post('/decisions', { photo_ids: targets, action, value });
      if (session && targets.includes(session.detail.id)) {
        const updated = await api<Detail>(`/photos/${session.detail.id}`);
        // Decisions only change selection metadata, never the recipe/draft or active frame.
        updateDetail(session.key, current => ({...current, status:updated.status, rating:updated.rating}));
      }
    }, action === 'keep' ? 'Кадры добавлены в отбор' : undefined);
  };
  const navigate = useCallback((step: number) => {
    if (!detail) return;
    const index = photos.findIndex(p => p.id === detail.id);
    if (photos[index + step]) { setCompare(false); void openPhoto(photos[index + step].id); }
  }, [detail, photos, openPhoto]);
  const requestRemoval = () => {
    const ids = detail ? [detail.id] : [...selected];
    if (!ids.length || busy || filter === 'removed') return;
    setRemovalIds(ids); setModal('remove');
  };
  const restoreRemoved = async () => {
    const ids = detail ? [detail.id] : [...selected];
    await act(async () => {
      await persistDraft();
      await post('/decisions', {photo_ids:ids, action:'restore_removed'});
      ++navigationEpoch.current; clear(); setSelected(new Set());
    }, 'Кадры возвращены в каталог');
  };
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable=true]') || modal || workflowModal || event.altKey) return;
      if (detail) {
        if (['Equal','Minus','NumpadAdd','NumpadSubtract'].includes(event.code)) { event.preventDefault(); viewport.scale(['Minus','NumpadSubtract'].includes(event.code) ? 1/1.25 : 1.25); return; }
        if ((event.ctrlKey || event.metaKey) && event.code === 'Digit0') { event.preventDefault(); viewport.fit(); return; }
        if ((event.ctrlKey || event.metaKey) && event.code === 'Digit1') { event.preventDefault(); viewport.native(detail.width*(showOriginal ? 1 : detail.recipe.crop.w),fitWidth); return; }
        if ((event.ctrlKey || event.metaKey) && event.code === 'Enter') { event.preventDefault(); if(!busy && !event.repeat) void save(); return; }
        if (!event.ctrlKey && !event.metaKey && event.code === 'KeyH') { event.preventDefault(); if(!event.repeat) viewport.setHand(v=>!v); return; }
        if (!event.ctrlKey && !event.metaKey && event.code === 'KeyB') { event.preventDefault(); if(!event.repeat) setBefore(v=>!v); return; }
        if (event.code === 'Space') { event.preventDefault(); if(!event.repeat) viewport.spaceDown(); return; }
      }
      if (event.ctrlKey || event.metaKey) {
        if (event.code === 'KeyA' && !detail) { event.preventDefault(); selectAll(); }
        if (event.code === 'KeyZ' && !detail && !busy && !event.repeat) { event.preventDefault(); void act(() => post('/decisions/undo'), 'Последнее действие отменено'); }
        return;
      }
      if (event.key === 'Delete') { event.preventDefault(); if (!event.repeat) requestRemoval(); return; }
      if (event.key === 'Escape') { if (!detail) setSelected(new Set()); else void leaveEditor(); setCompare(false); }
      if (event.key === 'ArrowRight') navigate(1);
      if (event.key === 'ArrowLeft') navigate(-1);
      if (filter !== 'removed' && !busy) {
        if (event.code === 'KeyP') void decision('keep');
        if (event.code === 'KeyX') void decision('reject');
        if (/^[0-5]$/.test(event.key)) void decision('rating', Number(event.key));
      }
    };
    const up = (event:KeyboardEvent) => {
      if (event.code === 'Space' && viewport.spaceHeld) {
        event.preventDefault(); const tapped=viewport.spaceUp();
        if (tapped && detail && !modal && !workflowModal) setBefore(v=>!v);
      }
    };
    window.addEventListener('keydown', key); window.addEventListener('keyup', up);
    return () => {window.removeEventListener('keydown', key);window.removeEventListener('keyup', up);};
  });

  const choose = async (files = false) => {
    if (!window.pywebview) return notify('В браузере вставьте локальный путь. В приложении доступен выбор папки.');
    const paths = await (files ? window.pywebview.api.choose_photos(modal === 'references') : window.pywebview.api.choose_folder());
    if (paths.length) { setFormPath(paths.join('\n')); if (!formName) setFormName(paths[0].split(/[\\/]/).pop() || 'Новая съёмка'); }
  };
  const showModal = (name: string) => { setFormPath(name === 'export' ? status?.export_directory || '' : ''); setFormName(''); setModal(name); if (name === 'settings') void api<typeof roots>('/roots').then(setRoots); };
  const patch = <K extends keyof Recipe,>(section: K, key: string, value: unknown) => setDraft(d => d ? { ...d, [section]: { ...(d[section] as object), [key]: value } } : d);
  const save = async (recipe = draft, source = 'manual') => {
    if (!recipe) return;
    await act(() => persistDraft(recipe, source), 'Рецепт сохранён. Обновляю превью.');
  };
  const acceptCrop = (crop: Crop) => { if (draft) { const r = { ...draft, crop, lock_crop: true }; setDraft(r); void save(r, 'crop_accept'); } };
  const point = (event: React.PointerEvent) => {
    const bounds = imageRef.current?.getBoundingClientRect();
    if (!bounds) return { x: 0, y: 0 };
    return { x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) };
  };
  const pointerDown = (event: React.PointerEvent) => {
    if (!draft || !renderReady || cameraView || (compare && !comparisonReady)) return;
    const p = point(event);
    if (brush !== 'none') { setBrushPoints([[p.x, p.y]]); event.currentTarget.setPointerCapture(event.pointerId); }
    else if (tab === 'crop') {
      event.preventDefault();
      const handle=(event.target as HTMLElement).closest<HTMLElement>('[data-crop-handle]')?.dataset.cropHandle as CropHandle | undefined;
      setCropDrag({start:p,crop:{...draft.crop},handle:handle || 'new'});
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  };
  const pointerMove = (event: React.PointerEvent) => {
    const p = point(event);
    if (brushPoints.length && brush === 'protect') setBrushPoints(v => [...v, [p.x, p.y]]);
    if (cropDrag && draft) {
      const crop = dragCrop(cropDrag,p);
      setDraft({ ...draft, crop, lock_crop: true });
    }
  };
  const pointerUp = () => {
    if (draft && brushPoints.length) {
      if (brush === 'protect') patch('retouch', 'protected', [...draft.retouch.protected, { points: brushPoints, radius: brushRadius }]);
      else if (brush === 'heal') patch('retouch', 'healing', [...draft.retouch.healing, { x: brushPoints[0][0], y: brushPoints[0][1], radius: brushRadius / 2 }]);
    }
    setBrushPoints([]); setCropDrag(null);
  };

  const activeJobs = jobs.filter(j => ['queued', 'running', 'paused'].includes(j.state));
  const runningJob = activeJobs.find(j => j.state === 'running') || activeJobs[0];
  const currentShoot = shoots.find(s => s.id === shootId);
  const openRemoved = () => { void leaveEditor(() => {setShootId('');setFilter('removed');setSelected(new Set());}); };
  const closeGuide = () => { void act(async () => {await api('/settings',{method:'PATCH',body:JSON.stringify({onboarding_completed:true})});setShowGuide(false);}); };
  const sideBySide = compare && detail ? photos.find(p => p.id === comparisonIds.find(id => id !== detail.id)) : null;
  const beginComparison = () => {
    const pair = comparisonPair([...selected], photos, detail);
    if (!pair) return notify('Выделите два кадра для сравнения');
    setComparisonIds(pair); setCompare(true); void openPhoto(pair[0]);
  };
  const compareBase = before || tab === 'crop' || brush !== 'none' || showMask;
  const compareVariant = fullResolution ? (compareBase ? 'fullbase' : 'full') : (compareBase ? 'base' : 'render');
  const peerKey = sideBySide ? `${sideBySide.id}:${sideBySide.revision}:${compareVariant}` : '';
  const comparisonReady = !!sideBySide && (fullResolution ? fullReady : renderReady) && peerReady === peerKey;
  useEffect(() => {
    if (!sideBySide) return;
    const img = new Image();
    img.onload = () => setPeerReady(peerKey);
    img.onerror = () => {
      if (!jobs.some(j => j.kind === 'render' && j.full === (fullResolution) && j.photo_ids.includes(sideBySide.id) && ['queued','running'].includes(j.state)))
        void post(`/photos/${sideBySide.id}/render?full=${fullResolution}`).catch(e => notify(String(e)));
    };
    img.src = imageUrl(sideBySide.id, compareVariant, sideBySide.revision);
    return () => { img.onload = null; img.onerror = null; };
  }, [peerKey, latestUpdate]);
  useEffect(() => {
    if (!detail || !draft || JSON.stringify(draft) === JSON.stringify(detail.recipe)) return;
    const timer = setTimeout(() => {
      void api(`/photos/${detail.id}/draft`, {method:'PUT',body:JSON.stringify({recipe:draft,expected_revision:detail.revision})}).catch(error => { if (editorRef.current?.detail.id === detail.id && editorRef.current.detail.revision === detail.revision) { setSaveState('error'); notify(`Черновик не сохранён: ${String(error)}`); } });
    }, 300);
    return () => clearTimeout(timer);
  }, [draft, detail?.id, detail?.revision]);
  useEffect(() => {
    const saveOnClose = () => {
      const current = editorRef.current?.detail, recipe = editorRef.current?.draft;
      if (current && recipe && JSON.stringify(recipe) !== JSON.stringify(current.recipe)) void api(`/photos/${current.id}/draft`, {method:'PUT',keepalive:true,body:JSON.stringify({recipe,expected_revision:current.revision})}).catch(() => {});
    };
    window.addEventListener('pagehide', saveOnClose);
    return () => window.removeEventListener('pagehide', saveOnClose);
  }, []);
  useEffect(() => {
    window.openPhotoFlush = async () => {
      setBusy(true);
      try { await persistDraft(); return true; }
      catch (error) { setToast(`Окно оставлено открытым: правка не сохранена. ${String(error)}`); return false; }
      finally { setBusy(false); }
    };
    return () => { delete window.openPhotoFlush; };
  }, [persistDraft]);
  const peerFull = comparisonReady && fullResolution;
  const canvasRatio = detail ? (detail.analysis?.canvas_width || detail.width) / (detail.analysis?.canvas_height || detail.height) : 1;
  const showOriginal = before || !renderReady || tab === 'crop' || brush !== 'none' || showMask;
  const displayFull = fullResolution && (sideBySide ? comparisonReady : fullReady || cameraView);
  const currentVariant = sideBySide ? (comparisonReady ? compareVariant : 'original') : cameraView ? (fullResolution ? 'camera-full' : 'camera') : displayFull ? (showOriginal ? 'fullbase' : 'full') : renderReady ? (showOriginal ? 'base' : 'render') : 'original';
  const renderJob = detail && jobs.find(j => j.kind === 'render' && j.photo_ids?.includes(detail.id) && j.full === (fullResolution));
  const renderError = renderJob && ['failed','completed_with_errors'].includes(renderJob.state);
  const currentProfile = profiles.find(p => p.id === profileId);
  const dirty = draft && detail && JSON.stringify(draft) !== JSON.stringify(detail.recipe);

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><Aperture size={28} strokeWidth={1.5} /><span>open<span>photo</span><small>ЛОКАЛЬНАЯ ФОТОЛАБОРАТОРИЯ</small></span></div>
      <button className="import-button" onClick={() => showModal('import')}><Plus size={17} /> Новая съёмка</button>
      <div className="nav-caption">БИБЛИОТЕКА</div>
      <button className={`nav-item ${!shootId && filter === 'all' ? 'selected' : ''}`} onClick={() => { void leaveEditor(() => { setShootId(''); setFilter('all'); setSelected(new Set()); }); }}><Grid2X2 size={17} /> Все фотографии <span>{shoots.reduce((n, s) => n + s.count, 0)}</span></button>
      <button className={`nav-item ${filter === 'keep' ? 'selected' : ''}`} onClick={() => { void leaveEditor(() => {setFilter('keep'); setSelected(new Set());}); }}><Heart size={17} /> Мой отбор</button>
      <button className={`nav-item ${filter === 'review' ? 'selected' : ''}`} onClick={() => { void leaveEditor(() => {setFilter('review'); setSelected(new Set());}); }}><CircleHelp size={17} /> На проверку</button>
      <button className={`nav-item ${filter === 'removed' ? 'selected' : ''}`} onClick={openRemoved}><Trash2 size={17}/> Удалённые</button>
      <div className="nav-caption caption-row">СЪЁМКИ <Folder size={13} /></div>
      <div className="shoot-list">{shoots.map(s => <div key={s.id} className={`shoot-row ${shootId === s.id ? 'selected' : ''}`}><button className="nav-item shoot" title={s.count ? s.name : `${s.name}: нет активных кадров${s.removed_count ? ', проверьте «Удалённые»' : ''}`} onClick={() => { void leaveEditor(() => { setShootId(s.id); setFilter('all'); setSelected(new Set()); }); }}><span className="shoot-dot"/><b>{s.name}</b><span>{s.count}</span></button><IconButton title={`Удалить съёмку «${s.name}»`} disabled={busy} onClick={()=>{setShootToRemove(s);setModal('remove-shoot');}}><Trash2 size={14}/></IconButton></div>)}{!shoots.length && <p className="muted-small">Съёмки появятся здесь<br/>после первого импорта</p>}</div>
      <div className="sidebar-bottom"><button className="nav-item" onClick={() => showModal('projects')}><Folder size={17}/> Проекты и библиотека</button><button className="nav-item" onClick={() => showModal('references')}><Palette size={17} /> Референсы и стили <span>{profiles.length}</span></button><button className="nav-item" onClick={() => showModal('settings')}><Settings2 size={17} /> Настройки</button><div className="local-badge"><span className="live-dot" /> На вашем компьютере <ShieldCheck size={14} /></div></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumb">Библиотека <span>/</span> {detail ? detail.name : currentShoot?.name || 'Все фотографии'}</div><div className="top-actions"><span className="offline"><span className="live-dot"/> OFFLINE FIRST</span><IconButton title="Горячие клавиши" onClick={() => showModal('help')}><CircleHelp size={17}/></IconButton><button className="button secondary" onClick={() => showModal('export')}><ArrowDownToLine size={16}/> Экспорт</button></div></header>

      {status && (showGuide || status.settings.onboarding_completed !== true) && <GettingStarted close={closeGuide}/>}
      {!detail ? <>
        <div className="page-heading"><div><div className="eyebrow">СЪЁМКА</div><h1>{filter === 'removed' ? 'Удалённые из каталога' : currentShoot?.name || 'Все фотографии'}<span className="count-pill">{photos.length}</span></h1><p>{filter === 'removed' ? 'Оригиналы на диске сохранены. Кадры можно вернуть в каталог.' : 'Выберите автоматическую обработку или откройте кадр для ручной правки.'}</p></div></div>
        {filter !== 'removed' && <WorkflowLauncher availableIds={photos.map(p=>p.id)} ids={selected.size ? [...selected] : filter !== 'all' ? photos.map(p=>p.id) : []} shootId={shootId} count={selected.size || photos.length} profiles={profiles} status={status} jobs={jobs} onModal={setWorkflowModal} manual={()=>{const first=photos.find(p=>selected.has(p.id)) || photos[0];if(first)void openPhoto(first.id);}} progress={()=>{setModal('jobs');void api<Job[]>('/jobs').then(setJobs).catch(e=>notify(String(e)));}} error={notify}/>}
        <div className="library-toolbar"><div className="filter-tabs">{[['all', 'Все кадры'], ['suggested', 'Предложенный отбор'], ['keep', 'Выбрано'], ['review', 'На проверку'], ['reject', 'Отклонено'], ['removed', 'Удалённые']].map(([id, label]) => <button key={id} className={filter === id ? 'active' : ''} onClick={() => { setFilter(id); setSelected(new Set()); }}>{label}</button>)}</div><button className="text-button" disabled={!photos.length} onClick={selectAll}>Выделить все</button><div className="sort-control"><SlidersHorizontal size={14} /><select aria-label="Сортировка" value={sort} onChange={e => setSort(e.target.value)}><option value="time">По времени</option><option value="score">По оценке</option><option value="taste">По моему вкусу</option><option value="rating">По рейтингу</option></select></div></div>
        {!!selected.size && <div className="selection-toolbar"><span>Выбрано {selected.size}</span>
          {filter === 'removed' ? <button disabled={busy} onClick={() => void restoreRemoved()}><RotateCcw size={15}/> Вернуть в каталог</button> : <>
            <button disabled={busy} onClick={() => void decision('keep')}><Check size={15}/> В отбор</button><button disabled={busy} onClick={() => void decision('reject')}><X size={15}/> Отклонить</button>
            <button disabled={busy} onClick={() => void act(() => post('/groups', { photo_ids: [...selected], action: 'merge' }), 'Кадры объединены в серию')}><Layers size={15}/> Объединить</button>
            <button disabled={busy} onClick={() => void act(() => post('/groups', {photo_ids: [...selected], action: 'split'}), 'Серия разделена')}>Разделить</button><button onClick={beginComparison}><Columns2 size={15}/> Сравнить</button>
            <button disabled={busy} onClick={requestRemoval}><Trash2 size={15}/> Удалить из каталога</button>
          </>}
          <button className="push-right" onClick={() => setSelected(new Set())}>Снять выделение</button></div>}

        <div className="gallery-scroll" ref={gridRef}>
          {!photos.length ? <div className="empty-state"><div className="empty-art"><div className="frame frame-back"/><div className="frame frame-front"><Aperture size={44} strokeWidth={1}/><span>Всё начинается с кадра</span></div><div className="art-cross one">+</div><div className="art-cross two">+</div></div><div className="eyebrow">ПРОСТРАНСТВО ДЛЯ ВАШИХ СНИМКОВ</div><h2>{filter === 'removed' ? 'Удалённых кадров нет' : currentShoot ? 'В съёмке нет активных кадров' : filter === 'all' ? 'Добавьте фотографии' : 'Здесь пока нет кадров'}</h2><p>{filter === 'removed' ? 'Удалённые карточки появятся здесь. Исходные файлы остаются на диске.' : filter === 'all' ? 'Если вы уже удалили эти кадры, откройте «Удалённые» или импортируйте их снова — правки и рейтинги восстановятся.' : 'Измените фильтр или начните отбор фотографий.'}</p><button className="button primary large" onClick={() => filter === 'all' ? showModal('import') : setFilter('all')}><FolderPlus size={18}/>{filter === 'all' ? 'Добавить фотографии' : 'Показать все кадры'}</button>{filter !== 'removed' && <button className="text-button" onClick={openRemoved}>Открыть удалённые</button>}<div className="empty-formats">SONY ARW <span>·</span> JPEG <span>·</span> TIFF <span className="divider"/> Оригиналы всегда сохраняются</div></div>
          : <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>{virtualizer.getVirtualItems().map(row => <div key={row.key} className="photo-row" style={{ transform: `translateY(${row.start}px)`, height: rowHeight, gridTemplateColumns: `repeat(${columns}, 1fr)` }}>{photos.slice(row.index * columns, (row.index + 1) * columns).map(photo => <article key={photo.id} className={`photo-card ${selected.has(photo.id) ? 'is-selected' : ''} ${photo.status === 'reject' ? 'rejected' : ''}`} onClick={e => { if (e.ctrlKey || e.metaKey || e.shiftKey) setSelected(v => { const next = new Set(v); next.has(photo.id) ? next.delete(photo.id) : next.add(photo.id); return next; }); else void openPhoto(photo.id); }}><div className="photo-image"><img loading="lazy" src={imageUrl(photo.id)} alt={photo.name} onError={e => { e.currentTarget.style.opacity = '0'; }}/><button className="select-photo" aria-label={`Выделить ${photo.name}`} onClick={e => { e.stopPropagation(); setSelected(v => { const next = new Set(v); next.has(photo.id) ? next.delete(photo.id) : next.add(photo.id); return next; }); }}>{selected.has(photo.id) && <Check size={13}/>}</button><span className="format-badge">{photo.raw ? photo.paired ? 'RAW + JPG' : 'RAW' : 'JPG'}</span>{photo.status === 'keep' ? <span className="pick-badge"><Check size={12}/> Выбрано</span> : photo.suggested && photo.score !== null ? <span className="pick-badge suggested"><Sparkles size={12}/> Выбор</span> : null}{photo.error && <span className="image-error">Файл требует проверки</span>}</div><div className="photo-info"><span className="photo-name">{photo.name}</span><span className="photo-score">{photo.score === null ? '—' : (photo.score * 10).toFixed(1)}</span></div><div className="photo-sub"><span>{photo.width} × {photo.height}</span><span className="stars">{photo.rating > 0 ? '★'.repeat(photo.rating) : '· · · · ·'}</span>{photo.review && photo.score !== null && <span className="review-dot" title="На проверку"/>}</div></article>)}</div>)}</div>}
        </div>
      </> : draft && <div className="editor">
        <section className="editor-main"><div className="editor-toolbar"><button className="text-button" onClick={() => { void leaveEditor(); setCompare(false); }}><ArrowLeft size={16}/> К съёмке</button><div className="editor-nav"><IconButton title="Предыдущий кадр" onClick={() => navigate(-1)}><ArrowLeft size={16}/></IconButton><span>{photos.findIndex(p => p.id === detail.id) + 1} / {photos.length}</span><IconButton title="Следующий кадр" onClick={() => navigate(1)}><ArrowRight size={16}/></IconButton></div><div className="editor-view-actions">{filter === 'removed' ? <button className="button small" disabled={busy} onClick={() => void restoreRemoved()}>Вернуть в каталог</button> : <IconButton title="Удалить из каталога" onClick={requestRemoval}><Trash2 size={16}/></IconButton>}{detail.paired && <button className={`button small ${cameraView ? 'active' : ''}`} disabled={compare} onClick={() => setCameraView(v => !v)}>{cameraView ? 'Вернуться к RAW' : 'JPEG камеры'}</button>}<IconButton title="Сравнить кадры" active={compare} onClick={() => compare ? setCompare(false) : beginComparison()}><Columns2 size={17}/></IconButton><button className={`button small ${before ? 'active' : ''}`} onClick={() => setBefore(v => !v)}>До / После</button><IconButton title="Уменьшить (−)" onClick={()=>viewport.scale(1/1.25)}><Minus size={16}/></IconButton><button className="button small" title="Вписать в окно (Ctrl+0)" onClick={viewport.fit}>По окну</button><IconButton title="Увеличить (+)" onClick={()=>viewport.scale(1.25)}><Plus size={16}/></IconButton><IconButton title="Масштаб 1:1 (Ctrl+1)" active={fullResolution} onClick={()=>viewport.native(detail.width*(showOriginal ? 1 : detail.recipe.crop.w),fitWidth)}><Maximize2 size={17}/></IconButton><IconButton title="Перетаскивание (H или удерживайте пробел)" active={viewport.hand || viewport.spaceHeld} onClick={()=>viewport.setHand(v=>!v)}><Hand size={17}/></IconButton></div></div>
          <div className={`image-stage ${sideBySide ? 'comparison' : ''}`}>
            <div ref={mainViewportRef} {...viewport.props} onScroll={e => syncScroll(e.currentTarget, peerViewportRef.current)} className={`image-viewport ${zoom > 1 ? "native-view" : ""} ${viewport.panning ? "panning" : viewport.hand || viewport.spaceHeld || (tab !== "crop" && brush === "none") ? "can-pan" : ""}`}><div className={`image-wrapper ${tab === 'crop' || brush !== 'none' ? 'interactive-image' : ''}`} style={fitWidth ? {width:fitWidth*zoom,maxWidth:"none",maxHeight:"none"} : undefined} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
              <img ref={imageRef} className="editor-image" draggable={false} src={imageUrl(detail.id, currentVariant, detail.revision)} onLoad={e => setImageAspect(e.currentTarget.naturalWidth/e.currentTarget.naturalHeight)} alt={detail.name}/>
              {showMask && renderReady && (!compare || comparisonReady) && !cameraView && <img className="mask-overlay" src={imageUrl(detail.id, 'mask', detail.revision)} alt="Изменённые области"/>}{tab === 'crop' && renderReady && (!compare || comparisonReady) && !cameraView && <CropOverlay crop={draft.crop}/>}
              {brush !== 'none' && renderReady && (!compare || comparisonReady) && !cameraView && <svg className="brush-overlay" viewBox={`0 0 ${canvasRatio*1000} 1000`} preserveAspectRatio="none">{draft.retouch.protected.map((s, i) => <polyline key={i} points={s.points.map(p => `${p[0]*canvasRatio*1000},${p[1]*1000}`).join(' ')} fill="none" stroke="#c3d9a980" strokeWidth={s.radius*Math.min(1,canvasRatio)*2000} strokeLinecap="round" strokeLinejoin="round"/>)}{draft.retouch.healing.map((s, i) => <circle key={i} cx={s.x*canvasRatio*1000} cy={s.y*1000} r={s.radius*Math.min(1,canvasRatio)*1000} fill="#efb37d70" stroke="#efb37d"/>)}</svg>}
            </div></div>
            {sideBySide && <div ref={peerViewportRef} onScroll={e => syncScroll(e.currentTarget, mainViewportRef.current)} className={`compare-image ${peerFull ? "native-peer" : ""}`}><img onLoad={e => setPeerWidth(e.currentTarget.naturalWidth)} style={peerFull ? {width:fitWidth*zoom*peerWidth/Math.max(1,detail.width*(showOriginal ? 1 : detail.recipe.crop.w)),maxWidth:"none",maxHeight:"none"} : undefined} src={imageUrl(sideBySide.id, comparisonReady ? compareVariant : "original", sideBySide.revision)} alt={sideBySide.name}/><div><span>{sideBySide.name}</span><button className="button primary small" onClick={() => void act(() => post('/decisions', { photo_ids: [sideBySide.id], other_id: detail.id, action: 'compare' }), 'Предпочтение сохранено')}>Этот лучше</button></div></div>}
            <div className="view-label">{sideBySide ? (comparisonReady ? (compareBase ? 'Оба кадра: базовая проявка' : 'Оба кадра: обработка') : 'Оба кадра: исходные превью · готовится проявка') : cameraView ? 'JPEG камеры' : currentVariant === 'original' ? 'Встроенное превью' : showOriginal ? 'Проявка до коррекции' : 'Обработка'} {zoom !== 1 && `· масштаб ${Math.round(zoom*100)}% от вписывания`} {dirty && <span>· Есть несохранённые правки</span>}</div>
            {!cameraView && (!renderReady || (fullResolution && !fullReady)) && <button className="render-status" onClick={() => setModal("jobs")}>{renderError ? <CircleHelp size={13}/> : <Loader2 size={13} className="spin"/>}{renderError ? "Ошибка обработки · подробнее" : fullResolution ? "Готовится полное разрешение" : "Проявленное превью готовится"}</button>}
          </div>
          <div className="viewport-hint">Ctrl + колесо / + −: масштаб · Ctrl+0: по окну · Ctrl+1: 1:1 · пробел + мышь: сдвиг · B: до / после</div>
          <div className="editor-bottom"><div><strong>{detail.name}</strong><span>{detail.width} × {detail.height} · {String(detail.metadata.Model || (detail.raw ? 'RAW' : 'JPEG'))}{detail.metadata.ISO ? ` · ISO ${detail.metadata.ISO}` : ''}</span></div>{sideBySide && <button className="button small" onClick={() => void act(() => post("/decisions", {photo_ids:[detail.id],other_id:sideBySide.id,action:"compare"}), "Предпочтение сохранено")}>Этот лучше</button>}<div className="rating-buttons">{[1,2,3,4,5].map(v => <button key={v} aria-label={`${v} звёзд`} onClick={() => void decision('rating', v)}><Star size={18} fill={detail.rating >= v ? 'currentColor' : 'none'}/></button>)}</div><button className={`button ${detail.status === 'reject' ? 'danger' : ''}`} onClick={() => void decision('reject')}><X size={16}/> Отклонить</button><button className="button primary" onClick={() => void decision('keep')}><Check size={16}/> В отбор</button></div>
          <div className="filmstrip">{photos.slice(Math.max(0, photos.findIndex(p => p.id === detail.id)-6), photos.findIndex(p => p.id === detail.id)+8).map(p => <button className={detail.id === p.id ? 'active' : ''} key={p.id} onClick={() => { setCompare(false); void openPhoto(p.id); }}><img src={imageUrl(p.id)} alt={p.name}/>{p.status === 'keep' && <Check size={12}/>}</button>)}</div>
        </section>

        <aside className="adjustments"><div className="adjustment-title"><h2>Работа с кадром</h2><span role="status">{saveState === 'saving' ? 'Сохраняю…' : saveState === 'error' ? 'Ошибка сохранения' : dirty ? 'Есть правки' : `v${detail.revision} · сохранено`}</span></div><div className="tool-tabs">{[['color', Palette, 'Цвет'], ['crop', CropIcon, 'Кадр'], ['retouch', WandSparkles, 'Ретушь'], ['analysis', Sparkles, 'Анализ']].map(([id, Icon, label]) => { const C = Icon as typeof Palette; return <button key={id as string} className={tab === id ? 'active' : ''} onClick={() => { setTab(id as string); setBrush('none'); }}><C size={17}/>{label as string}</button>; })}</div>
          <div className="adjustment-scroll">
            {tab === 'color' && <><Histogram src={imageUrl(detail.id, currentVariant, detail.revision)}/><section className="control-section"><h3>Проявка <span>{detail.raw ? 'RAW' : 'JPEG'}</span></h3><Slider label="Экспозиция" resetValue={0} value={draft.develop.exposure} min={-5} max={5} step={0.05} onChange={v => patch('develop', 'exposure', v)} format={v => `${v > 0 ? '+' : ''}${v.toFixed(2)} EV`}/><label className="check-label"><input type="checkbox" checked={draft.develop.temperature !== null} onChange={e => patch('develop', 'temperature', e.target.checked ? 5500 : null)}/> Свой баланс белого</label>{draft.develop.temperature !== null && <Slider label="Температура" resetValue={5500} value={draft.develop.temperature} min={2000} max={12000} step={50} onChange={v => patch('develop', 'temperature', v)} format={v => `${v} K`}/>}{detail.raw && <><Slider label="Оттенок баланса белого" resetValue={1} value={draft.develop.tint} min={0.5} max={2} onChange={v=>patch('develop','tint',v)}/><Slider label="Шумоподавление" resetValue={0} value={draft.develop.denoise} min={0} max={1} onChange={v => patch('develop', 'denoise', v)}/><label className="check-label"><input type="checkbox" checked={draft.develop.recover_highlights} onChange={e => patch('develop', 'recover_highlights', e.target.checked)}/> Восстановление светов</label></>}</section>
              <section className="control-section"><h3>Характер цвета</h3><Slider label="Контраст" resetValue={0} value={draft.color.contrast} min={-0.5} max={0.5} onChange={v => patch('color', 'contrast', v)}/><Slider label="Насыщенность" resetValue={1} value={draft.color.saturation} min={0} max={2} onChange={v => patch('color', 'saturation', v)}/><Slider label="Теплота" resetValue={0} value={draft.color.warmth} min={-0.3} max={0.3} onChange={v => patch('color', 'warmth', v)}/><Slider label="Оттенок" resetValue={0} value={draft.color.tint} min={-0.2} max={0.2} onChange={v => patch('color', 'tint', v)}/><Slider label="Тени" resetValue={0} value={draft.color.shadows} min={-0.3} max={0.3} onChange={v => patch('color', 'shadows', v)}/><Slider label="Света" resetValue={0} value={draft.color.highlights} min={-0.3} max={0.3} onChange={v => patch('color', 'highlights', v)}/><Slider label="Чёрная точка" resetValue={0} value={draft.color.black_point} min={-0.1} max={0.1} onChange={v=>patch('color','black_point',v)}/><Slider label="Сила стиля" resetValue={1} value={draft.color.strength} min={0} max={1} onChange={v => patch('color', 'strength', v)}/><label className="check-label"><input type="checkbox" checked={draft.color.protect_skin} onChange={e => patch('color', 'protect_skin', e.target.checked)}/> Беречь оттенок кожи</label></section>
              <section className="control-section"><h3>По референсу</h3><select className="field" value={profileId} onChange={e => setProfileId(e.target.value)}><option value="">Выберите направление</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>{currentProfile && <div className="reference-strip">{currentProfile.references.slice(0,4).map(r => <img key={r.id} src={`/api/references/${r.id}`} alt={r.name}/>)}</div>}<button className="button full" disabled={!profileId || busy} onClick={() => void act(async () => { await persistDraft(); return post('/style/propose', { photo_ids: [detail.id], profile_id: profileId }); }, 'Подбираю варианты цвета')}><Sparkles size={15}/> Подобрать цвет</button>{detail.analysis?.style_proposal?.input_revision === detail.revision && <div className="style-variants">{detail.analysis.style_proposal.variants?.map(v => <button key={v.name} className="button small" onClick={() => { const r = {...draft,color:v.color}; void save(r,'style_accept'); }}><img src={imageUrl(detail.id,`style-${v.name}`,detail.revision)} alt={`Вариант ${v.name}`}/><span>{{soft:'Мягко',medium:'Средне',strong:'Выраженно'}[v.name]}</span></button>)}</div>}</section></>}
            {tab === 'crop' && <><section className="control-section"><h3>Композиция и границы</h3>{draft.version === 1 && <button className="button full" onClick={() => void act(async () => { const key = editorRef.current?.key; await persistDraft(); const proposal = await post<{recipe:Recipe;note:string}>(`/photos/${detail.id}/geometry-preview`); if (editorRef.current?.key !== key) return; setGeometryReady(false); setGeometryProposal(proposal); setModal('geometry'); })}>Посмотреть новую геометрию</button>}<p className="control-note">Потяните край или угол рамки, чтобы изменить размер; внутри рамки — переместить. Ctrl + колесо — масштаб, «По окну» — вернуть общий вид. Оригинал сохраняется целиком.</p><div className="ratio-grid">{[['Оригинал', canvasRatio], ['3:2', 3/2], ['4:5', 4/5], ['1:1', 1], ['16:9', 16/9], ['9:16', 9/16]].map(([label, ratio]) => <button key={label} onClick={() => { const factor = (ratio as number) / (canvasRatio); const w = Math.min(1, factor), h = Math.min(1, 1/factor); setDraft({ ...draft, crop: { x: (1-w)/2, y: (1-h)/2, w, h }, lock_crop: true }); }}>{label}</button>)}</div>{detail.analysis?.horizon && <button className="button full" title={detail.analysis.horizon.reason} onClick={() => setDraft({...draft, rotation: detail.analysis!.horizon!.degrees})}>Линия горизонта: {detail.analysis.horizon.degrees}° · проверить</button>}<Slider label="Поворот" value={draft.rotation} min={-15} max={15} step={0.1} onChange={v => setDraft({ ...draft, rotation: v })} format={v => `${v.toFixed(1)}°`}/><button className="button full" onClick={() => setDraft({ ...draft, crop: { x: 0, y: 0, w: 1, h: 1 }, rotation: 0, lock_crop: false })}><RotateCcw size={15}/> Восстановить границы</button></section><section className="control-section"><h3>Предложения <span>{detail.analysis?.crops?.length || 0}</span></h3>{detail.analysis?.crops?.length ? detail.analysis.crops.map((c, i) => <button key={i} className="crop-option" onClick={() => acceptCrop(c.crop)}><CropIcon size={19}/><span><b>Вариант {i+1}</b><small>{Math.round(c.retained*100)}% площади · {c.safe ? 'Сдержанная обрезка' : 'Нужна проверка'}</small></span><Check size={15}/></button>) : <p className="control-note">После анализа здесь появятся варианты, если главный объект определён уверенно.</p>}<div className="info-box"><ShieldCheck size={16}/><span>{status?.auto_crop_active ? 'Включена консервативная автоматическая обрезка' : 'До проверки качества обрезка применяется только после выбора'}</span></div></section></>}
            {tab === 'retouch' && <><section className="control-section"><h3>Естественная ретушь</h3><label className="check-label"><input type="checkbox" checked={showMask} onChange={e => setShowMask(e.target.checked)}/> Показать изменённые области</label><p className="control-note">Локальные изменения сохраняют черты и фактуру. Для автоматической маски нужны лицевые ориентиры.</p><h3>Лицо</h3><Slider label="Ровнее свет" resetValue={0} value={draft.retouch.strength} min={0} max={0.6} onChange={v => patch('retouch', 'strength', v)}/><Slider label="Ровнее тон кожи" resetValue={0} value={draft.retouch.color_evenness} min={0} max={0.6} onChange={v => patch('retouch', 'color_evenness', v)}/>{draft.version === 2 && <><h3>Кожа тела</h3>{draft.version >= 2 && <Slider label="Ровнее свет тела" resetValue={0} value={draft.retouch.body_strength} min={0} max={0.6} onChange={v => patch('retouch','body_strength',v)}/>}{draft.version >= 2 && <Slider label="Ровнее тон тела" resetValue={0} value={draft.retouch.body_color_evenness} min={0} max={0.6} onChange={v => patch('retouch','body_color_evenness',v)}/>}</>}{!!detail.analysis?.spot_candidates?.length && <details><summary>Точки для проверки ({detail.analysis.spot_candidates.length})</summary><p className="control-note">Здесь могут быть родинки, веснушки или макияж. Применяйте только после просмотра 1:1.</p>{detail.analysis.spot_candidates.map((p,i) => <button className="button small" key={i} onClick={() => { patch('retouch','healing',[...draft.retouch.healing,{x:p.x,y:p.y,radius:p.radius}]); setBrush('heal'); }}>Отметить точку {i+1}</button>)}</details>}<div className="brush-buttons"><button className={`button ${brush === 'protect' ? 'active' : ''}`} onClick={() => setBrush(brush === 'protect' ? 'none' : 'protect')}><ShieldCheck size={15}/> Защитить</button><button className={`button ${brush === 'heal' ? 'active' : ''}`} onClick={() => setBrush(brush === 'heal' ? 'none' : 'heal')}><WandSparkles size={15}/> Убрать пятно</button></div>{brush !== 'none' && <Slider label="Размер кисти" value={brushRadius} min={0.006} max={0.1} step={0.002} onChange={setBrushRadius}/>}<p className="control-note">Защищённых штрихов: {draft.retouch.protected.length}<br/>Отмеченных пятен: {draft.retouch.healing.length}</p><button className="button full" onClick={() => { patch('retouch', 'protected', []); patch('retouch', 'healing', []); }}><RotateCcw size={15}/> Удалить локальные отметки</button></section>{detail.analysis?.faces?.map((face, i) => <section className="control-section" key={i}><h3>Лицо {i+1}</h3><label className="check-label"><input type="checkbox" checked={!draft.retouch.disabled_faces.includes(i)} onChange={e => patch('retouch', 'disabled_faces', e.target.checked ? draft.retouch.disabled_faces.filter(n => n !== i) : [...draft.retouch.disabled_faces, i])}/> Применять ретушь</label><small>Резкость: {face.sharpness?.toFixed(2) || '—'}</small></section>)}</>}
            {tab === 'analysis' && <AnalysisPanel analysis={detail.analysis} onAnalyze={() => void act(() => post('/analyze', { photo_ids: [detail.id], profile_id: profileId || null }), 'Анализ в очереди')}/>}
            <section className="control-section history"><h3>История изменений</h3><button className="button full" onClick={() => showModal("recipe")}>Восстановить из файла рецепта</button><button className="button full" title="Явно разрешить пересчёт новой версией движка, сохранив старый рецепт в истории" onClick={() => void act(() => replaceRecipe(current => post(`/photos/${current.id}/migrate-runtime`)))}>Новая версия движка</button><details open={detail.history.length <= 6}><summary>Все версии ({detail.history.length})</summary>{detail.history.map(r => <button key={r.revision} onClick={() => void act(() => replaceRecipe(current => post(`/photos/${current.id}/restore/${r.revision}`)))}><RotateCcw size={13}/><span>Версия {r.revision}</span><small>{historyNames[r.source] || 'Обработка'}</small></button>)}</details></section>
          </div>
          <div className="adjustment-footer"><p className="control-note">Превью обновляется после «Применить» · Ctrl+Enter</p><button className="button primary full" disabled={!dirty || busy} onClick={() => void save()}><Check size={16}/> Применить изменения</button><button className="button full" onClick={() => showModal('batch')}><Layers size={15}/> Применить к серии</button></div>
        </aside>
      </div>}

      <footer className="statusbar"><span><ShieldCheck size={13}/> Оригиналы не изменяются</span><button onClick={() => showModal('jobs')}>{runningJob ? <><Loader2 size={13} className={runningJob.state === 'running' ? 'spin' : ''}/>{jobNames[runningJob.kind]} · {runningJob.completed}/{runningJob.total || '…'}<span className="tiny-progress"><i style={{width: `${100*runningJob.completed/Math.max(1,runningJob.total)}%`}}/></span></> : <><span className="live-dot"/> Готово к работе</>}<ChevronDown size={12}/></button><span>OpenPhoto {status?.version || '0.1.0'}</span></footer>
    </main>

    {toast && <div className="toast" role="status"><span>{toast}</span><IconButton title="Скрыть уведомление" onClick={() => setToast('')}><X size={15}/></IconButton></div>}

    {modal === 'projects' && <ProjectsPanel shoots={shoots} profiles={profiles} prepare={persistDraft} refresh={refresh} notify={notify} close={()=>setModal(null)}/>}
    {modal === 'remove-shoot' && shootToRemove && <Modal title="Удалить съёмку" close={()=>!busy && setModal(null)}><p className="modal-description">Съёмка «{shootToRemove.name}» исчезнет из списка. Кадров будет перемещено в «Удалённые»: {shootToRemove.count}. Исходные файлы, правки и рейтинги сохранятся. Восстановление кадра или повторный импорт вернёт съёмку.</p><div className="modal-actions"><button className="button" disabled={busy} onClick={()=>setModal(null)}>Отмена</button><button className="button primary" disabled={busy} onClick={()=>void act(async()=>{await persistDraft();await api(`/shoots/${shootToRemove.id}`,{method:'DELETE'});++navigationEpoch.current;clear();setCompare(false);setShootId('');setFilter('all');setSelected(new Set());setModal(null);},'Съёмка убрана. Кадры доступны в «Удалённых».')}>Удалить съёмку</button></div></Modal>}
    {modal === 'remove' && <Modal title="Удалить из каталога" close={() => !busy && setModal(null)}><p className="modal-description">Убрать кадров: {removalIds.length}. ARW, JPEG и другие оригиналы останутся на диске. Рецепты и рейтинги сохранятся; кадры можно вернуть из раздела «Удалённые».</p><div className="modal-actions"><button className="button" disabled={busy} onClick={() => setModal(null)}>Отмена</button><button className="button primary" disabled={busy} onClick={() => void act(async () => { await persistDraft(); await post('/decisions', {photo_ids:removalIds,action:'remove'}); ++navigationEpoch.current; clear(); setCompare(false); setSelected(new Set()); setModal(null); }, 'Кадры в «Удалённых». Можно восстановить здесь или повторным импортом.')}><Trash2 size={16}/> Удалить из каталога</button></div></Modal>}
    {modal === 'import'  && <Modal title="Добавить съёмку" close={() => setModal(null)}><p className="modal-description">Выберите папку целиком или отдельные ARW/JPEG. В окне выбора папки Windows показывает только подпапки — сами фотографии там скрыты. Повторный импорт восстановит удалённые карточки вместе с правками. После импорта пара RAW + JPEG отображается одной карточкой. Оригиналы остаются на месте.</p><label className="form-label">Название съёмки<input className="field" value={formName} onChange={e => setFormName(e.target.value)} placeholder="Студия · Сентябрь"/></label><label className="form-label">Папка или пути к файлам<textarea className="field path-field" value={formPath} onChange={e => setFormPath(e.target.value)} placeholder={'C:\\Фото\\Съёмка\nКаждый путь с новой строки'}/></label><div className="modal-actions"><button className="button" onClick={() => void choose()}><Folder size={16}/> Выбрать папку</button><button className="button" onClick={() => void choose(true)}><ImagePlus size={16}/> Выбрать файлы ARW/JPEG</button><button className="button primary" disabled={!formPath.trim() || busy} onClick={() => void act(async () => { await persistDraft(); await post('/import', { paths: formPath.split('\n').filter(Boolean), shoot_name: formName || 'Новая съёмка' }); ++navigationEpoch.current; clear(); setShootId(''); setFilter('all'); setSelected(new Set()); setModal(null); }, 'Импорт запущен')}><ImagePlus size={16}/> Импортировать</button></div></Modal>}
    {modal === 'references' && <Modal title="Референсы и направления" close={() => setModal(null)} wide><p className="modal-description">Каждый профиль — отдельное визуальное направление. Добавьте локально сохранённые изображения в отдельный профиль. Цвета разных направлений не смешиваются автоматически. Подключение досок Pinterest пока недоступно.</p><div className="profiles-grid">{profiles.map(profile => <button key={profile.id} className={`profile-card ${profile.id === profileId ? 'active' : ''}`} onClick={() => setProfileId(profile.id)}><div>{profile.references.slice(0,3).map(r => <img key={r.id} src={`/api/references/${r.id}`} alt={r.name}/>)}</div><strong>{profile.name}</strong><small>{profile.references.length} референсов {profile.id === profileId ? '· Выбран' : ''}</small></button>)}</div>{currentProfile && <details className="reference-roles"><summary>Уточнить роли референсов</summary>{currentProfile.references.map(r => <div key={r.id}><img src={`/api/references/${r.id}`} alt={r.name}/><span>{r.name}</span>{[['color','Цвет'],['composition','Композиция'],['mood','Настроение']].map(([role,label]) => <label className="check-label" key={role}><input type="checkbox" checked={r.roles.includes(role)} disabled={r.roles.length===1 && r.roles.includes(role)} onChange={e => void act(() => api(`/profiles/${currentProfile.id}/references/${r.id}`, {method:'PATCH',body:JSON.stringify({roles:e.target.checked ? [...r.roles,role] : r.roles.filter(v => v!==role)})}))}/>{label}</label>)}</div>)}</details>}<div className="form-row"><label className="form-label">Новое направление<input className="field" value={formName} onChange={e => setFormName(e.target.value)} placeholder="Мягкий студийный свет"/></label><label className="form-label">Папка с референсами<input className="field" value={formPath} onChange={e => setFormPath(e.target.value)} placeholder="C:\Референсы"/></label></div><div className="modal-actions"><button className="button" onClick={() => void choose()}><Folder size={16}/> Выбрать папку</button><button className="button primary" disabled={!formName || !formPath || busy} onClick={() => void act(async () => { await post('/profiles', { name: formName, paths: formPath.split('\n').filter(Boolean) }); setFormName(''); setFormPath(''); }, 'Референсы добавлены в очередь анализа')}><Plus size={16}/> Создать профиль</button></div></Modal>}
    {modal === 'export' && <Modal title="Экспорт готовой серии" close={() => setModal(null)}><p className="modal-description">{selected.size ? `${selected.size} выделенных кадров` : 'Подтверждённый отбор текущей съёмки'}. Каждый файл сохраняется под новым именем вместе с рецептом обработки.</p><label className="form-label">Папка назначения<input className="field" value={formPath} onChange={e => setFormPath(e.target.value)} placeholder="C:\Фото\Готовое"/></label><div className="form-row"><label className="form-label">Формат<select className="field" value={exportFormat} onChange={e => setExportFormat(e.target.value)}><option value="jpeg">JPEG · выдача</option><option value="tiff">TIFF · 16 бит</option></select></label><label className="form-label">Цветовой профиль<select className="field" disabled={exportFormat === 'jpeg'} value={exportFormat === 'jpeg' ? 'srgb' : exportProfile} onChange={e => setExportProfile(e.target.value)}><option value="srgb">sRGB</option><option value="prophoto">ProPhoto RGB</option></select></label></div><label className="form-label">Длинная сторона<select className="field" value={exportEdge} onChange={e => setExportEdge(Number(e.target.value))}><option value={0}>Полное разрешение</option><option value={4000}>4 000 px</option><option value={2048}>2 048 px</option></select></label>{!selected.size && <label className="check-label"><input type="checkbox" checked={includeProposed} onChange={e => setIncludeProposed(e.target.checked)}/> Включить предложенные, ещё не подтверждённые кадры</label>}<div className="modal-actions"><button className="button" onClick={() => void choose()}><Folder size={16}/> Выбрать папку</button><button className="button primary" disabled={!formPath || busy} onClick={() => void act(async () => { await persistDraft(); await post('/export', { photo_ids: [...selected], shoot_id: shootId || null, directory: formPath, format: exportFormat, profile: exportFormat === 'jpeg' ? 'srgb' : exportProfile, long_edge: exportEdge, include_proposed: includeProposed }); setModal('jobs'); }, 'Экспорт добавлен в очередь')}><ArrowDownToLine size={16}/> Экспортировать</button></div></Modal>}
    {modal === 'jobs' && <JobsPanel jobs={jobs} close={() => setModal(null)} error={notify}/>}
    {modal === 'batch' && detail && draft && <BatchPanel selected={[...selected]} close={()=>setModal(null)} error={notify} done={message=>{notify(message);void refresh();}} prepare={async()=>{const key=editorRef.current?.key;await persistDraft();const current=editorRef.current;if(!current || current.key!==key) throw new Error('Открытый кадр изменился. Откройте пакетную правку повторно.');return {id:current.detail.id,recipe:structuredClone(current.detail.recipe)};}}/>}
    {modal === 'settings' && status && <Modal title="Локальные настройки" close={() => setModal(null)} wide><div className="settings-grid"><EngineSettings status={status} save={values => void act(() => api('/settings',{method:'PATCH',body:JSON.stringify(values)}))}/><section><h3>Кадрирование и вкус</h3><label className="form-label">Желаемая доля отбора<input className="field" type="number" min={1} max={100} defaultValue={Math.round(Number(status.settings.keeper_fraction || .35)*100)} onBlur={e => void act(() => api("/settings", {method:"PATCH",body:JSON.stringify({keeper_fraction:Number(e.target.value)/100})}))}/></label><p className="control-note">Уникальные и спорные кадры сохраняются сверх заданной доли.</p><label className="check-label"><input type="checkbox" checked={status.auto_crop_active} onChange={e => void act(() => api('/settings', {method:'PATCH',body:JSON.stringify({auto_crop:e.target.checked,crop_validated:e.target.checked})}))}/> Разрешить консервативную автообрезку</label><p className="control-note">Включайте после проверки предложений на своих съёмках. По умолчанию сохраняется минимум 80% площади.</p><Slider label="Минимум площади" value={Number(status.settings.crop_min_area || .8)} min={.5} max={1} onChange={v => setStatus({...status, settings: {...status.settings,crop_min_area:v}})}/><button className="button full" onClick={() => void act(() => api('/settings', {method:'PATCH',body:JSON.stringify({crop_min_area:status.settings.crop_min_area || .8})}), 'Ограничение сохранено')}>Сохранить ограничение</button><button className="button full" onClick={() => void act(() => post('/ranker/train'), 'Проверка персональной модели в очереди')}><Sparkles size={15}/> Обновить персональный отбор</button><p className="control-note">Обучение использует ваши сравнения и оценки. Проверка выполняется на других съёмках.</p></section></div><section><h3>Папки исходников</h3>{roots.map(r => <div className="root-row" key={r.id}><span className={r.available ? 'good-text' : 'error-text'}>{r.available ? '●' : '○'}</span><code>{r.path}</code><button className="button small" onClick={async () => { const path = window.pywebview ? (await window.pywebview.api.choose_folder())[0] : prompt('Новый путь к той же папке', r.path); if (path) void act(async () => { await post(`/roots/${r.id}/relink`, {path}); setRoots(await api('/roots')); }, 'Папка перепривязана, исходники проверены'); }}>Перепривязать</button></div>)}</section><div className="settings-project">Проект: {status.project}</div></Modal>}
    {modal === 'recipe' && detail && <Modal title="Восстановить рецепт" close={() => setModal(null)}><p className="modal-description">Укажите путь к файлу .openphoto.json, сохранённому при экспорте этого исходника. Будут проверены исходник и версии моделей.</p><label className="form-label">Файл рецепта<input className="field" value={formPath} onChange={e => setFormPath(e.target.value)}/></label><button className="button primary full" disabled={!formPath} onClick={() => void act(async () => { await replaceRecipe(current => post('/recipes/restore-file', {photo_id:current.id,path:formPath,expected_revision:current.revision})); setModal(null); })}>Восстановить как новую версию</button></Modal>}
    {modal === 'geometry' && detail && geometryProposal && <Modal title="Новая геометрия" close={() => setModal(null)} wide><p className="modal-description">{geometryProposal.note}</p><div className="geometry-comparison"><figure><img src={imageUrl(detail.id,'render',detail.revision)} alt="Текущая версия"/><figcaption>Текущая версия</figcaption></figure><figure><img key={latestUpdate} src={imageUrl(detail.id,'geometry-new',detail.revision)} alt="Предпросмотр новой геометрии" onLoad={() => setGeometryReady(true)} onError={() => setGeometryReady(false)}/><figcaption>После перехода</figcaption></figure></div><button className="button primary full" disabled={busy || !geometryReady || jobs.some(j => j.kind === 'geometry_preview' && j.photo_ids.includes(detail.id) && ['queued','running'].includes(j.state))} onClick={() => void act(async () => { await persistDraft(geometryProposal.recipe,'geometry_migration'); setModal(null); })}>Сохранить как новую версию</button></Modal>}
    {modal === 'help'  && <Modal title="Работа без лишних кликов" close={() => setModal(null)}><button className="button full" onClick={()=>{setModal(null);setShowGuide(true);}}>Пройти короткое обучение</button><div className="shortcut-list">{[['← / →','Перейти между кадрами'], ['P','Добавить в отбор'], ['X','Отклонить кадр'], ['1–5','Поставить рейтинг'], ['B / короткий пробел','Переключить до / после'], ['Ctrl + колесо / + −','Приблизить или отдалить фото'], ['Ctrl + 0 / Ctrl + 1','По окну / пиксель в пиксель'], ['Пробел + мышь / H','Перетаскивать, в том числе при кадрировании'], ['Ctrl + Enter','Применить ручные изменения'], ['Ctrl + клик','Выделить несколько кадров'], ['Ctrl + A','Выделить все кадры текущего фильтра'], ['Delete','Удалить из каталога, сохранив оригиналы'], ['Ctrl + Z','Отменить последнее действие в каталоге'], ['Esc','Вернуться к съёмке']].map(([key,text]) => <div key={key}><span>{text}</span><kbd>{key}</kbd></div>)}</div><button className="button full" onClick={() => void act(() => post('/decisions/undo'), 'Последнее решение отменено')}><RotateCcw size={15}/> Отменить последнее решение отбора</button></Modal>}
  </div>;
}
