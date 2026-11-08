@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Chua co .venv. Hay chay START_WINDOWS.bat de cai thu vien truoc.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-test.txt
if errorlevel 1 (
 echo Khong cai duoc thu vien kiem thu.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q
pause
