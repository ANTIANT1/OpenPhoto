import type { CSSProperties } from 'react';
import type { Crop } from './types';

export type CropHandle = 'move' | 'new' | 'n' | 's' | 'e' | 'w' | 'nw' | 'ne' | 'sw' | 'se';
export type CropDrag = {start:{x:number;y:number};crop:Crop;handle:CropHandle};
const clamp = (n:number, lo:number, hi:number) => Math.min(hi, Math.max(lo,n));

export function dragCrop(drag:CropDrag, point:{x:number;y:number}):Crop {
  const c=drag.crop, dx=point.x-drag.start.x, dy=point.y-drag.start.y;
  if(drag.handle==='move') return {...c,x:clamp(c.x+dx,0,1-c.w),y:clamp(c.y+dy,0,1-c.h)};
  if(drag.handle==='new') {
    const x=Math.min(point.x,drag.start.x), y=Math.min(point.y,drag.start.y);
    return {x,y,w:Math.min(1-x,Math.max(.005,Math.abs(dx))),h:Math.min(1-y,Math.max(.005,Math.abs(dy)))};
  }
  let left=c.x, top=c.y, right=c.x+c.w, bottom=c.y+c.h;
  if(drag.handle.includes('w')) left=clamp(c.x+dx,0,right-.005);
  if(drag.handle.includes('e')) right=clamp(c.x+c.w+dx,left+.005,1);
  if(drag.handle.includes('n')) top=clamp(c.y+dy,0,bottom-.005);
  if(drag.handle.includes('s')) bottom=clamp(c.y+c.h+dy,top+.005,1);
  return {x:left,y:top,w:right-left,h:bottom-top};
}

const handles:Record<string,[number,number,string]>={nw:[0,0,'nwse'],n:[50,0,'ns'],ne:[100,0,'nesw'],e:[100,50,'ew'],se:[100,100,'nwse'],s:[50,100,'ns'],sw:[0,100,'nesw'],w:[0,50,'ew']};
export function CropOverlay({crop}:{crop:Crop}) {
  return <div className="crop-overlay" data-crop-handle="move" style={{left:`${crop.x*100}%`,top:`${crop.y*100}%`,width:`${crop.w*100}%`,height:`${crop.h*100}%`}}>
    <i/><i/><b/><b/><span>{Math.round(crop.w*crop.h*100)}% площади</span>
    {Object.entries(handles).map(([name,[x,y,cursor]])=><button key={name} type="button" className={`crop-handle crop-handle-${name}`} data-crop-handle={name} aria-label={`Граница кадра ${name}`} style={{left:`${x}%`,top:`${y}%`,cursor:`${cursor}-resize`} as CSSProperties}/>)}
  </div>;
}
