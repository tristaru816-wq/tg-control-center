@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import telethon,requests,tzdata" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe manager.py %*
pause
exit /b
:failed
echo 請先安裝 Python 3.11 以上版本，包含 Python Launcher，並確認網路可下載套件。
pause
exit /b 1
