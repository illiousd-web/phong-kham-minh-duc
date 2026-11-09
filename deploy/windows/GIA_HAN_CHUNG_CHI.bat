@echo off
setlocal
rem Minh Duc - GIA HAN CHUNG CHI HTTPS bang CA hien co (may tram KHONG phai cai lai).
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0GiaHanChungChi.ps1" %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo Ma ket qua: %RC%. Doc thong bao phia tren; neu loi, chung chi cu da duoc tra lai.
)
echo %* | findstr /i /c:"-KhongHoi" >nul || pause
exit /b %RC%
