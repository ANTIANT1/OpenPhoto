import type { ReactNode } from 'react';
import { X } from 'lucide-react';

export function IconButton({ children, title, onClick, active = false, disabled = false }: { children: ReactNode; title: string; onClick: () => void; active?: boolean; disabled?: boolean }) {
  return <button className={`icon-button ${active ? 'active' : ''}`} title={title} aria-label={title} onClick={onClick} disabled={disabled}>{children}</button>;
}
export function Slider({ label, value, min, max, step = 0.01, onChange, format }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; format?: (v: number) => string }) {
  return <label className="slider"><span>{label}<output>{format ? format(value) : value.toFixed(2)}</output></span><input type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))} /></label>;
}
export function Modal({ title, children, close, wide = false }: { title: string; children: ReactNode; close: () => void; wide?: boolean }) {
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><section className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><IconButton title="Закрыть" onClick={close}><X size={18} /></IconButton></header>{children}</section></div>;
}
