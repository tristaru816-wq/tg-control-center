"""Firebase user authentication and masked Firestore writes. No service account key."""
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests

API_KEY='AIzaSyB7hUADy7ylleU7JuzY9_ucieDzpcmYr4s'
PROJECT='tg-control-center'
ADMIN_UID='3bYS2rcw9jOf4A5sIvdO5DejMKP2'
DOCUMENT=f'https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents/adminData/{ADMIN_UID}'
class CloudError(Exception):pass
class Conflict(CloudError):pass

def encode(v):
    if v is None:return {'nullValue':None}
    if isinstance(v,bool):return {'booleanValue':v}
    if isinstance(v,int):return {'integerValue':str(v)}
    if isinstance(v,float):return {'doubleValue':v}
    if isinstance(v,str):return {'stringValue':v}
    if isinstance(v,list):return {'arrayValue':{'values':[encode(x) for x in v]}}
    if isinstance(v,dict):return {'mapValue':{'fields':{k:encode(x) for k,x in v.items()}}}
    raise ValueError('Unsupported Firestore value')
def decode(v):
    for key,value in v.items():
        if key in ('stringValue','timestampValue','booleanValue','doubleValue'):return value
        if key=='integerValue':return int(value)
        if key=='nullValue':return None
        if key=='mapValue':return {k:decode(x) for k,x in value.get('fields',{}).items()}
        if key=='arrayValue':return [decode(x) for x in value.get('values',[])]
    return None

class Cloud:
    def __init__(self,vault):
        self.vault=vault;self.token='';self.expires=0;self.refresh_token=''
        try:self.refresh_token=vault.load('firebase')['refresh_token']
        except (OSError,ValueError,KeyError):pass
    def login(self,email,password):
        r=requests.post(f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}',json={'email':email,'password':password,'returnSecureToken':True},timeout=15)
        if not r.ok:raise CloudError('Firebase 登入失敗，請確認管理員信箱與密碼')
        d=r.json()
        if d.get('localId')!=ADMIN_UID:raise CloudError('此帳號沒有管理員權限')
        self.token=d['idToken'];self.refresh_token=d['refreshToken'];self.expires=time.monotonic()+int(d['expiresIn'])-90
        self.vault.save('firebase',{'refresh_token':self.refresh_token})
    def auth(self):
        if self.token and time.monotonic()<self.expires:return self.token
        if not self.refresh_token:raise CloudError('請先登入 Firebase 管理員')
        r=requests.post(f'https://securetoken.googleapis.com/v1/token?key={API_KEY}',data={'grant_type':'refresh_token','refresh_token':self.refresh_token},timeout=15)
        if not r.ok:raise CloudError('管理員登入已失效，請執行「設定與登入.cmd」重新登入')
        d=r.json()
        if d.get('user_id')!=ADMIN_UID:raise CloudError('管理員 UID 不符')
        self.token=d['id_token'];self.refresh_token=d['refresh_token'];self.expires=time.monotonic()+int(d['expires_in'])-90
        self.vault.save('firebase',{'refresh_token':self.refresh_token})
        return self.token
    def get(self):
        r=requests.get(DOCUMENT,headers={'Authorization':'Bearer '+self.auth(),'Cache-Control':'no-cache'},timeout=15)
        if not r.ok:raise CloudError('讀取雲端設定失敗，請確認網路與 Firestore 管理員規則')
        d=r.json()
        if not d.get('updateTime'):raise CloudError('請先在網頁登入並儲存一個帳號')
        result={k:decode(v) for k,v in d.get('fields',{}).items()}
        result['_updateTime']=d['updateTime']
        # Use the response server clock rather than relying on each PC's clock for leases.
        result['_serverNow']=parsedate_to_datetime(r.headers['Date']).timestamp() if r.headers.get('Date') else time.time()
        return result
    def patch(self,fields,version):
        if not fields:raise ValueError('拒絕沒有欄位遮罩的更新')
        params=[('updateMask.fieldPaths',k) for k in fields]+[('currentDocument.updateTime',version)]
        r=requests.patch(DOCUMENT,params=params,headers={'Authorization':'Bearer '+self.auth()},json={'fields':{k:encode(v) for k,v in fields.items()}},timeout=15)
        conflict=r.status_code in (409,412)
        if r.status_code==400:
            try:conflict=r.json().get('error',{}).get('status')=='FAILED_PRECONDITION'
            except ValueError:pass
        if conflict:raise Conflict('雲端資料同時更新，稍後重試')
        if not r.ok:raise CloudError('寫入雲端狀態失敗，已停止新的 TG 操作')
        return r.json()
