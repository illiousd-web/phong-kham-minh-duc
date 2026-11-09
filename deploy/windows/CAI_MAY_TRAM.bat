@echo off
setlocal EnableExtensions
rem Minh Duc - CAI MAY TRAM: tin cay chung chi phong kham, tao bieu tuong Desktop.
rem Chay duoc tren Windows 7 SP1, 10, 11. Chi dung lenh co san cua Windows: certutil va cscript.
rem Bam dup de chay. Windows se hoi quyen Administrator: chon "Yes" (Co).
set "HERE=%~dp0"
set "KHONGHOI="
if /i "%~1"=="-KhongHoi" set "KHONGHOI=1"
net session >nul 2>&1
if errorlevel 1 (
  cscript //nologo "%HERE%MayTram.vbs" elevate "%~f0" %*
  exit /b
)
echo ==========================================================
echo  CAI MAY TRAM - PHONG KHAM DA KHOA MINH DUC
echo ==========================================================
if not exist "%HERE%ca.crt" (
  echo DUNG LAI: khong thay tep ca.crt.
  echo  - Chep NGUYEN thu muc C:\MinhDuc-ChiaSe tu may chu sang may nay roi chay lai.
  set "RC=3" & goto ketthuc
)
if not exist "%HERE%may-chu.txt" (
  echo DUNG LAI: khong thay tep may-chu.txt.
  echo  - Chep NGUYEN thu muc C:\MinhDuc-ChiaSe tu may chu sang may nay roi chay lai.
  set "RC=2" & goto ketthuc
)
set "DIACHI="
set "VANTAY="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /c:"DIA_CHI=" "%HERE%may-chu.txt"`) do set "DIACHI=%%b"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /c:"VAN_TAY_CA=" "%HERE%may-chu.txt"`) do set "VANTAY=%%b"
echo %DIACHI%| findstr /r /x "https://[0-9][0-9.]*:[0-9][0-9]*" >nul
if errorlevel 1 (
  echo DUNG LAI: dia chi may chu trong may-chu.txt khong hop le.
  set "RC=2" & goto ketthuc
)

rem 1. Dung chung chi goc cua phong kham, van tay khop voi may chu.
certutil -dump "%HERE%ca.crt" | findstr /c:"CN=Minh Duc LAN Pilot CA" >nul
if errorlevel 1 (
  echo DUNG LAI: ca.crt khong phai chung chi goc cua phong kham Minh Duc. Khong cai tep la.
  set "RC=4" & goto ketthuc
)
set "TMPD=%TEMP%\minhduc-ca-%RANDOM%%RANDOM%"
mkdir "%TMPD%" >nul 2>&1
certutil -f -decode "%HERE%ca.crt" "%TMPD%\ca.der" >nul
if errorlevel 1 (
  echo DUNG LAI: khong doc duoc ca.crt.
  set "RC=4" & goto ketthuc
)
set "FP="
for /f "skip=1 delims=" %%h in ('certutil -hashfile "%TMPD%\ca.der" SHA256') do if not defined FP set "FP=%%h"
rmdir /s /q "%TMPD%" >nul 2>&1
set "FP=%FP: =%"
if /i not "%FP%"=="%VANTAY%" (
  echo DUNG LAI: van tay chung chi khong khop tep may-chu.txt. Lay lai thu muc tu may chu.
  set "RC=5" & goto ketthuc
)
echo   Van tay chung chi: %FP:~0,8%  ^(phai giong 8 ky tu in tren man hinh may chu luc cai^)
if not defined KHONGHOI (
  set "ANS="
  set /p "ANS=  Tam ky tu tren co giong may chu khong? Go C la co, K la khong, roi Enter: "
)
if not defined KHONGHOI (
  if /i not "%ANS%"=="C" (
    echo DUNG LAI: ban chon khong cai. Bao nguoi ho tro; khong bam bo qua canh bao chung chi tren trinh duyet.
    set "RC=6" & goto ketthuc
  )
)

rem 2. Tin cay chung chi goc (chi chung chi cong khai) trong kho Trusted Root cua may.
certutil -addstore -f Root "%HERE%ca.crt" >nul
if errorlevel 1 (
  echo DUNG LAI: khong cai duoc chung chi vao kho tin cay. Chay lai bang quyen Administrator.
  set "RC=7" & goto ketthuc
)
echo   [DAT] Da cai chung chi phong kham vao kho tin cay cua Windows.

rem 3. Bieu tuong Desktop mo Chrome che do ung dung (khong co Chrome thi Edge).
cscript //nologo "%HERE%MayTram.vbs" shortcut "%DIACHI%"
if errorlevel 3 (
  echo   [KHONG DAT] Chua co Chrome hoac Edge. Cai Google Chrome roi chay lai.
  set "RC=8" & goto ketthuc
)
echo   [DAT] Da tao bieu tuong "Phong kham Minh Duc" tren Desktop.

rem 4. Thu ket noi (Windows 10/11 co curl.exe; Windows 7 khong co: mo bieu tuong de thu).
where curl.exe >nul 2>&1
if errorlevel 1 (
  echo   [LUU Y] Windows nay khong co cong cu thu ket noi. Bam dup bieu tuong: thay trang dang nhap la dat.
  set "RC=0" & goto ketthuc
)
set "HTTP="
for /f %%c in ('curl.exe -s -o nul -w "%%{http_code}" --max-time 15 --ssl-no-revoke "%DIACHI%/api/health"') do set "HTTP=%%c"
if "%HTTP%"=="200" (
  echo   [DAT] Ket noi duoc may chu %DIACHI%, chung chi hop le.
  set "RC=0" & goto ketthuc
)
echo   [KHONG DAT] Chua ket noi duoc %DIACHI% ^(ma %HTTP%^).
echo    - May nay va may chu phai cung mang phong kham; may chu phai dang bat.
set "RC=9"

:ketthuc
echo.
if "%RC%"=="0" echo HOAN TAT. Bam dup bieu tuong "Phong kham Minh Duc" tren Desktop de dang nhap.
if not "%RC%"=="0" echo Ma ket qua: %RC%. Doc thong bao phia tren hoac goi nguoi ho tro.
if not defined KHONGHOI pause
exit /b %RC%
