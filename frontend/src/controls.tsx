import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { X } from 'lucide-react';

export function IconButton({ children, title, onClick, active = false, disabled = false }: { children: ReactNode; title: string; onClick: () => void; active?: boolean; disabled?: boolean }) {
  return <button className={`icon-button ${active ? 'active' : ''}`} title={title} aria-label={title} onClick={onClick} disabled={disabled}>{children}</button>;
}
export function Slider({ label, value, min, max, step = 0.01, onChange, format, resetValue }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; format?: (v: number) => string; resetValue?: number }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const number = Number(text.replace(',', '.'));
    if (!text.trim() || !Number.isFinite(number)) { setText(String(value)); return; }
    const next = Number(Math.max(min, Math.min(max, Math.round(number / step) * step)).toFixed(6));
    onChange(next); setText(String(next));
  };
  return <div className="slider"><span>{label}<span className="slider-value"><input className="numeric-value" type="text" inputMode="decimal" aria-label={`${label}: значение`} title={format ? format(value) : label} value={text} onChange={e=>setText(e.target.value)} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();e.currentTarget.blur();}if(e.key==='Escape'){setText(String(value));e.stopPropagation();}}}/>{resetValue !== undefined && <button type="button" title={`Сбросить: ${label}`} aria-label={`Сбросить: ${label}`} onClick={()=>onChange(resetValue)}>↺</button>}</span></span><input type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))} /></div>;
}
export function Modal({ title, children, close, wide = false }: { title: string; children: ReactNode; close: () => void; wide?: boolean }) {
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><section className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><IconButton title="Закрыть" onClick={close}><X size={18} /></IconButton></header>{children}</section></div>;
}
