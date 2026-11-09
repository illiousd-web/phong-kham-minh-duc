@echo off
setlocal
rem Minh Duc - CAI DAT MAY CHU (Python 3.12, PostgreSQL 17, dich vu web, sao luu).
rem Bam dup de chay. Windows se hoi quyen Administrator: chon "Yes" (Co).
net session >nul 2>&1
if errorlevel 1 (
  if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b
)
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CaiDat.ps1" %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo Ma ket qua: %RC%. Doc dong "DUNG LAI" phia tren. Huong dan: docs\CAI_DAT_TUNG_BUOC.md, muc "Gap loi".
)
echo %* | findstr /i /c:"-KhongHoi" >nul || pause
exit /b %RC%
