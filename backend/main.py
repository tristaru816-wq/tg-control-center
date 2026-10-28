"""Stateless Telegram execution API. Firebase Auth protects management endpoints.
Sessions and account payloads are encrypted before Firestore writes.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import firebase_admin
from firebase_admin import auth, firestore
from google.api_core.exceptions import AlreadyExists
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from scheduling import TZ, slot

PROJECT=os.environ.get('GOOGLE_CLOUD_PROJECT','tg-control-center')
ADMIN_UID=os.environ.get('ADMIN_UID','3bYS2rcw9jOf4A5sIvdO5DejMKP2')
FERNET=Fernet(os.environ['SESSION_KEY'].encode())
ORIGINS=os.environ.get('ALLOWED_ORIGINS','https://tristaru816-wq.github.io').split(',')
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(CORSMiddleware,allow_origins=ORIGINS,allow_methods=['GET','POST','PUT'],allow_headers=['Authorization','Content-Type'])
bearer=HTTPBearer(auto_error=False)
_store=None

def store():
    global _store
    if _store is None:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={'projectId':PROJECT})
        _store=firestore.client()
    return _store

def protect(value):
    return FERNET.encrypt(json.dumps(value).encode()).decode()
def unprotect(value):
    return json.loads(FERNET.decrypt(value.encode()))

def get_record(aid):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',aid):
        raise HTTPException(400,'無效帳號 ID')
    return store().collection('_tgAccounts').document(aid)
def read(aid):
    snap=get_record(aid).get()
    if not snap.exists:
        raise HTTPException(404,'此帳號尚未設定 TG 登入')
    return unprotect(snap.to_dict()['ciphertext'])
def write(aid,value):
    get_record(aid).set({'ciphertext':protect(value)})

def require_admin(cred:HTTPAuthorizationCredentials=Depends(bearer)):
    if not cred: raise HTTPException(401,'請先登入 Firebase')
    try:
        store()
        claims=auth.verify_id_token(cred.credentials,check_revoked=True)
    except Exception:
        raise HTTPException(401,'管理員登入已失效，請重新登入')
    if claims.get('uid')!=ADMIN_UID: raise HTTPException(403,'沒有管理權限')
    return claims

def require_scheduler(cred:HTTPAuthorizationCredentials=Depends(bearer)):
    if not cred: raise HTTPException(401,'未授權')
    try:
        claims=id_token.verify_oauth2_token(cred.credentials,GoogleRequest(),audience=os.environ['SERVICE_URL'])
        if claims.get('email')!=os.environ['SCHEDULER_EMAIL'] or not claims.get('email_verified'):
            raise ValueError()
    except Exception:
        raise HTTPException(403,'排程呼叫驗證失敗')

@asynccontextmanager
async def guard(aid):
    """Firestore transaction lease; all operations finish within 35s, lease is 90s."""
    ref=store().collection('_tgLocks').document(aid)
    owner=secrets.token_hex(16)
    @firestore.transactional
    def acquire(tx):
        snap=ref.get(transaction=tx)
        if snap.exists and snap.to_dict().get('until',0)>time.time():
            return False
        tx.set(ref,{'owner':owner,'until':time.time()+90})
        return True
    if not acquire(store().transaction()):
        raise HTTPException(409,'帳號正在處理其他工作，請稍後')
    try:
        yield
    finally:
        @firestore.transactional
        def release(tx):
            snap=ref.get(transaction=tx)
            if snap.exists and snap.to_dict().get('owner')==owner: tx.delete(ref)
        release(store().transaction())

def make_client(a):
    return TelegramClient(StringSession(a.get('session','')),a['api_id'],a['api_hash'],flood_sleep_threshold=0,request_retries=0,connection_retries=0,timeout=10)

async def with_client(a,operation):
    cl=make_client(a)
    try:
        async with asyncio.timeout(30):
            await cl.connect()
            return await operation(cl)
    finally:
        a['session']=cl.session.save()
        try:
            await asyncio.wait_for(cl.disconnect(),3)
        except Exception:
            pass

def public(aid,a):
    return {'id':aid,'ready':a.get('ready',False),'enabled':a.get('enabled',False),'schedule':a.get('schedule'),'last_result':a.get('last_result'),'cooldown_until':a.get('cooldown_until',0)}

def safe_error(ex):
    if isinstance(ex,errors.FloodWaitError): return f'Telegram 要求等待 {ex.seconds} 秒'
    if isinstance(ex,errors.PhoneCodeInvalidError): return '驗證碼錯誤，請重新輸入'
    if isinstance(ex,errors.PhoneCodeExpiredError): return '驗證碼已過期，請重新取得'
    if isinstance(ex,errors.PasswordHashInvalidError): return '兩步驗證密碼錯誤'
    return f'{type(ex).__name__}：操作未完成，請確認帳號、群組及權限'

def check_wait(a):
    wait=int(a.get('cooldown_until',0)-time.time())
    if wait>0: raise HTTPException(429,f'請等待 {wait} 秒')

def record_error(a,e):
    if isinstance(e,errors.FloodWaitError): a['cooldown_until']=time.time()+e.seconds

class CodeIn(BaseModel):
    phone:str=Field(pattern=r'^\+[1-9][0-9]{6,14}$')
    api_id:int=Field(gt=0)
    api_hash:str=Field(pattern=r'^[a-fA-F0-9]{32}$')
class LoginIn(BaseModel):
    code:str=Field(default='',max_length=20)
    password:str=Field(default='',max_length=256)
class Plan(BaseModel):
    start:str=Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    end:str=Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    interval:Literal[3,5,10,15]
    mode:Literal['check','send']='check'
    target:str=Field(default='',max_length=150)
    message:str=Field(default='',max_length=4096)
    @model_validator(mode='after')
    def validate_plan(self):
        if self.start==self.end: raise ValueError('開始與結束不可相同')
        if self.mode=='send' and (not self.target.strip() or not self.message.strip()):
            raise ValueError('發送模式需填群組與訊息')
        return self
class EnableIn(BaseModel):
    enabled:bool

@app.get('/health')
def health(): return {'service':'tg-execution','version':'0.2'}

@app.get('/accounts',dependencies=[Depends(require_admin)])
def accounts():
    return {'accounts':[public(s.id,unprotect(s.to_dict()['ciphertext'])) for s in store().collection('_tgAccounts').stream()]}

@app.post('/accounts/{aid}/code',dependencies=[Depends(require_admin)])
async def request_code(aid:str,b:CodeIn):
    get_record(aid)
    # Only IDs already present in the owner's existing dashboard can be configured.
    snap=store().collection('adminData').document(ADMIN_UID).get()
    dashboard=(snap.to_dict() or {}).get('dashboard',{}) if snap.exists else {}
    if aid not in [x.get('id') for x in dashboard.get('accounts',[])][:50]:
        raise HTTPException(400,'請先在後台建立此帳號，最多支援 50 個')
    async with guard(aid):
        try: old=read(aid)
        except HTTPException as e:
            if e.status_code!=404: raise
            old={}
        check_wait(old)
        if old.get('ready'):
            raise HTTPException(409,'帳號已登入；如需更換帳號，請先登出 TG')
        if old.get('code_after',0)>time.time():
            raise HTTPException(429,'請稍候再取得驗證碼')
        a={**b.model_dump(),'session':'','ready':False,'enabled':False,'code_after':time.time()+60}
        async def operation(cl):
            sent=await cl.send_code_request(b.phone)
            a['phone_code_hash']=sent.phone_code_hash
            a['code_expires']=time.time()+600
        try:
            await with_client(a,operation)
        except Exception as e:
            record_error(a,e);write(aid,a)
            raise HTTPException(400,safe_error(e))
        write(aid,a)
        return {'status':'code_sent'}

@app.post('/accounts/{aid}/login',dependencies=[Depends(require_admin)])
async def login(aid:str,b:LoginIn):
    async with guard(aid):
        a=read(aid);check_wait(a)
        if a.get('code_expires',0)<time.time(): raise HTTPException(400,'登入請求已過期，請重新取得驗證碼')
        async def operation(cl):
            if b.password: await cl.sign_in(password=b.password)
            else: await cl.sign_in(phone=a['phone'],code=b.code,phone_code_hash=a.get('phone_code_hash'))
        status='ok'
        try:
            await with_client(a,operation)
            a['ready']=True;a.pop('phone_code_hash',None)
        except errors.SessionPasswordNeededError:
            status='password_needed'
        except Exception as e:
            record_error(a,e);write(aid,a)
            raise HTTPException(400,safe_error(e))
        write(aid,a)
        return {'status':status}

@app.post('/accounts/{aid}/logout',dependencies=[Depends(require_admin)])
async def logout(aid:str):
    async with guard(aid):
        a=read(aid);a['enabled']=False;write(aid,a)
        async def operation(cl): await cl.log_out()
        try: await with_client(a,operation)
        except Exception as e: raise HTTPException(400,safe_error(e))
        get_record(aid).delete()
    return {'status':'logged_out'}

@app.put('/accounts/{aid}/schedule',dependencies=[Depends(require_admin)])
async def schedule(aid:str,b:Plan):
    async with guard(aid):
        a=read(aid);a['schedule']=b.model_dump();a['enabled']=False;write(aid,a)
    return {'status':'saved_paused'}

@app.post('/accounts/{aid}/enable',dependencies=[Depends(require_admin)])
async def enable(aid:str,b:EnableIn):
    async with guard(aid):
        a=read(aid)
        if b.enabled and (not a.get('ready') or not a.get('schedule')): raise HTTPException(400,'請先登入 TG 並設定排程')
        if b.enabled and a.get('inflight'): raise HTTPException(409,'上次結果待確認，請先執行連線檢查')
        a['enabled']=b.enabled;write(aid,a)
    return {'status':'ok'}

@app.post('/accounts/{aid}/check',dependencies=[Depends(require_admin)])
async def check(aid:str):
    async with guard(aid):
        a=read(aid);check_wait(a)
        async def operation(cl):
            if not await cl.is_user_authorized(): raise HTTPException(400,'請重新登入 TG')
            await cl.get_me()
        try: await with_client(a,operation)
        except Exception as e:
            record_error(a,e);a['ready']=False;a['enabled']=False;write(aid,a)
            raise HTTPException(400,safe_error(e))
        # Explicit manual check acknowledges the interrupted run; never replays it.
        a.pop('inflight',None)
        a['ready']=True
        a['last_result']={'at':datetime.now(TZ).isoformat(),'status':'ok','detail':'TG 連線成功（不代表顯示在線）'}
        write(aid,a)
    return a['last_result']

async def execute(aid):
    try:
        async with guard(aid):
            a=read(aid)
            if a.get('inflight'):
                a['enabled']=False
                a['last_result']={'at':datetime.now(TZ).isoformat(),'status':'unknown','detail':'上次操作中斷；請人工確認群組後，按連線檢查，再自行啟用'}
                write(aid,a);return
            if not a.get('enabled') or not a.get('ready') or a.get('cooldown_until',0)>time.time(): return
            s=a.get('schedule')
            if not s:return
            key=slot(datetime.now(TZ),s['start'],s['end'],s['interval'])
            if not key:return
            rid=hashlib.sha256((aid+key).encode()).hexdigest()
            ledger=store().collection('_tgRuns').document(rid)
            try: ledger.create({'account':aid,'slot':key,'status':'running','at':time.time()})
            except AlreadyExists: return
            a['inflight']=rid;write(aid,a)
            result={'at':datetime.now(TZ).isoformat(),'status':'ok','detail':'TG 連線成功（不代表顯示在線）'}
            async def operation(cl):
                if not await cl.is_user_authorized(): raise RuntimeError('Telegram session expired')
                await cl.get_me()
                if s['mode']=='send':
                    target=int(s['target']) if s['target'].lstrip('-').isdigit() else s['target']
                    sent=await cl.send_message(target,s['message'],parse_mode=None)
                    result['detail']=f'Telegram 已接受訊息 ID {sent.id}；未驗證機器人回覆'
            try: await with_client(a,operation)
            except errors.FloodWaitError as e:
                record_error(a,e);result.update(status='wait',detail=safe_error(e)+'；本時段不補發')
            except Exception as e:
                a['enabled']=False
                result.update(status='unknown',detail=safe_error(e)+'；已暫停，請核對群組，避免重複發送')
            ledger.set(result,merge=True)
            a.pop('inflight',None);a['last_result']=result;write(aid,a)
    except HTTPException as e:
        if e.status_code!=409: raise

@app.post('/tick',dependencies=[Depends(require_scheduler)])
async def tick():
    semaphore=asyncio.Semaphore(5)
    async def run(aid):
        async with semaphore: await execute(aid)
    owner=store().collection('adminData').document(ADMIN_UID).get()
    dashboard=(owner.to_dict() or {}).get('dashboard',{}) if owner.exists else {}
    allowed={x.get('id') for x in dashboard.get('accounts',[])[:50]}
    ids=[]
    for snap in store().collection('_tgAccounts').stream():
        if snap.id in allowed:
            ids.append(snap.id)
        else:
            try:
                async with guard(snap.id):
                    a=read(snap.id);a['enabled']=False;write(snap.id,a)
            except HTTPException as ex:
                if ex.status_code!=409: raise
    results=await asyncio.gather(*(run(aid) for aid in ids),return_exceptions=True)
    failed=sum(isinstance(r,Exception) for r in results)
    if failed: raise HTTPException(503,f'{failed} 個帳號本次處理未完成，其他帳號結果已保存')
    return {'processed':len(ids)}
