@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0Preflight.ps1" -Root "%~dp0..\.."
if errorlevel 1 (
 echo Chua vuot qua Preflight. Khong khoi dong ban thu moi.
 pause
 exit /b 2
)
powershell.exe -NoProfile -File "%~dp0Run-Clinic.ps1" -Root "%~dp0..\.." -Config "C:\ProgramData\MinhDuc\clinic.env"
echo.
echo Neu khong vao duoc: xem huong dan Windows 8 GB va tep server.log.
echo Khong tat Firewall/Defender de thu lai.
pause
