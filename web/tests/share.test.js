import test from 'node:test';
import assert from 'node:assert/strict';
import {renderShare,number,wrapText,shareHeading} from '../src/share.js';
import {radarGeometry,dimensionOrder} from '../src/radar.js';
import {displayCode,displayType} from '../src/dimensions.js';

test('PNG consumes nullable fixed values, waits for font and reserves wrapped lines',async()=>{
  const texts=[],rects=[];let fontReady=false;
  globalThis.document={fonts:{load:async()=>{fontReady=true;},ready:Promise.resolve()}};
  const ctx={beginPath(){},lineTo(){},moveTo(){},closePath(){},stroke(){},fill(){},arc(){},
             measureText:text=>({width:text.length*20}),fillRect:(...args)=>rects.push(args),
             fillText:(text,x,y)=>{assert.ok(fontReady);texts.push({text,x,y});}};
  const canvas={getContext:()=>ctx,dataset:{}};
  const share={type:null,label:'评论样本参考分位 · 实验性',report_sha256:'f'.repeat(64),versions:{model:'fixture'},
               dimensions:{P:{name:'规划',value:null,reason:'insufficient_reference'},R:{name:'反应',value:0,reason:null},
                           G:{name:'引导',value:88.125,reason:null}},groups:[{text:'较长中文组合解释。'.repeat(20)}]};
  await renderShare(share,canvas);
  assert.deepEqual(JSON.parse(canvas.dataset.values),{P:'—',R:'0.0',G:'88.1'});
  assert.equal(canvas.dataset.reportHash,share.report_sha256);
  assert.ok(texts.some(t=>t.text==='参考样本不足'));
  assert.ok(texts.some(t=>t.text==='规划 / PLAN'));
  assert.ok(texts.some(t=>t.text==='引导 / GUIDE'));
  assert.ok(texts.some(t=>t.text==='反应 REACT'));
  assert.ok(!texts.some(t=>t.text==='规划 / P'));
  assert.ok(texts.every(t=>t.y<canvas.height));
  assert.ok(texts.filter(t=>t.text.includes('较长中文')).length>1);
  assert.equal(rects.filter(r=>r[3]===10).length,5); // Three tracks, only two known fills.
  assert.equal(number(null),'—');assert.equal(number(0),'0.0');
});

test('radar keeps zero at center and unknown absent without bridging missing axes',()=>{
  const data=Object.fromEntries(dimensionOrder.map(k=>[k,{name:k,value:50}]));
  data.P.value=0;data.R.value=null;
  const g=radarGeometry(data);
  assert.equal(g.complete,false);
  assert.deepEqual(g.axes[0].point,{x:320,y:260});
  assert.equal(g.axes.find(a=>a.code==='R').point,null);
  assert.equal(g.segments.length,10);
  data.R.value=100;
  const full=radarGeometry(data);
  assert.equal(full.complete,true);
  assert.equal(full.segments.length,12);
  assert.deepEqual(full.axes.map(a=>a.code),dimensionOrder);
});

test('unbroken Chinese text wraps without dropping characters',()=>{
  const input='长中文标签与说明'.repeat(30);
  const lines=wrapText({measureText:t=>({width:t.length*20})},input,100);
  assert.equal(lines.join(''),input);
  assert.ok(lines.every(l=>l.length<=5));
});

test('entirely unavailable profiles say pending rather than mixed',()=>{
  assert.equal(shareHeading({type:null,groups:[{tendency:'pending'}]}),'数据不足 · 画像待定');
  assert.equal(shareHeading({type:null,groups:[{tendency:'pending'},{tendency:'mixed'}]}),'部分方向待定 · 类型缺省');
  assert.equal(shareHeading({type:null,groups:[{tendency:'mixed'}]}),'混合倾向 · 类型缺省');
});

test('fixed internal codes display readable abbreviations in type summaries',()=>{
  assert.equal(displayCode('M'),'MECH');
  assert.equal(displayType('RGMH'),'REACT · GUIDE · MECH · HARD');
  assert.equal(shareHeading({type:'PONC'}),'PLAN · OPEN · NARR · CALM');
  assert.equal(displayType(null),null);
});

test('a superseded font-loading preview does not repaint the current report',async()=>{
  globalThis.document={fonts:{load:async()=>{},ready:Promise.resolve()}};
  const share={type:null,label:'fixture',dimensions:{},groups:[]};
  const canvas={getContext(){throw new Error('Superseded preview must not draw');}};
  assert.equal(await renderShare(share,canvas,()=>false),null);
});
