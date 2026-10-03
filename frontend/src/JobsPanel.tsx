import { useEffect, useState } from 'react';
import { ArrowDownToLine, FolderOpen, Pause, Play, RefreshCw, Sparkles, X } from 'lucide-react';
import { api, post } from './api';
import { IconButton, Modal } from './controls';
import type { Job } from './types';

export const jobNames: Record<string, string> = { workflow:'Автоматическая обработка съёмки', geometry_preview:'Предпросмотр геометрии', import:'Импорт', analyze:'Анализ съёмки', render:'Проявка кадра', profile:'Подготовка референсов', style:'Подбор цвета', export:'Экспорт', train:'Обучение вкусу' };
const stateNames: Record<string, string> = {queued:'В очереди',running:'В работе',paused:'На паузе',completed:'Готово',completed_with_errors:'Есть ошибки',failed:'Ошибка',cancelled:'Отменено'};
const active = (job: Job) => ['queued','running','paused'].includes(job.state);
type Outputs = {directory: string; total: number; files: {path: string; available: boolean}[]};
type HistoryPage = {jobs: Job[]; next_cursor: string | null; total: number};

function JobRow({job, action, error}: {job: Job; action:(path:string)=>Promise<unknown>; error:(message:string)=>void}) {
  const [outputs, setOutputs] = useState<Outputs | null>(null);
  const [expandedErrors, setExpandedErrors] = useState<Job['result']['errors']>();
  const loadOutputs = async () => {
    try {
      const next = await api<Outputs>(`/jobs/${job.id}/outputs?offset=${outputs?.files.length || 0}`);
      setOutputs(previous => ({...next,files:[...(previous?.files || []),...next.files]}));
    } catch (e) { error(String(e)); }
  };
  return <div className="job">
    <div className="job-icon">{job.kind === 'export' ? <ArrowDownToLine size={18}/> : <Sparkles size={18}/>}</div>
    <div className="job-body">
      <strong>{jobNames[job.kind] || job.kind} <small>{stateNames[job.state] || job.state}</small></strong>
      <div className="job-progress"><i style={{width:`${100*job.completed/Math.max(job.total,1)}%`}}/></div>
      <span>{job.completed} / {job.total}{job.created ? ` · ${new Date(job.created).toLocaleString()}` : ''}</span>
      {job.error && <p className="error-text">{job.error}</p>}
      {(expandedErrors || job.result.errors)?.map((e,i)=><p className="error-text" key={i}>{e.error}</p>)}
      {!expandedErrors && (job.result.error_count || 0)>3 && <button className="text-button" onClick={()=>void api<Job>(`/jobs/${job.id}`).then(j=>setExpandedErrors(j.result.errors)).catch(e=>error(String(e)))}>Все ошибки ({job.result.error_count})</button>}
      {job.result.message && <p>{job.result.message}</p>}
      {job.kind === 'workflow' && job.result.prepared_count !== undefined && <p>Готовых превью: {job.result.prepared_count} · В отборе: {job.result.selected_count} · Вне отбора: {job.result.skipped_count}</p>}
      {!!job.result.warning_count && <p className="error-text">Кадров с ограничениями ИИ: {job.result.warning_count}. Подробности — вкладка «Анализ» открытого кадра.</p>}
      {job.kind === 'export' && <>
        <p>Готовых фотографий: {job.result.output_count || 0}</p>
        <div className="modal-actions">
          <button className="button small" onClick={()=>void action(`/jobs/${job.id}/open-folder`)}><FolderOpen size={15}/> Открыть папку результата</button>
          {!outputs && !!job.result.output_count && <button className="button small" onClick={()=>void loadOutputs()}>Показать файлы</button>}
        </div>
        {outputs && <><p className="file-path">{outputs.directory}</p>{outputs.files.map(f=><p className="file-path" key={f.path}>{f.path}{!f.available && <span className="error-text"> · файл перемещён или недоступен</span>}</p>)}
          {outputs.files.length<outputs.total && <button className="text-button" onClick={()=>void loadOutputs()}>Ещё файлы ({outputs.files.length} / {outputs.total})</button>}</>}
      </>}
    </div>
    <div className="job-buttons">
      {['running','queued'].includes(job.state) && <IconButton title="Пауза" onClick={()=>void action(`/jobs/${job.id}/pause`)}><Pause size={15}/></IconButton>}
      {job.state==='paused' && <IconButton title="Продолжить" onClick={()=>void action(`/jobs/${job.id}/resume`)}><Play size={15}/></IconButton>}
      {['failed','completed_with_errors'].includes(job.state) && <IconButton title="Повторить ошибки" onClick={()=>void action(`/jobs/${job.id}/retry`)}><RefreshCw size={15}/></IconButton>}
      {active(job) && <IconButton title="Отменить" onClick={()=>void action(`/jobs/${job.id}/cancel`)}><X size={15}/></IconButton>}
    </div>
  </div>;
}

export function JobsPanel({jobs,close,error}: {jobs:Job[];close:()=>void;error:(message:string)=>void}) {
  const [history,setHistory] = useState<Job[]>([]);
  const [snapshot,setSnapshot] = useState<Job[]>([]);
  const [cursor,setCursor] = useState<string | null>(null);
  const [loading,setLoading] = useState(false);
  const load = async (next: string | null = null) => {
    setLoading(true);
    try {
      const [page, live] = await Promise.all([api<HistoryPage>(`/jobs/history${next ? '?cursor='+encodeURIComponent(next) : ''}`),api<Job[]>('/jobs')]);
      setSnapshot(live);
      setHistory(previous=>next ? [...previous,...page.jobs] : page.jobs);
      setCursor(page.next_cursor);
    } catch (e) {error(String(e));} finally {setLoading(false);}
  };
  useEffect(()=>{void load();},[]);
  const action = async (path:string) => {try {await post(path);} catch(e) {error(String(e));}};
  const combined = new Map<string, Job>();
  for (const job of [...history,...snapshot,...jobs]) {
    const prior=combined.get(job.id);
    if (!prior || prior.updated <= job.updated) combined.set(job.id,job);
  }
  const current = [...combined.values()].filter(active);
  const finished = [...combined.values()].filter(j=>!active(j)).sort((a,b)=>(b.created || b.updated).localeCompare(a.created || a.updated) || b.id.localeCompare(a.id));
  return <Modal title="Обработка и экспорт" close={close} wide>
    <h3>Активные задания · {current.length}</h3>
    <div className="job-list">{current.map(job=><JobRow key={job.id} {...{job,action,error}}/>)}{!current.length && <p className="modal-description">{loading ? 'Загружаю состояние заданий…' : 'Сейчас нет активных заданий. Результаты завершённых заданий — ниже.'}</p>}</div>
    <h3>История</h3><div className="job-list">{finished.map(job=><JobRow key={job.id} {...{job,action,error}}/>)}</div>
    {cursor && <button className="button full" disabled={loading} onClick={()=>void load(cursor)}>{loading ? 'Загружаю…' : 'Показать более ранние задания'}</button>}
    {!finished.length && !loading && <p className="modal-description">Здесь появятся завершённые задания.</p>}
  </Modal>;
}
