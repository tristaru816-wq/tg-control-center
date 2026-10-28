import asyncio
import copy
from datetime import datetime
import hashlib
import json
import sqlite3
import time
from telethon import TelegramClient,errors
from cloud import CloudError,Conflict
from scheduling import TZ,slot

class Busy(CloudError):pass
class Engine:
    def __init__(self,cloud,root,worker_id,accounts):
        self.cloud=cloud;self.root=root;self.worker_id=worker_id;self.accounts=accounts;self.disabled=False
        self.clients={};self.ready=set();self.last_renew=0
        self.sql=sqlite3.connect(root/'runs.db')
        self.sql.execute('CREATE TABLE IF NOT EXISTS runs(aid TEXT, slot TEXT, status TEXT, detail TEXT, at TEXT, PRIMARY KEY(aid,slot))');self.sql.commit()
    def client(self,aid):
        if aid not in self.clients:
            a=self.accounts[aid];path=self.root/('tg_'+hashlib.sha256(aid.encode()).hexdigest())
            self.clients[aid]=TelegramClient(str(path),a['api_id'],a['api_hash'],flood_sleep_threshold=0,request_retries=0,connection_retries=0,timeout=10)
        return self.clients[aid]
    async def discover(self):
        for aid in self.accounts:
            cl=self.client(aid)
            try:
                async with asyncio.timeout(25):
                    await cl.connect()
                    if await cl.is_user_authorized():self.ready.add(aid)
            except Exception:pass
            finally:
                try:await asyncio.wait_for(cl.disconnect(),3)
                except Exception:pass
    def mutate(self,fn,attempts=4):
        for _ in range(attempts):
            d=self.cloud.get();fields,result=fn(d)
            if not fields:return result
            try:self.cloud.patch(fields,d['_updateTime']);return result
            except Conflict:continue
        raise Conflict('雲端設定持續更新，本次不執行 TG 操作')
    def own(self,d):
        lease=d.get('desktopLease',{})
        return lease.get('owner')==self.worker_id and lease.get('until',0)>d['_serverNow']
    def heartbeat(self,offline=False):
        def change(d):
            lease=d.get('desktopLease',{})
            if lease.get('owner')!=self.worker_id and lease.get('until',0)>d['_serverNow']:raise Busy('另一台電腦正在執行，這台等待接手')
            st=d.get('desktopStatus',{});st.update({'workerId':self.worker_id,'version':'3.0','lastSeen':d['_serverNow'],'online':not offline,'readyAccounts':sorted(self.ready)})
            return {'desktopLease':{'owner':self.worker_id,'until':d['_serverNow']+(0 if offline else 120)},'desktopStatus':st},None
        self.mutate(change);self.last_renew=time.monotonic()
    def report(self,aid,value):
        def change(d):
            if not self.own(d):raise Busy('已失去執行權，不再更新狀態')
            st=d.get('desktopStatus',{});rows=st.setdefault('accounts',{});old=rows.get(aid,{})
            rows[aid]={**old,**value,'at':datetime.now(TZ).isoformat()}
            history=st.get('history',[])
            history.insert(0,{'account':aid,'at':rows[aid]['at'],'status':value.get('status',''),'detail':value.get('detail','')})
            st['history']=history[:100]
            return {'desktopStatus':st},None
        self.mutate(change)
    def claim(self,aid):
        def change(d):
            if not self.own(d):raise Busy('執行權已過期，本次不執行')
            ids={a['id'] for a in d.get('dashboard',{}).get('accounts',[])[:50]}
            if aid not in ids:return {},None
            plan=d.get('desktopConfig',{}).get('plans',{}).get(aid,{})
            rows=d.get('desktopStatus',{}).get('accounts',{});previous=rows.get(aid,{})
            if aid not in self.ready:return {},None
            ack_fields={}
            if previous.get('blocked') or previous.get('status')=='running':
                if plan.get('ack') and plan.get('ack')!=previous.get('ackSeen'):
                    previous={**previous,'blocked':False,'ackSeen':plan['ack'],'status':'acknowledged','detail':'已人工核對，原時段不補發'}
                    st=d.get('desktopStatus',{});st.setdefault('accounts',{})[aid]=previous
                    ack_fields={'desktopStatus':st}
                else:
                    if previous.get('blocked') and previous.get('status')=='unknown':return {},None
                    st=d.get('desktopStatus',{});st.setdefault('accounts',{})[aid]={**previous,'blocked':True,'status':'unknown','detail':'上次結果待確認；請人工核對群組後解除暫停','at':datetime.now(TZ).isoformat()}
                    return {'desktopStatus':st},None
            if not plan.get('enabled'):return ack_fields,None
            validate_plan(plan)
            if previous.get('cooldownUntil',0)>d['_serverNow']:return ack_fields,None
            key=slot(datetime.now(TZ),plan['start'],plan['end'],int(plan['interval']))
            if not key:return ack_fields,None
            # Global last-slot claim plus durable local ledger; no replay on another PC.
            if previous.get('lastSlot')==key or self.sql.execute('SELECT 1 FROM runs WHERE aid=? AND slot=?',(aid,key)).fetchone():return ack_fields,None
            st=d.get('desktopStatus',{});st.setdefault('accounts',{})[aid]={**previous,'lastSlot':key,'status':'running','blocked':False,'at':datetime.now(TZ).isoformat(),'detail':'執行中'}
            return {'desktopStatus':st},(copy.deepcopy(plan),key)
        return self.mutate(change)
    async def run_account(self,aid):
        claim=self.claim(aid)
        if not claim:return
        plan,key=claim
        self.sql.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(aid,key,'running','',datetime.now(TZ).isoformat()));self.sql.commit()
        status,detail,blocked='ok','TG 連線檢查成功（不代表顯示在線）',False
        cooldown=0;cl=self.client(aid)
        try:
            async with asyncio.timeout(30):
                await cl.connect()
                if not await cl.is_user_authorized():
                    self.ready.discard(aid);raise RuntimeError('TG_LOGIN_REQUIRED')
                await cl.get_me()
                if plan['mode']=='send':
                    target=plan['target'];target=int(target) if target.lstrip('-').isdigit() else target
                    result=await cl.send_message(target,plan['message'],parse_mode=None)
                    detail=f'Telegram 已接受訊息 ID {result.id}（未驗證機器人回覆）'
        except errors.FloodWaitError as e:
            status,detail='wait',f'Telegram 限流，等待 {e.seconds} 秒；本時段不補發'
            cooldown=time.time()+e.seconds
        except Exception as e:
            status,detail,blocked='unknown',f'{type(e).__name__}：結果待確認，已暫停此帳號；請核對群組',True
        finally:
            try:await asyncio.wait_for(cl.disconnect(),3)
            except Exception:pass
        self.sql.execute('UPDATE runs SET status=?, detail=? WHERE aid=? AND slot=?',(status,detail,aid,key));self.sql.commit()
        # If this write fails, the cloud claim remains 'running', and a future worker blocks it.
        self.report(aid,{'status':status,'detail':detail,'blocked':blocked,'cooldownUntil':cooldown})
    async def run(self):
        print('正在檢查本機 TG 登入…');await self.discover()
        print(f'{len(self.ready)} 個本機 TG 帳號可用。請用手機後台設定「電腦執行」排程。')
        print('保持此視窗開啟；按 Ctrl+C 停止。電腦睡眠或斷網時不執行。')
        try:
            while True:
                try:
                    if time.monotonic()-self.last_renew>30:self.heartbeat()
                    d=self.cloud.get();ids=[x['id'] for x in d.get('dashboard',{}).get('accounts',[])[:50]]
                    for aid in ids:
                        if aid not in self.accounts or aid not in self.ready:continue
                        p=d.get('desktopConfig',{}).get('plans',{}).get(aid,{})
                        r=d.get('desktopStatus',{}).get('accounts',{}).get(aid,{})
                        ack_pending=(r.get('blocked') or r.get('status')=='running') and p.get('ack') and p.get('ack')!=r.get('ackSeen')
                        if not p.get('enabled') and not ack_pending:continue
                        if p.get('enabled'):
                            validate_plan(p)
                            key=slot(datetime.now(TZ),p['start'],p['end'],int(p['interval']))
                            if not ack_pending and (not key or (r.get('lastSlot')==key and r.get('status')!='running')):continue
                        # Refresh the global lease before each bounded operation if needed.
                        if time.monotonic()-self.last_renew>30:self.heartbeat()
                        await self.run_account(aid)
                    await asyncio.sleep(15)
                except (CloudError,OSError,ValueError) as e:
                    print('暫停 TG 執行：'+str(e));await asyncio.sleep(15)
                except Exception as e:
                    print('暫停 TG 執行：'+type(e).__name__);await asyncio.sleep(15)
        finally:
            try:self.heartbeat(offline=True)
            except Exception:pass
            for cl in self.clients.values():
                try:await asyncio.wait_for(cl.disconnect(),3)
                except Exception:pass
            self.sql.close()

def validate_plan(p):
    import re
    for key in ('start','end'):
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',str(p.get(key,''))):raise ValueError('排程時間格式錯誤')
    if p['start']==p['end'] or p.get('interval') not in (3,5,10,15):raise ValueError('排程時段或間隔錯誤')
    if p.get('mode') not in ('check','send'):raise ValueError('排程模式錯誤')
    if p['mode']=='send' and (not str(p.get('target','')).strip() or not str(p.get('message','')).strip() or len(p['message'])>4096):raise ValueError('缺少發送目標或文字')
