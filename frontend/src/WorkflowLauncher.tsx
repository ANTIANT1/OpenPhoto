import { useEffect, useState } from 'react';
import { Loader2, Settings2, SlidersHorizontal, Sparkles } from 'lucide-react';
import { Modal } from './controls';
import { post } from './api';
import type { Job, Profile, Status } from './types';

type Options={profile_id:string|null;strength:number;selection:'all'|'suggested';retouch_strength:number};
export function WorkflowLauncher({ids,shootId,count,profiles,status,jobs,manual,progress,error,onModal}:{
  ids:string[];shootId:string;count:number;profiles:Profile[];status:Status|null;jobs:Job[];
  manual:()=>void;progress:()=>void;error:(text:string)=>void;onModal:(open:boolean)=>void;
}) {
  const [options,setOptions]=useState<Options>({profile_id:null,strength:.6,selection:'suggested',retouch_strength:.15});
  const [configured,setConfigured]=useState(false);
  const [settings,setSettings]=useState(false);
  const [exportFiles,setExportFiles]=useState(false);
  const [directory,setDirectory]=useState('');
  const [starting,setStarting]=useState(false);
  useEffect(()=>{
    if(!configured && status) {
      const defaults=status.settings.workflow_defaults as Partial<Options> | undefined;
      if(defaults) setOptions(previous=>({...previous,...defaults}));
      setDirectory(status.export_directory || ''); setConfigured(true);
    }
  },[status,configured]);
  const showSettings=(open:boolean)=>{setSettings(open);onModal(open);};
  const current=jobs.find(j=>j.kind==='workflow' && ['queued','running','paused'].includes(j.state));
  const importing=jobs.some(j=>j.kind==='import' && ['queued','running','paused'].includes(j.state));
  const latest=jobs.find(j=>j.kind==='workflow');
  const start=async()=>{
    setStarting(true);
    try {
      if(exportFiles && !directory.trim()) throw new Error('Выберите папку для готовых JPEG');
      await post('/workflows',{...options,photo_ids:ids,shoot_id:shootId || null,export_directory:exportFiles ? directory : null});
      showSettings(false);progress();
    } catch(e) {error(String(e));} finally {setStarting(false);}
  };
  return <>
    <div className="workflow-launcher">
      <div className="workflow-card primary"><strong>Автоматически</strong><span>Отбор → цвет{options.profile_id ? ' по референсу' : ''} → естественная ретушь → готовые превью{exportFiles ? ' и JPEG' : ' для проверки'}.</span>
        <button className="button primary" disabled={!count || starting || !!current || importing} onClick={()=>void start()}>{starting ? <Loader2 size={16} className="spin"/> : <Sparkles size={16}/>} Обработать съёмку</button>
        {importing && <span>Дождитесь завершения импорта всей съёмки.</span>}
        <button className="text-button" onClick={()=>showSettings(true)}><Settings2 size={14}/> Настроить: {profiles.find(p=>p.id===options.profile_id)?.name || 'Естественный цвет'} · {count} кадров</button>
      </div>
      <div className="workflow-card"><strong>Вручную</strong><span>Открывайте кадры, меняйте цвет и кадрирование. Выделение Ctrl+A, удаление Delete, масштаб Ctrl+колесо.</span>
        <button className="button" disabled={!count} onClick={manual}><SlidersHorizontal size={16}/> Обрабатывать вручную</button>
        <span>После проверки нажмите «Экспорт» вверху.</span>
      </div>
    </div>
    {latest && <div className="workflow-status"><span>{current ? `${current.state==='paused' ? 'Пауза' : 'Обработка'} · ${current.completed}/${current.total}` : 'Последняя обработка'} — {latest.result.message || 'Подготовка съёмки'}</span>{!current && latest.state==='completed' && <button className="button small" onClick={manual}>Проверить кадры</button>}<button className="text-button" onClick={progress}>Прогресс и результаты</button></div>}
    {settings && <Modal title="Автоматическая обработка" close={()=>showSettings(false)}>
      <p className="modal-description">Настройте один раз и запускайте съёмку кнопкой «Обработать съёмку». Ручные правки сохранятся. Спорные кадры останутся для проверки.</p>
      <label className="form-label">Цвет<select className="field" value={options.profile_id || ''} onChange={e=>setOptions({...options,profile_id:e.target.value || null})}><option value="">Естественный цвет</option>{profiles.map(p=><option key={p.id} value={p.id} disabled={!p.references.length}>{p.name}</option>)}</select></label>
      {options.profile_id && <label className="form-label">Сила стиля<select className="field" value={options.strength} onChange={e=>setOptions({...options,strength:Number(e.target.value)})}><option value={.35}>Мягкая</option><option value={.6}>Средняя</option><option value={1}>Выраженная</option></select></label>}
      <label className="form-label">Какие кадры обрабатывать<select className="field" value={options.selection} onChange={e=>setOptions({...options,selection:e.target.value as Options['selection']})}><option value="suggested">Предложенный отбор и спорные кадры</option><option value="all">Все неотклонённые кадры</option></select></label>
      <label className="check-label"><input type="checkbox" checked={options.retouch_strength>0} onChange={e=>setOptions({...options,retouch_strength:e.target.checked ? .15 : 0})}/> Мягкая ретушь кожи</label>
      <label className="check-label"><input type="checkbox" checked={exportFiles} onChange={e=>setExportFiles(e.target.checked)}/> Сразу сохранить готовые JPEG</label>
      {exportFiles && <><label className="form-label">Папка результата<input className="field" value={directory} onChange={e=>setDirectory(e.target.value)}/></label><button className="button" onClick={()=>{if(window.pywebview) void window.pywebview.api.choose_folder().then(paths=>{if(paths[0])setDirectory(paths[0]);}).catch(e=>error(String(e)));}}>Выбрать папку результата</button></>}
      <p className="control-note">Кадрирование сохраняется, если вы отдельно не разрешили автообрезку. Отмеченные вами отклонённые и удалённые кадры пропускаются.</p>
      <div className="modal-actions"><button className="button" onClick={()=>showSettings(false)}>Готово</button><button className="button primary" disabled={!count || starting || !!current} onClick={()=>void start()}>Начать обработку</button></div>
    </Modal>}
  </>;
}
