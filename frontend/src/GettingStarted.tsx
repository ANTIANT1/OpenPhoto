import { useState } from 'react';

const steps=[
  ['Добавьте съёмку', 'Нажмите «Новая съёмка» и выберите папку или отдельные фотографии. Съёмка — группа кадров в каталоге; исходные файлы остаются на диске.'],
  ['Обработайте и проверьте', '«Обработать съёмку» запускает анализ, отбор и подготовку превью. Этапы и результат видны в «Обработка и экспорт». Цвет по референсу выбирается в настройках; JPEG сохраняются отдельно через экспорт.'],
  ['Управляйте фотографией', 'Откройте кадр. Ctrl + колесо или + / − меняют масштаб; Ctrl + 0 — по окну, Ctrl + 1 — 1:1. Тяните фото мышью; при кадрировании удерживайте пробел для перемещения. B — до/после.'],
  ['Удаление можно отменить', 'Удалённые кадры находятся в разделе «Удалённые». Их можно восстановить кнопкой или повторным импортом. Корзина рядом с названием убирает съёмку из списка. Исходники, оценки и история обработки сохраняются.'],
];
export function GettingStarted({close}:{close:()=>void}) {
  const [step,setStep]=useState(0);
  return <section className="getting-started" aria-label="Первое знакомство с OpenPhoto">
    <div><small>БЫСТРЫЙ СТАРТ · {step+1} / {steps.length}</small><h3>{steps[step][0]}</h3><p>{steps[step][1]}</p></div>
    <div className="guide-actions"><button className="text-button" onClick={close}>Закрыть обучение</button>
      {step>0 && <button className="button small" onClick={()=>setStep(step-1)}>Назад</button>}
      <button className="button primary small" onClick={()=>step===steps.length-1 ? close() : setStep(step+1)}>{step===steps.length-1 ? 'Понятно' : 'Далее'}</button></div>
  </section>;
}
