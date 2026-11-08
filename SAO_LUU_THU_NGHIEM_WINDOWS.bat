@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Chua cai dat moi truong .venv. Hay chay START_WINDOWS.bat truoc.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" scripts\backup_demo.py create
pause
