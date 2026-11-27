// The coldmap research app (served by coldmap/interfaces/launch.py). No inline scripts:
// the page's Content-Security-Policy only runs scripts served by coldmap itself.
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf=new Intl.NumberFormat();
const pct=x=>x==null?'—':Math.round(x*100)+'%';
const yrs=(a,b)=>a===b?String(a):a+'–'+b;
const day=iso=>iso?new Date(iso).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'}):'';
const clock=s=>{s=Math.round(s);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
const mb=n=>n==null?'':n>=1e7?Math.round(n/1e6)+' MB':(n/1e6).toFixed(1)+' MB';
const slug=s=>String(s).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
const who=s=>s==='Female'?'women':s==='Male'?'men':'victims';
const gapOf=f=>f.expected==null||!f.total?null:Math.round((f.solved/f.total-f.expected)*100);
const gapTxt=g=>g==null?'—':(g<0?'−':'+')+Math.abs(g);
const ICON={check:'<svg viewBox="0 0 12 12"><path d="M2.5 6.4l2.3 2.3 4.7-5"/></svg>',x:'<svg viewBox="0 0 12 12"><path d="M3.5 3.5l5 5m0-5l-5 5"/></svg>',
 keep:'<svg viewBox="0 0 16 16"><path d="M4 2h8v12l-4-2.8L4 14z"/></svg>',out:'<svg viewBox="0 0 16 16"><path d="M9 2.5h4.5V7M13.5 2.5L7 9M11 9.5v4H2.5V5h4"/></svg>'};
const CONF={high:'High',strong:'Strong',possible:'Possible'};
const STATUS={kept:'To review',reviewed:'Reviewed',sent:'Sent to MAP',dismissed:'Dismissed'};

const S={st:null,flags:null,meta:null,dec:{},detail:{},sel:null,limit:200,places:{},pl:null,ai:null,methods:null,guide:null,toast:null,
 f:{state:'',county:'',sex:'Female',conf:'strong',kind:'all',q:'',sort:'strength',show:'open'}};
const q0=new URLSearchParams(location.search);
if(q0.get('state'))S.f.state=q0.get('state');
const wantDownload=q0.get('download');
const wantMapFlag=q0.get('flag');
const wantModel=q0.get('m');
if(q0.toString())history.replaceState(null,'',location.pathname==='/'?'/flags':location.pathname);

// ---- data ------------------------------------------------------------------------------------
async function api(path){const r=await fetch(path,{cache:'no-store'});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||'Something went wrong.');return j}
async function post(path,body){
 const r=await fetch(path,{method:'POST',headers:{'X-Coldmap':'1','Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 const j=await r.json().catch(()=>({error:'coldmap stopped responding. Is its terminal window still open?'}));
 if(!r.ok)throw new Error(j.error||'Something went wrong.');return j;
}
function toast(t){S.toast=t;const el=document.createElement('div');el.className='toast';el.textContent=t;el.setAttribute('role','status');document.body.append(el);setTimeout(()=>el.remove(),1800)}
let timer=null;
async function poll(){
 clearTimeout(timer);
 try{S.st=await api('/api/status');S.err=null}catch(e){S.err="Can't reach coldmap. Run coldmap open in a terminal, then reload."}
 const st=S.st,job=st&&st.job;
 if(st&&st.national&&(!S.meta||S.meta.generated!==st.national.generated)){await loadFlags()}
 if(job&&!job.running&&S.lastJob===job.id+':run'){S.lastJob=job.id;if(!job.error)toast(job.title.replace(/^(Preparing|Scanning|Getting|Updating)/,m=>({Preparing:'Prepared',Scanning:'Scanned',Getting:'Got',Updating:'Updated'})[m])+' — done')}
 if(job&&job.running)S.lastJob=job.id+':run';
 if(job&&job.kind==='benchmark'&&!job.running&&S.benchWatch){S.benchWatch=0;S.bench=null}
 if(job&&['cities','cities-get'].includes(job.kind)&&!job.running&&S.cityWatch){S.cityWatch=0;S.cities=null;S.cgrid={}}
 if(wantDownload&&st&&!S.didDl&&st.mode==='map'&&!(job&&job.running)){S.didDl=1;try{await post('/api/download'+(wantDownload==='refresh'?'?refresh=1':''))}catch(e){}}
 render();
 timer=setTimeout(poll,S.err?3000:job&&job.running?600:15000);
}
async function loadFlags(){
 const j=await api('/api/flags');S.flags=j.flags;S.meta=j.meta;S.dec=await api('/api/decisions');
}
async function refreshDecisions(){S.dec=await api('/api/decisions');}

// ---- routing ---------------------------------------------------------------------------------
function route(){const p=location.pathname.replace(/\/+$/,'')||'/flags';const parts=p.split('/').filter(Boolean).map(decodeURIComponent);return {sec:parts[0]||'flags',a:parts[1],b:parts[2]}}
function go(href){history.pushState(null,'',href);render();$('main').querySelector('.view')?.scrollTo?.(0,0)}
addEventListener('popstate',render);

// ---- shared pieces ---------------------------------------------------------------------------
function jobView(job){
 const steps=job.steps.map(s=>{
  let extra='';
  const meter=(d,t,label)=>`<div class="meter" role="progressbar" aria-label="${esc(s.label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(d/t*100)}"><i style="width:${(d/t*100).toFixed(1)}%"></i></div><span class="muted num" style="font-size:12px">${label}</span>`;
  if(s.state==='active'&&job.bytes&&job.bytes[1])extra=meter(job.bytes[0],job.bytes[1],`${mb(job.bytes[0])} of ${mb(job.bytes[1])}`);
  else if(s.state==='active'&&job.count&&job.count[1])extra=meter(job.count[0],job.count[1],`${nf.format(job.count[0])} of ${nf.format(job.count[1])}`);
  return `<li data-state="${s.state}"><span class="ind">${s.state==='done'?ICON.check:s.state==='error'?ICON.x:''}</span><span>${esc(s.label)}${extra}</span></li>`;
 }).join('');
 return `<div><div class="row" style="margin-bottom:6px"><b>${esc(job.title)}</b><span class="muted num">${job.running?'':'took '}${clock(job.elapsed)}</span></div><ol class="checks">${steps}</ol>
  ${job.notes.map(n=>`<p class="msg warn" style="margin-top:10px">${esc(n)}</p>`).join('')}
  ${job.error?`<p class="msg err" role="alert" style="margin-top:10px"><b>That didn't work.</b> ${esc(job.error)}</p>`:''}</div>`;
}
function bar(f){return f.expected==null?'':`<span class="bar" aria-hidden="true"><i style="width:${(f.solved/f.total*100).toFixed(1)}%"></i><b style="left:${(f.expected*100).toFixed(1)}%"></b></span>`}
function status(id){const d=S.dec[id];return d?d.status:null}
function renderStatus(){
 const st=S.st;if(!st)return;
 const job=st.job&&st.job.running?st.job:null,n=st.national,c=st.data.files[0];
 const kept=(st.decisions.kept||0)+(st.decisions.reviewed||0)+(st.decisions.sent||0);
 const extra=st.plugins.enrichers.filter(x=>!['county','kind','coverage','namus'].includes(x)).concat(st.plugins.detectors.filter(x=>!['scan','window','map'].includes(x)));
 $('status').innerHTML=[
  `<span>${st.mode==='map'?(c.present?'MAP data '+esc(day(c.downloaded)||''):'no data yet'):st.mode==='sample'?'synthetic sample':'your files'}</span>`,
  n?`<span><b>${nf.format(n.findings)}</b> flags · ${n.states} states${n.stale?' · <span style="color:var(--amber)">out of date</span>':''}</span>`:'',
  `<span>models: ${esc(st.plugins.detectors.join(', '))}${extra.length?' + '+esc(extra.join(', ')):''}</span>`,
  kept?`<span>shortlist <b>${kept}</b></span>`:'',
  job?`<span><span class="spin"></span> ${esc(job.title)} ${clock(job.elapsed)}</span>`:'',
  `<span class="live">local only · nothing is uploaded</span>`].join('');
 $('ctFlags').textContent=S.flags?nf.format(S.flags.filter(f=>(S.f.sex==='all'||f.sex===S.f.sex)&&f.confidence!=='possible').length):'';
 $('ctShort').textContent=kept||'';$('ctShort').classList.toggle('on',!!st.decisions.kept);
 $('ctModels').textContent=st.plugins.files?'+'+st.plugins.files:'';
 $('ctData').textContent=n&&n.stale?'update':st.datasets?'+'+st.datasets:'';
}

// ---- render ----------------------------------------------------------------------------------
function render(){
 const r=route();
 document.querySelectorAll('.nav').forEach(a=>{if(a.dataset.sec===r.sec)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 const t=document.documentElement.dataset.theme||'light';document.querySelectorAll('[data-theme-set]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.themeSet===t));
 renderStatus();renderViewNav(r);
 const st=S.st;
 if(!st){$('main').innerHTML=`<div class="view"><div class="page"><p class="${S.err?'msg err':'muted'}">${esc(S.err||'Opening coldmap…')}</p></div></div>`;return}
 const research=['flags','shortlist','places','map','x'].includes(r.sec);
 if(research&&!st.national)return renderGate();
 ({flags:renderFlags,map:renderMap,x:renderViewPage,shortlist:renderShortlist,places:renderPlaces,cities:renderCities,models:renderModels,ai:renderAI,methods:renderMethods,data:renderData}[r.sec]||renderFlags)(r);
 document.title=({flags:'Flags',map:'Map',shortlist:'Shortlist',places:'Places',cities:'Cities',models:'Models',ai:'AI assistants',methods:'Methods',data:'Data'}[r.sec]||'coldmap')+' · coldmap';
}
function setMain(key,html){const m=$('main');if(m.dataset.key!==key){m.dataset.key=key;m.innerHTML=html;return true}return false}

// ---- setup gate ------------------------------------------------------------------------------
function renderGate(){
 const st=S.st,job=st.job,run=job&&job.running&&['setup','national','download'].includes(job.kind);
 const intro=`<h1>Set up coldmap</h1>
  <p class="lede">coldmap looks through public homicide records for places where similar killings went unsolved far more often than they should, and helps you check each one before it goes to the people who can act on it.</p>
  <div class="how">
   <div><b>The data</b><span>Homicides police reported to the FBI since 1976, and whether they identified who did it, published by the Murder Accountability Project (MAP).</span></div>
   <div><b>What you get</b><span>A ranked list of flags: a place, a method and a period where killings were solved far less often than expected.</span></div>
   <div><b>What you do</b><span>Read why each was flagged, look at the cases and the data's known problems, keep the ones worth pursuing, and have a second person review them.</span></div>
   <div><b>Where it goes</b><span>Reviewed leads go to MAP or the investigating agency. A flag is a pattern worth review, never evidence that cases are linked.</span></div>
  </div>`;
 let body;
 if(run)body=`<div class="box">${jobView(job)}<p class="muted" style="margin:12px 0 0">The download takes a minute or two; scanning every state about 5 minutes. You can read <a href="/methods" data-nav>Methods</a> meanwhile.</p></div>`;
 else{
  const need=st.mode==='map'&&!st.data.ready;
  const err=job&&job.error&&['setup','national'].includes(job.kind)?`<div class="box">${jobView(job)}</div>`:'';
  body=`${err}<div class="box"><h2>${need?'Download the data and scan every state':'Scan every state'}</h2>
   <p class="muted">${need?`About 365 MB from MAP, saved in <code>${esc(st.home)}</code>, then about 5 minutes to scan. You do this once; afterwards coldmap opens straight to your flags.`:'About 5 minutes. You do this once, and again only when the data or your models change.'}</p>
   <div class="row"><button class="btn primary" id="doSetup"${job&&job.running?' disabled':''}>${need?'Start setup':'Scan every state'}</button>${job&&job.running?`<span class="muted">Waiting for: ${esc(job.title)}</span>`:''}</div></div>`;
 }
 setMain('gate:'+(run?job.id:'idle')+(job&&job.error?':e':''),`<div class="view"><div class="gate">${intro}<div id="gateBody"></div></div></div>`);
 $('gateBody').innerHTML=body;
}

// ---- flags -----------------------------------------------------------------------------------
function filtered(){
 const f=S.f,ql=f.q.trim().toLowerCase();
 let rows=S.flags.filter(r=>(f.sex==='all'||r.sex===f.sex)&&(f.conf==='all'||(f.conf==='high'?r.confidence==='high':r.confidence!=='possible'))
  &&(f.kind==='all'||r.kind===f.kind)&&(!f.state||r.state===f.state)&&(!f.county||(r.counties||[r.county]).includes(f.county))
  &&(!ql||(r.place+' '+r.state+' '+r.weapon+' '+(r.county||'')).toLowerCase().includes(ql)));
 const stt=r=>status(r.id);
 if(f.show==='open')rows=rows.filter(r=>stt(r)!=='dismissed');
 else if(f.show==='kept')rows=rows.filter(r=>['kept','reviewed','sent'].includes(stt(r)));
 else if(f.show==='dismissed')rows=rows.filter(r=>stt(r)==='dismissed');
 else if(f.show==='unexplained')rows=rows.filter(r=>stt(r)!=='dismissed'&&r.ruleout!=='explains');
 else if(f.show==='new')rows=rows.filter(r=>r.history&&r.history.status==='new');
 else if(f.show==='growing')rows=rows.filter(r=>r.history&&r.history.trend==='growing');
 const by={strength:null,gap:(a,b)=>(gapOf(a)??0)-(gapOf(b)??0),unsolved:(a,b)=>(b.total-b.solved)-(a.total-a.solved),recent:(a,b)=>b.end-a.end};
 if(by[f.sort])rows=[...rows].sort(by[f.sort]);
 return rows;
}
function renderFlags(r){
 const f=S.f;
 if(!S.flags){setMain('loading',`<div class="view"><div class="page"><span class="spin"></span> Loading flags…</div></div>`);return}
 const states=[...new Set(S.flags.map(x=>x.state).filter(Boolean))].sort();
 const counties=f.state?[...new Set(S.flags.filter(x=>x.state===f.state).flatMap(x=>x.counties||[x.county]).filter(Boolean))].sort():[];
 const seg=(k,o)=>`<div class="seg" role="group">${o.map(([v,l])=>`<button data-f="${k}" data-v="${v}" aria-pressed="${f[k]===v}">${l}</button>`).join('')}</div>`;
 const fresh=setMain('flags',`<div class="toolbar" id="tb"></div><div id="banner"></div><div class="split" id="split"><div class="list" id="list" tabindex="-1"></div><div class="flag" id="flagPane"></div></div>`);
 const tb=`<h1>Flags</h1>
  <select class="sel" id="fState" aria-label="State"><option value="">All states</option>${states.map(s=>`<option${s===f.state?' selected':''}>${esc(s)}</option>`).join('')}</select>
  ${f.state?`<select class="sel" id="fCounty" aria-label="County"><option value="">All counties</option>${counties.map(c=>`<option${c===f.county?' selected':''}>${esc(c)}</option>`).join('')}</select>`:''}
  ${seg('sex',[['Female','Women'],['Male','Men'],['all','Both']])}
  ${seg('conf',[['high','High'],['strong','High + strong'],['all','All']])}
  <select class="sel" id="fKind" aria-label="Kind"><option value="all">Any kind</option><option value="serial-pattern"${f.kind==='serial-pattern'?' selected':''}>Serial-pattern</option><option value="accountability"${f.kind==='accountability'?' selected':''}>Accountability</option></select>
  <select class="sel" id="fShow" aria-label="Show"><option value="open"${f.show==='open'?' selected':''}>Not dismissed</option><option value="kept"${f.show==='kept'?' selected':''}>Kept only</option><option value="unexplained"${f.show==='unexplained'?' selected':''}>Not explained by a known series</option><option value="new"${f.show==='new'?' selected':''}>New since the last scan</option><option value="growing"${f.show==='growing'?' selected':''}>Growing since the last scan</option><option value="dismissed"${f.show==='dismissed'?' selected':''}>Dismissed</option><option value="all"${f.show==='all'?' selected':''}>Everything</option></select>
  <input class="inp" id="fQ" type="search" placeholder="Search place or method  /" aria-label="Search flags" value="${esc(f.q)}" style="width:210px">
  <select class="sel" id="fSort" aria-label="Sort"><option value="strength">Strongest first</option><option value="gap"${f.sort==='gap'?' selected':''}>Largest gap</option><option value="unsolved"${f.sort==='unsolved'?' selected':''}>Most unsolved</option><option value="recent"${f.sort==='recent'?' selected':''}>Most recent</option></select>`;
 const keep=document.activeElement&&document.activeElement.id==='fQ',caret=keep?document.activeElement.selectionStart:0;
 if($('tb')._h!==tb){$('tb').innerHTML=tb;$('tb')._h=tb;if(keep){$('fQ').focus();$('fQ').setSelectionRange(caret,caret)}}
 $('banner').innerHTML=S.meta&&S.meta.stale?`<div style="padding:8px 16px;border-bottom:1px solid var(--line);background:color-mix(in oklab,var(--amber) 9%,var(--surf));font-size:13px" class="row">Your models or data changed since this list was made (${esc(day(S.meta.generated))}). <button class="btn" id="rescan"${S.st.job&&S.st.job.running?' disabled':''}>Re-scan every state</button><span class="muted">about 5 minutes</span></div>`:'';
 const rows=filtered();
 if(r.a)S.sel=r.a;
 $('split').classList.toggle('open',!!r.a);
 const list=`<div class="lhead"><span>Conf.</span><span>Place · method · years</span><span>Solved</span><span>Gap pts</span><span>Unsolved</span></div>`+
  (rows.slice(0,S.limit).map(x=>{const g=gapOf(x),s=status(x.id);
   return `<button class="frow ${s||''}" data-id="${x.id}" aria-selected="${S.sel===x.id}" role="option">
    <span class="tag ${x.confidence}">${CONF[x.confidence]}</span>
    <span class="pl"><b>${esc(x.place)}${x.state&&x.level!=='region'?'':''}</b><span>${esc(x.state||'')} · ${esc(String(x.weapon).toLowerCase())} · ${who(x.sex)} · ${yrs(x.start,x.end)}${s?` · <span class="tag ${s}" style="font-size:9.5px">${STATUS[s]}</span>`:''}${x.ruleout==='explains'?' · <span class="tag" style="font-size:9.5px" title="A known series that went through the courts may explain this flag">known series</span>':''}${x.history&&x.history.status==='new'?' · <span class="tag kept" style="font-size:9.5px" title="Not in the last scan">new</span>':''}${x.history&&x.history.trend==='growing'?` · <span class="tag high" style="font-size:9.5px" title="${x.history.delta_unsolved} more unsolved than in the last scan">growing</span>`:''}</span></span>
    <span class="r rt">${pct(x.solved/x.total)}<span class="muted"> / ${pct(x.expected)}</span>${bar(x)}</span>
    <span class="r gp${g>0?' up':''}">${gapTxt(g)}</span>
    <span class="r un">${nf.format(x.total-x.solved)}</span></button>`}).join('')||`<div class="empty">No flags match. Widen the filters, or pick another state.</div>`)+
  (rows.length>S.limit?`<div class="more"><button class="btn" id="more">Show ${Math.min(200,rows.length-S.limit)} more of ${nf.format(rows.length)}</button></div>`:'')+
  `<div class="lfoot">${nf.format(rows.length)} flags · <kbd>↑</kbd> <kbd>↓</kbd> move · <kbd>s</kbd> keep · <kbd>x</kbd> dismiss · <kbd>/</kbd> search</div>`;
 if($('list')._h!==list){const sc=$('list').scrollTop;$('list').innerHTML=list;$('list')._h=list;if(!fresh)$('list').scrollTop=sc}
 if(fresh&&S.sel){const b=document.querySelector(`.frow[data-id="${S.sel}"]`);b&&b.scrollIntoView({block:'center'})}
 renderFlag(S.sel);
}
function selectFlag(id,{push=true,scroll=false}={}){
 S.sel=id;if(push)history.pushState(null,'','/flags/'+id);render();
 if(scroll){const b=document.querySelector(`.frow[data-id="${id}"]`);b&&b.scrollIntoView({block:'nearest'})}
}
async function renderFlag(id){
 const pane=$('flagPane');if(!pane)return;
 if(!id){const h=`<div class="empty" style="padding-top:80px"><p><b>Select a flag</b> to see why it was flagged, the trend, the cases and the data's known problems.</p><p>Then keep it for review or dismiss it. Kept flags collect on your <a href="/shortlist" data-nav>Shortlist</a>.</p></div>`;if(pane._h!==h){pane.innerHTML=h;pane._h=h}return}
 const d=S.detail[id];
 if(!d){if(pane._h!=='load:'+id){pane._h='load:'+id;pane.innerHTML=`<div class="fpage"><span class="spin"></span> Loading the evidence${S.loadedOnce?'':' (the first one reads the case file, a few seconds)'}…</div>`;
  try{S.detail[id]=await api('/api/flag/'+id);S.loadedOnce=1}catch(e){S.detail[id]={error:e.message}}if(S.sel===id)renderFlag(id)}return}
 if(d.error){pane.innerHTML=`<div class="fpage"><p class="msg err">${esc(d.error)}</p></div>`;pane._h='err';return}
 const f=d.flag,dec=S.dec[id],s=dec?dec.status:null,g=gapOf(f);
 const h=`<div class="fpage">
  <div class="crumb"><a href="/places/${slug(f.state)}" data-nav>${esc(f.state)}</a>${f.county&&f.level!=='county'&&f.level!=='region'?` › <a href="/places/${slug(f.state)}/${slug(f.county)}" data-nav>${esc(f.county)}</a>`:f.level==='county'?` › <a href="/places/${slug(f.state)}/${slug(f.place)}" data-nav>county profile</a>`:''} · ${esc(f.level)}${d.flag.archived?' · <span class="tag">from an earlier scan</span>':''}</div>
  <h1 style="margin-top:6px">${esc(f.place)}: ${esc(String(f.weapon).toLowerCase())} killings of ${who(f.sex)}, ${yrs(f.start,f.end)}</h1>
  <div class="row"><span class="tag ${f.confidence}">${CONF[f.confidence]} confidence</span><span class="tag">${esc(f.kind||'')}</span><a class="btn" href="/map?flag=${f.id}" data-nav style="height:24px;font-size:12px">Show on map</a><span class="muted" style="font-size:12px">found by ${(f.by||[]).map(b=>`<a href="/models?m=detector|${encodeURIComponent(b)}" data-nav>${esc(b)}</a>`).join(' + ')}${f.q!=null?` · q = ${f.q}`:''}</span></div>
  <div class="quote"><div><b>${pct(f.solved/f.total)}</b><span>Solved</span></div><div><b>${pct(f.expected)}</b><span>Expected</span></div><div class="${g<0?'neg':''}"><b>${gapTxt(g)}</b><span>Gap, points</span></div><div><b>${nf.format(f.total-f.solved)}</b><span>Unsolved of ${nf.format(f.total)}</span></div><div><b>${f.end-f.start+1}</b><span>Years</span></div></div>
  ${historyLine(f)}
  ${decideBox(id,f,dec)}
  ${ruleoutBox(f)}
  <h3>Why it was flagged</h3><div class="notes"><p><b>${esc(f.what)}</b></p><p>${esc(f.agreement||'')}</p>${f.statistics?`<p class="muted">${esc(f.statistics)}</p>`:''}</div>
  ${(f.plugins||[]).length?`<h3>From plugins</h3>${f.plugins.map(n=>`<div class="plug"><b>${esc(n.title)}</b> <span class="by">${esc(n.by)}</span><p style="margin:4px 0 0">${esc(n.text)}</p></div>`).join('')}`:''}
  ${(d.sections||[]).map(x=>`<h3>${esc(x.title)} <span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">from a plugin</span></h3><div class="vsec">${renderBlocks(x.blocks)}</div>`).join('')}
  ${(d.datasets||[]).length?`<h3>Your data <span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">from datasets you added, matched to this place</span></h3>${d.datasets.map(x=>mineView(x,f,d)).join('')}`:''}
  ${(f.data||[]).length?`<h3>Known problems in the data</h3><div class="notes"><ul>${f.data.map(n=>`<li>${esc(n)}</li>`).join('')}</ul></div>`:''}
  ${f.cases?`<h3>Victims, in aggregate</h3><p>${esc(f.cases)}</p>`:''}
  ${f.namus?`<h3>NamUs</h3><p>${esc(f.namus)}</p>`:''}
  <h3>Explore the evidence <span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">hover for numbers · click or drag across years · click any value to filter</span></h3>
  <section class="wb" id="wb"></section>
  <h3>Next steps</h3><div class="notes"><ol style="padding-left:18px"><li>Search public news and court records: is a series here already known or solved?</li><li>Read the case rows: do dates, ages and circumstances resemble each other?</li><li>If it still looks unexplained, keep it and ask a second person to review it, then export it for MAP.</li></ol><p class="muted" style="margin-top:8px">Never contact families, witnesses or possible suspects. A flag is a pattern worth review, not evidence that cases are linked.</p></div>
 </div>`;
 if(pane._h!==h){const sc=pane._h&&pane._h.includes(f.place)?pane.scrollTop:0;pane.innerHTML=h;pane._h=h;pane.scrollTop=sc;renderWB(id)}
}
const RULE={explains:['May explain this','high'],weakens:['Weakens this','strong'],clear:['Nothing found','possible']};
function historyLine(f){
 const h=f.history;if(!h)return '';
 if(h.status==='new')return `<p class="muted" style="margin:-4px 0 12px;font-size:12.5px"><span class="tag kept">new</span> Not in the scan before this one.</p>`;
 const b=h.before,was=`${yrs(b.start,b.end)}, ${nf.format(b.total-b.solved)} unsolved of ${nf.format(b.total)}`;
 const tr=h.trend==='growing'?`<b style="color:var(--red)">${nf.format(h.delta_unsolved)} more unsolved</b> than in the last scan`:h.trend==='shrinking'?`${nf.format(-h.delta_unsolved)} fewer unsolved than in the last scan`:'unchanged since the last scan';
 return `<p class="muted" style="margin:-4px 0 12px;font-size:12.5px">First seen ${esc(day(h.since))} · ${tr} (then: ${esc(was)}).</p>`;
}
function ruleoutBox(f){
 const rs=f.ruleouts;if(!rs||!rs.length)return '';
 const head=f.ruleout==='explains'?'A known explanation may fit this flag.':f.ruleout==='weakens'?'Something in the data could account for part of this flag.':'None of the usual explanations fit. That makes the flag stronger, not proof of anything.';
 return `<h3>Rule-out checks</h3><p style="margin:0 0 8px">${head}</p><table style="margin:0 0 14px"><tbody>${rs.map(r=>`<tr><td style="width:130px"><span class="tag ${RULE[r.status]?.[1]||''}">${esc(RULE[r.status]?.[0]||r.status)}</span></td><td><b>${esc(r.title)}.</b> ${esc(r.text)}</td></tr>`).join('')}</tbody></table>`;
}
function decideBox(id,f,dec){
 const s=dec?dec.status:null;
 const stage=k=>['kept','reviewed','sent'].indexOf(k);
 const steps=`<div class="steps3">${['kept','reviewed','sent'].map(k=>`<span class="${s===k?'on':stage(s)>stage(k)?'done':''}">${['1 Kept','2 Second review','3 Sent to MAP'][stage(k)]}</span>`).join('')}</div>`;
 if(!s)return `<div class="decide"><div class="row"><b>Worth pursuing?</b><span class="muted">Keep it for review, or dismiss it so it leaves your list.</span></div><div class="row"><button class="btn keep" data-act="kept">${ICON.keep}Keep for review <kbd>s</kbd></button><button class="btn" data-act="dismissed">Dismiss <kbd>x</kbd></button></div></div>`;
 if(s==='dismissed')return `<div class="decide"><div class="row"><span class="tag dismissed">Dismissed</span><span class="muted">${esc(day(dec.updated))}</span><button class="btn" data-act="restore">Restore</button></div></div>`;
 const note=`<label class="muted" style="font-size:12px" for="noteBox">Your note: what you checked, what's still open</label><textarea id="noteBox" data-id="${id}" placeholder="e.g. Searched local news 1980–1990: no known series. Three cases share a location.">${esc(dec.note||'')}</textarea>`;
 let act='';
 if(s==='kept')act=`<div class="row"><input class="inp" id="reviewer" placeholder="Second reviewer's name or initials" aria-label="Second reviewer" style="width:240px"><button class="btn primary" data-act="reviewed">Mark reviewed</button><button class="btn" data-act="forget">Remove from shortlist</button></div><p class="muted" style="margin:0;font-size:12px">A person other than you reviews every lead before it leaves the project (ethics rules).</p>`;
 if(s==='reviewed')act=`<div class="row"><span class="tag reviewed">Reviewed by ${esc(dec.reviewer)}</span><button class="btn primary" data-act="export">${ICON.out}Export for MAP</button><button class="btn" data-act="sent">Mark sent</button><button class="btn" data-act="kept">Back to review</button></div>`;
 if(s==='sent')act=`<div class="row"><span class="tag sent">Sent ${esc(day(dec.updated))}</span><span class="muted">reviewed by ${esc(dec.reviewer)}</span><button class="btn" data-act="export">${ICON.out}Export again</button></div>`;
 return `<div class="decide ${s}">${steps}${note}${act}</div>`;
}
// ---- evidence workbench ---------------------------------------------------------------------
const MONTHS=['Unknown','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const ageBand=a=>a>=999?'Unknown':a<18?'Under 18':a<30?'18–29':a<45?'30–44':'45 and over';
// [key, label, value of a case row, how to show it]; case rows: year, month, agency, solved, age, race, weapon, relationship, circumstance
const FACETS=[['month','Month',r=>String(r[1]||0),v=>MONTHS[+v]],['age','Victim age',r=>ageBand(r[4]),v=>v],
 ['relationship','Relationship',r=>r[7]||'Not recorded',v=>v],['circumstance','Circumstance',r=>r[8]||'Not recorded',v=>v],
 ['agency','Agency',r=>r[2],v=>v],['weapon','Weapon recorded',r=>r[6],v=>v],['race','Victim race',r=>r[5],v=>v]];
const CASEH=['Year','Month','Agency','Solved','Age','Race','Weapon','Relationship','Circumstance'];
S.wb={};
function wbOf(id){const f=S.detail[id].flag;return S.wb[id]||(S.wb[id]={y0:f.start,y1:f.end,sel:{},sort:[0,1],limit:300})}
function wbRows(d,w,skip){return d.cases.filter(r=>r[0]>=w.y0&&r[0]<=w.y1&&FACETS.every(([k,,fn])=>k===skip||w.sel[k]==null||fn(r)===w.sel[k]))}
function renderWB(id){
 const el=$('wb');const d=S.detail[id];if(!el||!d||d.error)return;
 const f=d.flag,w=wbOf(id),rows=wbRows(d,w),uns=rows.filter(r=>!r[3]).length;
 const [Y0,Y1]=d.years,isFlag=w.y0===f.start&&w.y1===f.end,isAll=w.y0===Y0&&w.y1===Y1;
 const yopt=(v,sel)=>{let o='';for(let y=Y0;y<=Y1;y++)o+=`<option${y===sel?' selected':''}>${y}</option>`;return o};
 const chips=Object.entries(w.sel).map(([k,v])=>{const F=FACETS.find(x=>x[0]===k);return `<button class="chip filter" data-wbx="${k}" aria-label="Remove filter ${esc(F[1])}">${esc(F[3](v))} <span>${esc(F[1].toLowerCase())}</span> ×</button>`}).join('');
 const bar=`<div class="wbbar"><span class="lbl">Years</span>
  <button class="chip" data-wbr="flag" aria-pressed="${isFlag}">Flagged ${yrs(f.start,f.end)}</button><button class="chip" data-wbr="all" aria-pressed="${isAll}">All years</button>
  <select class="sel" id="wbY0" aria-label="From year">${yopt(0,w.y0)}</select><span class="muted">to</span><select class="sel" id="wbY1" aria-label="To year">${yopt(0,w.y1)}</select>
  ${chips}${chips||!isFlag?'<button class="chip" data-wbr="reset">Reset</button>':''}
  <span class="sum"><b>${nf.format(rows.length)}</b> cases · <b>${nf.format(uns)}</b> unsolved (${rows.length?Math.round(uns/rows.length*100):0}%)</span></div>`;
 const facets=FACETS.map(([k,label,fn,fmt])=>{
  const base=wbRows(d,w,k),cnt={},un={};base.forEach(r=>{const v=fn(r);cnt[v]=(cnt[v]||0)+1;if(!r[3])un[v]=(un[v]||0)+1});
  let vals=Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a]);if(k==='month')vals=vals.sort((a,b)=>(+a||13)-(+b||13));
  const show=k==='month'?vals:vals.slice(0,w['all_'+k]?60:7),tot=base.length||1,bl=d.baseline[k]||{};
  return `<div class="facet"><h4><span>${esc(label)}</span><span>n · unsolved</span></h4>${show.map(v=>{const sh=cnt[v]/tot,st=bl[v];
   const tip=`${fmt(v)}\n${cnt[v]} of ${base.length} cases here (${Math.round(sh*100)}%)${st!=null?`\n${Math.round(st*100)}% across the rest of ${f.state}, ${yrs(f.start,f.end)}`:''}\n${un[v]||0} unsolved (${Math.round((un[v]||0)/cnt[v]*100)}%)`;
   return `<button class="fv${w.sel[k]===v?' on':''}" data-fk="${k}" data-fv="${esc(v)}" data-tip="${esc(tip)}" aria-pressed="${w.sel[k]===v}"><span class="fl">${esc(fmt(v))}</span><span class="fb"><i style="width:${(sh*100).toFixed(1)}%"></i>${st!=null&&k!=='agency'?`<b style="left:${Math.min(100,st*100).toFixed(1)}%"></b>`:''}</span><span class="fn">${cnt[v]}</span><span class="fu">${Math.round((un[v]||0)/cnt[v]*100)}%</span></button>`}).join('')}
   ${vals.length>show.length?`<button class="fv" data-fmore="${k}" style="color:var(--accent)"><span class="fl">Show all ${vals.length}</span></button>`:''}</div>`}).join('');
 const [sc,dir]=w.sort,sorted=[...rows].sort((a,b)=>{const x=a[sc],y=b[sc];return (x>y?1:x<y?-1:sc!==1?0:0)*dir||a[0]-b[0]||a[1]-b[1]});
 const table=`<div class="cases"><table><thead><tr>${CASEH.map((h,i)=>`<th data-sort="${i}"${sc===i?` aria-sort="${dir>0?'ascending':'descending'}"`:''} class="${i===4?'n':''}">${h}${sc===i?(dir>0?' ↑':' ↓'):''}</th>`).join('')}</tr></thead><tbody>${sorted.slice(0,w.limit).map(c=>`<tr><td class="num">${c[0]}</td><td>${MONTHS[c[1]||0]}</td><td>${esc(c[2])}</td><td class="st ${c[3]?'yes':'no'}">${c[3]?'Yes':'No'}</td><td class="n">${c[4]>=999?'?':c[4]}</td><td>${esc(c[5])}</td><td>${esc(c[6])}</td><td>${esc(c[7])}</td><td>${esc(c[8]||'')}</td></tr>`).join('')}</tbody></table></div>
  ${sorted.length>w.limit?`<div class="more"><button class="btn" data-wbmore="1">Show ${Math.min(300,sorted.length-w.limit)} more of ${nf.format(sorted.length)}</button></div>`:''}`;
 el.innerHTML=`${bar}<div class="chart" id="ch"></div><div class="chart tl" id="tl"></div>
  <div class="flegend"><span><i></i>share of the cases selected here</span><span><s></s>share across the rest of ${esc(f.state)}, same method and victims, ${yrs(f.start,f.end)}</span><span style="color:var(--red)">% unsolved</span></div>
  <div class="facets">${facets}</div>
  ${d.truncated?`<p class="muted" style="font-size:12px;margin:0">This place has ${nf.format(d.cases_total)} cases; the ones from ${d.covered[0]}–${d.covered[1]} are loaded here.</p>`:''}
  ${table}`;
 drawWBChart(id);drawTimeline(id,rows);
}
function drawWBChart(id){
 const el=$('ch');const d=S.detail[id];if(!el)return;const f=d.flag,w=wbOf(id);
 const [Y0,Y1]=d.years,N=Y1-Y0+1,W=el.clientWidth-24||640,H=230,L=34,R=8,T=8,mid=120,B=20;
 const by=Object.fromEntries(d.series.map(([y,n,s])=>[y,[n,s]])),st=Object.fromEntries(d.state_series.map(([y,n,s])=>[y,[n,s]]));
 const maxn=Math.max(1,...d.series.map(x=>x[1])),cw=(W-L-R)/N,x=y=>L+(y-Y0)*cw;
 const top2=mid+14,bot2=H-B-2,rt=v=>top2+(1-v)*(bot2-top2);
 let h=`<rect x="${x(f.start)}" y="${T}" width="${(f.end-f.start+1)*cw}" height="${H-T-B}" fill="var(--hl)" opacity=".7"/>`;
 h+=`<rect id="selr" x="${x(w.y0)}" y="${T-2}" width="${(w.y1-w.y0+1)*cw}" height="${H-T-B+4}" fill="color-mix(in oklab,var(--accent) 8%,transparent)" stroke="var(--accent)" stroke-width="1.5" rx="2"/>`;
 for(let y=Y0;y<=Y1;y++){const [n,s]=by[y]||[0,0];if(!n)continue;const hn=(mid-T-6)*n/maxn,hs=(mid-T-6)*s/maxn;
  h+=`<rect x="${x(y)+1}" y="${mid-hn}" width="${Math.max(cw-2,1)}" height="${hn-hs}" fill="var(--red)"/><rect x="${x(y)+1}" y="${mid-hs}" width="${Math.max(cw-2,1)}" height="${hs}" fill="var(--solved)"/>`}
 let ps='',pp='';for(let y=Y0;y<=Y1;y++){const a=st[y];if(a&&a[0])ps+=`${ps?'L':'M'}${x(y)+cw/2},${rt(a[1]/a[0])}`;const b=by[y];if(b&&b[0]>=2)pp+=`<circle cx="${x(y)+cw/2}" cy="${rt(b[1]/b[0])}" r="2.6" fill="var(--ink)"/>`}
 h+=`<path d="${ps}" fill="none" stroke="var(--mute)" stroke-width="1.5" stroke-dasharray="4 3"/>${pp}`;
 if(f.expected!=null)h+=`<line x1="${x(f.start)}" x2="${x(f.end+1)}" y1="${rt(f.expected)}" y2="${rt(f.expected)}" stroke="var(--ink)" stroke-width="2"/>`;
 h+=`<line x1="${L}" x2="${W-R}" y1="${mid}" y2="${mid}" stroke="var(--line2)"/><text x="${L-6}" y="${T+10}" text-anchor="end">${maxn}</text><text x="${L-6}" y="${top2+4}" text-anchor="end">100%</text><text x="${L-6}" y="${bot2}" text-anchor="end">0%</text>`;
 for(let y=Math.ceil(Y0/5)*5;y<=Y1;y+=5)h+=`<text x="${x(y)+cw/2}" y="${H-5}" text-anchor="middle">${y}</text>`;
 for(let y=Y0;y<=Y1;y++){const [n,s]=by[y]||[0,0],a=st[y];
  const tip=`<b>${y}</b>${y>=f.start&&y<=f.end?' · flagged years':''}\n${n} killings here: ${s} solved, ${n-s} unsolved${n?` (${Math.round(s/n*100)}% solved)`:''}${a&&a[0]?`\n${f.state}: ${Math.round(a[1]/a[0]*100)}% solved, ${nf.format(a[0])} killings`:''}`;
  h+=`<rect class="hit" data-hy="${y}" data-tip="${esc(tip)}" x="${x(y)}" y="${T}" width="${cw}" height="${H-T-B}" fill="transparent"/>`}
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="height:${H}px" role="img" aria-label="Killings per year and share solved, ${esc(f.place)}. The case table below lists the same data.">${h}</svg>
  <div class="key"><span><i style="background:var(--red)"></i>unsolved</span><span><i style="background:var(--solved)"></i>solved (killings per year)</span><span><i style="background:var(--ink);border-radius:50%"></i>share solved here</span><span><i style="border-top:2px dashed var(--mute);height:0"></i>${esc(f.state)} average</span><span><i style="background:var(--hl)"></i>flagged years and expected rate</span><span><i style="border:1.5px solid var(--accent)"></i>your selection</span></div>`;
 el.dataset.geo=JSON.stringify({L,cw,Y0,Y1});
}
function drawTimeline(id,rows){
 const el=$('tl');const d=S.detail[id];if(!el)return;const w=wbOf(id),span=w.y1-w.y0+1;
 if(span>25){el.innerHTML=`<p class="muted" style="margin:4px 2px;font-size:12.5px">Select 25 years or fewer to see each case on a month-by-month timeline.</p>`;return}
 const W=el.clientWidth-24||640,L=34,R=8,cw=(W-L-R)/(span*12),stack={};let maxk=0;
 const pts=rows.map((r,i)=>{const m=r[1]||0,slot=(r[0]-w.y0)*12+(m?m-1:5.5),key=r[0]+'-'+m,k=stack[key]=(stack[key]||0)+1;maxk=Math.max(maxk,k);return [slot,k,r,m]});
 const step=Math.max(4,Math.min(8,cw*.9)),H=Math.max(56,maxk*step+30);
 let h='';for(let y=w.y0;y<=w.y1;y++){const xx=L+(y-w.y0)*12*cw;h+=`<line x1="${xx}" x2="${xx}" y1="4" y2="${H-18}" stroke="var(--line)"/>`;if(span<=12||y%5===0)h+=`<text x="${xx+6*cw}" y="${H-4}" text-anchor="middle">${y}</text>`}
 pts.forEach(([slot,k,r,m])=>{const cx=L+(slot+.5)*cw,cy=H-22-(k-1)*step;
  const tip=`<b>${MONTHS[m]} ${r[0]}</b> · ${r[3]?'solved':'unsolved'}\n${esc(r[2])}\nVictim ${r[4]>=999?'age unknown':'age '+r[4]}, ${esc(r[5])}\n${esc(r[6])}\n${esc(r[7])}${r[8]?' · '+esc(r[8]):''}`;
  h+=`<circle cx="${cx.toFixed(1)}" cy="${cy}" r="${Math.min(3.2,step/2-.4)}" fill="${m?(r[3]?'var(--solved)':'var(--red)'):'none'}" stroke="${r[3]?'var(--solved)':'var(--red)'}" stroke-width="1.2" data-tip="${esc(tip)}"/>`});
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="height:${H}px" role="img" aria-label="Each case in the selected years by month">${h}</svg><div class="key"><span>Each dot is one case, by month: <span style="color:var(--red)">unsolved</span>, <span style="color:var(--solved)">solved</span>; hollow means the month wasn't recorded.</span></div>`;
}
// tooltips: anything with data-tip
const tipEl=document.createElement('div');tipEl.className='tip';tipEl.hidden=true;document.body.append(tipEl);
document.addEventListener('mouseover',e=>{const t=e.target.closest('[data-tip]');if(!t){tipEl.hidden=true;return}showTip(t.dataset.tip);tipEl.hidden=false});
// Tooltips are plain text: any markup in the data (a county name, a dataset column, a plugin's label)
// is shown as text, never run. The <b> markers only say the first line is a heading.
function showTip(raw){
 const text=new DOMParser().parseFromString(String(raw).replace(/<\/?b>/g,''),'text/html').documentElement.textContent;
 const lines=text.split('\n'),b=document.createElement('b');b.textContent=lines[0];
 tipEl.replaceChildren(b,...lines.slice(1).map(l=>'\n'+l));
}
document.addEventListener('mousemove',e=>{if(tipEl.hidden)return;const r=tipEl.getBoundingClientRect();let x=e.clientX+14,y=e.clientY+14;if(x+r.width>innerWidth-8)x=e.clientX-r.width-14;if(y+r.height>innerHeight-8)y=e.clientY-r.height-14;tipEl.style.left=x+'px';tipEl.style.top=y+'px'});
document.addEventListener('mouseleave',()=>tipEl.hidden=true);
// drag across years on the chart
let drag=null;
document.addEventListener('mousedown',e=>{const t=e.target.closest('.hit');if(!t||!S.sel)return;e.preventDefault();drag={a:+t.dataset.hy,b:+t.dataset.hy};showDrag()});
document.addEventListener('mouseover',e=>{if(!drag)return;const t=e.target.closest('.hit');if(t){drag.b=+t.dataset.hy;showDrag()}});
document.addEventListener('mouseup',()=>{if(!drag)return;const w=wbOf(S.sel);w.y0=Math.min(drag.a,drag.b);w.y1=Math.max(drag.a,drag.b);w.limit=300;drag=null;renderWB(S.sel)});
function showDrag(){const g=JSON.parse($('ch').dataset.geo||'{}'),r=$('selr');if(!r)return;const a=Math.min(drag.a,drag.b),b=Math.max(drag.a,drag.b);r.setAttribute('x',g.L+(a-g.Y0)*g.cw);r.setAttribute('width',(b-a+1)*g.cw)}

// ---- your datasets on a flag ---------------------------------------------------------------
function mineView(x,f,d){
 const [Y0,Y1]=d.years,W=600,H=64,L=4,cw=(W-L*2)/(Y1-Y0+1),xx=y=>L+(y-Y0)*cw;
 const charts=x.numeric.slice(0,2).map((col,ci)=>{const vals=x.series.map(r=>[r[0],r[1+ci]]).filter(r=>r[1]!=null),mx=Math.max(1,...vals.map(r=>Math.abs(r[1])));
  return `<div style="margin:6px 0 2px"><span class="muted" style="font-size:12px">${esc(col)}, by year</span><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(col)} by year"><rect x="${xx(f.start)}" y="0" width="${(f.end-f.start+1)*cw}" height="${H-12}" fill="var(--hl)" opacity=".7"/>${vals.map(([y,v])=>`<rect x="${xx(y)+.5}" y="${H-12-(H-16)*Math.abs(v)/mx}" width="${Math.max(cw-1,1)}" height="${(H-16)*Math.abs(v)/mx}" fill="var(--accent)" data-tip="${esc(`<b>${y}</b>\n${col}: ${v}`)}"/>`).join('')}<line x1="0" x2="${W}" y1="${H-12}" y2="${H-12}" stroke="var(--line2)"/></svg></div>`}).join('');
 const cols=x.columns;
 const table=x.rows.length?`<div class="cases" style="max-height:220px;margin-top:6px"><table><thead><tr><th>Year</th><th>Mo.</th>${x.level!=='county'?'<th>Place</th>':''}${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${x.rows.map(r=>`<tr><td class="num">${r.year}</td><td>${r.month?MONTHS[r.month]:''}</td>${x.level!=='county'?`<td>${esc(r.place)}</td>`:''}${cols.map(c=>`<td>${esc(r[c]??'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
 return `<div class="mine"><div class="row"><b>${esc(x.name)}</b><span class="tag">${esc(x.level)}</span><span class="muted" style="font-size:12px">${nf.format(x.rows_total)} rows within ten years of the flag${x.all_rows>x.rows_total?`, ${nf.format(x.all_rows)} in all`:''}</span></div>
  ${x.description?`<p class="muted" style="margin:4px 0 0;font-size:12.5px">${esc(x.description)}${x.source?` Source: ${esc(x.source)}`:''}</p>`:''}${charts}${table}</div>`;
}

// ---- map ------------------------------------------------------------------------------------
const MW=['Gun','Knife','Beating/blunt','Strangle/asphyxia','Fire','Other/unknown'];
const MP={methods:new Set(MW.filter(w=>w!=='Gun')),metric:'solved',links:true,dist:150,y:null,sel:null,stats:{},k:1};
function loadScript(src){return new Promise((res,rej)=>{if(document.querySelector(`script[src="${src}"]`))return res();const el=document.createElement('script');el.src=src;el.onload=res;el.onerror=()=>rej(new Error('Could not load '+src));document.head.append(el)})}
async function mapAssets(){
 if(MP.ready)return;
 if(!MP.loading)MP.loading=(async()=>{await loadScript('/vendor/d3.v7.min.js');await loadScript('/vendor/topojson-client.min.js');
  const topo=await (await fetch('/vendor/counties-10m.json')).json();
  MP.counties=topojson.feature(topo,topo.objects.counties).features;MP.states=topojson.mesh(topo,topo.objects.states,(a,b)=>a!==b);
  MP.nation=topojson.feature(topo,topo.objects.nation);MP.byId=Object.fromEntries(MP.counties.map(f=>[f.id,f]));MP.ready=true})();
 await MP.loading;
}
async function mapStats(sex){if(!MP.stats[sex])MP.stats[sex]=await api('/api/map?sex='+sex);return MP.stats[sex]}
function renderMap(r){
 const fresh=setMain('map',`<div class="mapwrap" id="mapwrap"><svg id="mapsvg" role="img" aria-label="Map of US counties with flags and the links between them"></svg>
  <div class="mapload" id="mapload"><span><span class="spin"></span> Drawing the map…</span></div>
  <aside class="mpanel left" id="mLeft" aria-label="Map filters"></aside><aside class="mpanel right" id="mRight" aria-label="Selection"></aside>
  <div class="mzoom"><button id="mzIn" aria-label="Zoom in">+</button><button id="mzOut" aria-label="Zoom out">−</button><button id="mzHome" aria-label="Whole country" style="font-size:11px">US</button></div>
  <div class="mlegend" id="mLegend"></div><div class="mtime" id="mTime"></div></div>`);
 const want=new URLSearchParams(location.search).get('flag')||(S.usedMapFlag?null:wantMapFlag);S.usedMapFlag=1;if(want&&MP.sel?.id!==want)MP.sel={type:'flag',id:want,zoom:true};
 // One build at a time: redraws that arrive while the map is being built wait for it.
 if(fresh)MP.svg=null;
 if(!MP.svg){if(!MP.building)MP.building=(async()=>{try{await mapAssets();await mapStats(S.f.sex==='all'?'all':S.f.sex);if($('mapsvg')){buildMap();updateMap()}}
   catch(e){const el=$('mapload');if(el)el.innerHTML=`<p class="msg err">${esc(e.message)}</p>`;else toast(e.message)}finally{MP.building=null}})();return}
 updateMap();
}
function buildMap(){
 const svg=d3.select('#mapsvg'),wrap=$('mapwrap');if(!wrap)return;const W=wrap.clientWidth,H=wrap.clientHeight;
 svg.attr('viewBox',`0 0 ${W} ${H}`);svg.selectAll('*').remove();
 const defs=svg.append('defs');const gl=defs.append('filter').attr('id','glow').attr('x','-50%').attr('y','-50%').attr('width','200%').attr('height','200%');
 gl.append('feGaussianBlur').attr('stdDeviation',2.2).attr('result','b');const mg=gl.append('feMerge');mg.append('feMergeNode').attr('in','b');mg.append('feMergeNode').attr('in','SourceGraphic');
 const proj=d3.geoAlbersUsa().fitExtent([[300,30],[W-350,H-120]],MP.nation),path=d3.geoPath(proj);
 MP.proj=proj;MP.path=path;const g=svg.append('g');MP.g=g;
 MP.cent={};MP.ll={};MP.counties.forEach(f=>{const c=path.centroid(f);if(isFinite(c[0])){MP.cent[f.id]=c;MP.ll[f.id]=d3.geoCentroid(f)}});
 g.append('g').selectAll('path').data(MP.counties).join('path').attr('class','county').attr('d',path).attr('data-fips',d=>d.id);
 g.append('path').attr('class','states').attr('d',path(MP.states)).attr('vector-effect','non-scaling-stroke');
 g.append('path').attr('class','nation').attr('d',path(MP.nation)).attr('vector-effect','non-scaling-stroke');
 g.selectAll('path.county').attr('vector-effect','non-scaling-stroke');
 MP.gLinks=g.append('g');MP.gFlags=g.append('g');
 MP.zoom=d3.zoom().scaleExtent([1,48]).on('zoom',e=>{g.attr('transform',e.transform);MP.k=e.transform.k;scaleMarks()});
 svg.call(MP.zoom).on('dblclick.zoom',null);
 svg.on('click',e=>{const c=e.target.closest('.county'),fl=e.target.closest('.flag');if(fl){MP.sel={type:'flag',id:fl.dataset.id};updateMap();return}if(c){MP.sel={type:'county',fips:c.dataset.fips};updateMap();return}});
 MP.svg=svg;$('mapload').remove();
}
function scaleMarks(){const k=MP.k,f=Math.pow(k,.8);MP.gFlags.selectAll('circle.dot').attr('r',function(){return this.dataset.r/f});MP.gFlags.selectAll('circle.ring').attr('r',function(){return this.dataset.r/f});MP.gLinks.selectAll('path').attr('stroke-width',function(){return this.dataset.w/Math.sqrt(k)})}
function strength(f){return f.q!=null?Math.max(.3,Math.min(1,-Math.log10(Math.max(f.q,1e-4))/3)):({high:.9,strong:.7,possible:.4})[f.confidence]||.4}
function mapFlags(){
 const st=MP.stats[S.f.sex==='all'?'all':S.f.sex];if(!st||!S.flags)return [];
 const [y0,y1]=MP.y||[0,9999];
 return S.flags.filter(f=>(S.f.sex==='all'||f.sex===S.f.sex)&&(S.f.conf==='all'||(S.f.conf==='high'?f.confidence==='high':f.confidence!=='possible'))
  &&MP.methods.has(f.weapon)&&f.end>=y0&&f.start<=y1).map(f=>{
   const ids=(f.counties||[f.county]).map(c=>st.fips[c]).filter(id=>id&&MP.cent[id]);if(!ids.length)return null;
   const xy=[d3.mean(ids,i=>MP.cent[i][0]),d3.mean(ids,i=>MP.cent[i][1])],ll=[d3.mean(ids,i=>MP.ll[i][0]),d3.mean(ids,i=>MP.ll[i][1])];
   return {f,ids,xy,ll,s:strength(f)}}).filter(Boolean);
}
function mapLinks(items){
 if(!MP.links)return [];const out=[],by={};items.forEach(it=>{(by[it.f.sex+'|'+it.f.weapon]=by[it.f.sex+'|'+it.f.weapon]||[]).push(it)});
 for(const grp of Object.values(by))for(let i=0;i<grp.length;i++)for(let j=i+1;j<grp.length;j++){const a=grp[i],b=grp[j];
  if(a.f.end<b.f.start||b.f.end<a.f.start||a.ids.some(x=>b.ids.includes(x)))continue;
  const mi=d3.geoDistance(a.ll,b.ll)*3958.8;if(mi>MP.dist)continue;
  const ov=Math.min(a.f.end,b.f.end)-Math.max(a.f.start,b.f.start)+1,span=Math.max(a.f.end-a.f.start+1,b.f.end-b.f.start+1);
  out.push({a,b,mi,ov,w:Math.min(a.s,b.s)*(ov/span)*(1-.6*mi/MP.dist)})}
 return out.sort((x,y)=>y.w-x.w).slice(0,600);
}
function updateMap(){
 if(!MP.svg||!S.flags)return;const sexKey=S.f.sex==='all'?'all':S.f.sex,st=MP.stats[sexKey];
 if(!st){mapStats(sexKey).then(updateMap);return}
 const years=S.flags.map(f=>[f.start,f.end]).flat();const Y0=d3.min(years),Y1=d3.max(years);if(!MP.y)MP.y=[Y0,Y1];
 // counties: shade by the chosen measure
 const C=st.counties,flagsIn={};const items=mapFlags();items.forEach(it=>it.ids.forEach(i=>flagsIn[i]=(flagsIn[i]||0)+1));
 const red='#c2392f',teal='#2fb3c9',base='#101820';
 const solvedC=d3.scaleLinear().domain([.35,.65,.95]).range([red,'#3a4552',teal]).clamp(true);
 const unsC=d3.scaleLog().domain([1,3000]).range(['#1b2633','#ff5a4e']).clamp(true);
 const flagC=d3.scaleLinear().domain([0,1,6]).range([base,'#4a3a12','#f5a524']).clamp(true);
 MP.g.selectAll('path.county').attr('fill',d=>{const c=C[d.id];if(MP.metric==='flags')return flagsIn[d.id]?flagC(flagsIn[d.id]):base;if(!c||!c[1])return base;
   return MP.metric==='solved'?(c[1]<8?d3.interpolateRgb(base,solvedC(c[2]/c[1]))(.45):solvedC(c[2]/c[1])):unsC(Math.max(1,c[1]-c[2]))})
  .attr('data-tip',d=>{const c=C[d.id];return c?`<b>${esc(c[0])}</b>\n${nf.format(c[1])} killings of ${who(S.f.sex)} 12+, ${Math.round(c[2]/c[1]*100)}% solved\n${nf.format(c[1]-c[2])} unsolved${flagsIn[d.id]?`\n${flagsIn[d.id]} flag${flagsIn[d.id]>1?'s':''} shown`:''}`:`${esc(d.properties.name)}\nNo cases in the file`})
  .classed('sel',d=>MP.sel&&MP.sel.type==='county'&&MP.sel.fips===d.id);
 // links: same method and victims, overlapping years, within the distance
 const links=mapLinks(items);MP.lastLinks=links;
 const selId=MP.sel&&MP.sel.type==='flag'?MP.sel.id:null,selF=MP.sel&&MP.sel.type==='county'?MP.sel.fips:null;
 const touches=it=>selId?it.f.id===selId:selF?it.ids.includes(selF):false;
 const linked=new Set();if(selId||selF)links.forEach(l=>{if(touches(l.a)||touches(l.b)){linked.add(l.a.f.id);linked.add(l.b.f.id)}});
 MP.gLinks.selectAll('path').data(links,l=>l.a.f.id+l.b.f.id).join('path').attr('class',l=>'link'+((selId||selF)&&!(touches(l.a)||touches(l.b))?' dim':'')+((selId||selF)&&(touches(l.a)||touches(l.b))?' hot':''))
  .attr('d',l=>{const [x1,y1]=l.a.xy,[x2,y2]=l.b.xy,mx=(x1+x2)/2,my=(y1+y2)/2,dx=x2-x1,dy=y2-y1,c=.22;return `M${x1},${y1}Q${mx-dy*c},${my+dx*c} ${x2},${y2}`})
  .attr('data-w',l=>(1.2+3.2*l.w).toFixed(2)).attr('opacity',l=>(.5+.5*l.w).toFixed(2)).attr('filter','url(#glow)')
  .attr('data-tip',l=>`<b>Shared pattern</b>\n${esc(l.a.f.place)} · ${esc(l.b.f.place)}\n${esc(String(l.a.f.weapon).toLowerCase())} killings of ${who(l.a.f.sex)}, overlapping ${Math.max(l.a.f.start,l.b.f.start)}–${Math.min(l.a.f.end,l.b.f.end)} (${l.ov} yr)\n${Math.round(l.mi)} miles apart · strength ${Math.round(l.w*100)}\nA shared pattern, not evidence that cases are linked.`);
 // flags: size = unsolved, colour = confidence, brightness = strength of evidence
 const col={high:'#ff5a4e',strong:'#f5a524',possible:'#7d91a4'};
 const sel=MP.gFlags.selectAll('g.flag').data(items.sort((a,b)=>(a.f.total-a.f.solved)-(b.f.total-b.f.solved)),it=>it.f.id).join(en=>{const g=en.append('g').attr('class','flag');g.append('circle').attr('class','ring');g.append('circle').attr('class','dot');return g});
 sel.attr('data-id',it=>it.f.id).attr('transform',it=>`translate(${it.xy[0]},${it.xy[1]})`).classed('dim',it=>(selId||selF)&&!(touches(it)||linked.has(it.f.id)))
  .attr('data-tip',it=>{const f=it.f,g=gapOf(f);return `<b>${esc(f.place)}</b>, ${esc(f.state)}\n${esc(String(f.weapon).toLowerCase())} killings of ${who(f.sex)}, ${yrs(f.start,f.end)}\n${pct(f.solved/f.total)} solved vs ${pct(f.expected)} expected (${gapTxt(g)} pts)\n${f.total-f.solved} of ${f.total} unsolved · ${CONF[f.confidence]}${f.q!=null?` · q = ${f.q}`:''}`});
 sel.select('circle.dot').attr('data-r',it=>(2.4+Math.sqrt(it.f.total-it.f.solved)*.55).toFixed(2)).attr('fill',it=>col[it.f.confidence]).attr('fill-opacity',it=>it.s.toFixed(2))
  .attr('stroke',it=>it.f.id===selId?'#fff':'#060a0f').attr('stroke-width',it=>it.f.id===selId?1.6:.6).attr('vector-effect','non-scaling-stroke').attr('filter',it=>it.f.confidence==='high'?'url(#glow)':null);
 sel.select('circle.ring').attr('data-r',it=>(2.4+Math.sqrt(it.f.total-it.f.solved)*.55).toFixed(2)).attr('display',it=>it.f.confidence==='high'&&it.s>.8?null:'none').attr('vector-effect','non-scaling-stroke');
 scaleMarks();
 if(MP.sel&&MP.sel.zoom){MP.sel.zoom=false;const it=items.find(x=>x.f.id===MP.sel.id);if(it)zoomTo(it.xy,6)}
 mapLeft(items,links);mapRight(items,links,st);mapLegend();mapTime(Y0,Y1);
}
function zoomTo([x,y],k){const wrap=$('mapwrap');MP.svg.transition().duration(750).call(MP.zoom.transform,d3.zoomIdentity.translate(wrap.clientWidth/2,wrap.clientHeight/2).scale(k).translate(-x,-y))}
function mapLeft(items,links){
 const f=S.f,seg=(k,o,obj=f)=>`<div class="seg" role="group">${o.map(([v,l])=>`<button data-mf="${k}" data-v="${v}" aria-pressed="${obj[k]===v}">${l}</button>`).join('')}</div>`;
 const html=`<h2>Map</h2><p><span class="num">${nf.format(items.length)}</span> flags · <span class="num">${nf.format(links.length)}</span> links</p>
  <span class="lbl">Victims</span>${seg('sex',[['Female','Women'],['Male','Men'],['all','Both']])}
  <span class="lbl">Confidence</span>${seg('conf',[['high','High'],['strong','High + strong'],['all','All']])}
  <span class="lbl">Methods</span><div class="mchips">${MW.map(w=>`<button class="mchip" data-mw="${w}" aria-pressed="${MP.methods.has(w)}">${esc(w.replace('Strangle/asphyxia','Strangle').replace('Beating/blunt','Beating').replace('Other/unknown','Other'))}</button>`).join('')}</div>
  <span class="lbl">Shade counties by</span><select class="sel" id="mMetric"><option value="solved"${MP.metric==='solved'?' selected':''}>Share solved</option><option value="unsolved"${MP.metric==='unsolved'?' selected':''}>Unsolved killings</option><option value="flags"${MP.metric==='flags'?' selected':''}>Flags shown</option></select>
  <span class="lbl">Links between places</span><label style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><input type="checkbox" id="mLinks"${MP.links?' checked':''}> Show shared patterns</label>
  <label for="mDist" style="font-size:12px;color:var(--m-mute)">Within <span class="num">${MP.dist}</span> miles</label><input type="range" id="mDist" min="25" max="500" step="25" value="${MP.dist}">
  <p style="font-size:11.5px;color:var(--m-mute);margin-top:8px">A link joins flags with the same method and victims, overlapping years, within the distance. Brighter means stronger evidence (lower q) and more overlap. A link is a shared pattern, never evidence that cases are connected.</p>`;
 if($('mLeft')._h!==html){$('mLeft').innerHTML=html;$('mLeft')._h=html}
}
function mapRight(items,links,st){
 const el=$('mRight');let html;
 if(!MP.sel)html=`<h2>Click anything</h2><p>Scroll to zoom, drag to move. Click a county for its record, a flag for its evidence and the places it shares a pattern with.</p><span class="lbl">Strongest links shown</span><ul class="mlist">${links.slice(0,8).map(l=>`<li><button data-mflag="${l.a.f.id}"><span class="d" style="background:var(--m-link)"></span><span class="t">${esc(l.a.f.place)} · ${esc(l.b.f.place)}</span><span class="r">${Math.round(l.mi)} mi</span></button></li>`).join('')||'<li class="muted">None with these filters.</li>'}</ul>`;
 else if(MP.sel.type==='county'){const c=st.counties[MP.sel.fips],here=items.filter(it=>it.ids.includes(MP.sel.fips)),feat=MP.byId[MP.sel.fips],lbl=c?c[0]:feat?.properties.name;
  const state=(S.flags.find(f=>(f.counties||[f.county]).includes(lbl))||{}).state;
  html=`<h2>${esc(lbl||'County')}</h2>${c?`<div class="mstat"><div><b>${nf.format(c[1])}</b><span>Killings</span></div><div><b>${pct(c[2]/c[1])}</b><span>Solved</span></div><div class="neg"><b>${nf.format(c[1]-c[2])}</b><span>Unsolved</span></div></div>`:'<p>No cases in the file.</p>'}
   <span class="lbl">Flags here (${here.length})</span><ul class="mlist">${here.map(it=>`<li><button data-mflag="${it.f.id}"><span class="d" style="background:${({high:'#ff5a4e',strong:'#f5a524',possible:'#7d91a4'})[it.f.confidence]}"></span><span class="t">${esc(String(it.f.weapon).toLowerCase())} · ${yrs(it.f.start,it.f.end)}</span><span class="r">${gapTxt(gapOf(it.f))}</span></button></li>`).join('')||'<li style="color:var(--m-mute);padding:6px 0">None with these filters.</li>'}</ul>
   <div class="row" style="margin-top:10px">${state&&lbl?`<a class="btn" href="/places/${slug(state)}/${slug(lbl)}" data-nav>County profile</a>`:''}<button class="btn" id="mClear">Clear</button></div>`}
 else{const it=items.find(x=>x.f.id===MP.sel.id),f=it?it.f:S.flags.find(x=>x.id===MP.sel.id);
  if(!f)html=`<p>That flag isn't in the current filters.</p><button class="btn" id="mClear">Clear</button>`;
  else{const g=gapOf(f),mine=links.filter(l=>l.a.f.id===f.id||l.b.f.id===f.id).map(l=>({o:l.a.f.id===f.id?l.b:l.a,l}));
   html=`<h2>${esc(f.place)}</h2><p>${esc(f.state)} · ${esc(String(f.weapon).toLowerCase())} killings of ${who(f.sex)}, ${yrs(f.start,f.end)}</p>
    <div class="mstat"><div><b>${pct(f.solved/f.total)}</b><span>Solved</span></div><div><b>${pct(f.expected)}</b><span>Expected</span></div><div class="neg"><b>${gapTxt(g)}</b><span>Gap pts</span></div></div>
    <p style="font-size:12px">${CONF[f.confidence]} confidence · found by ${esc((f.by||[]).join(' + '))}${f.q!=null?` · q = ${f.q}`:''}</p>
    <span class="lbl">Shares a pattern with (${mine.length})</span><ul class="mlist">${mine.map(({o,l})=>`<li><button data-mflag="${o.f.id}"><span class="d" style="background:var(--m-link)"></span><span class="t">${esc(o.f.place)}, ${esc(o.f.state)} · ${yrs(o.f.start,o.f.end)}</span><span class="r">${Math.round(l.mi)} mi</span></button></li>`).join('')||`<li style="color:var(--m-mute);padding:6px 0">No other flag with the same method and victims within ${MP.dist} miles and overlapping years.</li>`}</ul>
    <div class="row" style="margin-top:10px"><a class="btn primary" href="/flags/${f.id}" data-nav>Open the evidence</a><button class="btn" id="mClear">Clear</button></div>`}}
 if(el._h!==html){el.innerHTML=html;el._h=html}
}
function mapLegend(){
 const m=MP.metric,ramp=m==='solved'?'linear-gradient(90deg,#c2392f,#3a4552,#2fb3c9)':m==='unsolved'?'linear-gradient(90deg,#1b2633,#ff5a4e)':'linear-gradient(90deg,#101820,#4a3a12,#f5a524)';
 const ends=m==='solved'?['35% solved','95%']:m==='unsolved'?['1 unsolved','3,000+']:['no flags','6+'];
 const html=`<span>${m==='solved'?'Share solved':m==='unsolved'?'Unsolved killings':'Flags shown'} · ${who(S.f.sex)} 12+</span><div class="ramp" style="background:${ramp}"></div><div class="ends"><span>${ends[0]}</span><span>${ends[1]}</span></div>
  <span><span style="color:#ff5a4e">●</span> high <span style="color:#f5a524">●</span> strong <span style="color:#7d91a4">●</span> possible · size = unsolved</span>`;
 if($('mLegend')._h!==html){$('mLegend').innerHTML=html;$('mLegend')._h=html}
}
function mapTime(Y0,Y1){
 const el=$('mTime');if(!el)return;
 if(!el._built){el._built=1;el.innerHTML=`<div class="mplay"><button id="mPlay" aria-label="Play through the years"><svg viewBox="0 0 12 12"><path d="M3 2l7 4-7 4z"/></svg></button><span id="mYears"></span></div><svg id="mTimeSvg"></svg>`}
 const svg=d3.select('#mTimeSvg'),W=$('mTimeSvg').clientWidth||800,H=78,L=8,R=8,B=16;svg.attr('viewBox',`0 0 ${W} ${H}`);
 const x=d3.scaleLinear().domain([Y0,Y1+1]).range([L,W-R]);
 const pool=S.flags.filter(f=>(S.f.sex==='all'||f.sex===S.f.sex)&&(S.f.conf==='all'||(S.f.conf==='high'?f.confidence==='high':f.confidence!=='possible'))&&MP.methods.has(f.weapon));
 const counts=d3.range(Y0,Y1+1).map(y=>[y,pool.filter(f=>f.start<=y&&f.end>=y).length]),mx=d3.max(counts,c=>c[1])||1;
 svg.selectAll('g.bars').data([0]).join('g').attr('class','bars').selectAll('rect').data(counts).join('rect')
  .attr('x',d=>x(d[0])+.5).attr('width',Math.max(1,x(Y0+1)-x(Y0)-1)).attr('y',d=>H-B-(H-B-6)*d[1]/mx).attr('height',d=>(H-B-6)*d[1]/mx)
  .attr('class',d=>d[0]>=MP.y[0]&&d[0]<=MP.y[1]?'on':'').attr('data-tip',d=>`<b>${d[0]}</b>\n${d[1]} flags active`);
 svg.selectAll('g.ax').data([0]).join('g').attr('class','ax').attr('transform',`translate(0,${H-B+2})`).call(d3.axisBottom(x).ticks(10).tickFormat(d3.format('d')).tickSize(0)).call(g=>g.select('.domain').remove());
 if(!MP.brush){MP.brush=d3.brushX().extent([[L,2],[W-R,H-B]]).on('end',e=>{if(!e.sourceEvent)return;if(!e.selection){MP.y=[Y0,Y1]}else{MP.y=e.selection.map(v=>Math.round(x.invert(v))).map((v,i)=>i?Math.min(Y1,v-1):v)}updateMap()});svg.append('g').attr('class','brush').call(MP.brush)}
 svg.select('g.brush').call(MP.brush.move,[x(MP.y[0]),x(MP.y[1]+1)]);
 $('mYears').textContent=MP.y[0]===MP.y[1]?MP.y[0]:MP.y[0]+'–'+MP.y[1];
}
function mapPlay(){
 if(MP.timer){clearInterval(MP.timer);MP.timer=null;$('mPlay').innerHTML='<svg viewBox="0 0 12 12"><path d="M3 2l7 4-7 4z"/></svg>';return}
 const years=S.flags.map(f=>[f.start,f.end]).flat(),Y0=d3.min(years),Y1=d3.max(years),win=5;let y=Y0;
 $('mPlay').innerHTML='<svg viewBox="0 0 12 12"><path d="M3 2h2v8H3zM7 2h2v8H7z"/></svg>';
 MP.timer=setInterval(()=>{MP.y=[y,Math.min(Y1,y+win-1)];updateMap();y++;if(y>Y1-win+1){clearInterval(MP.timer);MP.timer=null;$('mPlay').innerHTML='<svg viewBox="0 0 12 12"><path d="M3 2l7 4-7 4z"/></svg>'}},420);
}

// ---- pages and sections from plugins -------------------------------------------------------
async function loadViews(){try{S.views=await api('/api/views')}catch(e){S.views=[]}render()}
function renderViewNav(r){
 if(!S.views){if(!S.viewsLoading){S.viewsLoading=1;loadViews()}return}
 const ico='<svg viewBox="0 0 16 16" class="plug-ico"><path d="M6 2.5h4v2a1.5 1.5 0 003 0v-0h1.5v4h-2a1.5 1.5 0 000 3h2v2.5h-12v-12h3.5"/></svg>';
 const item=v=>`<a class="nav" href="/x/${encodeURIComponent(v.name)}" data-nav data-sec="x:${esc(v.name)}"${r.sec==='x'&&r.a===v.name?' aria-current="page"':''} title="${esc(v.summary)} (from a plugin)">${ico}${esc(v.title)}</a>`;
 const pages=S.views.filter(v=>v.place==='page');
 const res=pages.filter(v=>v.group!=='Extend').map(item).join(''),ext=pages.filter(v=>v.group==='Extend').map(item).join('');
 if($('navResearchX')._h!==res){$('navResearchX').innerHTML=res;$('navResearchX')._h=res}
 if($('navExtendX')._h!==ext){$('navExtendX').innerHTML=ext;$('navExtendX')._h=ext}
}
function mdLite(t){return esc(t).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')}
const fmtV=v=>typeof v==='number'?nf.format(v):v==null?'':String(v);
const SER=['var(--accent)','var(--red)','var(--solved)','var(--amber)'];
function renderBlocks(bs){return (bs||[]).map(b=>{
 if(b.type==='heading')return `<h3>${esc(b.text)}</h3>`;
 if(b.type==='text')return `<p>${mdLite(b.text)}</p>`;
 if(b.type==='note')return `<p class="msg ${b.tone==='warn'?'warn':b.tone==='ok'?'ok':''}" style="margin:0 0 12px">${mdLite(b.text)}</p>`;
 if(b.type==='stats')return `<div class="quote" style="grid-template-columns:repeat(${Math.max(1,Math.min(5,b.items.length))},minmax(0,1fr))">${b.items.map(([l,v,t])=>`<div class="${t==='neg'?'neg':''}"><b>${esc(fmtV(v))}</b><span>${esc(l)}</span></div>`).join('')}</div>`;
 if(b.type==='table'){const num=new Set(b.numeric||[]);return `<div class="cases" style="max-height:520px;margin:0 0 12px"><table><thead><tr>${b.columns.map(c=>`<th class="${num.has(c)?'n':''}">${esc(c)}</th>`).join('')}</tr></thead><tbody>${b.rows.map((r,i)=>{const fid=b.flags&&b.flags[i];return `<tr${fid?` class="click" data-href="/flags/${esc(fid)}" title="Open this flag"`:''}>${r.map((v,j)=>`<td class="${num.has(b.columns[j])?'n':''}">${esc(fmtV(v))}</td>`).join('')}</tr>`}).join('')}</tbody></table></div>`}
 if(b.type==='bars'){const d=b.data.filter(x=>typeof x[1]==='number');if(!d.length)return '';const W=640,L=200,rh=22,H=d.length*rh+(b.title?26:6),mx=Math.max(...d.map(x=>Math.abs(x[1])))||1;
  return `<div class="vchart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(b.title||'Bar chart')}">${b.title?`<text class="t" x="0" y="14">${esc(b.title)}</text>`:''}${d.map(([k,v],i)=>{const y=(b.title?24:4)+i*rh,w=(W-L-70)*Math.abs(v)/mx;
   return `<text x="${L-8}" y="${y+14}" text-anchor="end">${esc(k.length>28?k.slice(0,27)+'…':k)}</text><rect x="${L}" y="${y+3}" width="${Math.max(1,w)}" height="${rh-8}" rx="2" fill="${v<0?'var(--red)':'var(--solved)'}" data-tip="${esc(`<b>${k}</b>\n${fmtV(v)}${b.unit?' '+b.unit:''}`)}"/><text x="${L+w+6}" y="${y+14}">${esc(fmtV(v))}${b.unit?' '+esc(b.unit):''}</text>`}).join('')}</svg></div>`}
 if(b.type==='line'){const xs=b.x,W=640,H=220,L=46,R=10,T=b.title?28:8,B=22,all=b.series.flatMap(s=>s[1]).filter(v=>typeof v==='number');if(!all.length||xs.length<2)return '';
  const lo=Math.min(0,...all),hi=Math.max(...all)||1,xx=i=>L+(W-L-R)*i/(xs.length-1),yy=v=>T+(H-T-B)*(1-(v-lo)/(hi-lo||1));
  return `<div class="vchart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(b.title||'Line chart')}">${b.title?`<text class="t" x="0" y="14">${esc(b.title)}</text>`:''}
   <text x="${L-6}" y="${T+4}" text-anchor="end">${esc(fmtV(hi))}</text><text x="${L-6}" y="${H-B}" text-anchor="end">${esc(fmtV(lo))}</text><line x1="${L}" x2="${W-R}" y1="${H-B}" y2="${H-B}" stroke="var(--line2)"/>
   ${[0,Math.floor((xs.length-1)/2),xs.length-1].map(i=>`<text x="${xx(i)}" y="${H-5}" text-anchor="middle">${esc(fmtV(xs[i]))}</text>`).join('')}
   ${b.series.map(([nm,vals],si)=>`<path d="${vals.map((v,i)=>typeof v==='number'?`${i&&typeof vals[i-1]==='number'?'L':'M'}${xx(i).toFixed(1)},${yy(v).toFixed(1)}`:'').join('')}" fill="none" stroke="${SER[si%4]}" stroke-width="2"/>${vals.map((v,i)=>typeof v==='number'?`<circle cx="${xx(i).toFixed(1)}" cy="${yy(v).toFixed(1)}" r="5" fill="transparent" data-tip="${esc(`<b>${fmtV(xs[i])}</b>\n${nm}: ${fmtV(v)}${b.unit?' '+b.unit:''}`)}"/>`:'').join('')}`).join('')}</svg>
   ${b.series.length>1?`<div class="key">${b.series.map(([nm],si)=>`<span><i style="background:${SER[si%4]}"></i>${esc(nm)}</span>`).join('')}</div>`:''}</div>`}
 if(b.type==='flags'){const fs=b.ids.map(id=>(S.flags||[]).find(f=>f.id===id)).filter(Boolean);return `${b.title?`<h3>${esc(b.title)}</h3>`:''}<table style="margin:0 0 12px"><tbody>${fs.map(f=>`<tr class="click" data-href="/flags/${f.id}"><td><span class="tag ${f.confidence}">${CONF[f.confidence]}</span></td><td>${esc(f.place)}, ${esc(f.state)}</td><td class="muted">${esc(String(f.weapon).toLowerCase())} · ${who(f.sex)} · ${yrs(f.start,f.end)}</td><td class="n" style="color:var(--red)">${gapTxt(gapOf(f))}</td></tr>`).join('')||'<tr><td class="muted">No flags.</td></tr>'}</tbody></table>`}
 return '';
}).join('')}
function viewInputs(v){
 const vals=S.vin[v.name]||(S.vin[v.name]=Object.fromEntries(v.inputs.map(i=>[i.name,i.default??''])));
 const states=[...new Set((S.flags||[]).map(f=>f.state).filter(Boolean))].sort();
 return v.inputs.map(i=>{const val=vals[i.name]??'';
  if(i.type==='state')return `<label>${esc(i.label)}<select class="sel" data-vin="${esc(i.name)}">${states.map(st=>`<option${st===val?' selected':''}>${esc(st)}</option>`).join('')}</select></label>`;
  if(i.type==='choice')return `<label>${esc(i.label)}<select class="sel" data-vin="${esc(i.name)}">${i.options.map(([o,t])=>`<option value="${esc(o)}"${String(o)===String(val)?' selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
  if(i.type==='number')return `<label>${esc(i.label)}<input class="inp" type="number" data-vin="${esc(i.name)}" value="${esc(val)}"${i.min!=null?` min="${i.min}"`:''}${i.max!=null?` max="${i.max}"`:''}${i.step!=null?` step="${i.step}"`:''} style="width:110px"></label>`;
  return `<label>${esc(i.label)}<input class="inp" data-vin="${esc(i.name)}" value="${esc(val)}" placeholder="${esc(i.placeholder||'')}"></label>`}).join('');
}
async function runView(name){
 const v=(S.views||[]).find(x=>x.name===name);if(!v)return;S.vres[name]={loading:true};render();
 try{S.vres[name]=await api('/api/view/'+encodeURIComponent(name)+'?'+new URLSearchParams(S.vin[name]||{}))}catch(e){S.vres[name]={error:e.message}}render();
}
S.vin={};S.vres={};
function renderViewPage(r){
 if(!S.views){setMain('vload',`<div class="view"><div class="page"><span class="spin"></span> Loading…</div></div>`);return}
 const v=S.views.find(x=>x.name===r.a);
 if(!v){setMain('vnone',`<div class="view"><div class="page"><h1>Page not found</h1><p class="muted">No plugin page called “${esc(r.a)}” is switched on. See <a href="/models" data-nav>Models</a>.</p></div></div>`);return}
 const res=S.vres[v.name];if(!res){runView(v.name)}
 const body=!res||res.loading?`<p><span class="spin"></span> Working…</p>`:res.error?`<p class="msg err">${esc(res.error)}</p>`:renderBlocks(res.blocks);
 setMain('x:'+v.name,`<div class="toolbar"><h1>${esc(v.title)}</h1><span class="muted" style="font-size:12.5px">${esc(v.summary)}</span><span style="flex:1"></span><span class="tag">plugin · ${esc(v.origin.replace(/^file /,''))}</span><a class="btn" href="/models?m=view|${encodeURIComponent(v.name)}" data-nav>Manage</a></div>${v.inputs.length?`<div class="vbar" id="vbar"></div>`:''}<div class="view"><div class="page" id="vbody"></div></div>`);
 if(v.inputs.length){const h=viewInputs(v);if($('vbar')._h!==h){$('vbar').innerHTML=h;$('vbar')._h=h}}
 if($('vbody')._h!==body){$('vbody').innerHTML=body;$('vbody')._h=body}
}

// ---- shortlist -------------------------------------------------------------------------------
function renderShortlist(){
 const all=Object.values(S.dec);
 const col=(k,title,help)=>{const items=all.filter(d=>d.status===k).sort((a,b)=>b.updated.localeCompare(a.updated));
  return `<section class="col"><header><b>${title}</b><span>${items.length}</span><p>${help}</p></header>${items.map(d=>{const f=d.flag,g=gapOf(f);
   return `<button class="card" data-open="${d.id}"><b>${esc(f.place)}, ${esc(f.state)}</b><span class="m">${esc(String(f.weapon).toLowerCase())} · ${who(f.sex)} · ${yrs(f.start,f.end)} · <span class="num">${pct(f.solved/f.total)} vs ${pct(f.expected)} (${gapTxt(g)})</span></span>${d.reviewer?`<span class="m">reviewed by ${esc(d.reviewer)}</span>`:''}${d.note?`<span class="nt">${esc(d.note)}</span>`:''}</button>`}).join('')||`<p class="muted" style="padding:10px 12px;margin:0;font-size:12.5px">Nothing here yet.</p>`}</section>`};
 const dis=all.filter(d=>d.status==='dismissed');
 setMain('short:'+JSON.stringify(S.dec).length,`<div class="view"><div class="page" style="max-width:1280px">
  <h1>Shortlist</h1><p class="lede">Flags you kept, on their way to MAP. Open one to add notes, record the second review and export it.</p>
  ${all.length?'':`<p class="msg">Your shortlist is empty. On <a href="/flags" data-nav>Flags</a>, select a flag and press <b>Keep for review</b> (or <kbd>s</kbd>).</p>`}
  <div class="board">${col('kept','To review','Kept by you. Ask a second person to review it.')}${col('reviewed','Reviewed','A second person checked it. Export it for MAP.')}${col('sent','Sent to MAP','Handed off. Keep notes on any reply.')}</div>
  ${dis.length?`<h3>Dismissed (${dis.length})</h3><table><tbody>${dis.map(d=>`<tr class="click" data-open="${d.id}"><td>${esc(d.flag.place)}, ${esc(d.flag.state)}</td><td class="muted">${esc(String(d.flag.weapon).toLowerCase())} · ${yrs(d.flag.start,d.flag.end)}</td><td class="muted">${esc(day(d.updated))}</td></tr>`).join('')}</tbody></table>`:''}
 </div></div>`);
}

// ---- places ----------------------------------------------------------------------------------
async function placeData(key,url){if(!S.places[key]){S.places[key]={loading:true};try{S.places[key]=await api(url)}catch(e){S.places[key]={error:e.message}}render()}return S.places[key]}
function renderPlaces(r){
 const sex=S.f.sex,sexSeg=`<div class="seg" role="group">${[['Female','Women'],['Male','Men'],['all','Both']].map(([v,l])=>`<button data-f="sex" data-v="${v}" aria-pressed="${sex===v}">${l}</button>`).join('')}</div>`;
 const wrap=(crumb,body)=>setMain('places:'+location.pathname+sex+body.length,`<div class="view"><div class="page">${crumb}${body}</div></div>`);
 const loadingOr=(d)=>d.loading?`<p><span class="spin"></span> Reading the case file…</p>`:d.error?`<p class="msg err">${esc(d.error)}</p>`:null;
 if(!r.a){
  placeData('states'+sex,'/api/places?sex='+sex).then(()=>{});const d=S.places['states'+sex];
  const body=loadingOr(d)??`<table><thead><tr><th>State</th><th class="n">Killings</th><th class="n">Solved</th><th class="n">Flags (high + strong)</th></tr></thead><tbody>${d.sort((a,b)=>b.flags-a.flags||b.killings-a.killings).map(x=>`<tr class="click" data-href="/places/${slug(x.state)}"><td>${esc(x.state)}</td><td class="n">${nf.format(x.killings)}</td><td class="n">${pct(x.solved/x.killings)}</td><td class="n">${x.flags}</td></tr>`).join('')}</tbody></table>`;
  return wrap(`<div class="row" style="justify-content:space-between"><div><h1>Places</h1><p class="lede">Every state's record: how many killings, how many solved, how many flags. Open one for its counties and trends.</p></div>${sexSeg}</div>`,body);
 }
 const state=(S.flags||[]).map(x=>x.state).find(s=>s&&slug(s)===r.a)||(S.places['states'+sex]||[]).map?.(x=>x.state).find(s=>slug(s)===r.a)||r.a;
 if(!r.b){
  placeData('st:'+state+sex,`/api/place?state=${encodeURIComponent(state)}&sex=${sex}`);const d=S.places['st:'+state+sex];
  const crumb=`<div class="crumb"><a href="/places" data-nav>Places</a> › <b>${esc(state)}</b></div>`;
  const body=loadingOr(d)??(()=>{const k=d.counties.reduce((a,c)=>a+c.killings,0),s=d.counties.reduce((a,c)=>a+c.solved,0);
   return `<div class="row" style="justify-content:space-between;margin:6px 0 4px"><h1>${esc(state)}</h1><div class="row">${sexSeg}<a class="btn primary" href="/flags" data-nav data-scope="${esc(state)}">See flags in ${esc(state)}</a></div></div>
   <p class="lede"><span class="num">${nf.format(k)}</span> killings of ${who(sex)} 12 and older, <span class="num">${pct(s/k)}</span> solved.</p>
   <div class="chart heat" id="trend"></div>
   <h3>Counties</h3>${d.population_source?`<p class="muted" style="font-size:12.5px">Per 100,000 people a year uses population from your dataset “${esc(d.population_source)}”, over the years it covers.</p>`:''}<table><thead><tr><th>County</th><th class="n">Killings</th><th class="n">Solved</th>${d.population_source?'<th class="n">Per 100,000 a year</th>':''}<th class="n">Flags</th></tr></thead><tbody>${d.counties.sort((a,b)=>b.flags-a.flags||b.killings-a.killings).map(c=>`<tr class="click" data-href="/places/${slug(state)}/${slug(c.county)}"><td>${esc(c.county)}</td><td class="n">${nf.format(c.killings)}</td><td class="n">${pct(c.solved/c.killings)}</td>${d.population_source?`<td class="n">${c.per_100k!=null?c.per_100k.toFixed(1):'—'}</td>`:''}<td class="n">${c.flags||''}</td></tr>`).join('')}</tbody></table>`})();
  const changed=wrap(crumb,body);if(d&&d.trend&&changed)drawTrend(d.trend);return;
 }
 const st=S.places['st:'+state+sex];
 if(!st){placeData('st:'+state+sex,`/api/place?state=${encodeURIComponent(state)}&sex=${sex}`);return wrap('',`<p><span class="spin"></span> Loading…</p>`)}
 if(st.loading||st.error)return wrap('',loadingOr(st));
 const county=(st.counties.find(c=>slug(c.county)===r.b)||{}).county||r.b;
 placeData('ct:'+state+county+sex,`/api/place?state=${encodeURIComponent(state)}&county=${encodeURIComponent(county)}&sex=${sex}`);const d=S.places['ct:'+state+county+sex];
 const here=(S.flags||[]).filter(f=>f.state===state&&(sex==='all'||f.sex===sex)&&(f.counties||[f.county]).includes(county)&&f.confidence!=='possible');
 const body=loadingOr(d)??`<div class="row" style="justify-content:space-between;margin:6px 0 4px"><h1>${esc(county)}</h1>${sexSeg}</div>
  <p class="lede"><span class="num">${nf.format(d.killings)}</span> killings of ${who(sex)} 12 and older, <span class="num">${pct(d.solved/d.killings)}</span> solved${d.per_100k!=null?`, <span class="num">${d.per_100k.toFixed(1)}</span> per 100,000 people a year (population from “${esc(d.population_source)}”)`:''}. Each square is a year and method; red means few were solved, blue means most were.</p>
  <div class="chart heat" id="heat"></div>
  <h3>Flags here (${here.length})</h3>${here.length?`<table><tbody>${here.map(f=>`<tr class="click" data-href="/flags/${f.id}"><td><span class="tag ${f.confidence}">${CONF[f.confidence]}</span></td><td>${esc(f.place)}</td><td class="muted">${esc(String(f.weapon).toLowerCase())} · ${who(f.sex)} · ${yrs(f.start,f.end)}</td><td class="n" style="color:var(--red)">${gapTxt(gapOf(f))}</td></tr>`).join('')}</tbody></table>`:`<p class="muted">No high or strong flags for ${who(sex)} here.</p>`}
  <h3>Largest agencies</h3><table><thead><tr><th>Agency</th><th class="n">Killings</th><th class="n">Solved</th></tr></thead><tbody>${d.agencies.map(a=>`<tr><td>${esc(a.agency)}</td><td class="n">${nf.format(a.killings)}</td><td class="n">${pct(a.solved/a.killings)}</td></tr>`).join('')}</tbody></table>`;
 const changed=wrap(`<div class="crumb"><a href="/places" data-nav>Places</a> › <a href="/places/${slug(state)}" data-nav>${esc(state)}</a> › <b>${esc(county)}</b></div>`,body);
 if(d&&d.cells&&changed)drawHeat(d);
}
function drawTrend(t){const el=$('trend');if(!el)return;const W=el.clientWidth-24||700,H=150,L=34,B=18,T=8;const y0=t[0][0],y1=t[t.length-1][0],cw=(W-L-8)/(y1-y0+1);
 let p='';t.forEach(([y,n,s])=>{p+=`${p?'L':'M'}${L+(y-y0)*cw+cw/2},${T+(1-s/n)*(H-T-B)}`});
 let ax='';for(let y=Math.ceil(y0/5)*5;y<=y1;y+=5)ax+=`<text x="${L+(y-y0)*cw+cw/2}" y="${H-4}" text-anchor="middle">${y}</text>`;
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="height:${H}px" role="img" aria-label="Share solved by year"><text x="${L-6}" y="${T+8}" text-anchor="end">100%</text><text x="${L-6}" y="${H-B}" text-anchor="end">0%</text><path d="${p}" fill="none" stroke="var(--solved)" stroke-width="2"/>${ax}</svg><div class="key"><span>Share solved, by year</span></div>`}
function drawHeat(d){const el=$('heat');if(!el)return;const [Y0,Y1]=d.years,W=el.clientWidth-24||700,H=260,L=86,B=18,ws=d.weapons,rh=(H-B-4)/ws.length,cw=(W-L-6)/(Y1-Y0+1);
 const maxn=Math.max(1,...d.cells.map(c=>c[2]));let h='';
 ws.forEach((w,i)=>{h+=`<text x="${L-8}" y="${4+i*rh+rh/2+4}" text-anchor="end">${esc(w.replace('Strangle/asphyxia','Strangle').replace('Beating/blunt','Beating').replace('Other/unknown','Other').replace('Not reported','Not rep.'))}</text>`});
 d.cells.forEach(([w,y,n,s])=>{const p=s/n,col=p<.5?`color-mix(in oklab,var(--red) ${Math.round((1-p*2)*100)}%,var(--pale))`:`color-mix(in oklab,var(--solved) ${Math.round((p-.5)*200)}%,var(--pale))`;
  h+=`<rect x="${L+(y-Y0)*cw+.5}" y="${4+w*rh+.5}" width="${Math.max(cw-1,1)}" height="${rh-1}" fill="${col}" opacity="${(.35+.65*Math.sqrt(n/maxn)).toFixed(2)}" data-tip="${esc(`<b>${ws[w]} · ${y}</b>\n${n} killings: ${s} solved, ${n-s} unsolved (${Math.round(p*100)}% solved)`)}"/>`});
 for(let y=Math.ceil(Y0/5)*5;y<=Y1;y+=5)h+=`<text x="${L+(y-Y0)*cw+cw/2}" y="${H-3}" text-anchor="middle">${y}</text>`;
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Share solved by method and year">${h}</svg>`}

// ---- models (plugins) ------------------------------------------------------------------------
async function loadPlugins(){try{S.pl=await api('/api/plugins')}catch(e){S.plErr=e.message}render()}
async function plugin(action,params,body){
 S.plMsg=null;try{const j=await post('/api/plugins/'+action+(params?'?'+new URLSearchParams(params):''),body);S.pl=j;
  if(j.added){const pr=j.added.provides[0];S.plMsg={ok:1,html:`Added <b>${esc(j.added.file)}</b>: ${j.added.provides.map(x=>`${esc(x.kind)} <code>${esc(x.name)}</code>`).join(', ')}, switched on. Re-scan every state to see it in your flags.`};
   S.mAdd=false;if(pr)S.mSel={kind:pr.kind,name:pr.name};if(action==='starter')post('/api/plugins/open?file='+encodeURIComponent(j.added.file)).catch(()=>{})}
  else if(action==='remove'){S.plMsg={ok:1,html:'Removed.'};S.mSel=null}
  else S.plMsg={ok:1,html:action==='param'||action==='reset'?'Setting saved. Re-scan every state to apply it to your flags.':'Saved. Re-scan every state to apply it to your flags.'};
  S.mCode=null;S.views=null;S.viewsLoading=0;S.vres={};S.detail={};
 }catch(e){S.plMsg={ok:0,html:esc(e.message)}}
 await poll();
}
function renderModels(r){
 if(r.a==='guide')return renderGuide();
 const mq=new URLSearchParams(location.search).get('m')||(S.usedM?null:wantModel);S.usedM=1;
 if(mq&&mq!==S.mLastQ){S.mLastQ=mq;const [kind,...rest]=mq.split('|');S.mSel={kind,name:rest.join('|')};S.mAdd=false}
 if(!S.pl){if(!S.plLoading){S.plLoading=1;loadPlugins()}setMain('models-load',`<div class="view"><div class="page"><span class="spin"></span> Loading…</div></div>`);return}
 const pl=S.pl,job=S.st.job,busy=job&&job.running,n=S.st.national,q=(S.mQ||'').toLowerCase();
 const grp=k=>pl.groups.find(x=>x.kind===k)||{items:[]};
 const match=i=>!q||(i.name+' '+i.summary).toLowerCase().includes(q);
 const tagFor=o=>o.startsWith('file ')?`<span class="tag kept">your file</span>`:o.startsWith('package ')?`<span class="tag">${esc(o)}</span>`:`<span class="tag">built in</span>`;
 const row=(kind,i)=>{const sel=S.mSel&&S.mSel.kind===kind&&S.mSel.name===i.name;
  return `<button class="mrow${i.on===false?' off':''}" data-msel="${kind}|${esc(i.name)}" aria-selected="${sel}"><span class="n">${esc(i.name)}${tagFor(i.origin)}${i.tier?`<span class="tag">${esc(i.tier)}</span>`:''}</span><span class="s">${esc(i.summary)}</span>
   <span class="a">${i.on==null?'':i.locked?'<span class="tag">always on</span>':`<span class="sw" role="switch" tabindex="0" aria-checked="${i.on}" aria-label="Use ${esc(i.name)}" data-kind="${kind}" data-name="${esc(i.name)}"></span>`}</span></button>`};
 const bad=pl.files.filter(f=>f.error);
 const ALSO={fix:'Data fixes',source:'Data sources',preset:'Presets','region set':'Region sets',check:'Data-quality checks'};
 const det=grp('detector').items.filter(match),enr=grp('enricher').items.filter(match);
 const others=pl.groups.filter(g=>ALSO[g.kind]).map(g=>({g,items:g.items.filter(match)})).filter(x=>x.items.length);
 const on=k=>grp(k).items.filter(i=>i.on).length;
 const list=`${bad.length?`<div class="mgrp"><span>Need attention</span><span>${bad.length}</span></div>${bad.map(f=>`<button class="mrow bad" data-msel="file|${esc(f.file)}" aria-selected="${S.mSel&&S.mSel.name===f.file}"><span class="n">${esc(f.file)}</span><span class="s">Couldn't load: ${esc(f.error)}</span></button>`).join('')}`:''}
  <div class="mgrp"><span>Find flags · detectors</span><span>${on('detector')} on</span></div>${det.map(i=>row('detector',i)).join('')||'<p class="empty">No match.</p>'}
  <div class="mgrp"><span>Add context · enrichers</span><span>${on('enricher')} on</span></div>${enr.map(i=>row('enricher',i)).join('')||'<p class="empty">No match.</p>'}
  <div class="mgrp"><span>App pages and sections · views</span><span>${on('view')} on</span></div>${grp('view').items.filter(match).map(i=>row('view',i)).join('')||'<p class="empty" style="padding:12px 14px;text-align:left">None yet. Add the Agency report example, or create a page starter.</p>'}
  ${others.map(({g,items})=>`<div class="mgrp"><span>${ALSO[g.kind]}</span><span>${items.length}</span></div>${items.map(i=>row(g.kind,i)).join('')}`).join('')}`;
 const banner=(n&&n.stale?`<div class="row" style="padding:8px 16px;border-bottom:1px solid var(--line);background:color-mix(in oklab,var(--amber) 9%,var(--surf));font-size:13px">Your flags were made with different models or settings. <button class="btn" id="rescan"${busy?' disabled':''}>Re-scan every state</button><span class="muted">about 5 minutes</span></div>`:'')+
  (S.plMsg?`<div style="padding:8px 16px;border-bottom:1px solid var(--line)"><span class="msg ${S.plMsg.ok?'ok':'err'}" role="${S.plMsg.ok?'status':'alert'}" style="display:block">${S.plMsg.html}</span></div>`:'')+
  (busy?`<div style="padding:8px 16px;border-bottom:1px solid var(--line);font-size:13px" class="muted">Models can be changed once this finishes: ${esc(job.title)}.</div>`:'');
 const key='models:'+JSON.stringify(pl).length+'|'+JSON.stringify([S.mSel,S.mAdd,S.mQ,S.plMsg,busy,n&&n.stale,S.mCode&&S.mCode.name]);
 const fresh=setMain('models',`<div class="toolbar"><h1>Models</h1><input class="inp" id="mQ" type="search" placeholder="Find a model" aria-label="Find a model" value="${esc(S.mQ||'')}" style="width:200px"><span class="muted" style="font-size:12.5px">${on('detector')} detectors and ${on('enricher')} enrichers on · ${pl.files.length} file${pl.files.length===1?'':'s'} of your own</span><span style="flex:1"></span><a class="btn" href="/models/guide" data-nav>Plugin guide</a><button class="btn primary" id="mAddBtn">Add a model</button></div><div id="mBanner"></div><div class="split open-both" id="msplit"><div class="list" id="mList"></div><div class="flag" id="mDetail"></div></div>`);
 const putIn=(id,h)=>{const el=$(id);if(el._h!==h){const sc=el.scrollTop;el.innerHTML=h;el._h=h;el.scrollTop=sc}};
 const keepQ=document.activeElement&&document.activeElement.id==='mQ',caret=keepQ?document.activeElement.selectionStart:0;
 putIn('mBanner',banner);putIn('mList',list);putIn('mDetail',S.mAdd?modelAdd(pl,busy):modelDetail(pl,busy));
 if(keepQ&&$('mQ')){$('mQ').focus();$('mQ').setSelectionRange(caret,caret)}
}
function modelAdd(pl,busy){
 const dis=busy?' disabled':'';
 return `<div class="fpage"><h1>Add a model</h1><p class="lede">A model is Python code that runs on your computer with access to your files. Add only ones from people you trust, and read the file first.</p>
  <ul class="plist">
   ${[['before_after.py','Example: Before &amp; after','Adds context: solve rates in the years before and after each flag, to tell a short drop from a long-running problem.'],
      ['agency_report.py','Example: Agency report','Adds a page and a section: an Agencies page ranking police agencies by their gap below the state, and an “Agency record” section on every flag.']].map(([f,t,d])=>{const ex=(pl.examples||[]).find(x=>x.file===f)||{};
     return `<li><span class="t">${t}</span><span class="d">${d} Written as a tutorial: <a href="/guide/${f}" target="_blank" rel="noopener">read its code</a>.</span><span class="a">${ex.added?'<span class="tag kept">added</span>':`<button class="btn" data-pa="example" data-pname="${f}"${dis}>Add</button>`}</span></li>`}).join('')}
   <li><span class="t">A file someone shared</span><span class="d">A single <code>.py</code> file.</span><span class="a"><input type="file" id="pFile" accept=".py" hidden><button class="btn" id="pPick"${dis}>Choose file…</button></span></li>
   <li><span class="t">From a link</span><span class="d"><span class="row"><input class="inp" id="pUrl" type="url" placeholder="https://github.com/…/my_model.py" aria-label="Link to a model file" style="flex:1"><button class="btn" id="pLink"${dis}>Add</button></span></span></li>
   <li><span class="t">Write your own</span><span class="d">A starter file with each part explained, in your models folder. It opens in your editor. Start from a model that adds context to flags, or from a new page for the app.</span><span class="a"><button class="btn" data-pa="starter" data-pkind="enricher"${dis}>Context starter</button><button class="btn" data-pa="starter" data-pkind="page"${dis}>Page starter</button></span></li>
  </ul><div class="row" style="margin-top:14px"><button class="btn" data-popen="">Open your models folder</button><button class="btn" id="mAddClose">Done</button></div></div>`;
}
function modelDetail(pl,busy){
 const sel=S.mSel;
 if(!sel)return `<div class="empty" style="padding-top:80px"><p><b>Select a model</b> to see what it does, how much of your research it shaped, its settings and its code.</p><p>Switch any detector or enricher on or off from the list. Your own files can be opened in your editor, replaced or removed.</p></div>`;
 const dis=busy?' disabled':'';
 if(sel.kind==='file'){const f=pl.files.find(x=>x.file===sel.name);if(!f)return '';
  return `<div class="fpage"><h1>${esc(f.file)}</h1><p class="msg err"><b>coldmap couldn't load this file.</b> ${esc(f.error)}</p><p class="muted">Open it in your editor, fix the problem and save; coldmap reloads it next time it starts or when you replace it here.</p>
   <div class="row"><button class="btn primary" data-popen="${esc(f.file)}">Open in your editor</button><button class="btn" data-preplace="${esc(f.file)}"${dis}>Replace with a new version…</button><button class="btn" data-rm="${esc(f.file)}"${dis}>Remove</button></div></div>`}
 const g=pl.groups.find(x=>x.kind===sel.kind),i=g&&g.items.find(x=>x.name===sel.name);if(!i)return '';
 const file=i.origin.startsWith('file ')?i.origin.slice(5):null;
 const flags=S.flags||[];let effect='';
 if(sel.kind==='detector'){const c=flags.filter(f=>(f.by||[]).includes(i.name)).length;effect=S.flags?`Found <b class="num">${nf.format(c)}</b> of your <span class="num">${nf.format(flags.length)}</span> flags${c?` (${Math.round(c/flags.length*100)}%)`:''}${i.on?'':' in the last scan; it is off now'}.`:''}
 else if(sel.kind==='enricher'){const c=flags.filter(f=>(f.plugins||[]).some(x=>x.by===i.name)).length;effect=c?`Wrote notes on <b class="num">${nf.format(c)}</b> of your flags.`:i.locked?'Runs on every flag; other steps rely on it.':`No notes on your current flags${i.on?'':' (it is off)'}; re-scan after switching it on.`}
 const params=(i.params||[]);
 const ptable=params.length?`<h3>Settings</h3><p class="muted" style="font-size:12.5px">Change a value and press Enter. Your flags are marked out of date until you re-scan.</p><table class="params"><thead><tr><th>Setting</th><th>Value</th><th>Default</th><th></th></tr></thead><tbody>${params.map(p=>`<tr class="${p.changed?'changed':''}"><td><code>${esc(p.name)}</code><br><span class="muted" style="font-size:12px">${esc(p.help)}</span></td>
   <td><input class="inp" data-param="${esc(p.name)}" data-det="${esc(i.name)}" value="${esc(Array.isArray(p.value)?p.value.join(', '):p.value??'')}" aria-label="${esc(p.name)}"${dis}></td><td class="num muted">${esc(Array.isArray(p.default)?p.default.join(', '):p.default??'none')}</td>
   <td>${p.changed?`<button class="btn" data-pdefault="${esc(p.name)}" data-det="${esc(i.name)}"${dis}>Default</button>`:''}</td></tr>`).join('')}</tbody></table>
   ${params.some(p=>p.changed)?`<div class="row" style="margin-top:8px"><button class="btn" data-preset="${esc(i.name)}"${dis}>Reset all settings</button></div>`:''}`:'';
 const code=S.mCode&&S.mCode.name===i.name&&S.mCode.kind===sel.kind?S.mCode:null;
 return `<div class="fpage">
  <div class="row" style="justify-content:space-between"><h1 style="font-family:var(--mono);font-size:19px">${esc(i.name)}</h1>
   ${i.on==null?'':i.locked?'<span class="tag">always on</span>':`<label class="row" style="gap:8px;font-weight:600">${i.on?'On':'Off'} <span class="sw" role="switch" tabindex="0" aria-checked="${i.on}" aria-label="Use ${esc(i.name)}" data-kind="${sel.kind}" data-name="${esc(i.name)}"></span></label>`}</div>
  ${sel.kind==='view'&&i.place==='page'&&i.on?`<p><a class="btn primary" href="/x/${encodeURIComponent(i.name)}" data-nav>Open the page</a></p>`:''}
  ${sel.kind==='view'?`<p class="muted" style="font-size:12.5px">${i.place==='page'?`Adds a page to the sidebar, under ${esc(i.group)}.`:'Adds a section to every flag\'s page.'} Switching a view on or off doesn't change your flags.</p>`:''}
  <div class="row" style="margin:4px 0 10px"><span class="tag">${esc({detector:'finds flags',enricher:'adds context',view:'adds to the app'}[sel.kind]||sel.kind)}</span>${i.tier?`<span class="tag">${esc(i.tier)}</span>`:''}<span class="tag${file?' kept':''}">${esc(file?'your file: '+file:i.origin)}</span></div>
  <p><b>${esc(i.summary)}</b></p>${i.doc?`<div class="notes">${esc(i.doc).split(/\n\s*\n/).map(x=>`<p style="white-space:pre-line">${x}</p>`).join('')}</div>`:''}
  ${effect?`<h3>In your research</h3><p>${effect}</p>`:''}
  ${ptable}
  ${file?`<h3>Your file</h3><div class="row"><button class="btn primary" data-popen="${esc(file)}">Open in your editor</button><button class="btn" data-popen="">Open the folder</button><button class="btn" data-preplace="${esc(file)}"${dis}>Replace with a new version…</button><button class="btn" data-rm="${esc(file)}"${dis}>Remove</button></div><p class="muted" style="font-size:12px;margin-top:6px">After editing the file, press Replace and choose it, or restart coldmap, then re-scan.</p>`:''}
  <h3>Code</h3>${code?`<pre class="code">${esc(code.code)}</pre>${code.path?`<p class="muted" style="font-size:12px">${esc(code.path)}</p>`:''}`:`<button class="btn" data-pcode="${sel.kind}|${esc(i.name)}">Show the code</button>`}
 </div>`;
}
async function renderGuide(){
 if(!S.guide){setMain('guide-load',`<div class="view"><div class="page"><span class="spin"></span> Loading the guide…</div></div>`);try{S.guide=md(await (await fetch('/guide.md')).text())}catch(e){S.guide='<p class="msg err">The guide could not be loaded.</p>'}}
 setMain('guide',`<div class="view"><div class="page"><div class="crumb"><a href="/models" data-nav>Models</a> › <b>Plugin guide</b></div><article class="doc" style="margin-top:12px">${S.guide}</article></div></div>`);
}
const REPO='https://github.com/jamesdesantiago/coldmap/blob/main/';
function mdHref(h){if(/^https?:/.test(h))return h;{const m=h.match(/^\.\.\/examples\/([a-z_]+\.py)$/);if(m)return '/guide/'+m[1]}return REPO+h.replace(/^(\.\.\/)+/,'')}
function mdText(t){return t.split(/(`[^`]+`)/).map(p=>/^`[^`]+`$/.test(p)?`<code>${esc(p.slice(1,-1))}</code>`:esc(p).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[^*])\*([^*\s][^*]*)\*/g,'$1<i>$2</i>')).join('')}
function mdInline(t){const links=[];t=t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,(m,txt,href)=>{const u=mdHref(href),ext=/^https?:|\.py$/.test(u);links.push(`<a href="${esc(u)}"${ext?' target="_blank" rel="noopener"':''}>${mdText(txt)}</a>`);return `\u0000${links.length-1}\u0000`});return mdText(t).replace(/\u0000(\d+)\u0000/g,(m,i)=>links[+i])}
function md(src){const lines=src.replace(/\r/g,'').split('\n');let out='',i=0;const para=[];const flush=()=>{if(para.length){out+=`<p>${mdInline(para.join(' '))}</p>`;para.length=0}};
 while(i<lines.length){const l=lines[i];
  if(/^```/.test(l)){flush();const c=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))c.push(lines[i++]);i++;out+=`<pre><code>${esc(c.join('\n'))}</code></pre>`;continue}
  const h=l.match(/^(#{1,3}) (.*)/);if(h){flush();out+=`<h${h[1].length}>${mdInline(h[2])}</h${h[1].length}>`;i++;continue}
  if(/^> /.test(l)){flush();const q=[];while(i<lines.length&&/^> ?/.test(lines[i]))q.push(lines[i++].replace(/^> ?/,''));out+=`<blockquote><p>${mdInline(q.join(' '))}</p></blockquote>`;continue}
  if(/^(- |\d+\. )/.test(l)){flush();const ord=/^\d/.test(l),it=[];while(i<lines.length&&/^(- |\d+\. )/.test(lines[i])){let x=lines[i++].replace(/^(- |\d+\. )/,'');while(i<lines.length&&/^ {2,}\S/.test(lines[i]))x+=' '+lines[i++].trim();it.push(x)}out+=`<${ord?'ol':'ul'}>${it.map(x=>`<li>${mdInline(x)}</li>`).join('')}</${ord?'ol':'ul'}>`;continue}
  if(!l.trim()){flush();i++;continue}para.push(l.trim());i++}
 flush();return out}

// ---- AI assistants ---------------------------------------------------------------------------
function renderAI(){
 if(!S.ai){if(!S.aiLoading){S.aiLoading=1;api('/api/ai').then(j=>{S.ai=j;S.aiLoading=0;render()})}setMain('ai-load',`<div class="view"><div class="page"><span class="spin"></span> Loading…</div></div>`);return}
 const a=S.ai,json=JSON.stringify(a.desktop,null,2),ds=a.desktop_status,T=S.aiTest,C=S.aiConn,K=S.aiCode;
 const testMsg=T==='run'?'<p class="msg"><span class="spin"></span> Starting coldmap\'s AI server the way Claude will…</p>':T?(T.ok?`<p class="msg ok"><b>Working.</b> ${T.tools.length} tools answer${T.flags!=null?`, and it can read your ${nf.format(T.flags)} flags`:''}.</p>`:`<p class="msg err"><b>It didn't start.</b> <code style="white-space:pre-wrap">${esc(T.error)}</code></p>`):'';
 const deskState=ds.problem?`<p class="msg warn">${esc(ds.problem)}</p>`:ds.current?`<p class="msg ok"><b>Connected.</b> coldmap is in Claude Desktop's settings. If you just connected, quit Claude Desktop completely and open it again.</p>`:ds.connected?`<p class="msg warn">Claude Desktop has an older coldmap setting. Connect again to update it.</p>`:'';
 setMain('ai:'+JSON.stringify([ds,T,C,K]),`<div class="view"><div class="page">
  <h1>AI assistants</h1><p class="lede">Connect Claude to coldmap. It can read the same flags, shortlist and datasets you see, explain why a place was flagged, pull the case rows, check the data's known problems and run models. Every answer carries the ethics notice, and it can't send anything or contact anyone; you stay the one who decides.</p>
  ${a.sdk_installed?'':`<p class="msg warn">The MCP library isn't installed in this copy of coldmap, so the setup uses uvx to run coldmap with it (<code>coldmap[mcp]</code>).</p>`}
  <div class="box"><h2>1. Check the connection</h2><p class="muted">Starts coldmap's AI server exactly as Claude will and asks it for your flags.</p>${testMsg}<button class="btn" id="aiTest"${T==='run'?' disabled':''}>Run the check</button></div>
  <div class="box"><h2>2. Claude Desktop</h2><p class="muted">One click adds coldmap to Claude Desktop's settings. Your existing settings are kept, and the old file is saved as a backup first.</p>
   ${deskState}${C&&C.error?`<p class="msg err">${esc(C.error)}</p>`:''}${C&&!C.error?`<p class="msg ok"><b>Done.</b> ${C.repaired?'The file had two JSON objects pasted one after the other; they are now one, so Claude can read it. ':''}Now quit Claude Desktop completely (in the taskbar's hidden icons, right-click Claude › Quit, or File › Exit) and open it again. Then ask: <i>“Use coldmap to list the strongest flags in Ohio.”</i>${C.backup?`<br><span class="muted" style="font-size:12px">Backup: <code>${esc(C.backup)}</code></span>`:''}</p>`:''}
   <div class="row"><button class="btn primary" id="aiConnect"${C==='run'?' disabled':''}>${ds.connected?'Connect again':'Connect to Claude Desktop'}</button><span class="muted" style="font-size:12px">Settings file: <code>${esc(ds.path)}</code></span></div>
   <details style="margin-top:12px"><summary class="muted" style="cursor:pointer">Set it up by hand instead</summary><p class="muted" style="margin-top:8px">In Claude Desktop: Settings › Developer › Edit Config. Add <code>"mcpServers"</code> as another key inside the file's outer braces (one JSON object, not a second <code>{ … }</code> below the first), save, then quit and reopen Claude.</p><pre id="cfgDesk">${esc(json)}</pre><button class="btn" data-copy="cfgDesk">Copy</button></details></div>
  <div class="box"><h2>3. Claude Code</h2>${a.claude_code_installed?`<p class="muted">One click adds coldmap for every project.</p>${K==='run'?'<p class="msg"><span class="spin"></span> Adding…</p>':K?`<p class="msg ${K.ok?'ok':'err'}">${K.ok?'<b>Added.</b> Start a new Claude Code session to use it.':esc(K.error||K.output)}</p>`:''}<button class="btn" id="aiCode">Add to Claude Code</button>`:'<p class="muted">Claude Code isn\'t installed here. If you install it later, run this once in a terminal:</p>'}
   <details style="margin-top:10px"${a.claude_code_installed?'':' open'}><summary class="muted" style="cursor:pointer">The command</summary><pre id="cfgCode" style="margin-top:8px">${esc(a.claude_code)}</pre><button class="btn" data-copy="cfgCode">Copy</button></details></div>
  <h3>Things to ask</h3><ul class="notes" style="padding-left:18px">
   <li>“Which high-confidence flags for women in Ohio have the largest gap? Explain each in two sentences.”</li>
   <li>“Read my coldmap shortlist and list what a second reviewer should check for each lead.”</li>
   <li>“For the Multnomah strangulation flag, pull the case rows and tell me whether the dates cluster.”</li>
   <li>“Where does the case file miss the most reported murders in Florida?”</li></ul>
  <h3>Tools it gets</h3><table><tbody>${a.tools.map(([n,d])=>`<tr><td><code>${esc(n)}</code></td><td>${esc(d)}</td></tr>`).join('')}</tbody></table>
 </div></div>`);
}

// ---- methods ---------------------------------------------------------------------------------
function renderMethods(){
 if(!S.methods){if(!S.mLoading){S.mLoading=1;api('/api/methods').then(j=>{S.methods=j;render()})}setMain('m-load',`<div class="view"><div class="page"><span class="spin"></span> Loading…</div></div>`);return}
 const m=S.methods,states=[...new Set((S.flags||[]).map(f=>f.state).filter(Boolean))].sort();
 const qk=S.qState||'';const qd=qk?S.quality&&S.quality[qk]:null;
 if(!S.bench&&!S.benchLoading){S.benchLoading=1;api('/api/benchmark').then(j=>{S.bench=j;S.benchLoading=0;render()})}
 setTimeout(renderBench,0);
 setMain('methods:'+qk+(qd?Object.keys(qd).length:'x'),`<div class="view"><div class="page">
  <h1>Methods</h1><p class="lede">How a flag is made, how much to trust it, and how to make coldmap better. Everything here is open: the code, the tests and the false-alarm measurements.</p>
  <h3>How a flag is made</h3><ol class="notes" style="padding-left:18px">
   <li><b>Data.</b> MAP's case file: every homicide reported to the FBI's Supplementary Homicide Report since 1976. <b>Solved</b> means police identified an offender when the report was filed.</li>
   <li><b>Fixes.</b> Known reporting problems are corrected or marked before anything runs (listed below).</li>
   <li><b>Detectors.</b> For each place, victim sex and method, models compare how often killings were solved with the rest of the same state, year by year. The strict detector (scan) tests every window length and controls false discoveries; the sensitive one (window) catches more and invents more.</li>
   <li><b>Enrichers.</b> Each flag gets its county, the share of reported murders the case file actually holds, NamUs counts if loaded, and notes from plugins.</li>
   <li><b>Agreement.</b> Flags that more than one detector finds are labelled high confidence; one strict detector alone is strong; one sensitive detector alone is possible.</li>
   <li><b>Rule-out checks.</b> Every flag is checked against ordinary explanations: a known series that has been through the courts, agencies that reported murders to the FBI but sent no case records, clearance reports far above the case file's solve rate, and documented coding problems. The verdict is shown beside the flag, never used to hide it.</li></ol>
  <h3>Confidence levels</h3><table><tbody>${Object.entries(m.confidence).map(([k,v])=>`<tr><td><span class="tag ${k}">${CONF[k]}</span></td><td>${esc(v)}</td></tr>`).join('')}</tbody></table>
  <h3>Data fixes applied</h3><table><tbody>${m.fixes.map(f=>`<tr><td><b>${esc(f.title)}</b></td><td>${esc(f.summary)}</td></tr>`).join('')}</tbody></table>
  <h3>Data quality, by state</h3><div class="row"><select class="sel" id="qState" aria-label="State"><option value="">Choose a state</option>${states.map(s=>`<option${s===qk?' selected':''}>${esc(s)}</option>`).join('')}</select><span class="muted">Reporting gaps and oddities that can create or hide flags.</span></div>
  <div id="qBody" style="margin-top:10px">${qk?(qd?Object.entries(qd).map(([n,t])=>`<p style="margin:12px 0 4px"><b>${esc(n)}</b> <span class="muted">${esc(t.summary)}</span></p>${t.rows.length?`<table><thead><tr>${Object.keys(t.rows[0]).map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(r=>`<tr>${Object.values(r).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`:'<p class="muted">Nothing found.</p>'}`).join(''):'<p><span class="spin"></span> Checking…</p>'):''}</div>
  <h3>How well it works</h3><p>Two measurements keep coldmap honest. The <b>benchmark</b> checks which known series that went through the courts each model finds, using your current models and settings. <b>False-alarm tests</b> (<code>coldmap controls</code> in a terminal) shuffle the solved labels to count how many flags appear by chance. A model that catches more but invents more isn't an improvement.</p>
  <div class="box" id="benchBox"></div>
  <h3>Ethics</h3><ul class="notes" style="padding-left:18px"><li>A flag is a pattern worth review, never evidence that cases are linked. Only investigators can link cases.</li><li>Never contact families, witnesses or possible suspects.</li><li>Never describe a flag as a “serial killer”, name suspects, or profile neighbourhoods or groups.</li><li>A second person reviews every lead before it goes to MAP or the investigating agency.</li></ul>
  <h3>Improve the research</h3><ul class="notes" style="padding-left:18px"><li>Write a model: start from <a href="/models" data-nav>Models</a> › Write your own, then share it as a file or a package.</li><li>Add a known, adjudicated series to the benchmark so every model is measured against it: <a href="${REPO}CONTRIBUTING.md#add-a-known-series" target="_blank" rel="noopener">how</a>.</li><li>Document a data problem you found: <a href="${REPO}DATA_ISSUES.md" target="_blank" rel="noopener">DATA_ISSUES.md</a>.</li><li>Read the full guide for contributors: <a href="${REPO}CONTRIBUTING.md" target="_blank" rel="noopener">CONTRIBUTING.md</a>.</li></ul>
 </div></div>`);
}

function renderBench(){
 const el=$('benchBox');if(!el)return;const b=S.bench,job=S.st&&S.st.job,run=job&&job.running;
 if(!b){if(el._h!=='l'){el.innerHTML='<span class="spin"></span> Loading…';el._h='l'}return}
 const bj=job&&job.kind==='benchmark'&&(job.running||job.error)?job:null;
 const L=b.last,GR={full:['Found','reviewed'],partial:['Partly','strong']};
 const res=L?`<p class="muted" style="font-size:12.5px">Last run ${esc(day(L.generated))}${L.stale?' · <b>out of date</b>: your data, models or settings changed since':''}. <b>Found</b>: a flag covers most of the series' years. <b>Partly</b>: a flag touches it but mostly describes something else.</p>
  <div class="cases" style="max-height:none;margin-bottom:10px"><table><thead><tr><th>Series</th><th>Source</th>${L.detectors.map(d=>`<th>${esc(d==='ensemble'?'Combined':d)}</th>`).join('')}</tr></thead><tbody>
   ${L.series.map(r=>`<tr><td>${esc(r.label||r.county+', '+r.start+'–'+r.end)}</td><td class="muted">${esc(r.source==='built in'?'built in':'yours')}</td>${L.detectors.map(d=>{const x=r.results[d];return `<td>${x?`<span class="tag ${GR[x.grade][1]}" title="${esc(x.place+', '+x.weapon+' '+x.start+'–'+x.end)}">${GR[x.grade][0]}</span>`:'<span class="muted">Missed</span>'}</td>`}).join('')}</tr>`).join('')}
   <tr><td><b>Found or partly found</b></td><td></td>${L.detectors.map(d=>{const c=L.caught[d];return `<td class="num"><b>${c.full}</b> + ${c.partial} of ${c.of}</td>`}).join('')}</tr></tbody></table></div>`:'<p class="muted">Not run yet.</p>';
 const h=`<h2>Benchmark</h2><p>${b.built_in} series ship with coldmap${b.yours?`, plus <b>${b.yours}</b> of your own`:''}. Add your own adjudicated series with <code>coldmap series import FILE.csv</code>; they stay in <code>${esc(b.folder)}</code> on this computer.</p>
  ${b.problems.length?`<p class="msg warn">Some of your series were skipped: ${b.problems.slice(0,5).map(esc).join('; ')}${b.problems.length>5?'…':''}</p>`:''}
  ${bj?jobView(bj):res}
  <div class="row"><button class="btn${!L||L.stale?' primary':''}" id="benchRun"${run?' disabled':''}>${L?'Run it again':'Run the benchmark'}</button><span class="muted">about 6 minutes on the national file: each series' state is scanned</span></div>`;
 if(el._h!==h){el.innerHTML=h;el._h=h}
}

// ---- cities --------------------------------------------------------------------------------------
function loadCities(){if(S.citiesLoading)return;S.citiesLoading=1;api('/api/cities').then(j=>{S.cities=j;S.citiesLoading=0;render()}).catch(e=>{S.citiesLoading=0;toast(e.message)})}
function renderCities(r){
 const C=S.cities;if(!C){loadCities();return setMain('cities:l','<div class="view"><div class="page"><span class="spin"></span> Loading…</div></div>')}
 const sex=S.citySex||'all';
 const sexSeg=`<div class="seg" role="group" aria-label="Victims">${[['Female','Women'],['Male','Men'],['all','Both']].map(([v,l])=>`<button data-csex="${v}" aria-pressed="${sex===v}">${l}</button>`).join('')}</div>`;
 if(r.a)return renderCity(r.a,sex,sexSeg);
 const job=S.st&&S.st.job,cj=job&&job.kind==='cities'&&(job.running||job.error)?job:null,run=job&&job.running;
 const R=C.results,areas=R?R.areas.filter(a=>a.sex===sex):[];
 const intro=`<p class="lede">Areas of about 1 to 5 km within a city where killings were solved far less often than in the rest of the same city, in the same years. Uses city data you add: one row per killing with a location. Locations are kept only as cells of about 1 km, cells with fewer than ${C.min_shown} killings are never shown, and names, race, age and exact dates are left out on import.</p>`;
 const imp=S.cimp;
 const form=imp?`<div class="box"><h2>Add “${esc(imp.file)}”</h2>${imp.err?`<p class="msg err">${esc(imp.err)}</p>`:!imp.preview?'<span class="spin"></span> Reading…':(()=>{const pv=imp.preview;
   return `${pv.missing.length?`<p class="msg err">Couldn't find: ${esc(pv.missing.join(', '))}. City data needs a latitude, a longitude, a city, a date or year, and a status (solved, closed, arrest…).</p>`:`<p>${nf.format(pv.rows)} rows in ${pv.cities} cities.</p>`}
    <table><thead><tr><th>Column</th><th>Used as</th></tr></thead><tbody>${Object.entries(pv.columns).filter(([k,v])=>v).map(([k,v])=>`<tr><td><code>${esc(v)}</code></td><td>${esc({lat:'latitude, turned into a ~1 km cell',lon:'longitude, turned into a ~1 km cell',date:'date: year and month kept',year:'year',city:'city',state:'state',status:'solved or not',sex:'victim sex'}[k])}</td></tr>`).join('')}</tbody></table>
    ${pv.status_values?`<p class="muted" style="font-size:12.5px">Status: ${Object.entries(pv.status_values).map(([k,v])=>`“${esc(k)}” → <b>${esc(v)}</b>`).join(' · ')}</p>`:''}
    <h3>Left out, never stored</h3><ul>${Object.entries(pv.left_out).map(([c,why])=>`<li><code>${esc(c)}</code>: ${esc(why)}</li>`).join('')}</ul>
    <div class="row"><label>Name <input id="ciName" value="${esc(imp.name)}"></label><label style="flex:1">Source and terms <input id="ciSource" style="width:100%" value="${esc(imp.source??pv.source??'')}" placeholder="Who published it, and its licence"></label></div>
    <div class="row"><button class="btn primary" id="ciAdd"${pv.missing.length?' disabled':''}>Add it</button><button class="btn" id="ciCancel">Cancel</button></div>`})()}</div>`:'';
 const ds=C.datasets.length?`<table><thead><tr><th>City data</th><th class="n">Killings</th><th class="n">Cities</th><th>Years</th><th>Source</th><th></th></tr></thead><tbody>${C.datasets.map(m=>`<tr><td><b>${esc(m.name)}</b>${Object.keys(m.dropped||{}).length?`<br><span class="muted" style="font-size:12px">skipped: ${esc(Object.entries(m.dropped).map(([k,v])=>v+' '+k).join(', '))}</span>`:''}</td><td class="n">${nf.format(m.rows)}</td><td class="n">${m.cities}</td><td class="num">${m.years[0]}–${m.years[1]}</td><td style="font-size:12.5px">${esc(m.source||'not given')}</td><td><button class="btn" data-cirm="${esc(m.slug)}">Remove</button></td></tr>`).join('')}</tbody></table>`:`<p class="muted">No city data yet. Get The Washington Post’s data below, or add your own file: one row per killing with a location.</p>`;
 const add=imp?'':`<div class="row"><input type="file" id="ciFile" accept=".csv,text/csv" hidden><button class="btn${C.datasets.length?'':' primary'}" id="ciPick">Add city data (CSV)…</button></div>`;
 const scanRow=C.datasets.length?`<div class="row"><button class="btn${R?'':' primary'}" id="ciScan"${run?' disabled':''}>${R?'Scan again':'Scan cities'}</button><label style="display:inline-flex;gap:6px;align-items:center"><input type="checkbox" id="ciPeriods"${S.cityPeriods?' checked':''}> Also test periods of 1–5 years</label><span class="muted">${S.cityPeriods?'about 8 minutes; with many more areas and periods tried, one must stand out much further to count':'about 2–3 minutes'}</span></div>`:'';
 const res=!R?'':`<p class="muted" style="font-size:12.5px">Scanned ${esc(day(R.generated))}${R.settings.periods?', whole period and 1–5 year periods':', whole period'}; areas up to ${R.settings.radius_km} km from their centre, at least ${R.settings.min_cases} killings, false discovery rate ${R.settings.max_q}. ${R.areas.length} area${R.areas.length===1?'':'s'} in all.</p>
  ${areas.length?`<table><thead><tr><th>City</th><th>Years</th><th class="n">Killings</th><th class="n">Solved here</th><th class="n">Rest of city</th><th class="n">Across</th><th class="n">q</th></tr></thead><tbody>${areas.map(a=>`<tr class="click" data-href="/cities/${encodeURIComponent(a.city)}"><td><b>${esc(a.city)}</b></td><td class="num">${a.start}–${a.end}</td><td class="n">${a.killings}</td><td class="n"><b>${pct(a.solved/a.killings)}</b></td><td class="n">${a.rest_rate!=null?pct(a.rest_rate):'—'}</td><td class="n">${(2*a.radius_km).toFixed(0)} km</td><td class="n">${a.q_value.toFixed(3)}</td></tr>`).join('')}</tbody></table>`:`<p class="muted">No area stands out for ${who(sex)} once chance is accounted for.</p>`}`;
 const cityList=C.cities.length?`<h3>Every city</h3><p class="muted" style="font-size:12.5px">${C.cities.map(c=>`<a href="/cities/${encodeURIComponent(c)}" data-nav>${esc(c)}</a>`).join(' · ')}</p>`:'';
 return setMain('cities:'+sex+':'+(R?R.generated:'')+':'+(imp?JSON.stringify([imp.file,!!imp.preview,imp.err]):'')+':'+C.datasets.length+':'+(job&&job.kind==='cities-get'?job.id+job.running+(job.error||'')+job.steps.map(x=>x.done+'/'+x.total).join():'')+':'+(cj?cj.id+cj.steps.map(x=>x.done+'/'+x.total).join():'')+':'+!!S.cityPeriods+run,
  `<div class="view"><div class="page"><div class="row" style="justify-content:space-between"><div><h1>Cities</h1>${intro}</div>${sexSeg}</div>
   ${form}<div class="box"><h2>Your city data</h2>${ds}${(()=>{const have=C.datasets.some(m=>m.source&&m.source.startsWith('The Washington Post'));const gj=job&&job.kind==='cities-get'&&(job.running||job.error)?job:null;
   return gj?jobView(gj):`<div class="row" style="margin-top:10px"><button class="btn${C.datasets.length?'':' primary'}" id="ciWapo"${run?' disabled':''}>${have?'Get The Washington Post’s data again':'Get The Washington Post’s data'}</button><span class="muted" style="font-size:12.5px">${nf.format(52000)} homicides in 50 large cities, 2007–2017, about 4 MB. CC BY-NC-SA 4.0: non-commercial use, with credit. Names and exact locations are discarded as it’s imported.</span></div>`})()}${add}</div>
   ${C.datasets.length?`<div class="box"><h2>Areas</h2>${cj?jobView(cj):res}${scanRow}</div>`:''}
   ${cityList}
   <p class="muted" style="font-size:12.5px">An area is a pattern worth review, never evidence that killings are linked. Low clearance across a neighbourhood usually reflects how cases there are investigated and resourced; read it alongside what is known locally.</p></div></div>`);
}
function renderCity(city,sex,sexSeg){
 S.cgrid=S.cgrid||{};const k=city+'|'+sex,g=S.cgrid[k];
 if(!g){S.cgrid[k]='l';api('/api/cities/grid?city='+encodeURIComponent(city)+'&sex='+sex).then(j=>{S.cgrid[k]=j;render()}).catch(e=>toast(e.message))}
 const crumb=`<div class="crumb"><a href="/cities" data-nav>Cities</a> › <b>${esc(city)}</b></div>`;
 if(!g||g==='l')return setMain('city:l'+k,`<div class="view"><div class="page">${crumb}<span class="spin"></span> Loading…</div></div>`);
 const W=760,H=560;
 let svg='<p class="muted">No cells with enough killings to show.</p>';
 if(g.cells.length){
  const lat0=g.cells.reduce((a,c)=>a+c.lat,0)/g.cells.length,kx=Math.cos(lat0*Math.PI/180);
  const xs=g.cells.map(c=>c.lon*kx),ys=g.cells.map(c=>c.lat);
  const pad=.02,x0=Math.min(...xs)-pad,x1=Math.max(...xs)+pad,y0=Math.min(...ys)-pad,y1=Math.max(...ys)+pad;
  const sc=Math.min(W/(x1-x0),H/(y1-y0)),X=v=>(v*kx-x0)*sc,Y=v=>(y1-v)*sc;
  const cell=(1/110.574)*sc;
  const col=c=>{const r=c.solved/c.killings;return `color-mix(in oklab, var(--solved) ${Math.round(r*100)}%, var(--red))`};
  svg=`<svg viewBox="0 0 ${Math.ceil((x1-x0)*sc)} ${Math.ceil((y1-y0)*sc)}" style="width:100%;max-width:${W}px;height:auto;display:block" role="img" aria-label="Cells of about 1 km in ${esc(city)}, shaded by share solved">
   ${g.cells.map(c=>`<rect x="${(X(c.lon)-cell/2).toFixed(1)}" y="${(Y(c.lat)-cell/2).toFixed(1)}" width="${cell.toFixed(1)}" height="${cell.toFixed(1)}" fill="${col(c)}" opacity="${Math.min(1,.35+c.killings/40).toFixed(2)}" data-tip="${esc(c.killings+' killings, '+pct(c.solved/c.killings)+' solved')}"/>`).join('')}
   ${g.areas.map((a,i)=>`<circle cx="${X(a.lon).toFixed(1)}" cy="${Y(a.lat).toFixed(1)}" r="${(a.radius_km/110.574*sc).toFixed(1)}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-dasharray="5 3" data-tip="${esc(`Area ${i+1}: ${a.solved} of ${a.killings} solved (${pct(a.solved/a.killings)}), rest of city ${a.rest_rate!=null?pct(a.rest_rate):'—'}, ${a.start}–${a.end}`)}"/><text x="${X(a.lon).toFixed(1)}" y="${(Y(a.lat)+4).toFixed(1)}" text-anchor="middle" font-size="13" font-weight="700" fill="var(--ink)">${i+1}</text>`).join('')}
  </svg>`}
 const areas=g.areas.length?`<table><thead><tr><th>Area</th><th>Years</th><th class="n">Killings</th><th class="n">Solved here</th><th class="n">Rest of city</th><th class="n">q</th></tr></thead><tbody>${g.areas.map((a,i)=>`<tr><td><b>${i+1}</b>, about ${(2*a.radius_km).toFixed(0)} km across</td><td class="num">${a.start}–${a.end}</td><td class="n">${a.killings}</td><td class="n"><b>${pct(a.solved/a.killings)}</b></td><td class="n">${a.rest_rate!=null?pct(a.rest_rate):'—'}</td><td class="n">${a.q_value.toFixed(3)}</td></tr>`).join('')}</tbody></table>`:`<p class="muted">No area here stands out for ${who(sex)} in the last scan.</p>`;
 return setMain('city:'+k,`<div class="view"><div class="page">${crumb}<div class="row" style="justify-content:space-between"><div><h1>${esc(city)}</h1>
  <p class="lede">${nf.format(g.killings)} killings of ${who(sex)}, <span class="num">${pct(g.killings?g.solved/g.killings:0)}</span> solved. Each square is about 1 km, shaded from unsolved (red) to solved; fainter squares hold fewer killings. ${g.hidden_cells} cell${g.hidden_cells===1?'':'s'} with fewer than ${g.min_shown} killings ${g.hidden_cells===1?'is':'are'} hidden. Dashed circles are areas the scan found.</p></div>${sexSeg}</div>
  <div class="box">${svg}</div><div class="box"><h2>Areas</h2>${areas}</div></div></div>`);
}

// ---- data ------------------------------------------------------------------------------------
function renderData(){
 const st=S.st,job=st.job,busy=job&&job.running,n=st.national,ck=st.data.check;
 const files=st.data.files.filter(f=>f.path).map(f=>`<tr><td>${esc(f.label)}</td><td><code>${esc(f.name)}</code></td><td class="n">${f.present?mb(f.size):'missing'}</td><td>${esc(day(f.downloaded))}</td></tr>`).join('');
 const jobHtml=job&&(busy||job.error)&&['download','national','setup'].includes(job.kind)?`<div class="box">${jobView(job)}</div>`:'';
 if(!S.ds&&!S.dsLoading){S.dsLoading=1;api('/api/datasets').then(j=>{S.ds=j;S.dsLoading=0;render()})}
 setMain('data:'+JSON.stringify([st.data,n,job&&job.id,job&&job.steps,S.checking,S.ds,S.imp&&{...S.imp,text:0}]),`<div class="view"><div class="page">
  <h1>Data</h1><p class="lede">Where coldmap's data comes from and how current it is. Everything stays in <code>${esc(st.home)}</code>.</p>
  ${jobHtml}
  <div class="box"><h2>Source files</h2><p class="muted">${st.mode==='map'?"The Murder Accountability Project's public files.":st.mode==='sample'?'The synthetic sample: invented data with one planted series.':'Your own files.'}</p>
   <table><thead><tr><th>File</th><th>Name</th><th class="n">Size</th><th>Downloaded</th></tr></thead><tbody>${files}</tbody></table>
   ${st.mode==='map'?`<div class="row" style="margin-top:12px"><button class="btn" id="check"${busy||S.checking?' disabled':''}>${S.checking?'<span class="spin"></span> Checking…':'Check for updates'}</button>
   ${ck&&ck.error?`<span class="msg err">${esc(ck.error)}</span>`:ck&&ck.updates?`<span class="msg warn">MAP has published newer files.</span><button class="btn primary" id="update"${busy?' disabled':''}>Download the update</button>`:ck?'<span class="muted">Up to date with MAP.</span>':''}</div>`:''}</div>
  <div class="box"><h2>National scan</h2>${n?`<p>${nf.format(n.findings)} flags in ${n.states} states, made ${esc(day(n.generated))}${n.stale?'. <b>Out of date:</b> the data or your models changed since.':'.'}</p>`:'<p class="muted">Not run yet.</p>'}
   ${n&&n.history&&n.history.previous?historyBox(n.history):''}
   <div class="row"><button class="btn${n&&n.stale?' primary':''}" id="rescan"${busy?' disabled':''}>Re-scan every state</button><span class="muted">about 5 minutes</span></div></div>
  ${datasetsBox()}
  <p class="muted" style="font-size:12px">coldmap ${esc(st.version)}</p>
 </div></div>`);
}

function historyBox(h){
 if(!S.hist&&!S.histLoading){S.histLoading=1;api('/api/history').then(j=>{S.hist=j;S.histLoading=0;$('main').dataset.key='';render()})}
 const why={data:'the data',models:'your models or settings',nothing:'nothing (the same data and models)'};
 const gone=(S.hist&&S.hist.gone_flags)||[];
 return `<h3 style="margin-top:14px">Since the scan of ${esc(day(h.previous))}</h3>
  <p><b class="num">${nf.format(h.new)}</b> new · <b class="num">${nf.format(h.continuing)}</b> continuing (<span style="color:var(--red)">${nf.format(h.growing)} growing</span>, ${nf.format(h.steady)} steady, ${nf.format(h.shrinking)} shrinking) · <b class="num">${nf.format(h.gone)}</b> gone. What changed between the two scans: ${(h.changed||[]).map(c=>why[c]||c).join(' and ')}.</p>
  ${h.gone?`<p class="muted" style="font-size:12.5px">${(h.changed||[]).includes('data')&&!(h.changed||[]).includes('models')?'Flags that vanish when only new data arrives are worth noting: some were likely false alarms.':'Gone flags can come from changed models as well as new data.'}</p>
  <details><summary class="muted" style="cursor:pointer">Flags that are gone (${nf.format(h.gone)})</summary><table style="margin-top:8px"><tbody>${gone.slice(0,100).map(g=>`<tr><td><span class="tag ${g.confidence}">${CONF[g.confidence]||esc(g.confidence)}</span></td><td>${esc(g.place)}, ${esc(g.state)}</td><td class="muted">${esc(String(g.weapon).toLowerCase())} · ${who(g.sex)} · ${yrs(g.start,g.end)}</td><td class="n">${nf.format(g.total-g.solved)} of ${nf.format(g.total)} unsolved</td></tr>`).join('')}</tbody></table></details>`:''}`;
}
function datasetsBox(){
 const ds=S.ds||[],im=S.imp;
 const list=ds.length?`<table style="margin-top:8px"><thead><tr><th>Dataset</th><th>Place level</th><th class="n">Rows</th><th class="n">Places</th><th>Years</th><th>Columns</th><th></th></tr></thead><tbody>${ds.map(m=>`<tr><td><b>${esc(m.name)}</b>${m.description?`<br><span class="muted" style="font-size:12px">${esc(m.description)}</span>`:''}${Object.keys(m.left_out||{}).length?`<br><span class="muted" style="font-size:12px">left out: ${esc(Object.keys(m.left_out).join(', '))}</span>`:''}</td><td>${esc(m.level)}</td><td class="n">${nf.format(m.rows)}</td><td class="n">${m.places}</td><td class="num">${m.years[0]}–${m.years[1]}</td><td>${esc(m.columns.join(', '))}</td><td><button class="btn" data-dsrm="${esc(m.slug)}">Remove</button></td></tr>`).join('')}</tbody></table>`:'<p class="muted" style="margin:8px 0 0">None yet.</p>';
 let form='';
 if(im&&!im.preview)form=`<div class="msg" style="margin-top:12px">${im.err?`<span style="color:var(--red)">${esc(im.err)}</span>`:'<span class="spin"></span> Reading the file…'}</div>`;
 else if(im){const pv=im.preview,left=pv.columns.filter(c=>c.left_out),safe=pv.columns.filter(c=>!c.left_out),ck=im.check;
  const opt=(sel)=>safe.map(c=>`<option${c.name===sel?' selected':''}>${esc(c.name)}</option>`).join('');
  form=`<div style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px"><h2>Add “${esc(im.file)}”</h2><p class="muted">${nf.format(pv.rows)} rows. Check what coldmap found, then add it.</p>
   ${left.length?`<p class="msg warn"><b>Left out, never stored:</b> ${left.map(c=>`<code>${esc(c.name)}</code> (${esc(c.left_out)})`).join(', ')}. Datasets describe places and times, never people.</p>`:''}
   <div class="dsform">
    <label class="wide">Name<input class="inp" id="dsName" value="${esc(im.name)}"></label>
    <label>Place column<select class="sel" id="dsPlace">${opt(im.place)}</select></label>
    <label>Places are<select class="sel" id="dsLevel">${['county','agency','state'].map(l=>`<option value="${l}"${l===im.level?' selected':''}>${l==='county'?'Counties':l==='agency'?'Police agencies':'States'}</option>`).join('')}</select></label>
    <label>Time column (a year or a date)<select class="sel" id="dsTime">${opt(im.time)}</select></label>
    <label>Source (optional)<input class="inp" id="dsSource" value="${esc(im.source||'')}" placeholder="Where it came from"></label>
    <label class="wide">What it is (optional)<input class="inp" id="dsDesc" value="${esc(im.description||'')}" placeholder="e.g. Missing-person reports per county and year, from NamUs"></label>
    <div class="wide"><span style="font-size:12px;color:var(--mute);font-weight:600">Columns to keep</span><div class="keep">${safe.filter(c=>c.name!==im.place&&c.name!==im.time).map(c=>`<label><input type="checkbox" data-dskeep="${esc(c.name)}"${im.keep.includes(c.name)?' checked':''}>${esc(c.name)}${c.numeric?' <span class="muted">(numbers)</span>':''}</label>`).join('')||'<span class="muted">None besides place and time.</span>'}</div></div>
   </div>
   ${ck?(ck.error?`<p class="msg err">${esc(ck.error)}</p>`:`<p class="msg ${ck.places_matched?'ok':'err'}"><b>${nf.format(ck.places_matched)} of ${nf.format(ck.rows)}</b> rows matched a place in the case file (${ck.places} places); <b>${nf.format(ck.times_read)}</b> have a readable time.${ck.unmatched_examples.length?` Not matched, for example: ${ck.unmatched_examples.map(x=>`<code>${esc(x)}</code>`).join(', ')}. Counties match as “Multnomah, OR” or “Multnomah County, Oregon”.`:''}</p>`):'<p class="muted"><span class="spin"></span> Checking places…</p>'}
   <div class="cases" style="max-height:180px"><table><thead><tr>${safe.map(c=>`<th>${esc(c.name)}</th>`).join('')}</tr></thead><tbody>${pv.sample.map(r=>`<tr>${safe.map(c=>`<td>${esc(r[c.name])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
   <div class="row" style="margin-top:12px"><button class="btn primary" id="dsAdd"${ck&&ck.places_matched?'':' disabled'}>Add dataset</button><button class="btn" id="dsCancel">Cancel</button>${im.err?`<span style="color:var(--red)">${esc(im.err)}</span>`:''}</div></div>`;
 }
 return `<div class="box"><h2>Your datasets</h2>
  <p class="muted">Data you add yourself about places and times: missing-person counts, events, agency changes, your own research notes. It stays on this computer, appears on every flag in the places it covers, and your models can use it (<code>data.aux["dataset:&lt;name&gt;"]</code>, see the <a href="/models/guide" data-nav>guide</a>). Columns that identify people are left out on import: names, addresses, phone numbers, emails, IP addresses, dates of birth, biometric or DNA records, licence plates and exact coordinates. coldmap connects patterns, never people.</p>
  ${list}${im?form:`<div class="row" style="margin-top:12px"><input type="file" id="dsFile" accept=".csv,text/csv" hidden><button class="btn" id="dsPick">Add a dataset (CSV)…</button></div>`}</div>`;
}
async function dsCheck(){const im=S.imp;if(!im||!im.preview)return;im.check=null;render();
 try{im.check=await post('/api/datasets/check',{text:im.text,place:im.place,level:im.level,time:im.time})}catch(e){im.check={error:e.message}}render()}

// ---- events ----------------------------------------------------------------------------------
document.addEventListener('click',async e=>{
 const a=e.target.closest('a[data-nav]');
 if(a&&!e.metaKey&&!e.ctrlKey){e.preventDefault();if(a.dataset.scope!=null){S.f.state=a.dataset.scope;S.f.county='';S.sel=null}go(a.getAttribute('href'));return}
 const tr=e.target.closest('[data-href]');if(tr){go(tr.dataset.href);return}
 const op=e.target.closest('[data-open]');if(op){S.f.show='all';selectFlag(op.dataset.open);return}
 const th=e.target.closest('th[data-sort]');if(th&&S.sel){const w=wbOf(S.sel),i=+th.dataset.sort;w.sort=[i,w.sort[0]===i?-w.sort[1]:1];renderWB(S.sel);return}
 const swEl=e.target.closest('.sw');if(swEl&&swEl.dataset.kind){e.preventDefault();plugin('enable',{kind:swEl.dataset.kind,name:swEl.dataset.name,on:swEl.getAttribute('aria-checked')==='true'?'0':'1'});return}
 const t=e.target.closest('button');if(!t)return;
 if(t.dataset.mf){S.f[t.dataset.mf]=t.dataset.v;updateMap();return}
 if(t.dataset.mw){MP.methods.has(t.dataset.mw)?MP.methods.delete(t.dataset.mw):MP.methods.add(t.dataset.mw);updateMap();return}
 if(t.dataset.mflag){MP.sel={type:'flag',id:t.dataset.mflag,zoom:true};updateMap();return}
 if(t.id==='mClear'){MP.sel=null;updateMap();return}
 if(t.id==='mPlay'){mapPlay();return}
 if(t.id==='mzIn'||t.id==='mzOut'){MP.svg.transition().duration(300).call(MP.zoom.scaleBy,t.id==='mzIn'?1.8:1/1.8);return}
 if(t.id==='mzHome'){MP.svg.transition().duration(600).call(MP.zoom.transform,d3.zoomIdentity);return}
 if(t.dataset.themeSet){document.documentElement.dataset.theme=t.dataset.themeSet;try{localStorage.setItem('coldmap-theme',t.dataset.themeSet)}catch(_){}document.querySelectorAll('svg').length&&($('main').dataset.key='');render();return}
 if(t.dataset.f){S.f[t.dataset.f]=t.dataset.v;S.limit=200;$('main').dataset.key=location.pathname.startsWith('/places')?'':$('main').dataset.key;render();return}
 if(t.classList.contains('frow')){selectFlag(t.dataset.id);return}
 if(t.id==='more'){S.limit+=200;render();return}
 if(t.id==='doSetup'){try{await post('/api/setup')}catch(err){toast(err.message)}poll();return}
 if(t.dataset&&t.dataset.csex){S.citySex=t.dataset.csex;render();return}
 if(t.id==='ciPick'){$('ciFile').click();return}
 if(t.id==='ciCancel'){S.cimp=null;render();return}
 if(t.id==='ciAdd'&&S.cimp){const b=t;b.disabled=true;post('/api/cities/add',{text:S.cimp.text,name:$('ciName').value,source:$('ciSource').value}).then(m=>{S.cimp=null;S.cities=null;S.cgrid={};toast(`Added ${nf.format(m.rows)} killings in ${m.cities} cities`);render()}).catch(err=>{b.disabled=false;toast(err.message)});return}
 if(t.dataset&&t.dataset.cirm){if(!confirm('Remove this city data and the last city scan?'))return;post('/api/cities/remove?slug='+encodeURIComponent(t.dataset.cirm)).then(()=>{S.cities=null;S.cgrid={};render()}).catch(err=>toast(err.message));return}
 if(t.id==='ciWapo'){try{await post('/api/cities/wapo')}catch(err){toast(err.message)}S.cityWatch=1;poll();return}
 if(t.id==='ciScan'){try{await post('/api/cities/scan'+(S.cityPeriods?'?periods=1':''))}catch(err){toast(err.message)}S.cityWatch=1;poll();return}
 if(t.id==='benchRun'){try{await post('/api/benchmark')}catch(err){toast(err.message)}S.benchWatch=1;poll();return}
 if(t.id==='rescan'){try{await post('/api/national')}catch(err){toast(err.message)}$('main').dataset.key='';poll();return}
 if(t.id==='check'){S.checking=1;render();try{await post('/api/check')}catch(err){toast(err.message)}S.checking=0;poll();return}
 if(t.id==='update'){try{await post('/api/download?refresh=1')}catch(err){toast(err.message)}poll();return}
 if(t.dataset.act)return act(t.dataset.act);
 if(t.dataset.wbr&&S.sel){const w=wbOf(S.sel),f=S.detail[S.sel].flag,[Y0,Y1]=S.detail[S.sel].years;if(t.dataset.wbr==='all'){w.y0=Y0;w.y1=Y1}else{w.y0=f.start;w.y1=f.end}if(t.dataset.wbr==='reset')w.sel={};w.limit=300;renderWB(S.sel);return}
 if(t.dataset.wbx&&S.sel){delete wbOf(S.sel).sel[t.dataset.wbx];renderWB(S.sel);return}
 if(t.dataset.fk&&S.sel){const w=wbOf(S.sel);if(w.sel[t.dataset.fk]===t.dataset.fv)delete w.sel[t.dataset.fk];else w.sel[t.dataset.fk]=t.dataset.fv;w.limit=300;renderWB(S.sel);return}
 if(t.dataset.fmore&&S.sel){wbOf(S.sel)['all_'+t.dataset.fmore]=1;renderWB(S.sel);return}
 if(t.dataset.wbmore&&S.sel){wbOf(S.sel).limit+=300;renderWB(S.sel);return}
 if(t.id==='aiTest'){S.aiTest='run';render();try{S.aiTest=await post('/api/ai/test')}catch(err){S.aiTest={ok:false,error:err.message}}render();return}
 if(t.id==='aiConnect'){S.aiConn='run';render();try{const r=await post('/api/ai/connect');S.aiConn=r;S.ai.desktop_status=r.status}catch(err){S.aiConn={error:err.message}}render();return}
 if(t.id==='aiCode'){S.aiCode='run';render();try{S.aiCode=await post('/api/ai/claude-code')}catch(err){S.aiCode={ok:false,error:err.message}}render();return}
 if(t.dataset.copy){navigator.clipboard.writeText($(t.dataset.copy).textContent).then(()=>toast('Copied'));return}
 if(t.dataset.pa){plugin(t.dataset.pa,t.dataset.pname?{name:t.dataset.pname}:t.dataset.pkind?{kind:t.dataset.pkind}:null);return}
 if(t.dataset.msel){const [kind,...rest]=t.dataset.msel.split('|');if(e.target.closest('.sw'))return;S.mSel={kind,name:rest.join('|')};S.mAdd=false;render();return}
 if(t.id==='mAddBtn'){S.mAdd=true;render();return}
 if(t.id==='mAddClose'){S.mAdd=false;render();return}
 if(t.dataset.popen!=null){try{await post('/api/plugins/open'+(t.dataset.popen?'?file='+encodeURIComponent(t.dataset.popen):''));toast(t.dataset.popen?'Opened in your editor':'Opened the folder')}catch(err){toast(err.message)}return}
 if(t.dataset.preplace){S.replaceName=t.dataset.preplace;$('pReplace').click();return}
 if(t.dataset.pdefault){plugin('param',{detector:t.dataset.det,name:t.dataset.pdefault});return}
 if(t.dataset.preset){plugin('reset',{detector:t.dataset.preset});return}
 if(t.dataset.pcode){const [kind,...rest]=t.dataset.pcode.split('|'),name=rest.join('|');try{S.mCode={kind,name,...await api('/api/plugins/source?kind='+encodeURIComponent(kind)+'&name='+encodeURIComponent(name))}}catch(err){toast(err.message)}render();return}
 if(t.dataset.rm){if(confirm(`Remove ${t.dataset.rm}? This deletes the file from your models folder.`))plugin('remove',{file:t.dataset.rm});return}
 if(t.id==='pPick'){$('pFile').click();return}
 if(t.id==='pLink'){const u=$('pUrl').value.trim();if(!u)return;try{const j=await post('/api/plugins/fetch?url='+encodeURIComponent(u));reviewPlugin(j.file,j.text,j.review)}catch(err){S.plMsg={ok:0,html:esc(err.message)};render()}return}
 if(t.id==='rvInstall'){const d=S.pending;document.querySelector('.dialog')?.remove();S.pending=null;if(d)plugin('upload',null,{file:d.file,text:d.text});return}
 if(t.id==='dsPick'){$('dsFile').click();return}
 if(t.id==='dsCancel'){S.imp=null;render();return}
 if(t.id==='dsAdd'){const im=S.imp;try{const m=await post('/api/datasets/add',{name:im.name,text:im.text,place:im.place,level:im.level,time:im.time,keep:im.keep,description:im.description||'',source:im.source||''});
   S.imp=null;S.ds=await api('/api/datasets');S.detail={};toast(`Added ${m.name}: ${nf.format(m.rows)} rows`);poll()}catch(err){im.err=err.message;render()}return}
 if(t.dataset.dsrm){if(confirm('Remove this dataset? Its copy in coldmap is deleted; your original file is untouched.')){try{await post('/api/datasets/remove?slug='+encodeURIComponent(t.dataset.dsrm));S.ds=await api('/api/datasets');S.detail={};poll()}catch(err){toast(err.message)}}return}
 if(t.id==='dlgClose'||t.id==='dlgBg'){document.querySelector('.dialog')?.remove();return}
 if(t.id==='dlgCopy'){navigator.clipboard.writeText(document.querySelector('.dialog pre').textContent).then(()=>toast('Copied'));return}
});
async function act(kind){
 const id=S.sel;if(!id)return;const f=(S.detail[id]&&S.detail[id].flag)||S.flags.find(x=>x.id===id);
 try{
  if(kind==='forget'||kind==='restore'){await post('/api/forget?id='+encodeURIComponent(id))}
  else if(kind==='export'){const r=await fetch('/api/export?id='+encodeURIComponent(id));const t=await r.text();if(!r.ok)throw new Error(JSON.parse(t).error);return exportDialog(f,t)}
  else{const body={id,status:kind,flag:f};if(kind==='reviewed')body.reviewer=($('reviewer')||{}).value;await post('/api/decide',body);
   toast({kept:'Kept for review',dismissed:'Dismissed',reviewed:'Marked reviewed',sent:'Marked sent'}[kind])}
  await refreshDecisions();
  if(kind==='dismissed'&&S.f.show==='open'){const rows=filtered();const nx=rows[0];if(nx)return selectFlag(nx.id,{scroll:true})}
  poll();
 }catch(err){toast(err.message)}
}
// Nothing from a file or a link is installed before its code has been on screen.
function reviewPlugin(file,text,rv){
 S.pending={file,text};
 const flags=(rv&&rv.flags)||[],regs=(rv&&rv.registers)||[];
 const d=document.createElement('div');d.className='dialog';
 d.innerHTML=`<div role="dialog" aria-modal="true" aria-label="Review before installing"><header><b>Review <code>${esc(file)}</code> before installing</b><button class="btn" id="dlgClose">Cancel</button></header>
  <div style="padding:12px 16px;border-bottom:1px solid var(--line);display:grid;gap:8px">
   <p class="msg warn" style="margin:0">This is Python code. Once installed it runs on this computer with your permissions, every time coldmap starts. Install it only if you trust where it came from and have read it.</p>
   ${rv&&!rv.valid?`<p class="msg err" style="margin:0">It isn't valid Python: ${esc(rv.error)}</p>`:''}
   <p style="margin:0">${regs.length?`It adds: ${regs.map(r=>`<code>${esc(r.registry)}</code> ${esc(r.class)}`).join(', ')}.`:'<b>It doesn\'t register a model</b> with <code>@DETECTORS</code>, <code>@ENRICHERS</code> or <code>@VIEWS.register</code>, so coldmap will refuse it.'}</p>
   ${flags.length?`<div class="msg err" style="margin:0"><b>It reaches for things a model about patterns rarely needs:</b><ul style="margin:6px 0 0;padding-left:18px">${flags.map(x=>`<li>${esc(x.what)}: <code>${esc(x.uses.join(', '))}</code></li>`).join('')}</ul>Read those parts closely before installing.</div>`:'<p class="muted" style="margin:0">It doesn\'t use the network, other programs, run-time code or files outside coldmap, as far as a quick read of its imports and calls can tell.</p>'}
  </div><pre class="code" style="max-height:46vh">${esc(text)}</pre>
  <footer><span class="muted" style="margin-right:auto;font-size:12px">${(rv&&rv.lines)||''} lines</span><button class="btn" id="dlgCancel">Don't install</button><button class="btn primary" id="rvInstall"${rv&&rv.valid&&regs.length?'':' disabled'}>Install</button></footer></div>`;
 document.body.append(d);d.querySelector('#dlgCancel').focus();
 d.addEventListener('keydown',e=>{if(e.key==='Escape'){d.remove();S.pending=null}});
 d.querySelector('#dlgCancel').addEventListener('click',()=>{d.remove();S.pending=null});
}
function exportDialog(f,text){
 const name=`coldmap-lead-${slug(f.state)}-${slug(f.place)}-${f.start}.md`;
 const d=document.createElement('div');d.className='dialog';d.innerHTML=`<div role="dialog" aria-modal="true" aria-label="Export for MAP"><header><b>Export for MAP</b><button class="btn" id="dlgClose">Close</button></header><pre>${esc(text)}</pre><footer><span class="muted" style="margin-right:auto;font-size:12px">Send it to MAP through their contact page, with this text attached.</span><button class="btn" id="dlgCopy">Copy</button><a class="btn primary" download="${esc(name)}" href="data:text/markdown;charset=utf-8,${encodeURIComponent(text)}">Download .md</a></footer></div>`;
 document.body.append(d);d.querySelector('#dlgClose').focus();
 d.addEventListener('keydown',e=>{if(e.key==='Escape')d.remove()});
}
document.addEventListener('change',async e=>{
 const t=e.target;
 if(t.id==='fState'){S.f.state=t.value;S.f.county='';S.limit=200;render()}
 if(t.id==='fCounty'){S.f.county=t.value;render()}
 if(t.id==='mMetric'){MP.metric=t.value;updateMap()}
 if(t.dataset&&t.dataset.vin){const r=route();S.vin[r.a]={...(S.vin[r.a]||{}),[t.dataset.vin]:t.value};runView(r.a);return}
 if(t.id==='mLinks'){MP.links=t.checked;updateMap()}
 if((t.id==='wbY0'||t.id==='wbY1')&&S.sel){const w=wbOf(S.sel);w[t.id==='wbY0'?'y0':'y1']=+t.value;if(w.y0>w.y1)[w.y0,w.y1]=[w.y1,w.y0];renderWB(S.sel)}
 if(t.id==='fKind'){S.f.kind=t.value;render()}
 if(t.id==='fShow'){S.f.show=t.value;render()}
 if(t.id==='fSort'){S.f.sort=t.value;render()}
 if(t.id==='qState'){S.qState=t.value;S.quality=S.quality||{};if(t.value&&!S.quality[t.value])api('/api/quality?state='+encodeURIComponent(t.value)).then(j=>{S.quality[t.value]=j;render()}).catch(err=>toast(err.message));render()}
 if(t.id==='noteBox'){post('/api/note',{id:t.dataset.id,note:t.value}).then(()=>{refreshDecisions();toast('Note saved')}).catch(err=>toast(err.message))}
 if(t.id==='ciPeriods'){S.cityPeriods=t.checked;render();return}
 if(t.id==='ciFile'&&t.files[0]){const fl=t.files[0];t.value='';
  if(fl.size>25*1024*1024){toast('That file is over 25 MB.');return}
  S.cimp={file:fl.name,name:fl.name.replace(/\.csv$/i,'').replace(/[_-]+/g,' ')};render();
  const buf=await fl.arrayBuffer();let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(buf)}catch(e){text=new TextDecoder('windows-1252').decode(buf)}
  S.cimp.text=text;try{S.cimp.preview=await post('/api/cities/preview',{text})}catch(e){S.cimp.err=e.message}render();return}
 if(t.id==='dsFile'&&t.files[0]){const fl=t.files[0];t.value='';
  if(fl.size>25*1024*1024){toast('That file is over 25 MB. Aggregate it by place and year first.');return}
  S.imp={file:fl.name,name:fl.name.replace(/\.csv$/i,'').replace(/[_-]+/g,' '),keep:[]};render();
  fl.text().then(async text=>{S.imp.text=text;try{const pv=await post('/api/datasets/preview',{text});const g=pv.guess;
   Object.assign(S.imp,{preview:pv,place:g.place||pv.columns.find(c=>!c.left_out)?.name,level:g.level,time:g.time||pv.columns.filter(c=>!c.left_out)[1]?.name});
   S.imp.keep=pv.columns.filter(c=>!c.left_out&&c.name!==S.imp.place&&c.name!==S.imp.time).map(c=>c.name);render();dsCheck()}catch(e){S.imp.err=e.message;render()}});return}
 if(S.imp&&['dsPlace','dsLevel','dsTime'].includes(t.id)){const k={dsPlace:'place',dsLevel:'level',dsTime:'time'}[t.id];S.imp[k]=t.value;S.imp.keep=S.imp.keep.filter(c=>c!==S.imp.place&&c!==S.imp.time);dsCheck();return}
 if(S.imp&&t.dataset.dskeep!=null){const c=t.dataset.dskeep;S.imp.keep=t.checked?[...S.imp.keep,c]:S.imp.keep.filter(x=>x!==c);return}
 if(t.id==='pReplace'&&t.files[0]){const f=t.files[0];t.value='';f.text().then(async text=>{const r=await post('/api/plugins/review',{text});reviewPlugin(S.replaceName||f.name,text,r.review)});return}
 if(t.dataset.param){plugin('param',{detector:t.dataset.det,name:t.dataset.param,value:t.value});return}
 if(t.id==='pFile'&&t.files[0]){const f=t.files[0];if(f.size>512*1024){toast('That file is too big for a model (over 512 KB).');return}f.text().then(async text=>{const r=await post('/api/plugins/review',{text});reviewPlugin(f.name,text,r.review)});t.value=''}
});
document.addEventListener('input',e=>{if(e.target.id==='fQ'){S.f.q=e.target.value;S.limit=200;render()}
 if(e.target.id==='mQ'){S.mQ=e.target.value;render();return}
 if(e.target.id==='mDist'){MP.dist=+e.target.value;clearTimeout(MP.dt);MP.dt=setTimeout(updateMap,120);return}
 const k={dsName:'name',dsDesc:'description',dsSource:'source'}[e.target.id];if(k&&S.imp)S.imp[k]=e.target.value});
document.addEventListener('keydown',e=>{
 if(document.querySelector('.dialog'))return;
 if((e.key===' '||e.key==='Enter')&&e.target.classList&&e.target.classList.contains('sw')){e.preventDefault();e.target.click();return}
 const typing=/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
 if(e.key==='Escape'&&typing){document.activeElement.blur();return}
 if(typing||e.metaKey||e.ctrlKey||e.altKey||route().sec!=='flags'||!S.flags)return;
 const rows=filtered(),i=rows.findIndex(r=>r.id===S.sel);
 if(e.key==='ArrowDown'||e.key==='j'){e.preventDefault();const n=rows[Math.min(rows.length-1,i+1)];if(n)selectFlag(n.id,{scroll:true})}
 else if(e.key==='ArrowUp'||e.key==='k'){e.preventDefault();const n=rows[Math.max(0,i-1)];if(n)selectFlag(n.id,{scroll:true})}
 else if(e.key==='/'){e.preventDefault();$('fQ')&&$('fQ').focus()}
 else if(e.key==='s'&&S.sel&&!status(S.sel)){act('kept')}
 else if(e.key==='x'&&S.sel&&!status(S.sel)){act('dismissed')}
});
addEventListener('resize',()=>{if(route().sec==='map'&&MP.svg){MP.svg=null;$('main').dataset.key='';MP.brush=null}const m=$('main');if(m){const pane=$('flagPane');if(pane)pane._h='';tipEl.hidden=true;m.dataset.key=location.pathname.startsWith('/places')?'':m.dataset.key;render()}});
if(location.pathname==='/')history.replaceState(null,'','/flags');
poll();
