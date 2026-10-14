import {dimensionNames,displayCode} from './dimensions.js';

// Keep each paired dimension six axes (180°) apart.
export const dimensionOrder=['P','G','M','H','SOLO','COMP','R','O','N','C','SOCIAL','COOP'];
export function radarGeometry(dimensions,cx=320,cy=260,radius=180,labelRadius=225) {
  const axes=dimensionOrder.map((code,index)=>{
    const angle=-Math.PI/2+index*2*Math.PI/dimensionOrder.length;
    const item=dimensions[code],value=item?.value ?? null;
    const point=(r)=>({x:cx+Math.cos(angle)*r,y:cy+Math.sin(angle)*r});
    return {code,name:item?.name||dimensionNames[code]||displayCode(code),value,end:point(radius),label:point(labelRadius),
            point:value==null?null:point(radius*value/100)};
  });
  const complete=axes.every(a=>a.point);
  const segments=axes.flatMap((axis,i)=>{
    const next=axes[(i+1)%axes.length];
    return axis.point&&next.point?[[axis.point,next.point]]:[];
  });
  const rings=[20,40,60,80,100].map(level=>({level,points:axes.map(a=>({
    x:cx+(a.end.x-cx)*level/100,y:cy+(a.end.y-cy)*level/100}))}));
  return {cx,cy,radius,axes,rings,complete,segments};
}

export function drawRadar(ctx,dimensions,cx,cy,radius,labelRadius) {
  const geometry=radarGeometry(dimensions,cx,cy,radius,labelRadius);
  function path(points,close=false) {ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));if(close)ctx.closePath();}
  ctx.lineWidth=1.5;ctx.strokeStyle='#35504b';
  for(const ring of geometry.rings){path(ring.points,true);ctx.stroke();}
  for(const axis of geometry.axes){path([{x:cx,y:cy},axis.end]);ctx.stroke();}
  ctx.fillStyle='#a6e6ce22';ctx.strokeStyle='#a6e6ce';ctx.lineWidth=3;
  if(geometry.complete){path(geometry.axes.map(a=>a.point),true);ctx.fill();ctx.stroke();}
  else for(const segment of geometry.segments){path(segment);ctx.stroke();}
  for(const axis of geometry.axes){
    if(axis.point){ctx.beginPath();ctx.arc(axis.point.x,axis.point.y,4,0,2*Math.PI);ctx.fillStyle='#a6e6ce';ctx.fill();}
    ctx.fillStyle=axis.value==null?'#82968f':'#d5e1db';
    ctx.font='400 23px "Noto Sans SC", sans-serif';
    ctx.textAlign=Math.abs(axis.label.x-cx)<2?'center':axis.label.x>cx?'left':'right';
    ctx.fillText(`${axis.name} ${displayCode(axis.code)}`,axis.label.x,axis.label.y);
    ctx.font='400 19px "Noto Sans SC", sans-serif';
    ctx.fillText(axis.value==null?'—':axis.value.toFixed(1),axis.label.x,axis.label.y+28);
  }
  ctx.textAlign='left';
  return geometry;
}
