@echo off
setlocal
rem Minh Duc - CAP NHAT: sao luu, kiem ban sao luu, thay ma tu tep zip, migration, kiem tra.
rem Loi o buoc nao thi tu quay ve ban cu. Bam dup de chay; chon "Yes" khi Windows hoi quyen.
net session >nul 2>&1
if errorlevel 1 (
  if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b
)
(
  chcp 65001 >nul
  if exist "%TEMP%\MinhDuc-CapNhat" rmdir /s /q "%TEMP%\MinhDuc-CapNhat"
  mkdir "%TEMP%\MinhDuc-CapNhat"
  copy /y "%~dp0CapNhat.ps1" "%TEMP%\MinhDuc-CapNhat\" >nul
  copy /y "%~dp0MinhDuc.Install.psm1" "%TEMP%\MinhDuc-CapNhat\" >nul
  copy /y "%~dp0DanhMucGoc.ps1" "%TEMP%\MinhDuc-CapNhat\" >nul
  cd /d "%TEMP%\MinhDuc-CapNhat"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\MinhDuc-CapNhat\CapNhat.ps1" -ThuMucMa "%~dp0..\.." %*
  call set "RC=%%errorlevel%%"
  call echo Ma ket qua: %%RC%% ^(0 = thanh cong^).
  echo %* | findstr /i /c:"-KhongHoi" >nul || pause
  rem Expand the saved result at execution time; CALL may reset errorlevel.
  setlocal EnableDelayedExpansion
  exit /b !RC!
)
