import asyncio
import copy
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import cloud
import engine
from engine import Engine,Busy

class MemoryCloud:
    def __init__(self):
        self.version=1;self.calls=[]
        self.data={'dashboard':{'accounts':[{'id':'a','name':'A'}],'attendance':[{'note':'keep'}]},'executionEndpoint':'keep-old-config','desktopConfig':{'plans':{'a':{'start':'09:00','end':'18:00','interval':5,'mode':'send','target':'me','message':'hello','enabled':True}}}}
    def get(self):return {**copy.deepcopy(self.data),'_updateTime':str(self.version),'_serverNow':time.time()}
    def patch(self,fields,version):
        assert fields,'No empty masked write permitted'
        if version!=str(self.version):raise cloud.Conflict('race')
        self.data.update(copy.deepcopy(fields));self.version+=1;self.calls.append(copy.deepcopy(fields))

@pytest.fixture
def worker(tmp_path,monkeypatch):
    c=MemoryCloud();e=Engine(c,tmp_path,'pc1',{'a':{'api_id':1,'api_hash':'a'*32}});e.ready.add('a');e.heartbeat()
    monkeypatch.setattr(engine,'slot',lambda *args:'slot1')
    yield e,c
    e.sql.close()

def test_firestore_round_trip_and_empty_patch_guard():
    values={'name':'玉如','enabled':False,'n':3,'map':{'status':None},'list':[1,True,'a'],'double':2.5}
    assert cloud.decode(cloud.encode(values))==values
    class Vault:
        def load(self,k):raise FileNotFoundError()
    c=cloud.Cloud(Vault())
    with pytest.raises(ValueError):c.patch({},'version')

def test_noop_never_writes_or_destroys_dashboard(worker):
    e,c=worker;c.data['desktopConfig']['plans']['a']['enabled']=False
    before=copy.deepcopy(c.data);count=len(c.calls)
    assert e.claim('a') is None
    assert c.data==before and len(c.calls)==count
    assert c.data['dashboard']['attendance']==[{'note':'keep'}]
    assert c.data['executionEndpoint']=='keep-old-config'

def test_global_claim_stops_duplicate_on_second_computer(worker,tmp_path):
    e,c=worker
    assert e.claim('a') is not None
    e2=Engine(c,tmp_path/'..','pc2',{});e2.ready.add('a')
    try:
        with pytest.raises(Busy):e2.heartbeat()
        c.data['desktopLease']['until']=0
        e2.heartbeat()
        assert e2.claim('a') is None
        assert c.data['desktopStatus']['accounts']['a']['blocked']
    finally:e2.sql.close()

def test_unknown_requires_explicit_ack_and_does_not_replay(worker,monkeypatch):
    e,c=worker;assert e.claim('a')
    assert e.claim('a') is None
    p=c.data['desktopConfig']['plans']['a'];p['enabled']=False;p['ack']='manual-ack'
    assert e.claim('a') is None
    st=c.data['desktopStatus']['accounts']['a']
    assert not st['blocked'] and st['ackSeen']=='manual-ack'
    p['enabled']=True
    assert e.claim('a') is None
    monkeypatch.setattr(engine,'slot',lambda *args:'slot2')
    assert e.claim('a') is not None

def test_success_once_and_cloud_result(worker,monkeypatch):
    e,c=worker;client=AsyncMock();client.is_user_authorized.return_value=True;client.send_message.return_value.id=99
    monkeypatch.setattr(e,'client',lambda aid:client)
    asyncio.run(e.run_account('a'));asyncio.run(e.run_account('a'))
    assert client.send_message.await_count==1
    assert c.data['desktopStatus']['accounts']['a']['status']=='ok'
    assert e.sql.execute('SELECT status FROM runs').fetchone()[0]=='ok'
    assert len(c.data['desktopStatus']['history'])==1

def test_network_uncertain_pauses_and_never_retries(worker,monkeypatch):
    e,c=worker;client=AsyncMock();client.is_user_authorized.return_value=True;client.send_message.side_effect=OSError()
    monkeypatch.setattr(e,'client',lambda aid:client)
    asyncio.run(e.run_account('a'));asyncio.run(e.run_account('a'))
    assert client.send_message.await_count==1
    assert c.data['desktopStatus']['accounts']['a']['blocked']

def test_floodwait_survives_new_slot(worker,monkeypatch):
    e,c=worker;client=AsyncMock();client.is_user_authorized.return_value=True;client.send_message.side_effect=engine.errors.FloodWaitError(request=None,capture=600)
    monkeypatch.setattr(e,'client',lambda aid:client)
    asyncio.run(e.run_account('a'))
    monkeypatch.setattr(engine,'slot',lambda *args:'slot2')
    asyncio.run(e.run_account('a'))
    assert client.send_message.await_count==1
    assert c.data['desktopStatus']['accounts']['a']['cooldownUntil']>time.time()

def test_no_send_when_cloud_claim_fails(worker,monkeypatch):
    e,c=worker;client=AsyncMock();monkeypatch.setattr(e,'client',lambda aid:client)
    monkeypatch.setattr(c,'patch',lambda *a:(_ for _ in ()).throw(cloud.CloudError('network')))
    with pytest.raises(cloud.CloudError):asyncio.run(e.run_account('a'))
    client.send_message.assert_not_awaited()

def test_pause_delete_and_missing_local_session_prevent_claim(worker):
    e,c=worker
    c.data['dashboard']['accounts']=[]
    assert e.claim('a') is None
    c.data['dashboard']['accounts']=[{'id':'a'}];e.ready.clear()
    assert e.claim('a') is None

def test_status_write_failure_blocks_next_worker(worker,monkeypatch):
    e,c=worker;client=AsyncMock();client.is_user_authorized.return_value=True;client.send_message.return_value.id=99
    monkeypatch.setattr(e,'client',lambda aid:client)
    monkeypatch.setattr(e,'report',lambda *a:(_ for _ in ()).throw(cloud.CloudError('save failed')))
    with pytest.raises(cloud.CloudError):asyncio.run(e.run_account('a'))
    assert c.data['desktopStatus']['accounts']['a']['status']=='running'
    assert e.claim('a') is None
    assert client.send_message.await_count==1

def test_invalid_schedule_fails_before_send(worker):
    e,c=worker;c.data['desktopConfig']['plans']['a']['interval']=1
    with pytest.raises(ValueError):e.claim('a')

def test_refresh_token_uses_rotated_token_and_admin_gate(monkeypatch):
    class Vault:
        def __init__(self):self.values={'refresh_token':'old'}
        def load(self,k):return self.values
        def save(self,k,v):self.values=v
    class Reply:
        ok=True
        def json(self):return {'user_id':cloud.ADMIN_UID,'id_token':'fresh','refresh_token':'rotated','expires_in':'3600'}
    monkeypatch.setattr(cloud.requests,'post',lambda *a,**kw:Reply())
    v=Vault();c=cloud.Cloud(v)
    assert c.auth()=='fresh' and v.values=={'refresh_token':'rotated'}
    monkeypatch.setattr(Reply,'json',lambda self:{'user_id':'wrong'})
    c.expires=0
    with pytest.raises(cloud.CloudError):c.auth()

def test_firestore_precondition_conflict_is_retryable(monkeypatch):
    class Vault:
        def load(self,k):raise FileNotFoundError()
    class Reply:
        status_code=400;ok=False
        def json(self):return {'error':{'status':'FAILED_PRECONDITION'}}
    monkeypatch.setattr(cloud.requests,'patch',lambda *a,**kw:Reply())
    c=cloud.Cloud(Vault());c.token='memory-only';c.expires=time.monotonic()+100
    with pytest.raises(cloud.Conflict):c.patch({'desktopStatus':{}},'old-version')

@pytest.mark.parametrize('code', ['INVALID_LOGIN_CREDENTIALS','API_KEY_HTTP_REFERRER_BLOCKED','OPERATION_NOT_ALLOWED'])
def test_auth_error_displays_safe_actionable_code(code):
    class Reply:
        status_code=400
        def json(self):return {'error':{'message':code,'metadata':{'password':'private-password','idToken':'private-token'}}}
    message=str(cloud.auth_error(Reply()))
    assert code in message
    assert 'private-password' not in message and 'private-token' not in message

def test_auth_error_uses_reason_and_hides_unrecognized_body():
    class Reply:
        status_code=403
        def json(self):return {'error':{'message':'contains private-password','details':[{'reason':'API_KEY_HTTP_REFERRER_BLOCKED'}]}}
    assert 'API_KEY_HTTP_REFERRER_BLOCKED' in str(cloud.auth_error(Reply()))
    class Unknown:
        status_code=500
        def json(self):return {'error':{'message':'private-password'}}
    text=str(cloud.auth_error(Unknown()))
    assert 'HTTP_500' in text and 'private-password' not in text
