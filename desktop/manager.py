import argparse
import asyncio
import getpass
import hashlib
import os
from pathlib import Path
import re
import sys
import uuid

from telethon import TelegramClient,errors
from cloud import Cloud,CloudError
from engine import Engine
from local import Vault,instance_lock

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'

def firebase_login(cloud):
    print('\n登入你原網站的 Firebase 管理員帳號（不是 Google 帳號密碼）。')
    email=input('管理員信箱：').strip();password=getpass.getpass('管理員密碼（輸入時不顯示）：')
    try:cloud.login(email,password)
    finally:password=''
    cloud.get();print('已連接原有 Firebase 資料。')

async def tg_login(cloud,vault,config):
    d=cloud.get();rows=d.get('dashboard',{}).get('accounts',[])[:50]
    if not rows:
        print('請先在手機網頁的「帳號」頁新增帳號資料，等候 Firebase 同步後再試。');return
    print('\n選擇要在這台電腦登入的帳號：')
    for i,a in enumerate(rows,1):print(f"{i}. {a['name']}")
    try:a=rows[int(input('編號：'))-1]
    except (ValueError,IndexError):print('編號無效');return
    aid=a['id']
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',aid):raise ValueError('帳號 ID 格式無效')
    if aid in config['accounts']:
        print('此帳號已有本機設定。請先使用選單登出後再更換登入。');return
    print('API 資料可在 https://my.telegram.org 申請。只會保存在這台電腦。')
    phone=input('TG 電話（含國碼，例如 +886…）：').strip()
    if not re.fullmatch(r'\+[1-9][0-9]{6,14}',phone):raise ValueError('電話格式錯誤')
    api_id=int(input('API ID：').strip());api_hash=getpass.getpass('API Hash（輸入不顯示）：').strip()
    if api_id<=0 or not re.fullmatch('[a-fA-F0-9]{32}',api_hash):raise ValueError('API ID / Hash 格式錯誤')
    path=DATA/('tg_'+hashlib.sha256(aid.encode()).hexdigest())
    cl=TelegramClient(str(path),api_id,api_hash,flood_sleep_threshold=0,request_retries=0,connection_retries=0,timeout=10)
    try:
        async with asyncio.timeout(300):
            await cl.connect()
            if not await cl.is_user_authorized():
                sent=await cl.send_code_request(phone)
                code=input('Telegram 驗證碼：').strip()
                try:await cl.sign_in(phone=phone,code=code,phone_code_hash=sent.phone_code_hash)
                except errors.SessionPasswordNeededError:
                    password=getpass.getpass('TG 兩步驗證密碼（輸入不顯示）：')
                    try:await cl.sign_in(password=password)
                    finally:password=''
                finally:code=''
            config['accounts'][aid]={'api_id':api_id,'api_hash':api_hash,'phone':phone,'name':a['name']}
            vault.save('settings',config)
            print('TG 已登入本機。選擇「啟動同步與排程」後，手機會顯示帳號可用。')
    finally:
        try:await asyncio.wait_for(cl.disconnect(),3)
        except Exception:pass

async def tg_logout(config,vault):
    rows=list(config['accounts'].items())
    if not rows:print('沒有本機 TG 帳號');return
    for i,(aid,a) in enumerate(rows,1):print(f"{i}. {a['name']}")
    index=int(input('要登出的編號：'))-1
    if not 0<=index<len(rows):raise ValueError('編號無效')
    aid,a=rows[index]
    if input('確定登出並移除本機憑證？輸入 YES：')!='YES':return
    cl=TelegramClient(str(DATA/('tg_'+hashlib.sha256(aid.encode()).hexdigest())),a['api_id'],a['api_hash'],flood_sleep_threshold=0,request_retries=0,connection_retries=0,timeout=10)
    try:
        async with asyncio.timeout(30):
            await cl.connect();await cl.log_out()
        del config['accounts'][aid];vault.save('settings',config);print('已登出本機 TG。')
    finally:
        try:await asyncio.wait_for(cl.disconnect(),3)
        except Exception:pass

def main():
    if os.name!='nt':raise RuntimeError('此使用者安裝包僅支援 Windows；請在 Windows 電腦執行。')
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--setup',action='store_true');args=parser.parse_args()
    vault=Vault(DATA);file_lock=instance_lock(DATA)
    try:config=vault.load('settings')
    except FileNotFoundError:
        config={'worker_id':str(uuid.uuid4()),'accounts':{}};vault.save('settings',config)
    cloud=Cloud(vault)
    if not cloud.refresh_token:firebase_login(cloud)
    if not args.setup and config['accounts']:
        asyncio.run(Engine(cloud,DATA,config['worker_id'],config['accounts']).run());return
    while True:
        print('\nTG 電腦執行器 3.0\n1. 新增／登入 TG 帳號\n2. 啟動同步與排程\n3. 查看本機帳號\n4. 重新登入 Firebase 管理員\n5. 登出本機 TG 帳號\n0. 離開')
        choice=input('請輸入編號：').strip()
        try:
            if choice=='1':asyncio.run(tg_login(cloud,vault,config))
            elif choice=='2':
                if not config['accounts']:print('請先登入至少一個 TG 帳號');continue
                asyncio.run(Engine(cloud,DATA,config['worker_id'],config['accounts']).run());break
            elif choice=='3':
                for a in config['accounts'].values():print(a['name']+' · '+a['phone'])
            elif choice=='4':firebase_login(cloud)
            elif choice=='5':asyncio.run(tg_logout(config,vault))
            elif choice=='0':break
        except errors.FloodWaitError as e:print(f'Telegram 要求等待 {e.seconds} 秒，請勿反覆取得驗證碼。')
        except CloudError as e:print(str(e))
        except Exception as e:print('操作未完成：'+type(e).__name__+'。請確認輸入、網路與 TG 權限。')
    file_lock.close()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\n已停止。')
    except (CloudError,RuntimeError) as e:print(str(e));sys.exit(1)
    except Exception as e:print('啟動失敗：'+type(e).__name__+'。請確認 Python、Windows 使用者權限與網路。');sys.exit(1)
