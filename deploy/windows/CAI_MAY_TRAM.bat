@echo off
setlocal EnableExtensions
rem Minh Duc - CAI MAY TRAM: tin cay chung chi phong kham, tao bieu tuong Desktop.
rem Chay duoc tren Windows 7 SP1, 10, 11. Chi dung lenh co san cua Windows: certutil va cscript.
rem Bam dup de chay. Windows se hoi quyen Administrator: chon "Yes" (Co).
rem Moi ma thoat khac 0 cua certutil va cscript (ke ca ma am) deu la loi: kiem bang "neq 0",
rem khong dung "if errorlevel 1" (bo sot ma am).
set "HERE=%~dp0"
set "KHONGHOI="
set "KIEMTAY="
if /i "%~1"=="-KhongHoi" set "KHONGHOI=1"
net session >nul 2>&1
if not errorlevel 1 goto coquyen
cscript //nologo "%HERE%MayTram.vbs" elevate "%~f0" %*
if %errorlevel% neq 0 (
  echo DUNG LAI: khong xin duoc quyen Administrator ^(cscript ma %errorlevel%^).
  echo  - Bam chuot phai CAI_MAY_TRAM.bat, chon "Run as administrator".
  if not defined KHONGHOI pause
  exit /b 10
)
exit /b 0
:coquyen
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
set "TMPD=%TEMP%\minhduc-ca-%RANDOM%%RANDOM%"
mkdir "%TMPD%" >nul 2>&1
certutil -dump "%HERE%ca.crt" >"%TMPD%\dump.txt" 2>&1
if %errorlevel% neq 0 (
  echo DUNG LAI: certutil khong doc duoc ca.crt ^(ma %errorlevel%^).
  set "RC=4" & goto donvaket
)
findstr /c:"CN=Minh Duc LAN Pilot CA" "%TMPD%\dump.txt" >nul
if errorlevel 1 (
  echo DUNG LAI: ca.crt khong phai chung chi goc cua phong kham Minh Duc. Khong cai tep la.
  set "RC=4" & goto donvaket
)
certutil -f -decode "%HERE%ca.crt" "%TMPD%\ca.der" >nul 2>&1
if %errorlevel% neq 0 (
  echo DUNG LAI: certutil khong giai ma duoc ca.crt ^(ma %errorlevel%^).
  set "RC=4" & goto donvaket
)
certutil -hashfile "%TMPD%\ca.der" SHA256 >"%TMPD%\hash.txt" 2>&1
if %errorlevel% neq 0 (
  echo DUNG LAI: certutil khong tinh duoc van tay SHA-256 ^(ma %errorlevel%^).
  set "RC=4" & goto donvaket
)
set "FP="
for /f "usebackq skip=1 delims=" %%h in ("%TMPD%\hash.txt") do if not defined FP set "FP=%%h"
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
if %errorlevel% neq 0 (
  echo DUNG LAI: khong cai duoc chung chi vao kho tin cay ^(certutil ma %errorlevel%^). Chay lai bang quyen Administrator.
  set "RC=7" & goto ketthuc
)
echo   [DAT] Da cai chung chi phong kham vao kho tin cay cua Windows.

rem 3. Bieu tuong Desktop mo Chrome che do ung dung (khong co Chrome thi Edge).
cscript //nologo "%HERE%MayTram.vbs" shortcut "%DIACHI%"
set "VBRC=%errorlevel%"
if "%VBRC%"=="3" (
  echo   [KHONG DAT] Chua co Chrome hoac Edge. Cai Google Chrome roi chay lai.
  set "RC=8" & goto ketthuc
)
if not "%VBRC%"=="0" (
  echo   [KHONG DAT] Khong tao duoc bieu tuong ^(cscript ma %VBRC%^). Goi nguoi ho tro.
  set "RC=11" & goto ketthuc
)
rem Kiem tep .lnk that su ton tai (ten co dau, dung ky tu dai dien).
if not exist "%PUBLIC%\Desktop\Ph*ng kh*m Minh *.lnk" (
  echo   [KHONG DAT] Khong thay tep bieu tuong tren Desktop chung ^(%PUBLIC%\Desktop^). Goi nguoi ho tro.
  set "RC=11" & goto ketthuc
)
echo   [DAT] Da tao bieu tuong "Phong kham Minh Duc" tren Desktop ^(da kiem tep ton tai^).

rem 4. Thu ket noi (Windows 10/11 co curl.exe; Windows 7 khong co: mo bieu tuong de thu).
where curl.exe >nul 2>&1
if errorlevel 1 (
  set "KIEMTAY=1"
  echo   [CAN KIEM TAY] Windows nay ^(vi du Windows 7^) khong co curl.exe nen CHUA kiem ket noi.
  echo    - Bam dup bieu tuong "Phong kham Minh Duc" tren Desktop.
  echo    - DAT khi: thay trang dang nhap PHONG KHAM va KHONG co canh bao chung chi
  echo      ^(khong co trang do "Ket noi cua ban khong phai la ket noi rieng tu"/"Your connection is not private",
  echo      o khoa canh dia chi khong bi gach do^).
  echo    - Co canh bao: KHONG bam "Nang cao"/"Tiep tuc"; dung lai va goi nguoi ho tro.
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

:donvaket
rmdir /s /q "%TMPD%" >nul 2>&1
:ketthuc
echo.
if "%RC%"=="0" if defined KIEMTAY echo DA CAI XONG. CON MOT VIEC: kiem tay nhu huong dan [CAN KIEM TAY] o tren.
if "%RC%"=="0" if not defined KIEMTAY echo HOAN TAT. Bam dup bieu tuong "Phong kham Minh Duc" tren Desktop de dang nhap.
if not "%RC%"=="0" echo Ma ket qua: %RC%. Doc thong bao phia tren hoac goi nguoi ho tro.
if not defined KHONGHOI pause
exit /b %RC%
