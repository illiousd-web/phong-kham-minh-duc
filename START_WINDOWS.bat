@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Phong kham Minh Duc - demo

echo ===================================================
echo   PHONG KHAM MINH DUC - KHOI DONG DEMO v0.3
echo ===================================================
echo Thu muc: %CD%
echo.

rem Uu tien su dung moi truong da cai san (khong bat buoc py)
if exist ".venv\Scripts\python.exe" goto INSTALL_DEPS

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1 && set "PY_CMD=py -3.13"
  if not defined PY_CMD py -3.12 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1 && set "PY_CMD=py -3.12"
  if not defined PY_CMD py -3.11 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1 && set "PY_CMD=py -3.11"
)
if not defined PY_CMD (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; assert sys.version_info >= (3,11) and sys.version_info < (3,14)" >nul 2>&1 && set "PY_CMD=python"
  )
)
if not defined PY_CMD (
  echo [LOI] Khong tim thay Python phu hop 3.11 - 3.13.
  echo Cai Python 3.12 64-bit tu https://www.python.org/downloads/windows/
  echo Khi cai, chon "Add python.exe to PATH" va cai Python Launcher neu duoc hoi.
  echo Cai xong dong/mo lai cua so va chay START_WINDOWS.bat.
  goto FAILED
)
echo [1/3] Tao moi truong Python bang %PY_CMD% ...
%PY_CMD% -m venv .venv
if errorlevel 1 (
  echo [LOI] Khong tao duoc thu muc .venv. Kiem tra quyen ghi tren o dia.
  goto FAILED
)

:INSTALL_DEPS
if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Chua co file .venv\Scripts\python.exe
  goto FAILED
)
echo [2/3] Cai/kiem tra thu vien. Lan dau can ket noi Internet.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [LOI] Cai thu vien that bai. Kiem tra Internet / proxy / dia trong.
  echo Co the chay: .venv\Scripts\python.exe -m pip install --upgrade pip
  goto FAILED
)
echo [3/3] Khoi dong web server tai http://127.0.0.1:8000
echo Mo Chrome hoac Edge tren CUNG MAY TINH theo dia chi tren.
echo Chi nhap du lieu GIA LAP. KHONG mo cong ra Internet.
echo Nhan Ctrl+C de dung chuong trinh.
echo.
".venv\Scripts\python.exe" scripts\run_demo.py
if errorlevel 1 (
  echo [LOI] Server khong khoi dong. Co the cong 8000 dang duoc su dung.
  echo Mo PowerShell tai thu muc nay va thu:
  echo .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
)
goto END

:FAILED
echo.
echo Vui long chup anh CAC DONG LOI o cua so nay de duoc ho tro.
:END
pause
endlocal
