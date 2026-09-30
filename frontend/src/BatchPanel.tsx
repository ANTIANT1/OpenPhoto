import { useState } from 'react';
import { CheckCheck } from 'lucide-react';
import { Modal } from './controls';
import { post } from './api';
import type { Recipe } from './types';

export function BatchPanel({selected,prepare,close,done,error}: {
  selected:string[]; prepare:()=>Promise<{id:string;recipe:Recipe}>;close:()=>void;
  done:(message:string)=>void;error:(message:string)=>void;
}) {
  const [scope,setScope]=useState(selected.length>1 ? 'selection' : 'group');
  const [sections,setSections]=useState(['color','retouch']);
  const [harmonize,setHarmonize]=useState(false);
  const [preserve,setPreserve]=useState(true);
  const [busy,setBusy]=useState(false);
  const submit=async()=>{
    setBusy(true);
    try {
      const source=await prepare();
      const result=await post<{updated:string[];skipped:string[]}>('/recipes/batch',{
        photo_ids:scope==='selection' ? selected.filter(id=>id!==source.id) : [source.id],scope,sections,
        source_photo_id:source.id,recipe:source.recipe,preserve_manual:preserve,harmonize_exposure:harmonize
      });
      done(`Обновлено: ${result.updated.length}. Сохранены без изменений: ${result.skipped.length}.`);
      close();
    } catch(e) {error(String(e));} finally {setBusy(false);}
  };
  return <Modal title="Настройки для серии" close={close}>
    <p className="modal-description">Выберите, какие настройки переносить с открытого кадра. Маски защиты и точки восстановления других фотографий сохраняются.</p>
    <label className="form-label">Область применения<select className="field" value={scope} onChange={e=>setScope(e.target.value)}>
      <option value="group">Эта группа</option><option value="shoot">Вся съёмка</option>
      <option value="selection" disabled={selected.length<2}>Выделенные кадры ({selected.length})</option>
    </select></label>
    {([['develop','Проявка · экспозиция, баланс белого и RAW-параметры'],['color','Цвет и тон'],['retouch','Сила ретуши лица и тела'],['crop','Композиция · безопасное кадрирование']] as const).map(([key,label])=>
      <label className="check-label" key={key}><input type="checkbox" checked={sections.includes(key)} onChange={e=>setSections(s=>e.target.checked ? [...s,key] : s.filter(x=>x!==key))}/>{label}</label>)}
    {sections.includes('develop') && <p className="control-note">Для JPEG переносится экспозиция; параметры RAW применяются к RAW-файлам.</p>}
    <label className="check-label"><input type="checkbox" checked={preserve} onChange={e=>setPreserve(e.target.checked)}/> Сохранять индивидуальные правки</label>
    <label className="check-label"><input type="checkbox" checked={harmonize} onChange={e=>setHarmonize(e.target.checked)}/> Согласовать экспозицию похожих кадров · до ±0,5 EV</label>
    <div className="modal-actions"><button className="button" onClick={close}>Отмена</button><button className="button primary" disabled={busy || !sections.length} onClick={()=>void submit()}><CheckCheck size={16}/>{busy ? 'Сохраняю…' : 'Применить к серии'}</button></div>
  </Modal>;
}
