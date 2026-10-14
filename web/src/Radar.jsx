import React from 'react';
import {radarGeometry} from './radar';
import {displayCode} from './dimensions.js';

const points=values=>values.map(p=>`${p.x},${p.y}`).join(' ');
export default function Radar({dimensions}) {
  const chart=radarGeometry(dimensions);
  return <section className="radar-panel"><div className="card-top"><span>十二维偏好地图</span><span>参考分位 / 0—100</span></div>
    <svg viewBox="0 0 640 520" className="radar" role="img" aria-label="十二维雷达图，未知维度留空，零分与未知分开">
      <title>十二维评论样本参考分位雷达图</title>
      {chart.rings.map(r=><g key={r.level}><polygon className="radar-ring" points={points(r.points)}/><text x="326" y={260-180*r.level/100-4} className="radar-scale">{r.level}</text></g>)}
      {chart.axes.map(a=><line key={a.code} className="radar-axis" x1="320" y1="260" x2={a.end.x} y2={a.end.y}/>)}
      {chart.complete?<polygon className="radar-shape" points={points(chart.axes.map(a=>a.point))}/>:chart.segments.map((s,i)=><line key={i} className="radar-segment" x1={s[0].x} y1={s[0].y} x2={s[1].x} y2={s[1].y}/>)}
      {chart.axes.map(a=><g key={a.code}>{a.point&&<circle className="radar-dot" cx={a.point.x} cy={a.point.y} r="3.5"/>}<text className={a.value==null?'radar-label missing-label':'radar-label'} x={a.label.x} y={a.label.y} textAnchor={Math.abs(a.label.x-320)<2?'middle':a.label.x>320?'start':'end'}>{a.name} {displayCode(a.code)}<tspan x={a.label.x} dy="19" className="radar-value">{a.value==null?'—':a.value.toFixed(1)}</tspan></text></g>)}
    </svg><p className="small">各维独立计分；面积不表示能力或准确率。不可估计项留空，缺失区间不填充。</p>
  </section>;
}
