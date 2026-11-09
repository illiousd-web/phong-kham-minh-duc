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
echo.
if "%RC%"=="0" (
  echo Ma 0: DAT. Xem thong bao phia tren.
) else if "%RC%"=="50" (
  echo Ma 50: GIA HAN LOI nhung DA TRA CHUNG CHI CU va HTTPS da kiem lai: DAT.
  echo Bao nguoi ho tro de gia han lai.
) else if "%RC%"=="51" (
  echo Ma 51: KHONG TRA DUOC CHUNG CHI CU / PHUC HOI KHONG THANH CONG.
  echo Phan mem CO THE KHONG TRUY CAP DUOC tu may tram. GOI NGUOI HO TRO NGAY.
) else (
  echo Ma %RC%: LOI. Doc dong "DUNG LAI" phia tren va nhat ky C:\ProgramData\MinhDuc\nhatky\ket-qua-gia-han.json
)
echo %* | findstr /i /c:"-KhongHoi" >nul || pause
exit /b %RC%
