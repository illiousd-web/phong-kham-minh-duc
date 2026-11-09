# Cài máy trạm Phòng khám Minh Đức: tin cậy chứng chỉ của phòng khám, tạo biểu tượng Desktop.
# Tệp này độc lập (không cần mô-đun khác); chạy từ thư mục chia sẻ hoặc USB có ca.crt và may-chu.txt.
[CmdletBinding()]
param(
    [switch]$KhongHoi,
    [string]$MayChu = '',        # ví dụ https://192.168.1.10:8443 (mặc định đọc từ may-chu.txt)
    [string]$TepCA = ''
)
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script (App Control / Smart App Control). Xem hướng dẫn cài đặt, mục "Gặp lỗi".' -ForegroundColor Red
    exit 20
}
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Dat([string]$t) { Write-Host ('  [ĐẠT] ' + $t) -ForegroundColor Green }
function Loi([string]$t) { Write-Host ('  [KHÔNG ĐẠT] ' + $t) -ForegroundColor Red }
function Dung([string]$t, [string[]]$huong, [int]$code) {
    Write-Host ''; Write-Host ('DỪNG LẠI: ' + $t) -ForegroundColor Red
    foreach ($h in $huong) { Write-Host ('  - ' + $h) -ForegroundColor Yellow }
    exit $code
}

$admin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Dung 'Cần quyền Administrator.' @('Bấm đúp CAI_MAY_TRAM.bat và chọn "Có" (Yes).') 30 }
Write-Host 'CÀI MÁY TRẠM — PHÒNG KHÁM ĐA KHOA MINH ĐỨC' -ForegroundColor Cyan

$info = @{}
$infoFile = Join-Path $PSScriptRoot 'may-chu.txt'
if (Test-Path -LiteralPath $infoFile) {
    foreach ($line in Get-Content -LiteralPath $infoFile -Encoding UTF8) { $i = $line.IndexOf('='); if ($i -gt 0) { $info[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim() } }
}
if (-not $MayChu) { $MayChu = $info['DIA_CHI'] }
if (-not $TepCA) { $TepCA = Join-Path $PSScriptRoot 'ca.crt' }
if (-not $MayChu -or $MayChu -notmatch '^https://(10|172|192)\.[0-9.]+:\d+$') {
    Dung 'Không đọc được địa chỉ máy chủ (tệp may-chu.txt).' @('Chép NGUYÊN thư mục C:\MinhDuc-ChiaSe từ máy chủ sang máy này rồi chạy lại.') 2
}
if (-not (Test-Path -LiteralPath $TepCA)) { Dung 'Không thấy tệp ca.crt.' @('Chép nguyên thư mục C:\MinhDuc-ChiaSe từ máy chủ.') 3 }

# 1. Kiểm tra đúng chứng chỉ của phòng khám, đối chiếu vân tay với máy chủ.
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Resolve-Path $TepCA).Path)
if ($cert.Subject -ne 'CN=Minh Duc LAN Pilot CA' -or $cert.HasPrivateKey) {
    Dung 'Tệp ca.crt không phải chứng chỉ gốc của phòng khám Minh Đức.' @('Không cài tệp lạ. Lấy lại thư mục từ máy chủ.') 4
}
$sha = [Security.Cryptography.SHA256]::Create()
$fp = (($sha.ComputeHash($cert.RawData) | ForEach-Object { $_.ToString('X2') }) -join '')
if ($info['VAN_TAY_CA'] -and $info['VAN_TAY_CA'] -ne $fp) { Dung 'Vân tay chứng chỉ không khớp tệp may-chu.txt.' @('Lấy lại thư mục từ máy chủ.') 5 }
Write-Host ('  Vân tay chứng chỉ: ' + $fp.Substring(0, 8) + '  (phải giống 8 ký tự in trên màn hình máy chủ lúc cài)')
if (-not $KhongHoi) {
    $ans = (Read-Host '  Tám ký tự trên có giống máy chủ không? Gõ C (có) hoặc K (không)').Trim().ToUpperInvariant()
    if ($ans -notin @('C', 'CO', 'CÓ', 'Y')) { Dung 'Bạn chọn không cài vì vân tay không khớp.' @('Báo người hỗ trợ; không bấm bỏ qua cảnh báo chứng chỉ trên trình duyệt.') 6 }
}

# 2. Tin cậy chứng chỉ gốc (chỉ chứng chỉ công khai, không có khóa bí mật).
if (Test-Path -LiteralPath ('Cert:\LocalMachine\Root\' + $cert.Thumbprint)) { Dat 'Chứng chỉ phòng khám đã được tin cậy từ trước.' }
else { Import-Certificate -FilePath $TepCA -CertStoreLocation Cert:\LocalMachine\Root | Out-Null; Dat 'Đã cài chứng chỉ phòng khám vào kho tin cậy của Windows.' }

# 3. Biểu tượng Desktop mở Chrome chế độ ứng dụng.
$browser = $null
foreach ($c in @((Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'), (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
                 (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'), (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'))) {
    if ($c -and (Test-Path -LiteralPath $c)) { $browser = $c; break }
}
if ($browser) {
    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $link = Join-Path $desktop 'Phòng khám Minh Đức.lnk'
    $tmp = Join-Path $desktop 'MinhDuc-tam.lnk'   # WScript.Shell chỉ lưu tên ANSI; đổi tên sau
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($tmp)
    $sc.TargetPath = $browser; $sc.Arguments = '--app=' + $MayChu; $sc.Description = 'Phần mềm Phòng khám đa khoa Minh Đức'
    $sc.Save()
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
    Move-Item -LiteralPath $tmp -Destination $link -Force
    Dat 'Đã tạo biểu tượng "Phòng khám Minh Đức" trên Desktop.'
    if ($browser -notmatch 'chrome') { Write-Host '  [LƯU Ý] Chưa có Chrome; biểu tượng dùng Microsoft Edge.' -ForegroundColor Yellow }
} else { Loi 'Chưa có Chrome hoặc Edge. Cài Google Chrome rồi chạy lại.' }

# 4. Thử kết nối thật tới máy chủ (kiểm luôn chứng chỉ).
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
try {
    $r = Invoke-WebRequest -Uri ($MayChu + '/api/health') -UseBasicParsing -TimeoutSec 15
    if ($r.Content -match 'lan-pilot') { Dat ('Kết nối được máy chủ ' + $MayChu + ', chứng chỉ hợp lệ.') } else { throw 'Phản hồi lạ' }
} catch {
    Loi ('Chưa kết nối được ' + $MayChu)
    Write-Host '  - Máy này và máy chủ phải cùng mạng phòng khám (cùng modem/switch, không dùng Wi-Fi khách).' -ForegroundColor Yellow
    Write-Host '  - Máy chủ phải đang bật; trên máy chủ bấm KIEM_TRA.bat để xem dịch vụ.' -ForegroundColor Yellow
    exit 7
}
Write-Host ''
Write-Host 'HOÀN TẤT. Bấm đúp biểu tượng "Phòng khám Minh Đức" trên Desktop để đăng nhập.' -ForegroundColor Green
exit 0
