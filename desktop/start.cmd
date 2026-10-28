@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
echo TG Desktop Worker - Windows launcher v3.1
echo.
if exist ".venv\Scripts\python.exe" goto dependencies
py -3 -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if errorlevel 1 goto try_python
set "TG_WORKER_PY=py -3"
goto create_venv
:try_python
python -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if errorlevel 1 goto missing_python
set "TG_WORKER_PY=python"
:create_venv
echo Creating Python environment...
%TG_WORKER_PY% -m venv .venv
if errorlevel 1 goto failed
:dependencies
".venv\Scripts\python.exe" -c "import telethon, requests, tzdata" >nul 2>&1
if not errorlevel 1 goto run
 echo Installing required packages. Please wait...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:run
".venv\Scripts\python.exe" manager.py %*
if errorlevel 1 goto failed
goto finished
:missing_python
echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo Include Python Launcher, then run this file again.
goto finished
:failed
echo.
echo Startup stopped. Please take a screenshot of the error above.
:finished
echo.
pause
endlocal
