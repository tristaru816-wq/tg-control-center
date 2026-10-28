"""Windows DPAPI for local configuration and refresh tokens; OS process lock."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

class Vault:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':
            user=os.environ.get('USERDOMAIN','')+'\\'+os.environ['USERNAME']
            # Remove inherited access. Session files are accessible to this Windows user.
            subprocess.run(['icacls',str(self.root),'/inheritance:r','/grant:r',user+':(OI)(CI)F'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:os.chmod(self.root,0o700)
    def _crypt(self,value,decrypt=False):
        if os.name!='nt':raise OSError('此套件的憑證保存只支援 Windows DPAPI')
        from ctypes import wintypes
        class Blob(ctypes.Structure):_fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
        buf=ctypes.create_string_buffer(value)
        src=Blob(len(value),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));dst=Blob()
        crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        if decrypt:
            fn=crypt.CryptUnprotectData
            fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        else:
            fn=crypt.CryptProtectData
            fn.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        fn.restype=wintypes.BOOL
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(dst)):raise ctypes.WinError(ctypes.get_last_error())
        try:return ctypes.string_at(dst.pbData,dst.cbData)
        finally:kernel.LocalFree(dst.pbData)
    def save(self,name,value):
        path=self.root/(name+'.bin');tmp=path.with_suffix('.tmp')
        tmp.write_bytes(self._crypt(json.dumps(value).encode()))
        os.replace(tmp,path)
    def load(self,name):return json.loads(self._crypt((self.root/(name+'.bin')).read_bytes(),True))

def instance_lock(root):
    path=Path(root)/'worker.lock';f=path.open('a+b');f.seek(0)
    if not path.stat().st_size:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise RuntimeError('此資料夾已有執行器在運行，請勿重複啟動')
    return f
