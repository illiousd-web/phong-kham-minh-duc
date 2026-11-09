# Bộ cài máy chủ Phòng khám đa khoa Minh Đức (Windows 10/11 64-bit).
# Gọi từ CAI_DAT.bat (đã xin quyền Administrator). Chạy lại nhiều lần an toàn:
# không xóa dữ liệu, không đổi mật khẩu đang dùng, không tạo lại khóa sao lưu.
[CmdletBinding()]
param(
    [switch]$KhongHoi,                     # chạy không hỏi (kiểm thử tự động)
    [switch]$ChapNhanIPDong,               # đã đặt giữ IP trên modem dù máy dùng DHCP
    [ValidateSet('Hoi', 'Doi', 'Giu')][string]$PageFile = 'Hoi',
    [string]$OSaoLuuNgoai = '',            # ví dụ E: — khai báo ổ USB/ổ ngoài
    [string]$ThuMucMa = 'C:\MinhDuc',
    [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc'
)

# Kiểm tra chế độ ngôn ngữ TRƯỚC mọi lệnh .NET: App Control/Smart App Control
# chạy script ở chế độ hạn chế (ConstrainedLanguage) và sẽ làm hỏng bộ cài.
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script cài đặt (App Control / Smart App Control).' -ForegroundColor Red
    Write-Host '  - Nếu là Smart App Control: mở Windows Security > App & browser control > Smart App Control settings > chọn Off.' -ForegroundColor Yellow
    Write-Host '  - Nếu máy do bộ phận CNTT quản lý: nhờ họ cho phép thư mục cài đặt.' -ForegroundColor Yellow
    Write-Host '  - Không tắt Microsoft Defender hay Tường lửa.' -ForegroundColor Yellow
    exit 20
}

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$Names = Get-MinhDucNames
$Pins = Get-MinhDucPins
$P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Tong = 13
$CanKhoiDongLai = $false

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------------------------------------------------------------------------
function Step-KiemTraMay {
    Write-Buoc "Bước 1/${Tong}: Kiểm tra máy"
    $snap = Get-PrecheckSnapshot
    $items = Get-PrecheckAssessment -Snapshot $snap
    $stop = @()
    foreach ($it in $items) {
        switch ($it.level) {
            'OK' { Write-Dat $it.message }
            'WARN' { Write-Luu $it.message }
            'STOP' { Write-Loi $it.message; $stop += $it }
            default { Write-Luu $it.message }
        }
    }
    if ($stop.Count -gt 0) {
        $huong = @(); foreach ($s in $stop) { $huong += $s.huong }
        Stop-CaiDat 'Máy chưa đạt điều kiện cài đặt.' $huong 2
    }
    foreach ($it in $items | Where-Object { $_.level -like 'ASK_*' }) {
        foreach ($h in $it.huong) { Write-Thongtin ('- ' + $h) }
        if ($it.level -eq 'ASK_DHCP') {
            $ok = if ($KhongHoi) { [bool]$ChapNhanIPDong } else { Read-CoKhong 'Bạn ĐÃ đặt giữ IP cho máy này trên modem chưa?' }
            if (-not $ok) { Stop-CaiDat 'Cần IP cố định cho máy chủ (máy trạm và chứng chỉ HTTPS dựa vào IP này).' $it.huong 3 }
            Write-Luu 'Ghi nhận: đã đặt giữ IP trên modem.'
        } elseif ($it.level -eq 'ASK_PAGEFILE') {
            $doi = switch ($PageFile) { 'Doi' { $true } 'Giu' { $false } default { Read-CoKhong 'Chuyển tệp hoán đổi sang "Windows tự quản lý"?' -KhongHoi:$KhongHoi -MacDinh $false } }
            if ($doi) { Set-PagefileSystemManaged; $script:CanKhoiDongLai = $true; Write-Dat 'Đã chuyển sang Windows tự quản lý (có hiệu lực sau khi khởi động lại).' }
            else { Write-Luu 'Giữ nguyên tệp hoán đổi. Máy có thể chậm hoặc báo thiếu bộ nhớ khi mở nhiều trang.' }
        } elseif ($it.level -eq 'ASK_SAC') {
            if (-not (Read-CoKhong 'Vẫn tiếp tục cài khi Smart App Control đang đánh giá?' -KhongHoi:$KhongHoi -MacDinh $true)) { Stop-CaiDat 'Bạn chọn dừng để tắt Smart App Control trước.' @() 4 }
        }
    }
    return $snap
}

function Step-ThuMucDuLieu {
    foreach ($d in @($P.Data, $P.Admin, $P.Journal, $P.Downloads)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    Set-SecureAcl -Path $P.Data -Directory
    Set-SecureAcl -Path $P.Admin -Directory
    Set-SecureAcl -Path $P.Journal -Directory
}

# ---------------------------------------------------------------------------
function Step-CaiPython {
    Write-Buoc "Bước 2/${Tong}: Cài Python $($Pins.Python.Version)"
    if (Test-Path -LiteralPath $P.BasePython) {
        $v = ((Invoke-Native -FilePath $P.BasePython -Arguments @('--version') -Quiet).Output -join '').Trim()
        if ($v -match '^Python 3\.12\.\d+$') { Write-Dat ("Đã có $v tại $($P.BasePython), bỏ qua."); return }
        Stop-CaiDat ("$($P.BasePython) là $v, không phải Python 3.12.") @('Liên hệ người hỗ trợ.') 5
    }
    $file = Get-PinnedFile -Pin $Pins.Python -CacheDir $P.Downloads -LocalDirs @((Join-Path $PSScriptRoot 'taive'))
    Write-Thongtin 'Đang cài Python (không cần bấm gì, khoảng 1–3 phút)...'
    $proc = Start-Process -FilePath $file -Wait -PassThru -ArgumentList @('/quiet', 'InstallAllUsers=1', 'PrependPath=0', 'Include_test=0',
        'Include_doc=0', 'Include_launcher=0', 'Shortcuts=0', 'AssociateFiles=0', ('TargetDir="' + $Names.PythonRoot + '"'))
    $script:P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
    if ($proc.ExitCode -notin @(0, 3010) -or -not (Test-Path -LiteralPath $script:P.BasePython)) {
        Stop-CaiDat "Cài Python thất bại (mã $($proc.ExitCode))." @('Khởi động lại máy rồi chạy lại CAI_DAT.bat.',
            'Nếu máy đã có Python 3.12 cài riêng cho một tài khoản: gỡ nó trong Settings > Apps > Installed apps rồi chạy lại.') 6
    }
    Write-Dat "Đã cài Python $($Pins.Python.Version)."
}

function Step-CaiPostgres {
    Write-Buoc "Bước 3/${Tong}: Cài PostgreSQL $($Pins.Postgres.Version)"
    $pgExe = Join-Path $P.PgBin 'postgres.exe'
    $svc = Get-Service -Name $Names.PgService -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $pgExe) -and $svc) {
        $v = ((Invoke-Native -FilePath $pgExe -Arguments @('--version') -Quiet).Output -join '')
        if ($v -notmatch 'PostgreSQL\) 17\.') { Stop-CaiDat "Đã có PostgreSQL nhưng không phải bản 17 ($v)." @('Liên hệ người hỗ trợ; không gỡ PostgreSQL đang có dữ liệu.') 7 }
        Write-Dat 'Đã có PostgreSQL 17, bỏ qua bước cài.'
        if (-not (Read-EnvFile -Path $P.SuperEnv)['MINHDUC_PG_SUPER_PASSWORD']) {
            if ($KhongHoi) { Stop-CaiDat 'PostgreSQL 17 đã có sẵn nhưng bộ cài không biết mật khẩu tài khoản postgres.' @('Chạy lại không có tham số -KhongHoi để nhập mật khẩu.') 8 }
            Write-Thongtin 'PostgreSQL này được cài trước đó. Cần mật khẩu tài khoản "postgres" đã đặt khi cài (nhập sẽ không hiện chữ).'
            $sec = Read-Host -AsSecureString '  Mật khẩu postgres'
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
            if ($plain -match '[\r\n]') { Stop-CaiDat 'Mật khẩu không hợp lệ.' @() 8 }
            Set-Content -LiteralPath $P.SuperEnv -Value ('MINHDUC_PG_SUPER_PASSWORD=' + $plain) -Encoding ASCII
            $plain = $null
            Set-SecureAcl -Path $P.SuperEnv
        }
        if ($svc.Status -ne 'Running') { Start-Service -Name $Names.PgService }
        return
    }
    $file = Get-PinnedFile -Pin $Pins.Postgres -CacheDir $P.Downloads -LocalDirs @((Join-Path $PSScriptRoot 'taive'))
    $r = Invoke-Python -Paths $P -Base -Quiet -Arguments @((Join-Path $P.Code 'scripts\install_env.py'), 'super', '--file', $P.SuperEnv)
    if (-not $r.Ok) { Stop-CaiDat 'Không tạo được mật khẩu cho PostgreSQL.' $r.Output 9 }
    Set-SecureAcl -Path $P.SuperEnv
    $super = (Read-EnvFile -Path $P.SuperEnv)['MINHDUC_PG_SUPER_PASSWORD']
    # Mật khẩu đi qua tệp tùy chọn (chỉ Administrators đọc), không qua dòng lệnh; xóa ngay sau khi cài.
    $opt = Join-Path $P.Admin 'pg-install.options'
    try {
        @('mode=unattended', 'unattendedmodeui=none', 'superaccount=postgres', ('superpassword=' + $super), 'serverport=5432',
          ('prefix=' + $Names.PgRoot), ('datadir=' + $P.PgData), ('servicename=' + $Names.PgService),
          'enable-components=server,commandlinetools', 'disable-components=pgAdmin,stackbuilder', 'install_runtimes=1') |
            Set-Content -LiteralPath $opt -Encoding ASCII
        Set-SecureAcl -Path $opt
        Write-Thongtin 'Đang cài PostgreSQL (không cần bấm gì, khoảng 3–10 phút)...'
        $proc = Start-Process -FilePath $file -Wait -PassThru -ArgumentList @('--optionfile', ('"' + $opt + '"'))
    } finally { Remove-Item -LiteralPath $opt -Force -ErrorAction SilentlyContinue; $super = $null }
    $svc = Get-Service -Name $Names.PgService -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0 -or -not $svc) {
        Stop-CaiDat "Cài PostgreSQL thất bại (mã $($proc.ExitCode))." @('Xem nhật ký trong thư mục %TEMP% (tệp install-postgresql.log).', 'Khởi động lại máy rồi chạy lại CAI_DAT.bat.') 10
    }
    Set-Service -Name $Names.PgService -StartupType Automatic
    Write-Dat "Đã cài PostgreSQL $($Pins.Postgres.Version)."
}

# ---------------------------------------------------------------------------
function Step-ChepMa {
    Write-Buoc "Bước 4/${Tong}: Chép mã vào $($P.Code), tạo môi trường Python và cài thư viện"
    if ($SourceRoot.TrimEnd('\') -ne $P.Code.TrimEnd('\')) {
        New-Item -ItemType Directory -Force -Path $P.Code | Out-Null
        $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($SourceRoot, $P.Code, '/MIR',
            '/XD', '.venv', '.venv-cu', '.git', '__pycache__', 'test_evidence', 'data', 'backups', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
        if (-not $r.Ok) { Stop-CaiDat 'Không chép được mã nguồn.' $r.Output 11 }
        Write-Dat "Đã chép mã từ $SourceRoot."
    } else { Write-Dat 'Đang chạy từ chính thư mục cài đặt, không cần chép.' }
    Get-ChildItem -LiteralPath $P.Code -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
    # Mặc định C:\ cho mọi người dùng quyền sửa thư mục con: khóa lại để không ai sửa được mã dịch vụ chạy.
    Set-SecureAcl -Path $P.Code -Directory -Readers @('*S-1-5-32-545')
    if (-not (Test-Path -LiteralPath $P.VenvPython)) {
        $r = Invoke-Native -FilePath $P.BasePython -Arguments @('-m', 'venv', $P.Venv) -Quiet
        if (-not $r.Ok) { Stop-CaiDat 'Không tạo được môi trường Python (.venv).' $r.Output 12 }
    }
    Write-Thongtin 'Đang cài thư viện có kiểm mã băm (requirements.lock)...'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'pip', 'install', '--no-input', '--require-hashes', '--no-deps',
        '--only-binary=:all:', '-r', (Join-Path $P.Code 'requirements.lock'))
    if (-not $r.Ok) { Stop-CaiDat 'Cài thư viện Python thất bại (kiểm tra Internet).' ($r.Output | Select-Object -Last 8) 13 }
    Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'compileall', '-q', (Join-Path $P.Code 'app'), (Join-Path $P.Code 'scripts')) | Out-Null
    Write-Dat 'Đã cài thư viện (đúng mã băm).'
}

# ---------------------------------------------------------------------------
function Step-CauHinhVaCSDL {
    param($Snap)
    Write-Buoc "Bước 5/${Tong}: Tạo cơ sở dữ liệu và tệp cấu hình bảo mật"
    $ip = $Snap.ip
    $r = Invoke-Python -Paths $P -Base -Quiet -Arguments @((Join-Path $P.Code 'scripts\install_env.py'), 'write', '--clinic-env', $P.ClinicEnv,
        '--owner-env', $P.OwnerEnv, '--ip', $ip.address, '--prefix', [string]$ip.prefix, '--data-dir', $P.Data, '--pg-bin', $P.PgBin)
    if (-not $r.Ok) { Stop-CaiDat 'Không tạo được tệp cấu hình.' $r.Output 14 }
    $report = ConvertFrom-PythonJson $r
    Set-SecureAcl -Path $P.ClinicEnv
    Set-SecureAcl -Path $P.OwnerEnv
    if ($report.ip_changed) {
        Stop-CaiDat ("IP máy đã đổi từ $($report.configured_ip) sang $($ip.address).") @(
            'Cách đơn giản: đặt lại IP ' + $report.configured_ip + ' cho máy (hoặc giữ IP trên modem) rồi chạy lại.',
            'Nếu buộc phải đổi IP: liên hệ người hỗ trợ (cần tạo lại chứng chỉ và cài lại cho máy trạm).') 15
    }
    if ($report.clinic_env_created) { Write-Dat 'Đã tạo clinic.env với mật khẩu ngẫu nhiên mạnh.' } else { Write-Dat 'Giữ nguyên clinic.env và mật khẩu đang dùng.' }
    $script:Origin = $report.origin
    $script:Cidr = $report.cidr
    $dbArgs = @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv, '--super-env', $P.SuperEnv, 'ensure')
    if (@($report.new_password_roles).Count -gt 0) { $dbArgs += '--allow-password-reset' }
    $r = Invoke-Python -Paths $P -Quiet -Arguments $dbArgs
    if (-not $r.Ok) { Stop-CaiDat 'Không tạo được tài khoản/cơ sở dữ liệu PostgreSQL.' $r.Output 16 }
    $db = ConvertFrom-PythonJson $r
    if ($db.created_database) { Write-Dat 'Đã tạo cơ sở dữ liệu minhduc (UTF-8).' } else { Write-Dat 'Cơ sở dữ liệu đã có, giữ nguyên dữ liệu.' }
    foreach ($d in @($P.Attachments, $P.Logs, $P.Backups, $P.Tls)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

function Step-CauHinhPostgres {
    Write-Buoc "Bước 6/${Tong}: Áp cấu hình PostgreSQL cho máy 8 GB, chỉ nghe 127.0.0.1"
    $conf = Join-Path $P.PgData 'postgresql.conf'
    $hba = Join-Path $P.PgData 'pg_hba.conf'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $changed = $false
    $src = Join-Path $P.Code 'deploy\postgresql\minhduc-8gb.conf'
    $dst = Join-Path $P.PgData 'minhduc-8gb.conf'
    if (-not (Test-Path -LiteralPath $dst) -or (Get-FileHash $src).Hash -ne (Get-FileHash $dst).Hash) {
        Copy-Item -LiteralPath $src -Destination $dst -Force; $changed = $true
    }
    $text = Get-Content -LiteralPath $conf -Raw
    if ($text -notmatch "(?m)^\s*include_if_exists\s*=\s*'minhduc-8gb\.conf'") {
        Copy-Item -LiteralPath $conf -Destination ($conf + '.truoc-minhduc-' + $stamp)
        Add-Content -LiteralPath $conf -Value "`r`n# Minh Duc: cau hinh may 8 GB (them tu dong, ban sao luu: postgresql.conf.truoc-minhduc-$stamp)`r`ninclude_if_exists = 'minhduc-8gb.conf'" -Encoding ASCII
        $changed = $true
        Write-Dat "Đã sao lưu postgresql.conf và thêm cấu hình 8 GB."
    }
    $wanted = "# Minh Duc: chi cho ket noi trong may, mat khau SCRAM.`r`n# TYPE  DATABASE  USER  ADDRESS        METHOD`r`nhost    all       all   127.0.0.1/32   scram-sha-256`r`nhost    all       all   ::1/128        scram-sha-256`r`n"
    $current = Get-Content -LiteralPath $hba -Raw
    if ($current -ne $wanted) {
        Copy-Item -LiteralPath $hba -Destination ($hba + '.truoc-minhduc-' + $stamp)
        [IO.File]::WriteAllText($hba, $wanted, (New-Object Text.ASCIIEncoding))
        $changed = $true
        Write-Dat 'Đã giới hạn pg_hba.conf chỉ cho 127.0.0.1 (bản cũ được sao lưu).'
    }
    if ($changed) {
        Write-Thongtin 'Khởi động lại PostgreSQL...'
        if (Get-Service -Name $Names.Service -ErrorAction SilentlyContinue) { Stop-Service -Name $Names.Service -Force -ErrorAction SilentlyContinue }
        Restart-Service -Name $Names.PgService -Force
        Start-Sleep -Seconds 3
    }
    $listen = @(Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue | ForEach-Object { [string]$_.LocalAddress } | Sort-Object -Unique)
    if ($listen.Count -eq 0 -or @($listen | Where-Object { $_ -notin @('127.0.0.1', '::1') }).Count -gt 0) {
        Stop-CaiDat ('PostgreSQL đang nghe ' + ($listen -join ', ') + ' thay vì chỉ 127.0.0.1.') @('Gửi thư mục nhật ký cho người hỗ trợ.') 17
    }
    Write-Dat 'PostgreSQL chỉ nghe 127.0.0.1, fsync/commit giữ nguyên an toàn.'
}

function Step-Migration {
    Write-Buoc "Bước 7/${Tong}: Cập nhật cấu trúc dữ liệu (migration) và cấp quyền"
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.with_env', $P.OwnerEnv, 'scripts.manage', 'migrate')
    if (-not $r.Ok) { Stop-CaiDat 'Migration thất bại.' ($r.Output | Select-Object -Last 6) 18 }
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv, 'grant')
    if (-not $r.Ok) { Stop-CaiDat 'Cấp quyền cho tài khoản ứng dụng thất bại.' $r.Output 19 }
    Write-Dat 'Cấu trúc dữ liệu đã cập nhật; tài khoản web chỉ có quyền tối thiểu.'
}

function Step-ChungChi {
    param($Snap)
    Write-Buoc "Bước 8/${Tong}: Chứng chỉ HTTPS theo IP $($Snap.ip.address)"
    $cert = Join-Path $P.Tls 'server.crt'
    $r = Invoke-Python -Paths $P -Quiet -OkCodes @(0, 1) -Arguments @('-m', 'scripts.install_cert', 'check', '--cert', $cert, '--ip', $Snap.ip.address)
    $state = ConvertFrom-PythonJson $r
    if ($r.Code -ne 0) {
        if (Test-Path -LiteralPath $cert) {
            Write-Luu ('Chứng chỉ hiện tại cần thay: ' + $state.reason + '.')
            Write-Luu 'Sau khi tạo mới, MỌI máy trạm phải chạy lại CAI_MAY_TRAM.bat.'
            if (-not (Read-CoKhong 'Tạo chứng chỉ mới?' -KhongHoi:$KhongHoi -MacDinh $false)) { Stop-CaiDat 'Chưa tạo chứng chỉ mới theo lựa chọn của bạn.' @() 21 }
        }
        $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_cert', 'create', '--ip', $Snap.ip.address, '--tls-dir', $P.Tls, '--ca-key', $P.CaKey)
        if (-not $r.Ok) { Stop-CaiDat 'Không tạo được chứng chỉ.' $r.Output 22 }
        Write-Dat 'Đã tạo chứng chỉ mới (hạn 1 năm).'
    } else { Write-Dat ('Giữ chứng chỉ đang dùng: ' + $state.reason + '.') }
    Set-SecureAcl -Path $P.CaKey
    $fp = (ConvertFrom-PythonJson (Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_cert', 'fingerprint', '--ca', (Join-Path $P.Tls 'ca.crt')))).fingerprint
    $script:Fingerprint = $fp
    # Máy chủ cũng tin CA này để Chrome trên máy chủ mở được.
    $ca = Join-Path $P.Tls 'ca.crt'
    $thumb = (New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ca)).Thumbprint
    if (-not (Test-Path -LiteralPath ("Cert:\LocalMachine\Root\" + $thumb))) { Import-Certificate -FilePath $ca -CertStoreLocation Cert:\LocalMachine\Root | Out-Null }
    # Thư mục chia sẻ chỉ đọc cho máy trạm: ca.crt + bộ cài máy trạm (không có khóa bí mật).
    New-Item -ItemType Directory -Force -Path $P.Share | Out-Null
    Copy-Item -LiteralPath $ca -Destination (Join-Path $P.Share 'ca.crt') -Force
    foreach ($f in @('CAI_MAY_TRAM.bat', 'CaiMayTram.ps1')) { Copy-Item -LiteralPath (Join-Path $P.Code ('deploy\windows\' + $f)) -Destination (Join-Path $P.Share $f) -Force }
    Set-Content -LiteralPath (Join-Path $P.Share 'may-chu.txt') -Encoding UTF8 -Value @("DIA_CHI=$($script:Origin)", "VAN_TAY_CA=$fp")
    Set-SecureAcl -Path $P.Share -Directory -Readers @('*S-1-1-0')
    try {
        if (-not (Get-SmbShare -Name $Names.Share -ErrorAction SilentlyContinue)) {
            $everyone = (New-Object Security.Principal.SecurityIdentifier('S-1-1-0')).Translate([Security.Principal.NTAccount]).Value
            New-SmbShare -Name $Names.Share -Path $P.Share -ReadAccess $everyone -Description 'Minh Duc: ca.crt va bo cai may tram (chi doc)' | Out-Null
        }
        Write-Dat ('Thư mục chia sẻ chỉ đọc: \\' + $env:COMPUTERNAME + '\' + $Names.Share + '  (cũng là ' + $P.Share + ')')
    } catch { Write-Luu ('Không tạo được chia sẻ mạng; chép thư mục ' + $P.Share + ' sang USB để cài máy trạm.') }
    Write-Thongtin ('Vân tay chứng chỉ (8 ký tự đầu để đối chiếu trên máy trạm): ' + $fp.Substring(0, 8))
}

function Step-DichVu {
    Write-Buoc "Bước 9/${Tong}: Đăng ký dịch vụ Windows tự khởi động, tự chạy lại khi lỗi"
    New-Item -ItemType Directory -Force -Path $P.ServiceDir, (Join-Path $P.Logs 'service') | Out-Null
    $exe = Join-Path $P.ServiceDir ($Names.Service + '.exe')
    $pinned = Get-PinnedFile -Pin $Pins.WinSW -CacheDir $P.Downloads -LocalDirs @((Join-Path $PSScriptRoot 'taive'))
    if (-not (Test-Path -LiteralPath $exe) -or (Get-FileHash $exe).Hash.ToLowerInvariant() -ne $Pins.WinSW.Sha256) {
        if (Get-Service -Name $Names.Service -ErrorAction SilentlyContinue) { Stop-Service -Name $Names.Service -Force -ErrorAction SilentlyContinue }
        Copy-Item -LiteralPath $pinned -Destination $exe -Force
    }
    $xmlPath = Join-Path $P.ServiceDir ($Names.Service + '.xml')
    [IO.File]::WriteAllText($xmlPath, (New-ServiceXml -Paths $P), (New-Object Text.UTF8Encoding($false)))
    if (-not (Get-Service -Name $Names.Service -ErrorAction SilentlyContinue)) {
        $r = Invoke-Native -FilePath $exe -Arguments @('install') -Quiet
        if (-not $r.Ok) { Stop-CaiDat 'Không đăng ký được dịch vụ Windows.' $r.Output 23 }
    } else { Stop-Service -Name $Names.Service -Force -ErrorAction SilentlyContinue }
    # Tài khoản dịch vụ ảo riêng (NT SERVICE\MinhDuc), không dùng LocalSystem.
    $r = Invoke-Native -FilePath 'sc.exe' -Arguments @('config', $Names.Service, 'obj=', $Names.ServiceAcct, 'start=', 'delayed-auto', 'depend=', $Names.PgService) -Quiet
    if (-not $r.Ok) { Stop-CaiDat 'Không đặt được tài khoản dịch vụ.' $r.Output 24 }
    Invoke-Native -FilePath 'sc.exe' -Arguments @('failure', $Names.Service, 'reset=', '3600', 'actions=', 'restart/10000/restart/30000/restart/60000') -Quiet | Out-Null
    Invoke-Native -FilePath 'sc.exe' -Arguments @('failureflag', $Names.Service, '1') -Quiet | Out-Null
    # Quyền tối thiểu: đọc cấu hình/chứng chỉ, ghi tệp đính kèm và nhật ký; không đọc thư mục quản trị.
    Set-SecureAcl -Path $P.Data -Directory -Readers @($Names.ServiceAcct)
    Set-SecureAcl -Path $P.Admin -Directory
    Set-SecureAcl -Path $P.ClinicEnv -Readers @($Names.ServiceAcct)
    Set-SecureAcl -Path $P.Tls -Directory -Readers @($Names.ServiceAcct)
    Set-SecureAcl -Path $P.Backups -Directory
    foreach ($w in @($P.Attachments, $P.Logs)) { Set-SecureAcl -Path $w -Directory -Writers @($Names.ServiceAcct) }
    Set-SecureAcl -Path $P.ServiceDir -Directory -Readers @($Names.ServiceAcct)
    Set-SecureAcl -Path $P.Journal -Directory
    Set-SecureAcl -Path $P.Code -Directory -Readers @('*S-1-5-32-545', $Names.ServiceAcct)
    Start-Service -Name $Names.Service
    if (-not (Wait-Https -Origin $script:Origin -Seconds 120)) {
        Show-ServiceDiagnostics -Paths $P
        Stop-CaiDat 'Dịch vụ web chưa trả lời sau 2 phút.' @(('Xem nhật ký: ' + (Join-Path $P.Logs 'service') + ' và ' + (Join-Path $P.Logs 'server.log')), 'Bấm đúp KIEM_TRA.bat và gửi kết quả cho người hỗ trợ.') 25
    }
    Write-Dat ('Dịch vụ "' + $Names.Service + '" đang chạy tại ' + $script:Origin)
}

function Step-TuongLua {
    param($Snap)
    Write-Buoc "Bước 10/${Tong}: Tường lửa chỉ mở cổng $($Names.Port) cho mạng $($script:Cidr)"
    $netProfile = Get-NetConnectionProfile -InterfaceIndex $Snap.ip.interface_index -ErrorAction SilentlyContinue
    if ($netProfile -and [string]$netProfile.NetworkCategory -eq 'Public') {
        if (Read-CoKhong 'Mạng này đang là "Công cộng". Chuyển sang "Riêng tư" (mạng phòng khám)?' -KhongHoi:$KhongHoi -MacDinh $true) {
            Set-NetConnectionProfile -InterfaceIndex $Snap.ip.interface_index -NetworkCategory Private
            Write-Dat 'Đã chuyển mạng sang Riêng tư.'
        }
    }
    Get-NetFirewallRule -Group $Names.FirewallGrp -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $Names.FirewallWeb -Group $Names.FirewallGrp -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $Names.Port -LocalAddress $Snap.ip.address -RemoteAddress $script:Cidr -Profile Private, Domain | Out-Null
    New-NetFirewallRule -DisplayName $Names.FirewallPg -Group $Names.FirewallGrp -Direction Inbound -Action Block -Protocol TCP `
        -LocalPort 5432 -Profile Any | Out-Null
    $blocks = @(Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue | Where-Object { $_.Program -match 'python' } |
        Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' -and $_.Enabled -eq 'True' })
    if ($blocks.Count -gt 0) { Write-Luu ('Có ' + $blocks.Count + ' quy tắc tường lửa cũ đang CHẶN python (do bấm "Hủy" trước đây). Máy trạm có thể không vào được; báo người hỗ trợ.') }
    Write-Dat 'Đã mở cổng web chỉ cho mạng nội bộ; chặn cổng PostgreSQL từ mạng.'
}

function Step-SaoLuu {
    Write-Buoc "Bước 11/${Tong}: Lịch sao lưu 20:00 hằng ngày, giữ 30 bản"
    if (-not (Test-Path -LiteralPath $P.BackupKey)) {
        $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.with_env', $P.ClinicEnv, 'scripts.backup_lan', 'keygen', '--key', $P.BackupKey)
        if (-not $r.Ok) { Stop-CaiDat 'Không tạo được khóa sao lưu.' $r.Output 26 }
        Write-Dat 'Đã tạo khóa mã hóa sao lưu.'
    } else { Write-Dat 'Giữ nguyên khóa sao lưu đang có (không tạo lại).' }
    Set-SecureAcl -Path $P.BackupKey
    # Ổ ngoài: nhận biết bằng tệp đánh dấu, không phụ thuộc chữ cái ổ đĩa.
    if (-not (Test-Path -LiteralPath $P.ExternalCfg)) {
        $letter = $OSaoLuuNgoai
        if (-not $letter -and -not $KhongHoi) {
            if (Read-CoKhong 'Có ổ USB hoặc ổ cứng gắn ngoài dùng riêng để chép thêm bản sao lưu không?') {
                Write-Thongtin 'Cắm ổ vào máy. Các ổ đang thấy:'
                Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveLetter -ne 'C' -and $_.DriveType -in @('Removable', 'Fixed') } |
                    ForEach-Object { Write-Thongtin ("  " + $_.DriveLetter + ':  ' + $_.FileSystemLabel + '  (' + [math]::Round($_.SizeRemaining / 1GB, 1) + ' GB trống)') }
                $letter = (Read-Host '  Gõ chữ cái của ổ (ví dụ E) rồi Enter, để trống nếu bỏ qua').Trim()
            }
        }
        if ($letter) {
            $letter = $letter.TrimEnd(':', '\').ToUpperInvariant()
            if ($letter -notmatch '^[D-Z]$' -or -not (Test-Path -LiteralPath ($letter + ':\'))) { Stop-CaiDat "Không thấy ổ $letter`:." @('Cắm ổ, kiểm tra trong This PC rồi chạy lại.') 27 }
            $id = [guid]::NewGuid().ToString('N')
            $folder = $letter + ':\MinhDuc-SaoLuu'
            New-Item -ItemType Directory -Force -Path $folder | Out-Null
            Set-Content -LiteralPath (Join-Path $folder 'minhduc-backup-target.json') -Encoding UTF8 -Value (@{ id = $id } | ConvertTo-Json)
            $label = (Get-Volume -DriveLetter $letter).FileSystemLabel
            Set-Content -LiteralPath $P.ExternalCfg -Encoding UTF8 -Value (@{ id = $id; label = ([string]$label + ' (' + $letter + ':)'); declared_at = (Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json)
            Write-Dat "Đã khai báo ổ $letter`: cho bản sao lưu ngoài."
        } else { Write-Luu 'Chưa khai báo ổ ngoài: bản sao lưu chỉ nằm trên máy này. Nên có ổ ngoài trước khi dùng dữ liệu thật.' }
    } else { Write-Dat 'Giữ ổ sao lưu ngoài đã khai báo.' }
    $alert = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) $Names.AlertFile
    $jobArgs = @('-m', 'scripts.with_env', ('"' + $P.ClinicEnv + '"'), 'scripts.backup_job', '--key', ('"' + $P.BackupKey + '"'),
        '--directory', ('"' + $P.Backups + '"'), '--state', ('"' + $P.BackupState + '"'),
        '--external-config', ('"' + $P.ExternalCfg + '"'), '--alert-file', ('"' + $alert + '"')) -join ' '
    $action = New-ScheduledTaskAction -Execute $P.VenvPython -Argument $jobArgs -WorkingDirectory $P.Code
    $trigger = New-ScheduledTaskTrigger -Daily -At '20:00'
    $principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $Names.BackupTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'Sao luu ma hoa + kiem tra ban sao luu, giu 30 ban; chep ra o ngoai neu co.' -Force | Out-Null
    Write-Dat 'Đã đặt lịch sao lưu 20:00 hằng ngày (chạy bù nếu máy tắt lúc 20:00).'
    Write-Thongtin 'Chạy sao lưu thử ngay bây giờ...'
    $r = Invoke-Python -Paths $P -Quiet -OkCodes @(0, 3) -Arguments @('-m', 'scripts.with_env', $P.ClinicEnv, 'scripts.backup_job', '--key', $P.BackupKey,
        '--directory', $P.Backups, '--state', $P.BackupState, '--external-config', $P.ExternalCfg, '--alert-file', $alert)
    $r.Output | Where-Object { $_ -match '^(Sao luu|CANH BAO)' } | ForEach-Object { Write-Thongtin $_ }
    if (-not $r.Ok) { Stop-CaiDat 'Sao lưu thử thất bại.' ($r.Output | Select-Object -Last 5) 28 }
    Write-Dat 'Sao lưu thử và kiểm tra bản sao lưu: ĐẠT.'
}

function Step-QuanTri {
    Write-Buoc "Bước 12/${Tong}: Tài khoản quản trị đầu tiên"
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, 'admin-count')
    if ($r.Ok -and (ConvertFrom-PythonJson $r).admins -gt 0) { Write-Dat 'Đã có tài khoản quản trị, bỏ qua.'; return }
    if ($KhongHoi) {
        $user = $env:MINHDUC_ADMIN_USER; $name = $env:MINHDUC_ADMIN_NAME
        if (-not $user -or -not $env:MINHDUC_ADMIN_PASSWORD) { Write-Luu 'Chế độ không hỏi: chưa tạo tài khoản quản trị (thiếu biến môi trường).'; return }
        if (-not $name) { $name = 'Quản trị viên' }
        $env:MINHDUC_TMP_ADMIN_PW = $env:MINHDUC_ADMIN_PASSWORD
    } else {
        Write-Thongtin 'Tên đăng nhập: chữ thường không dấu, số, dấu chấm; bắt đầu bằng chữ (ví dụ: quantri.tuan).'
        do { $user = (Read-Host '  Tên đăng nhập').Trim().ToLowerInvariant() } until ($user -match '^[a-z][a-z0-9_.-]{1,39}$')
        do { $name = (Read-Host '  Họ và tên').Trim() } until ($name.Length -ge 2 -and $name.Length -le 180)
        while ($true) {
            $s1 = Read-Host -AsSecureString '  Mật khẩu (từ 12 ký tự, gõ sẽ không hiện)'
            $s2 = Read-Host -AsSecureString '  Nhập lại mật khẩu'
            $p1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
            $p2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
            if ($p1 -ne $p2) { Write-Luu 'Hai lần nhập không giống nhau.'; continue }
            if ($p1.Length -lt 12) { Write-Luu 'Mật khẩu cần từ 12 ký tự.'; continue }
            break
        }
        $env:MINHDUC_TMP_ADMIN_PW = $p1
        $p1 = $null; $p2 = $null
    }
    try {
        # Mật khẩu chỉ đi qua biến môi trường của tiến trình con, không qua dòng lệnh; chỉ lưu dạng băm PBKDF2.
        $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.with_env', $P.ClinicEnv, 'scripts.manage', 'create-admin',
            '--username', $user, '--name', $name, '--password-env', 'MINHDUC_TMP_ADMIN_PW')
    } finally { Remove-Item Env:\MINHDUC_TMP_ADMIN_PW -ErrorAction SilentlyContinue }
    if (-not $r.Ok) { Stop-CaiDat 'Không tạo được tài khoản quản trị.' ($r.Output | Select-Object -Last 3) 29 }
    Write-Dat "Đã tạo tài khoản quản trị: $user"
}

function Step-BieuTuong {
    $icon = Join-Path $P.ServiceDir 'minhduc.ico'
    $logo = Join-Path $P.Code 'app\static\logo_minh_duc.png'
    Invoke-Python -Paths $P -Quiet -OkCodes @(0, 1) -Arguments @('-c', 'import sys;from PIL import Image;Image.open(sys.argv[1]).convert("RGBA").save(sys.argv[2],sizes=[(256,256),(48,48),(32,32),(16,16)])', $logo, $icon) | Out-Null
    try {
        $link = New-AppShortcut -Url $script:Origin -Icon $icon
        if ($link) { Write-Dat ('Đã tạo biểu tượng "Phòng khám Minh Đức" trên Desktop.') }
    } catch { Write-Luu ('Chưa tạo được biểu tượng Desktop (' + $_.Exception.Message + '). Mở Chrome và gõ địa chỉ ' + $script:Origin) }
}

# ---------------------------------------------------------------------------
$exitCode = 0
$transcript = $false
try {
    if (-not (Test-Admin)) { Stop-CaiDat 'Cần chạy bằng quyền Administrator.' @('Bấm đúp CAI_DAT.bat và chọn "Có" (Yes) khi Windows hỏi.') 30 }
    Write-Host 'CÀI ĐẶT PHẦN MỀM PHÒNG KHÁM ĐA KHOA MINH ĐỨC — MÁY CHỦ' -ForegroundColor Cyan
    Write-Host 'Không tắt cửa sổ này cho tới khi thấy dòng "HOÀN TẤT" hoặc "DỪNG LẠI".'
    Step-ThuMucDuLieu
    Start-Transcript -Path (Join-Path $P.Journal ('cai-dat-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')) | Out-Null
    $transcript = $true
    $snap = Step-KiemTraMay
    Step-CaiPython
    if ($SourceRoot.TrimEnd('\') -ne $P.Code.TrimEnd('\') -and -not (Test-Path -LiteralPath (Join-Path $P.Code 'scripts\install_env.py'))) {
        # install_env.py cần có trong thư mục mã trước bước cài PostgreSQL.
        New-Item -ItemType Directory -Force -Path (Join-Path $P.Code 'scripts') | Out-Null
        Copy-Item -LiteralPath (Join-Path $SourceRoot 'scripts\install_env.py') -Destination (Join-Path $P.Code 'scripts\install_env.py') -Force
    }
    Step-CaiPostgres
    Step-ChepMa
    Step-CauHinhVaCSDL -Snap $snap
    Step-CauHinhPostgres
    Step-Migration
    Step-ChungChi -Snap $snap
    Step-DichVu
    Step-TuongLua -Snap $snap
    Step-SaoLuu
    Step-QuanTri
    Step-BieuTuong
    Write-Buoc "Bước 13/${Tong}: Kiểm tra sức khỏe"
    $report = Join-Path $P.Journal ('kiem-tra-sau-cai-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
    $healthy = Invoke-HealthReport -Paths $P -Output $report -Title 'KẾT QUẢ KIỂM TRA SAU CÀI ĐẶT'
    Write-Host ''
    if ($healthy) { Write-Host 'HOÀN TẤT: tất cả mục ĐẠT.' -ForegroundColor Green }
    else { Write-Host 'HOÀN TẤT CÀI ĐẶT nhưng có mục KHÔNG ĐẠT (xem danh sách trên).' -ForegroundColor Yellow; $exitCode = 40 }
    Write-Host ('Địa chỉ phần mềm: ' + $script:Origin)
    Write-Host ('Cài máy trạm: chép thư mục ' + $P.Share + ' (hoặc mở \\' + $env:COMPUTERNAME + '\' + $Names.Share + ') rồi bấm đúp CAI_MAY_TRAM.bat.')
    Write-Host ('VIỆC BẮT BUỘC: chép tệp khóa ' + $P.BackupKey + ' sang một USB KHÁC (không phải ổ sao lưu), cất nơi an toàn. Mất khóa = không mở được bản sao lưu.') -ForegroundColor Yellow
    if ($CanKhoiDongLai) { Write-Host 'Cần KHỞI ĐỘNG LẠI máy để áp dụng tệp hoán đổi mới.' -ForegroundColor Yellow }
} catch {
    $code = $_.Exception.Data['MinhDucExit']
    if ($null -eq $code) {
        $code = 99
        Write-Host ''
        Write-Host ('LỖI KHÔNG LƯỜNG TRƯỚC: ' + $_.Exception.Message) -ForegroundColor Red
        Write-Host ('  Vị trí: ' + $_.InvocationInfo.PositionMessage) -ForegroundColor DarkGray
        Write-Host '  Gửi tệp nhật ký trong C:\ProgramData\MinhDuc\nhatky cho người hỗ trợ. Dữ liệu chưa bị xóa.' -ForegroundColor Yellow
    }
    $exitCode = [int]$code
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
}
exit $exitCode
