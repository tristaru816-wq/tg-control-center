import asyncio
import copy
import importlib
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ['SESSION_KEY']=Fernet.generate_key().decode()
import main as api

class Snap:
    def __init__(self,ref): self.id=ref.id;self.value=copy.deepcopy(ref.store.data.get(ref.key));self.exists=self.value is not None
    def to_dict(self):return self.value
class Ref:
    def __init__(self,store,key):self.store=store;self.key=key;self.id=key[1]
    def get(self,**kwargs):return Snap(self)
    def set(self,value,merge=False):
        self.store.data[self.key]={**self.store.data.get(self.key,{}),**copy.deepcopy(value)} if merge else copy.deepcopy(value)
    def create(self,value):
        if self.key in self.store.data:raise api.AlreadyExists('exists')
        self.set(value)
    def delete(self):self.store.data.pop(self.key,None)
class Collection:
    def __init__(self,store,name):self.store=store;self.name=name
    def document(self,id):return Ref(self.store,(self.name,id))
    def stream(self):return [Snap(Ref(self.store,k)) for k in list(self.store.data) if k[0]==self.name]
class Memory:
    def __init__(self):self.data={}
    def collection(self,name):return Collection(self,name)

@pytest.fixture
def setup(monkeypatch):
    mem=Memory();monkeypatch.setattr(api,'_store',mem)
    @asynccontextmanager
    async def guard(aid):yield
    monkeypatch.setattr(api,'guard',guard)
    monkeypatch.setattr(api.auth,'verify_id_token',lambda token,**kw:{'uid':api.ADMIN_UID} if token=='valid' else {})
    mem.collection('adminData').document(api.ADMIN_UID).set({'dashboard':{'accounts':[{'id':'acct1','name':'Work'}]}})
    return mem

def record(**kw):
    return {'api_id':1,'api_hash':'a'*32,'phone':'+886912345678','session':'secret-session','ready':True,'enabled':True,'schedule':{'start':'00:00','end':'23:59','interval':5,'mode':'send','target':'me','message':'test'},**kw}

def test_auth_cors_and_no_credential_leak(setup):
    api.write('acct1',record())
    with TestClient(api.app) as c:
        assert c.get('/accounts').status_code==401
        assert c.get('/accounts',headers={'Authorization':'Bearer other'}).status_code==403
        res=c.get('/accounts',headers={'Authorization':'Bearer valid','Origin':'https://evil.test'})
        assert 'access-control-allow-origin' not in res.headers
        assert res.status_code==200
        assert 'secret-session' not in res.text and 'api_hash' not in res.text and '+886' not in res.text
    encrypted=setup.data[('_tgAccounts','acct1')]['ciphertext']
    assert 'secret-session' not in encrypted
    assert api.unprotect(encrypted)['session']=='secret-session'

def test_fails_closed_without_admin(setup,monkeypatch):
    def fail(*a,**k):raise ValueError('expired')
    monkeypatch.setattr(api.auth,'verify_id_token',fail)
    with TestClient(api.app) as c:
        assert c.get('/accounts',headers={'Authorization':'Bearer invalid'}).status_code==401
        assert c.post('/tick').status_code==401

def test_schedule_validation_and_pause(setup):
    api.write('acct1',record())
    with TestClient(api.app) as c:
        h={'Authorization':'Bearer valid'}
        assert c.put('/accounts/acct1/schedule',headers=h,json={'start':'99:00','end':'18:00','interval':5}).status_code==422
        assert c.put('/accounts/acct1/schedule',headers=h,json={'start':'09:00','end':'09:00','interval':5}).status_code==422
        assert c.put('/accounts/acct1/schedule',headers=h,json={'start':'09:00','end':'18:00','interval':5,'mode':'send'}).status_code==422
        assert c.put('/accounts/acct1/schedule',headers=h,json={'start':'22:00','end':'02:00','interval':3}).status_code==200
        assert not api.read('acct1')['enabled']

def test_two_factor_and_no_code_persistence(setup,monkeypatch):
    cl=AsyncMock();cl.sign_in.side_effect=api.errors.SessionPasswordNeededError(request=None)
    async def operation(a,fn):await fn(cl)
    monkeypatch.setattr(api,'with_client',operation)
    a=record(ready=False,enabled=False,code_expires=api.time.time()+600,phone_code_hash='hash');api.write('acct1',a)
    with TestClient(api.app) as c:
        h={'Authorization':'Bearer valid'}
        assert c.post('/accounts/acct1/login',headers=h,json={'code':'90807'}).json()['status']=='password_needed'
        cl.sign_in.side_effect=None
        assert c.post('/accounts/acct1/login',headers=h,json={'password':'test-password'}).json()['status']=='ok'
    assert api.read('acct1')['ready']
    assert 'test-password' not in str(api.read('acct1'))
    assert '90807' not in str(api.read('acct1'))

def test_unique_slot_and_unknown_result_stop(setup,monkeypatch):
    api.write('acct1',record())
    monkeypatch.setattr(api,'slot',lambda *a:'one-slot')
    cl=AsyncMock();cl.is_user_authorized.return_value=True;cl.send_message.side_effect=TimeoutError()
    async def operation(a,fn):await fn(cl)
    monkeypatch.setattr(api,'with_client',operation)
    asyncio.run(api.execute('acct1'));asyncio.run(api.execute('acct1'))
    assert cl.send_message.await_count==1
    assert not api.read('acct1')['enabled']
    assert api.read('acct1')['last_result']['status']=='unknown'

def test_floodwait_blocks_following_slot(setup,monkeypatch):
    api.write('acct1',record());monkeypatch.setattr(api,'slot',lambda *a:'one-slot')
    cl=AsyncMock();cl.is_user_authorized.return_value=True;cl.send_message.side_effect=api.errors.FloodWaitError(request=None,capture=600)
    async def operation(a,fn):await fn(cl)
    monkeypatch.setattr(api,'with_client',operation)
    asyncio.run(api.execute('acct1'))
    monkeypatch.setattr(api,'slot',lambda *a:'next-slot')
    asyncio.run(api.execute('acct1'))
    assert cl.send_message.await_count==1
    assert api.read('acct1')['cooldown_until']>api.time.time()

def test_interrupted_run_is_not_replayed(setup,monkeypatch):
    api.write('acct1',record(inflight='unknown-run'));operation=AsyncMock();monkeypatch.setattr(api,'with_client',operation)
    asyncio.run(api.execute('acct1'))
    operation.assert_not_awaited()
    assert api.read('acct1')['last_result']['status']=='unknown'
    assert not api.read('acct1')['enabled']

def test_midnight_window():
    from scheduling import TZ,slot
    assert slot(datetime(2026,10,28,0,2,tzinfo=TZ),'22:00','02:00',5)=='2026-10-28T00:00:00+08:00'
    assert slot(datetime(2026,10,28,2,0,tzinfo=TZ),'22:00','02:00',5) is None

def test_removed_dashboard_account_paused(setup,monkeypatch):
    api.write('removed',record())
    asyncio.run(api.tick())
    assert not api.read('removed')['enabled']

def test_success_deduplicates(setup,monkeypatch):
    api.write('acct1',record());monkeypatch.setattr(api,'slot',lambda *a:'one-slot')
    cl=AsyncMock();cl.is_user_authorized.return_value=True;cl.send_message.return_value.id=42
    async def operation(a,fn):await fn(cl)
    monkeypatch.setattr(api,'with_client',operation)
    asyncio.run(api.execute('acct1'));asyncio.run(api.execute('acct1'))
    assert cl.send_message.await_count==1
    assert api.read('acct1')['last_result']['status']=='ok'
