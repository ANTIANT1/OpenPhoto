import { useEffect, useRef, useState } from 'react';
import type { PointerEvent, RefObject } from 'react';

export function useImageViewport(view: RefObject<HTMLDivElement | null>, image: RefObject<HTMLImageElement | null>,
  photoId: string | undefined, editing: boolean, blocked: boolean) {
  const [zoom, setZoom] = useState(1);
  const [pixelView, setPixelView] = useState(false);
  const [hand, setHand] = useState(false);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [panning, setPanning] = useState(false);
  const pan = useRef<{id: number; x: number; y: number; left: number; top: number} | null>(null);
  const dragged = useRef(false);
  const endPan = () => {pan.current = null; setPanning(false);};
  const fit = () => {
    setZoom(1); setPixelView(false);
    if (view.current) {view.current.scrollLeft=0; view.current.scrollTop=0;}
  };
  useEffect(() => {fit(); endPan(); setHand(false); setSpaceHeld(false);}, [photoId]);
  useEffect(() => {
    const blur = () => {endPan(); setSpaceHeld(false); dragged.current=true;};
    window.addEventListener('blur',blur);
    return () => window.removeEventListener('blur',blur);
  }, []);
  const scale = (factor: number, x?: number, y?: number) => {
    const viewport=view.current, picture=image.current;
    if(!viewport || !picture || blocked) return;
    const bounds=picture.getBoundingClientRect(), area=viewport.getBoundingClientRect();
    const anchorX=x ?? area.left+area.width/2, anchorY=y ?? area.top+area.height/2;
    const imageX=(anchorX-bounds.left)/bounds.width, imageY=(anchorY-bounds.top)/bounds.height;
    setPixelView(false); setZoom(previous=>Math.max(.1,Math.min(32,previous*factor)));
    requestAnimationFrame(()=>{
      if(image.current!==picture || view.current!==viewport) return;
      const next=picture.getBoundingClientRect();
      viewport.scrollLeft+=next.left+imageX*next.width-anchorX;
      viewport.scrollTop+=next.top+imageY*next.height-anchorY;
    });
  };
  useEffect(() => {
    const viewport=view.current;
    if(!viewport || !photoId) return;
    const wheel=(event: WheelEvent)=>{
      if(!event.ctrlKey && !event.metaKey) return;
      event.preventDefault(); event.stopPropagation();
      scale(Math.exp(-event.deltaY*.002),event.clientX,event.clientY);
    };
    viewport.addEventListener('wheel',wheel,{passive:false});
    return ()=>viewport.removeEventListener('wheel',wheel);
  }, [photoId,blocked]);
  const down=(event: PointerEvent<HTMLDivElement>)=>{
    if(blocked || (event.button!==1 && (event.button!==0 || (editing && !spaceHeld && !hand)))) return;
    event.preventDefault(); event.stopPropagation();
    const viewport=event.currentTarget;
    pan.current={id:event.pointerId,x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};
    viewport.setPointerCapture(event.pointerId); setPanning(true);
  };
  const move=(event: PointerEvent<HTMLDivElement>)=>{
    const start=pan.current;
    if(!start || start.id!==event.pointerId) return;
    event.preventDefault(); event.stopPropagation();
    const dx=event.clientX-start.x, dy=event.clientY-start.y;
    if(Math.abs(dx)+Math.abs(dy)>3) dragged.current=true;
    event.currentTarget.scrollLeft=start.left-dx; event.currentTarget.scrollTop=start.top-dy;
  };
  const up=(event: PointerEvent<HTMLDivElement>)=>{
    if(!pan.current) return;
    event.stopPropagation();
    if(event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    endPan();
  };
  return {zoom, fullResolution:pixelView || zoom>1, hand, setHand, spaceHeld, panning, fit, scale,
    native:(width: number,fitWidth: number)=>{setPixelView(true); setZoom(Math.max(.1,Math.min(32,width/Math.max(1,fitWidth)/(window.devicePixelRatio || 1))));},
    spaceDown:()=>{if(!spaceHeld) dragged.current=false; setSpaceHeld(true);},
    spaceUp:()=>{const tapped=spaceHeld && !dragged.current; setSpaceHeld(false); endPan(); return tapped;},
    props:{onPointerDownCapture:down,onPointerMoveCapture:move,onPointerUpCapture:up,onPointerCancelCapture:up,
      onLostPointerCapture:()=>endPan()}};
}
