import {displayCode,displayType} from './dimensions.js';

export const reasonText = {
  insufficient_games:'有效游戏不足', insufficient_coverage:'可计分覆盖不足', unknown_duration:'时长信息不足',
  no_reference_group:'无适用参考组', outside_reference_range:'超出参考支持范围', insufficient_reference:'参考样本不足',
  degenerate_reference:'该维参考分布退化', concentrated_evidence:'贡献过于集中',
  insufficient_effective_reference:'相近投入的有效参考不足'
};
export const number = value => value == null ? '—' : value.toFixed(1);
export function shareHeading(share) {
  if(share.type)return displayType(share.type);
  if(share.groups.every(g=>g.tendency==='pending'))return '数据不足 · 画像待定';
  if(share.groups.some(g=>g.tendency==='pending'))return '部分方向待定 · 类型缺省';
  return '混合倾向 · 类型缺省';
}
export function wrapText(ctx,text,width) {
  const lines=[]; let line='';
  for(const char of text) { if(ctx.measureText(line+char).width>width && line) {lines.push(line);line=char;} else line+=char; }
  if(line) lines.push(line);
  return lines;
}
export async function renderShare(share,canvas,isCurrent=()=>true) {
  const fontText=[share.label,shareHeading(share),...Object.values(share.dimensions).map(d=>d.name),
    ...share.groups.map(g=>g.text),...Object.values(reasonText),'观察证据的参考位置，不是喜欢概率或现实人格。低位不表示不喜欢。'].join('');
  await document.fonts.load('400 24px "Noto Sans SC"',fontText); await document.fonts.ready;
  if(!isCurrent())return null;
  const order=dimensionOrder;
  const width=1080, rows=order.filter(k=>share.dimensions[k]).map(k=>[k,share.dimensions[k]]);
  canvas.width=width;
  let ctx=canvas.getContext('2d');ctx.font='400 20px "Noto Sans SC", sans-serif';
  const groupLines=share.groups.map(g=>wrapText(ctx,g.text,952));
  canvas.height=1000+rows.length*100+groupLines.reduce((n,lines)=>n+lines.length*30+15,0);
  ctx=canvas.getContext('2d');
  ctx.fillStyle='#0b171b';ctx.fillRect(0,0,width,canvas.height);
  const font = size => {ctx.font=`400 ${size}px "Noto Sans SC", sans-serif`;};
  ctx.fillStyle='#9cddc8';font(24);ctx.fillText('GAMEPERSONA / 游戏偏好画像',64,70);
  ctx.fillStyle='#f2f5ef';font(52);ctx.fillText(shareHeading(share),64,152);
  ctx.fillStyle='#a9b9b5';font(24);ctx.fillText(share.label,64,207);
  drawRadar(ctx,share.dimensions,540,520,200,265);
  let y=875;
  for(const [code,item] of rows) {
    ctx.fillStyle='#d5e1db';font(26);ctx.fillText(`${item.name} / ${displayCode(code)}`,64,y);
    ctx.textAlign='right';ctx.fillText(number(item.value),1016,y);ctx.textAlign='left';
    ctx.fillStyle='#243337';ctx.fillRect(64,y+20,952,10);
    if(item.value!=null) {ctx.fillStyle='#9cddc8';ctx.fillRect(64,y+20,952*item.value/100,10);}
    else {ctx.fillStyle='#a9b9b5';font(20);ctx.fillText(reasonText[item.reason]||'无法估计',64,y+58);}
    y+=100;
  }
  ctx.fillStyle='#a9b9b5';font(20);
  for(const lines of groupLines) {
    for(const line of lines) {ctx.fillText(line,64,y);y+=30;}
    y+=15;
  }
  const note='观察证据的参考位置，不是喜欢概率或现实人格。低位不表示不喜欢。';
  for(const line of wrapText(ctx,note,952)) {ctx.fillText(line,64,y);y+=30;}
  font(16);ctx.fillText(`模型 ${share.versions.model} · ${share.report_sha256.slice(0,16)}`,64,y+28);
  canvas.dataset.reportHash=share.report_sha256;
  canvas.dataset.values=JSON.stringify(Object.fromEntries(rows.map(([k,v])=>[k,number(v.value)])));
  return canvas;
}

export async function downloadShare(share,canvas) {
  // An export in progress must not repaint a newer selected report's preview.
  const output=document.createElement('canvas');
  await renderShare(share,output);
  const blob=await new Promise((resolve,reject)=>output.toBlob(b=>b?resolve(b):reject(new Error('图片生成失败')),'image/png'));
  const url=URL.createObjectURL(blob), link=document.createElement('a');
  link.href=url;link.download=`gamepersona-${share.report_sha256.slice(0,12)}.png`;link.click();
  setTimeout(()=>URL.revokeObjectURL(url),10000);
}
import {drawRadar,dimensionOrder} from './radar.js';
