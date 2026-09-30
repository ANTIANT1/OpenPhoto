import type { Status } from './types';

export function EngineSettings({status, save}: {status: Status; save: (values: Record<string, unknown>) => void}) {
  return <section><h3>Движок, модели и ресурсы</h3>
    {([['rawtherapee','RawTherapee CLI'],['exiftool','ExifTool'],['models_directory','Папка моделей']] as const).map(([key,label]) =>
      <div key={key}><label className="form-label" htmlFor={`setting-${key}`}>{label}<input id={`setting-${key}`} className="field" key={String(status.settings[key])} defaultValue={String(status.settings[key] || '')} onBlur={e => {if(e.target.value !== status.settings[key]) save({[key]:e.target.value});}}/></label><button className="text-button" onClick={() => save({[key]:''})}>Использовать встроенный путь</button></div>)}
    {([['cache_gb','Лимит кэша, ГБ',1,500,20],['cpu_threads','Потоки CPU',1,4,4],['worker_idle_seconds','Освобождать модели после простоя, секунд',10,120,120]] as const).map(([key,label,min,max,fallback]) =>
      <label className="form-label" key={key}>{label}<input className="field" type="number" min={min} max={max} defaultValue={Number(status.settings[key] || fallback)} onBlur={e => {const value=Number(e.target.value); if(Number.isFinite(value) && value>=min && value<=max) save({[key]:value});}}/></label>)}
    <p className="control-note">Одна тяжёлая операция одновременно. Новые ограничения применяются при следующем запуске рабочего процесса.</p>
    <div className="model-list">{Object.entries(status.models).map(([name, ready]) => <div key={name}><span>{name}</span><small className={ready ? 'good-text' : ''}>{ready ? 'Файл доступен' : 'Не найдена'}</small></div>)}</div>
    <p className="control-note">Контрольные суммы проверяются перед загрузкой моделей. Обработка работает без сети.</p>
  </section>;
}
