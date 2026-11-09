# Kiểm thử logic bộ cài (không cần quyền Administrator, không thay đổi máy).
# Chạy: powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\Test-Installer.ps1
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$script:count = 0
function Assert-True($Condition, $Message) { if (-not $Condition) { throw ('FAIL: ' + $Message) }; $script:count++ }

function New-Snap {
    return [pscustomobject]@{
        os = [pscustomobject]@{ caption = 'Microsoft Windows 11 Pro'; architecture = '64-bit'; build = 26200 }
        ram_gib = 8.0; free_c_gib = 120.0; internet = $true; already_installed = $false
        ip = [pscustomobject]@{ address = '192.168.1.10'; prefix = 24; dhcp = $false; gateway = '192.168.1.1'; interface_index = 5 }
        pagefile = [pscustomobject]@{ auto = $true; max_mib = 0 }
        code_integrity = [pscustomobject]@{ language_mode = 'FullLanguage'; sac_state = 0; usermode = 0; kernel = 2 }
        port_conflict = $null
    }
}
function Levels($snap) { $h = @{}; foreach ($i in (Get-PrecheckAssessment -Snapshot $snap)) { $h[$i.id] = $i.level }; return $h }

# Máy đúng cấu hình phòng khám (kernel policy Enforced = danh sách chặn driver) phải đạt.
$l = Levels (New-Snap)
Assert-True (@($l.Values | Where-Object { $_ -ne 'OK' }).Count -eq 0) 'Máy chuẩn phải ĐẠT mọi mục'
$s = New-Snap; $s.os.architecture = '32-bit'; Assert-True ((Levels $s).os -eq 'STOP') '32-bit phải dừng'
$s = New-Snap; $s.os.caption = 'Microsoft Windows Server 2022'; Assert-True ((Levels $s).os -eq 'STOP') 'Không phải Win10/11 phải dừng'
$s = New-Snap; $s.ram_gib = 4; Assert-True ((Levels $s).ram -eq 'STOP') 'RAM 4 GB phải dừng'
$s = New-Snap; $s.ram_gib = 7.8; Assert-True ((Levels $s).ram -eq 'OK') 'RAM 8 GB (hiển thị 7.8) phải đạt'
$s = New-Snap; $s.free_c_gib = 19.9; Assert-True ((Levels $s).disk -eq 'STOP') 'C dưới 20 GB phải dừng'
$s = New-Snap; $s.internet = $false; Assert-True ((Levels $s).internet -eq 'STOP') 'Không Internet lần đầu phải dừng'
$s = New-Snap; $s.internet = $false; $s.already_installed = $true; Assert-True ((Levels $s).internet -eq 'WARN') 'Chạy lại không Internet chỉ cảnh báo'
$s = New-Snap; $s.ip.dhcp = $true; Assert-True ((Levels $s).ip -eq 'ASK_DHCP') 'IP động phải hỏi đặt giữ IP'
$s = New-Snap; $s.ip = $null; Assert-True ((Levels $s).ip -eq 'STOP') 'Không có IP phải dừng'
$s = New-Snap; $s.ip.address = '8.8.8.8'; Assert-True ((Levels $s).ip -eq 'STOP') 'IP công cộng phải dừng'
$s = New-Snap; $s.pagefile = [pscustomobject]@{ auto = $false; max_mib = 512 }; Assert-True ((Levels $s).pagefile -eq 'ASK_PAGEFILE') 'Page file 512 MB phải hỏi'
$s = New-Snap; $s.pagefile = [pscustomobject]@{ auto = $false; max_mib = 8192 }; Assert-True ((Levels $s).pagefile -eq 'OK') 'Page file 8 GB đạt'
$s = New-Snap; $s.code_integrity.sac_state = 1; Assert-True ((Levels $s).appcontrol -eq 'STOP') 'Smart App Control bật phải dừng'
$s = New-Snap; $s.code_integrity.sac_state = 2; Assert-True ((Levels $s).appcontrol -eq 'ASK_SAC') 'SAC đánh giá phải hỏi'
$s = New-Snap; $s.code_integrity.usermode = 2; Assert-True ((Levels $s).appcontrol -eq 'STOP') 'App Control user-mode phải dừng'
$s = New-Snap; $s.code_integrity.language_mode = 'ConstrainedLanguage'; Assert-True ((Levels $s).appcontrol -eq 'STOP') 'Chế độ hạn chế phải dừng'
$s = New-Snap; $s.port_conflict = 5432; Assert-True ((Levels $s).ports -eq 'STOP') 'Trùng cổng phải dừng'
$s = New-Snap; $s.code_integrity.kernel = 2
$msg = (Get-PrecheckAssessment -Snapshot $s | Where-Object id -eq 'appcontrol').message
Assert-True ($msg -match 'trình điều khiển') 'Giải thích dòng Enforced trong System Information'

# Tệp dịch vụ WinSW: tự khởi động, tự chạy lại, phụ thuộc PostgreSQL, log xoay vòng, không chứa mật khẩu.
$paths = Get-MinhDucPaths -Code 'C:\MinhDuc' -Data 'C:\ProgramData\MinhDuc'
[xml]$x = New-ServiceXml -Paths $paths
Assert-True ($x.service.id -eq 'MinhDuc') 'id dịch vụ'
Assert-True ($x.service.startmode -eq 'Automatic') 'Tự khởi động'
Assert-True (@($x.service.onfailure).Count -ge 3 -and @($x.service.onfailure | Where-Object { $_.action -ne 'restart' }).Count -eq 0) 'Tự chạy lại khi lỗi'
Assert-True ($x.service.depend -eq 'postgresql-x64-17') 'Phụ thuộc PostgreSQL'
Assert-True ($x.service.log.mode -eq 'roll-by-size' -and [int]$x.service.log.keepFiles -le 10) 'Log xoay vòng'
Assert-True ($x.service.arguments -match 'scripts.with_env' -and $x.service.arguments -notmatch 'postgresql://') 'Không đưa mật khẩu vào XML'
Assert-True ($x.service.executable -eq 'C:\MinhDuc\.venv\Scripts\python.exe') 'Chạy python trong venv'

# Phiên bản ghim có SHA256 64 ký tự hex.
foreach ($pin in (Get-MinhDucPins).Values) { Assert-True ($pin.Sha256 -match '^[0-9a-f]{64}$' -and $pin.Url -like 'https://*') ('Ghim ' + $pin.File) }

# Tệp tải sẵn sai mã băm bị bỏ qua (không bao giờ chạy tệp chưa kiểm).
$tmp = Join-Path $env:TEMP ('minhduc-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $fake = @{ Version = '0'; File = 'gia.exe'; Url = 'https://127.0.0.1:1/khong-ton-tai'; Sha256 = ('0' * 64) }
    Set-Content -LiteralPath (Join-Path $tmp 'gia.exe') -Value 'not the pinned file'
    $failed = $false
    try { Get-PinnedFile -Pin $fake -CacheDir (Join-Path $tmp 'cache') -LocalDirs @($tmp) | Out-Null } catch { $failed = $true }
    Assert-True $failed 'Tệp sai SHA256 không được dùng'
    $good = 'tệp đúng'
    Set-Content -LiteralPath (Join-Path $tmp 'dung.exe') -Value $good -Encoding UTF8
    $hash = (Get-FileHash -LiteralPath (Join-Path $tmp 'dung.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    $okPin = @{ Version = '1'; File = 'dung.exe'; Url = 'https://127.0.0.1:1/x'; Sha256 = $hash }
    Assert-True ((Get-PinnedFile -Pin $okPin -CacheDir (Join-Path $tmp 'cache') -LocalDirs @($tmp)) -like '*dung.exe') 'Tệp đặt sẵn đúng SHA256 được dùng (không cần Internet)'
    # Đọc tệp KEY=VALUE.
    Set-Content -LiteralPath (Join-Path $tmp 'a.env') -Value @('# c', 'CLINIC_ORIGIN=https://192.168.1.10:8443', 'X=a=b') -Encoding UTF8
    $e = Read-EnvFile -Path (Join-Path $tmp 'a.env')
    Assert-True ($e['CLINIC_ORIGIN'] -eq 'https://192.168.1.10:8443' -and $e['X'] -eq 'a=b') 'Đọc tệp cấu hình'
} finally { Remove-Item -LiteralPath $tmp -Recurse -Force }

# Cú pháp mọi script (PowerShell 5.1) và mã hóa UTF-8 có BOM khi có tiếng Việt.
foreach ($path in Get-ChildItem $PSScriptRoot -Include *.ps1, *.psm1 -Recurse) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path.FullName, [ref]$tokens, [ref]$errors)
    Assert-True ($errors.Count -eq 0) ('Lỗi cú pháp: ' + $path.Name + ' ' + ($errors | Out-String))
    $bytes = [IO.File]::ReadAllBytes($path.FullName)
    $hasNonAscii = @($bytes | Where-Object { $_ -gt 127 }).Count -gt 0
    if ($hasNonAscii) { Assert-True ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) ('Thiếu BOM UTF-8: ' + $path.Name) }
}
Write-Output ('PASS: ' + $script:count + ' kiểm tra bộ cài Windows')
