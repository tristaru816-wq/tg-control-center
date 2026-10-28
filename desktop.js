(()=>{'use strict';
const $=id=>document.getElementById(id);let state={config:{},status:{}};
function msg(t){$('desktopMessage').textContent=t;}
const accountId=()=>$('desktopAccount').value;
const currentPlan=()=>state.config.plans?.[accountId()]||{};
function loadPlan(){const p=currentPlan(),f=$('desktopPlan');f.reset();for(const k of ['start','end','interval','mode','target','message'])if(p[k]!==undefined)f.elements[k].value=p[k];}
window.renderTgAccounts=()=>{const select=$('desktopAccount'),old=select.value;select.replaceChildren();for(const a of window.getTgDashboardAccounts?.()||[]){const n=document.createElement('option');n.value=a.id;n.textContent=a.name;select.append(n);}if([...select.options].some(n=>n.value===old))select.value=old;else loadPlan();draw();};
function draw(){const st=state.status,online=st.online&&Number(st.lastSeen)>Date.now()/1000-120;$('desktopHeartbeat').textContent=online?'● 電腦執行器已連線':'○ 電腦執行器未連線／狀態已過期';$('desktopHeartbeat').style.color=online?'#8ce4ba':'#edca86';$('desktopSeen').textContent=st.lastSeen?'最後回報：'+new Date(st.lastSeen*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'尚未收到電腦回報。請在 Windows 啟動 start.cmd。';const list=$('desktopRows');list.replaceChildren();const ready=new Set(st.readyAccounts||[]);for(const a of window.getTgDashboardAccounts?.()||[]){const p=state.config.plans?.[a.id],r=st.accounts?.[a.id],n=document.createElement('div');n.className='item';n.textContent=`${a.name} · ${online?(ready.has(a.id)?'電腦 TG 可用':'需在電腦登入 TG'):'等待電腦連線'} · ${p?.enabled?(r?.blocked?'結果待確認，已阻擋':'排程已啟用'):'排程暫停／尚未設定'}${r?' · '+r.detail:''}`;list.append(n);}const logs=$('desktopLogs');logs.replaceChildren();for(const r of (st.history||[]).slice(0,40)){const n=document.createElement('div');n.className='item';n.textContent=`${r.at} · ${window.getTgAccountName(r.account)} · ${r.detail}`;logs.append(n);}}
window.addEventListener('desktop-cloud-state',e=>{state=e.detail;window.renderTgAccounts();});
window.addEventListener('desktop-cloud-error',e=>msg(e.detail));
async function act(fn){const buttons=[...$('desktopControls').querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{await fn();msg('已儲存至 Firebase，電腦連線時會讀取；已開始的操作無法撤回。');}catch(e){msg(e.message);}finally{buttons.forEach(b=>b.disabled=false);}}
async function save(p){const id=accountId();if(!id)throw Error('請先在「帳號」頁新增帳號資料');if(!window.desktopSavePlan)throw Error('請先登入 Firebase 管理員');await window.desktopSavePlan(id,p);state.config.plans={...state.config.plans,[id]:p};draw();}
$('desktopAccount').onchange=loadPlan;
$('desktopPlan').onsubmit=e=>{e.preventDefault();act(async()=>{const p=Object.fromEntries(new FormData(e.target));p.interval=Number(p.interval);p.enabled=false;p.revision=crypto.randomUUID();p.ack=currentPlan().ack||'';if(p.start===p.end)throw Error('開始與結束不可相同');if(p.mode==='send'&&(!p.target.trim()||!p.message.trim()))throw Error('發送模式請填群組／機器人與訊息');await save(p);});};
$('desktopEnable').onclick=()=>act(async()=>{const p=currentPlan();if(!p.start)throw Error('請先儲存一組執行排程');const r=state.status.accounts?.[accountId()];if(r?.blocked&&(!p.ack||p.ack===r.ackSeen))throw Error('請先核對群組，再解除結果待確認暫停');if(!confirm(`啟用 ${p.start}–${p.end}，每 ${p.interval} 分鐘${p.mode==='send'?'發送到 '+p.target:'檢查連線'}？電腦連線後可能立即執行目前時段。`))return;await save({...p,enabled:true});});
$('desktopPause').onclick=()=>act(()=>save({...currentPlan(),enabled:false}));
$('desktopAcknowledge').onclick=()=>act(async()=>{if(!confirm('請先人工核對 TG 群組，確認上次訊息是否送達。解除後不會補發原時段，下個符合的區段才可執行。確定已核對？'))return;await save({...currentPlan(),ack:crypto.randomUUID(),enabled:false});msg('已記錄人工核對，請再按啟用；原時段不補發。');});
$('desktopPauseAll').onclick=()=>act(async()=>{for(const [id,p] of Object.entries(state.config.plans||{}))await window.desktopSavePlan(id,{...p,enabled:false});});
setInterval(draw,15000);
})();
