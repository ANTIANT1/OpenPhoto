import { useEffect, useState } from 'react';

export function Histogram({src}:{src:string}) {
  const [paths,setPaths]=useState<string[]>([]);
  useEffect(()=>{
    let cancelled=false;
    const image=new Image();
    setPaths([]);
    image.onload=()=>{
      if(cancelled) return;
      const canvas=document.createElement('canvas'); canvas.width=160; canvas.height=100;
      const context=canvas.getContext('2d');
      if(!context) return;
      context.drawImage(image,0,0,160,100);
      const pixels=context.getImageData(0,0,160,100).data;
      const bins=Array.from({length:3},()=>Array<number>(64).fill(0));
      for(let i=0;i<pixels.length;i+=4) for(let channel=0;channel<3;channel++) bins[channel][pixels[i+channel]>>2]++;
      const peak=Math.max(1,...bins.flat());
      setPaths(bins.map(values=>'M 0 60 '+values.map((value,i)=>`L ${i*4} ${60-58*Math.sqrt(value/peak)}`).join(' ')+' L 252 60 Z'));
    };
    image.onerror=()=>{if(!cancelled) setPaths([]);}; image.src=src;
    return ()=>{cancelled=true; image.onload=null; image.onerror=null;};
  },[src]);
  return <section className="histogram" aria-label="Гистограмма текущего превью"><span>Гистограмма превью</span>
    <svg viewBox="0 0 252 62" role="img" aria-label={paths.length ? 'Распределение красного, зелёного и синего каналов' : 'Гистограмма загружается'}>
      {paths.map((d,i)=><path key={i} d={d} fill={['#ea8c8055','#acdb9855','#80bce855'][i]} stroke={['#ea8c80','#acdb98','#80bce8'][i]} strokeWidth=".8"/>)}</svg>
    <small>Обновляется после применения правок</small></section>;
}
