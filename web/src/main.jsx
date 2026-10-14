import React,{useState,useEffect,useRef} from 'react';
import {createRoot} from 'react-dom/client';
import '@fontsource/noto-sans-sc/400.css';
import './style.css';
import {number,reasonText,renderShare,downloadShare} from './share';
import Radar from './Radar.jsx';
import {dimensionNames as names,displayCode,displayType} from './dimensions.js';

const pairs=[['P','R'],['G','O'],['M','N'],['H','C'],['SOLO','SOCIAL'],['COMP','COOP']];
const readReasons={insufficient_response:'登录成功，但游戏记录暂不可读取。请检查 Steam 游戏详情的可见性，再重新读取。',timeout:'读取超时，请稍后重试。',rate_limited:'Steam 暂时限制请求，请稍后重试。',credential_or_access_error:'数据访问受限，请检查服务器配置与游戏详情可见性。',assessment_failed:'计算未完成，报告没有被更改。请重试或检查服务日志。'};
const exclusions={zero_duration:'零时长',all_zero_feature:'标签未提供计分支持',unknown_feature:'标签不可用',unmatched_feature:'暂无游戏特征',conflicting_user_game:'重复记录冲突',duration_unknown_or_invalid:'时长缺失或异常',duration_unknown:'时长未知',duration_non_finite:'时长异常',duration_negative:'负时长',duration_invalid_type:'时长格式异常',invalid_app_id:'游戏标识无效'};

function App() {
  const [session,setSession]=useState(null),[report,setReport]=useState(null),[history,setHistory]=useState([]);
  const [task,setTask]=useState(null),[message,setMessage]=useState(''),[share,setShare]=useState(null),[busy,setBusy]=useState(false);
  const canvas=useRef(null);
  const openSequence=useRef(0),authGeneration=useRef(0);
  const anyScore=report&&Object.values(report.percentiles).some(p=>p.value!=null);
  const reportTitle=displayType(report?.interpretation.type)|| (anyScore?'你的多面游戏画像':report?.score.unknown_duration_games>0?'时长信息不足，画像待定':report?.score.known_positive_hours===0?'暂无正向游玩记录':'有效记录不足，画像待定');
  async function api(path,options={}) {
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{...options.headers,...(options.method?{'X-CSRF-Token':session?.csrf}: {})}});
    const payload=await response.json();if(!response.ok) throw new Error(payload.detail||'请求失败');return payload;
  }
  async function refreshHistory(){const generation=authGeneration.current,h=await api('/api/reports');if(generation!==authGeneration.current)return [];setHistory(h);return h;}
  async function openReport(id){const sequence=++openSequence.current,generation=authGeneration.current;const [r,s]=await Promise.all([api(`/api/reports/${id}`),api(`/api/reports/${id}/share`)]);if(sequence!==openSequence.current||generation!==authGeneration.current)return;setReport(r);setShare(s);}
  useEffect(()=>{fetch('/api/session').then(r=>r.json()).then(async s=>{setSession(s);if(s.authenticated){const h=await refreshHistory();if(h.length)await openReport(h[0].id);}}).catch(e=>setMessage(e.message));
    if(new URLSearchParams(location.search).has('login'))setMessage('Steam 登录未完成。你可以重新登录。');},[]);
  useEffect(()=>{if(!task)return;let cancelled=false;
    async function poll(){try{const t=await api(`/api/tasks/${task}`);if(cancelled)return;
      if(t.state==='succeeded'){await refreshHistory();await openReport(t.report_id);setTask(null);setBusy(false);setMessage('报告已保存，分享图片沿用同一结果。');}
      else if(t.state==='failed'){setTask(null);setBusy(false);setMessage(readReasons[t.error_code]||'暂时无法读取，请重试。');}
    }catch(e){if(!cancelled){setTask(null);setBusy(false);setMessage(e.message);}}}
    poll();const timer=setInterval(poll,1500);return()=>{cancelled=true;clearInterval(timer);};},[task]);
  useEffect(()=>{let active=true;if(share&&canvas.current)renderShare(share,canvas.current,()=>active).catch(e=>{if(active)setMessage(e.message);});return()=>{active=false;};},[share]);
  async function assess(){setBusy(true);setMessage('正在读取可见游戏记录…');try{const result=await api('/api/assessments',{method:'POST'});setTask(result.task_id);}catch(e){setBusy(false);setMessage(e.message);}}
  async function leave(remove){if(remove&&!confirm('删除网站保存的身份关联、全部会话、输入和报告？已下载图片及旧 CLI 快照需要单独删除。'))return;
    try{await api(remove?'/api/account':'/api/logout',{method:remove?'DELETE':'POST'});authGeneration.current++;openSequence.current++;setSession({authenticated:false});setReport(null);setHistory([]);setShare(null);setTask(null);setBusy(false);setMessage(remove?'网站个人记录已删除。':'已退出。');}catch(e){setMessage(e.message);}}
  return <><header><a href="/" className="brand"><span className="brand-mark">G</span> GAMEPERSONA</a><span className="header-note">由真实游玩记录出发</span>{session?.authenticated&&<button className="quiet" onClick={()=>leave(false)}>退出</button>}</header>
  <main><section className="hero"><div><div className="eyebrow">PLAY RECORDS, PERSONAL PATTERNS</div><h1>游玩之间，<br/>看见你的偏好。</h1><p>十二个方向，六组观察。从你在游戏里投入的时间，理解自己选择怎样的体验。</p><div className="actions">{session?.authenticated?<button disabled={busy} onClick={assess}>{busy?'读取与计算中…':report?'重新读取，生成新报告':'读取游戏，生成画像'}</button>:<a className="button" href="/auth/steam">通过 Steam 登录 <span>↗</span></a>}<span className="pill">实验性测评</span></div></div><aside className="hero-aside"><span>01 / 偏好是一张地图</span><div className="orbit"><i/><i/><i/><b>12</b></div><p>连续评分优先<br/>类型是可选摘要</p></aside></section>
  <div className="notice">我们读取可见的 AppID、游戏名称和累计游玩时长；Steam 官方完成登录，本站不收集密码。个人记录在本机保存到主动删除，不默认用于研究。分位参照评论样本，不能视为全体玩家排名或喜欢概率。</div>
  {message&&<div className="message" role="status">{message}</div>}
  {report?<><section className="report-heading"><div><span className="eyebrow">YOUR PLAY PROFILE</span><h2>{reportTitle}</h2><p>{report.label} · {report.interpretation.type?'缩写组合为实验性摘要':'存在混合或待定组，完整类型缺省。'}</p></div><span className="pill">固定报告 · {report.report_sha256.slice(0,8)}</span></section>
    <Radar dimensions={Object.fromEntries(Object.entries(report.percentiles).map(([k,v])=>[k,{...v,name:names[k]}]))}/>
    <div className="grid">{pairs.map(([a,b],index)=><section className="pair-card" key={a}><div className="card-top"><span>0{index+1}</span><span>{names[a]} / {names[b]}</span></div>{[a,b].map(k=><div className="dimension" key={k}><div><span>{names[k]} <small>{displayCode(k)}</small></span><strong data-dimension={k}>{number(report.percentiles[k].value)}</strong></div>{report.percentiles[k].value==null?<div className="missing">{reasonText[report.percentiles[k].reason]||'无法估计'}</div>:<meter min="0" max="100" low="0" high="100" optimum="100" value={report.percentiles[k].value}/>} {report.percentiles[k].zero_evidence&&<small>暂无该维标签支持证据，不表示不喜欢。</small>}</div>)}<p>{report.interpretation.groups[index].text}</p></section>)}</div>
    <section className="coverage"><div><strong>{report.score.N}</strong><span>纳入游戏数</span></div><div><strong>{report.score.H.toFixed(1)} <small>h</small></strong><span>有效记录时长</span></div><div><strong>{report.score.coverage==null?'—':(report.score.coverage*100).toFixed(1)+'%'}</strong><span>已知正时长覆盖</span></div><div><strong>{report.score.observed_games-report.score.N}</strong><span>未纳入记录</span></div></section>
    <section className="share-section"><div><span className="eyebrow">TAKE YOUR PROFILE WITH YOU</span><h2>让画像成为一张卡片。</h2><p>只分享十二维摘要、组合状态与实验性标记。图片不包含身份、头像或游戏明细。</p><button onClick={()=>downloadShare(share,canvas.current).catch(e=>setMessage(e.message))}>下载 PNG 图片 ↓</button><p className="small">图片沿用当前固定报告，不重新计算。</p></div><canvas ref={canvas} className="share-canvas" aria-label="分享卡预览"/></section>
    <details><summary>贡献游戏与规则依据</summary>{Object.keys(names).map(k=><div className="contributions" key={k}><h3>{names[k]} / {displayCode(k)}</h3>{[...report.score.contributions].sort((a,b)=>b.ticks[k]-a.ticks[k]||a.app_id-b.app_id).filter(g=>g.ticks[k]>0).slice(0,3).map(g=><p key={g.app_id}><a href={`https://store.steampowered.com/app/${g.app_id}/`} target="_blank" rel="noreferrer">{report.game_names?.[g.app_id]||`AppID ${g.app_id}`}</a> · {g.hours.toFixed(1)} 小时 · 标签支持 {g.values[k]} · 证据贡献 {g.evidence[k].toFixed(3)}<br/><small>{(g.matches[k]||[]).map(m=>`${m.tag}：${m.reason}`).join('；')}</small></p>)}</div>)}</details>
    <details><summary>数据范围、排除项与版本</summary><p>读取时间：{report.collection?.collected_at?new Date(report.collection.collected_at).toLocaleString(): '见输入快照记录'}。未知时长：{report.score.unknown_duration_games} 款。</p>{report.score.W!=null&&<p>分位与累计游玩投入相近的评论样本比较；游戏数用于判断记录是否充分。</p>}{report.collection?.recomputed_at&&<p>本报告沿用已保存的游戏记录，于 {new Date(report.collection.recomputed_at).toLocaleString()} 按新模型重新计算。</p>}<p>排除：{Object.entries(report.score.exclusion_counts).map(([k,v])=>`${exclusions[k]||'来源数据不可用'} ${v} 款`).join('；')||'无'}</p><p>{report.limitations.join(' ')}</p><pre>{JSON.stringify(report.versions,null,2)}</pre></details>
  </>:<section className="empty-state"><span>一份可解释的画像，从一次真实读取开始。</span><div className="three"><div><b>01</b><h3>验证身份</h3><p>在 Steam 官方页面登录。</p></div><div><b>02</b><h3>累计证据</h3><p>已知时长与固定标签规则共同计算。</p></div><div><b>03</b><h3>保留多面</h3><p>未知留空，混合倾向也能分享。</p></div></div></section>}
  {session?.authenticated&&<section className="account-area"><h3>我的报告</h3>{history.map(h=><button className="history" key={h.id} onClick={()=>openReport(h.id).catch(e=>setMessage(e.message))}>{new Date(h.created_at).toLocaleString()} · {h.report_sha256.slice(0,8)}</button>)}<button className="danger quiet" onClick={()=>leave(true)}>删除网站个人记录</button><p className="small">删除覆盖网站身份关联、所有会话、任务、输入与报告；浏览器下载 PNG、旧 CLI 快照不在范围内。</p></section>}
  </main><footer><span>GAMEPERSONA</span><span>游戏偏好与行为观察 · 不是现实人格测试</span></footer></>;
}
createRoot(document.getElementById('root')).render(<App/>);
