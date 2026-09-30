import { useEffect, useState } from 'react';
import { FolderOpen, Save, Trash2 } from 'lucide-react';
import { api, post } from './api';
import { Modal } from './controls';
import type { Profile, Shoot } from './types';

function NamedRow({name,remove,rename}: {name:string;remove?:()=>Promise<void>;rename:(value:string)=>Promise<void>}) {
  const [value,setValue]=useState(name);
  return <div className="root-row"><input className="field" aria-label={`Название: ${name}`} value={value} onChange={e=>setValue(e.target.value)}/>
    <button className="button small" disabled={!value.trim() || value.trim()===name} onClick={()=>void rename(value)}><Save size={14}/> Сохранить</button>
    {remove && <button className="button small" aria-label={`Удалить: ${name}`} onClick={()=>{if(confirm(`Удалить «${name}» из каталога? Исходные фотографии останутся на месте.`)) void remove();}}><Trash2 size={14}/></button>}
  </div>;
}

export function ProjectsPanel({shoots,profiles,prepare,refresh,notify,close}: {
  shoots:Shoot[];profiles:Profile[];prepare:()=>Promise<void>;refresh:()=>Promise<void>;
  notify:(message:string)=>void;close:()=>void;
}) {
  const [directory,setDirectory]=useState('');
  const [current,setCurrent]=useState('');
  const [recent,setRecent]=useState<string[]>([]);
  const [create,setCreate]=useState(false);
  const [backups,setBackups]=useState<{name:string;bytes:number;modified:number}[]>([]);
  const [busy,setBusy]=useState(false);
  const loadBackups=()=>api<typeof backups>('/project/backups').then(setBackups);
  useEffect(()=>{
    void api<{directory:string;recent:string[]}>('/project').then(p=>{setCurrent(p.directory);setRecent(p.recent);}).catch(e=>notify(String(e)));
    void loadBackups().catch(e=>notify(String(e)));
  },[]);
  const act=async(fn:()=>Promise<unknown>)=>{setBusy(true);try{await fn();await refresh();}catch(e){notify(String(e));}finally{setBusy(false);}};
  const open=async(path=directory)=>{
    await prepare();
    if(!window.pywebview) throw new Error('Переключение проекта доступно в десктоп-приложении. Путь: '+path);
    await window.pywebview.api.open_project(path,create);
  };
  return <Modal title="Проекты и библиотека" close={close} wide>
    <h3>Текущий проект</h3><p className="file-path">{current}</p>
    <p className="modal-description">В проекте хранятся каталог, правки и референсы. Фотографии остаются в выбранных при импорте папках.</p>
    <label className="form-label">Папка проекта<input className="field" value={directory} onChange={e=>setDirectory(e.target.value)}/></label>
    <label className="check-label"><input type="checkbox" checked={create} onChange={e=>setCreate(e.target.checked)}/> Создать новый проект в пустой папке</label>
    <div className="modal-actions"><button className="button" disabled={busy || !window.pywebview} onClick={()=>void act(async()=>{const paths=await window.pywebview!.api.choose_folder();if(paths[0])setDirectory(paths[0]);})}><FolderOpen size={16}/> Выбрать папку</button>
      <button className="button primary" disabled={busy || !directory.trim()} onClick={()=>void act(()=>open())}>{create ? 'Создать и открыть' : 'Открыть проект'}</button></div>
    {recent.length>0 && <details><summary>Недавние проекты</summary>{recent.filter(p=>p!==current).map(p=><button key={p} className="button full file-path" disabled={busy} onClick={()=>{setDirectory(p);setCreate(false);}}>{p}</button>)}</details>}
    <section className="control-section"><h3>Резервные копии</h3>
      <p className="control-note">Восстановление создаёт отдельную копию проекта. Текущий каталог и оригиналы сохраняются; незавершённые задания в копии остаются на паузе.</p>
      <button className="button" disabled={busy} onClick={()=>void act(async()=>{await prepare();await post('/project/backups');await loadBackups();notify('Резервная копия каталога создана');})}>Создать резервную копию</button>
      <details><summary>Доступные копии ({backups.length})</summary>{backups.map(b=><div className="root-row" key={b.name}><span className="file-path">{new Date(b.modified*1000).toLocaleString()} · {Math.round(b.bytes/1024)} КБ</span>
        <button className="button small" disabled={busy} onClick={()=>void act(async()=>{await prepare();const result=await post<{directory:string}>(`/project/backups/${encodeURIComponent(b.name)}/restore`);setDirectory(result.directory);setCreate(false);notify('Копия восстановлена. Нажмите «Открыть проект», чтобы перейти к ней.');})}>Восстановить копией</button></div>)}</details>
    </section>
    <section className="control-section"><h3>Съёмки</h3>{shoots.map(s=><NamedRow key={s.id+':'+s.name} name={s.name}
      rename={value=>act(()=>api(`/shoots/${s.id}`,{method:'PATCH',body:JSON.stringify({name:value})}))}
      remove={s.count===0 ? ()=>act(()=>api(`/shoots/${s.id}`,{method:'DELETE'})) : undefined}/>)}</section>
    <section className="control-section"><h3>Профили референсов</h3>{profiles.map(p=><NamedRow key={p.id+':'+p.name} name={p.name}
      rename={value=>act(()=>api(`/profiles/${p.id}`,{method:'PATCH',body:JSON.stringify({name:value})}))}
      remove={()=>act(()=>api(`/profiles/${p.id}`,{method:'DELETE'}))}/>)}</section>
  </Modal>;
}
