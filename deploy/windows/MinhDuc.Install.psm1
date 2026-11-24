# Mô-đun dùng chung cho CAI_DAT / CAP_NHAT / KIEM_TRA (Windows PowerShell 5.1).
# Lưu dạng UTF-8 có BOM: PowerShell 5.1 đọc tệp không BOM theo bảng mã ANSI.
# Không in mật khẩu, không ghi mật khẩu vào nhật ký.
Set-StrictMode -Version 2.0

# ---------------------------------------------------------------------------
# Phiên bản ghim cố định. SHA256 do người phát triển tự tính từ tệp tải về
# (đối chiếu chữ ký số Authenticode của nhà phát hành). Đổi phiên bản = đổi cả mã băm.
# ---------------------------------------------------------------------------
$script:Pins = @{
    Python   = @{ Version = '3.12.10'; File = 'python-3.12.10-amd64.exe'; Url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'; Sha256 = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb' }
    Postgres = @{ Version = '17.11'; File = 'postgresql-17.11-1-windows-x64.exe'; Url = 'https://get.enterprisedb.com/postgresql/postgresql-17.11-1-windows-x64.exe'; Sha256 = 'f104c552d8495a6f20738c2a03f643164bc64b9985363329e314dec24559f0b7' }
    WinSW    = @{ Version = '2.12.0'; File = 'WinSW-x64-2.12.0.exe'; Url = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'; Sha256 = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da' }
}

# Thứ tự thời gian dừng dịch vụ, phải luôn đúng: Python tự dừng (scripts/run_lan.py,
# timeout_graceful_shutdown 60 giây, đủ cho xuất báo cáo/in phiếu đang chạy dở)
# < WinSW cưỡng chế (stoptimeout) < PowerShell chờ Stopped.
# Hai mốc WinSW và PowerShell trước đây cùng 30 giây nên chạy đua: PowerShell bỏ cuộc
# đúng lúc WinSW còn đang chờ. Kiểm bởi tests/test_windows_service_stop_order.py.
$script:ServiceStopTimeoutSec = 90

# Số giây ghi thẳng trong hàm để bài thử trích riêng hàm (không nạp mô-đun) vẫn chạy đúng.
function Get-MinhDucServiceStopWait {
    return New-TimeSpan -Seconds 120
}

$script:Names = @{
    Service      = 'MinhDuc'
    ServiceAcct  = 'NT SERVICE\MinhDuc'
    PgService    = 'postgresql-x64-17'
    PgRoot       = 'C:\Program Files\PostgreSQL\17'
    PythonRoot   = 'C:\Program Files\Python312'
    FirewallWeb  = 'MinhDuc - web HTTPS (LAN)'
    FirewallPg   = 'MinhDuc - chan PostgreSQL tu mang'
    FirewallGrp  = 'MinhDuc'
    FirewallMaintenance = 'MinhDuc - tam chan HTTPS bao tri'
    BackupTask   = 'MinhDuc - Sao luu 20h'
    StartupRecoveryTask = 'MinhDuc - Tu go bao tri'
    Share        = 'MinhDuc'
    Port         = 8443
    Shortcut     = 'Phòng khám Minh Đức.lnk'
    AlertFile    = 'CANH BAO SAO LUU - Phong kham Minh Duc.txt'
}

function Get-MinhDucPins { return $script:Pins }
function Get-MinhDucNames { return $script:Names }

function Find-Python312 {
    # Python 3.12 64-bit cài cho mọi người dùng (HKLM), để tài khoản dịch vụ đọc được.
    # Không dùng bản cài riêng cho một người dùng (nằm trong hồ sơ cá nhân).
    try {
        $key = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Python\PythonCore\3.12\InstallPath' -ErrorAction Stop
        $exe = $null
        if ($key.PSObject.Properties.Name -contains 'ExecutablePath' -and $key.ExecutablePath) { $exe = $key.ExecutablePath }
        elseif ($key.'(default)') { $exe = Join-Path $key.'(default)' 'python.exe' }
        if ($exe -and (Test-Path -LiteralPath $exe)) { return $exe }
    } catch { }
    $default = Join-Path $script:Names.PythonRoot 'python.exe'
    if (Test-Path -LiteralPath $default) { return $default }
    return $null
}

function Get-MinhDucPaths {
    param([string]$Code = 'C:\MinhDuc', [string]$Data = 'C:\ProgramData\MinhDuc')
    return [pscustomobject]@{
        Code        = $Code
        Data        = $Data
        Admin       = Join-Path $Data 'quantri'
        ClinicEnv   = Join-Path $Data 'clinic.env'
        OwnerEnv    = Join-Path $Data 'quantri\owner.env'
        SuperEnv    = Join-Path $Data 'quantri\postgres.env'
        BackupKey   = Join-Path $Data 'quantri\backup.key'
        CaKey       = Join-Path $Data 'quantri\ca.key'
        ExternalCfg = Join-Path $Data 'quantri\o-sao-luu-ngoai.json'
        BackupState = Join-Path $Data 'backup-status.json'
        Backups     = Join-Path $Data 'backups'
        Attachments = Join-Path $Data 'attachments'
        Settings    = Join-Path $Data 'caidat'
        Logs        = Join-Path $Data 'logs'
        Journal     = Join-Path $Data 'nhatky'
        Tls         = Join-Path $Data 'tls'
        ServiceDir  = Join-Path $Data 'service'
        ServiceStartModePending = Join-Path $Data 'service-startmode-pending.json'
        # Dùng chung với KIEM_TRA và PR #49, kể cả khi chỉ định thư mục dữ liệu khác.
        MaintenanceLockBase = 'C:\ProgramData\MinhDuc\service-startmode-pending.json'
        Downloads   = Join-Path $Data 'taive'
        Updates     = Join-Path $Data 'capnhat'
        Share       = 'C:\MinhDuc-ChiaSe'
        Venv        = Join-Path $Code '.venv'
        VenvPython  = Join-Path $Code '.venv\Scripts\python.exe'
        BasePython  = $(if ($found = Find-Python312) { $found } else { Join-Path $script:Names.PythonRoot 'python.exe' })
        PgBin       = Join-Path $script:Names.PgRoot 'bin'
        PgData      = Join-Path $script:Names.PgRoot 'data'
    }
}

# ---------------------------------------------------------------------------
# Hiển thị tiếng Việt
# ---------------------------------------------------------------------------
function Write-Buoc([string]$Text) { Write-Host ''; Write-Host ('==== ' + $Text + ' ====') -ForegroundColor Cyan }
function Write-Dat([string]$Text) { Write-Host ('  [ĐẠT] ' + $Text) -ForegroundColor Green }
function Write-Luu([string]$Text) { Write-Host ('  [LƯU Ý] ' + $Text) -ForegroundColor Yellow }
function Write-Loi([string]$Text) { Write-Host ('  [KHÔNG ĐẠT] ' + $Text) -ForegroundColor Red }
function Write-Thongtin([string]$Text) { Write-Host ('  ' + $Text) }

function Stop-CaiDat {
    param([string]$Message, [string[]]$Huong = @(), [int]$Code = 1)
    Write-Host ''
    Write-Host ('DỪNG LẠI: ' + $Message) -ForegroundColor Red
    foreach ($line in $Huong) { Write-Host ('  - ' + $line) -ForegroundColor Yellow }
    Write-Host '  Chưa có dữ liệu nào bị xóa. Sửa xong thì bấm đúp lại tệp cài đặt.' -ForegroundColor Yellow
    $ex = New-Object System.Exception($Message)
    $ex.Data['MinhDucExit'] = $Code
    throw $ex
}

function Read-CoKhong {
    param([string]$Question, [switch]$KhongHoi, [bool]$MacDinh = $false)
    if ($KhongHoi) { return $MacDinh }
    while ($true) {
        $answer = (Read-Host ($Question + ' Gõ C (có) hoặc K (không) rồi bấm Enter')).Trim().ToUpperInvariant()
        if ($answer -in @('C', 'CO', 'CÓ', 'Y')) { return $true }
        if ($answer -in @('K', 'KHONG', 'KHÔNG', 'N')) { return $false }
        Write-Host '  Chỉ gõ C hoặc K.'
    }
}

# ---------------------------------------------------------------------------
# Kiểm tra máy (bước a) — phần đánh giá là hàm thuần, kiểm thử được.
# ---------------------------------------------------------------------------
function Get-PrecheckAssessment {
    param([Parameter(Mandatory = $true)]$Snapshot)
    $checks = New-Object System.Collections.Generic.List[object]
    function Add-Item($Id, $Level, $Message, $Huong) {
        $checks.Add([pscustomobject]@{ id = $Id; level = $Level; message = $Message; huong = @($Huong) })
    }
    $os = $Snapshot.os
    if ($os.architecture -notmatch '64') {
        Add-Item 'os' 'STOP' 'Cần Windows 64-bit.' @('Cài Windows 10 hoặc 11 bản 64-bit.')
    } elseif ($os.caption -match 'Windows Server' -and [int]$os.build -ge 17763) {
        Add-Item 'os' 'WARN' ($os.caption + ', bản ' + $os.build + ': chạy được nhưng không phải cấu hình đã chốt (Windows 10/11).') @()
    } elseif ($os.caption -notmatch 'Windows (10|11)' -or [int]$os.build -lt 19041) {
        Add-Item 'os' 'STOP' ('Chỉ hỗ trợ Windows 10/11 64-bit (đang là ' + $os.caption + ', bản ' + $os.build + ').') @('Cập nhật Windows hoặc dùng máy khác.')
    } else {
        Add-Item 'os' 'OK' ($os.caption + ' 64-bit, bản ' + $os.build + '.') @()
    }
    if ($Snapshot.ram_gib -lt 7.5) {
        Add-Item 'ram' 'STOP' ('RAM chỉ có ' + $Snapshot.ram_gib + ' GB, cần từ 8 GB.') @('Dùng máy có RAM 8 GB trở lên.')
    } else { Add-Item 'ram' 'OK' ('RAM ' + $Snapshot.ram_gib + ' GB.') @() }
    if ($Snapshot.free_c_gib -lt 20) {
        Add-Item 'disk' 'STOP' ('Ổ C chỉ còn ' + $Snapshot.free_c_gib + ' GB trống, cần từ 20 GB.') @('Dọn Thùng rác và tệp tạm: Settings > System > Storage > Temporary files.', 'Không xóa tệp sao lưu hay tệp của phần mềm khác khi chưa hỏi người phụ trách.')
    } else { Add-Item 'disk' 'OK' ('Ổ C còn ' + $Snapshot.free_c_gib + ' GB trống.') @() }
    if (-not $Snapshot.internet) {
        if ($Snapshot.already_installed) { Add-Item 'internet' 'WARN' 'Không có Internet; các thành phần đã cài sẵn nên vẫn tiếp tục.' @() }
        else { Add-Item 'internet' 'STOP' 'Máy chưa vào được Internet để tải Python và PostgreSQL.' @('Cắm dây mạng hoặc kiểm tra modem, mở thử trang web bất kỳ rồi chạy lại.') }
    } else { Add-Item 'internet' 'OK' 'Có kết nối Internet.' @() }
    $ip = $Snapshot.ip
    if ($null -eq $ip -or -not $ip.address) {
        Add-Item 'ip' 'STOP' 'Không tìm thấy địa chỉ IP mạng nội bộ của máy.' @('Kiểm tra dây mạng/Wi-Fi nội bộ của phòng khám rồi chạy lại.')
    } elseif ($ip.address -notmatch '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)') {
        Add-Item 'ip' 'STOP' ('IP ' + $ip.address + ' không phải IP nội bộ.') @('Máy chủ phải nằm trong mạng LAN của phòng khám, không đặt IP công cộng.')
    } elseif ($ip.dhcp) {
        Add-Item 'ip' 'ASK_DHCP' ('IP ' + $ip.address + ' đang do modem tự cấp (IP động), có thể đổi sau khi khởi động lại.') @(
            'Cách 1 (khuyên dùng): vào trang quản trị modem, mục DHCP Reservation / Giữ IP, gán IP ' + $ip.address + ' cho máy này.',
            'Cách 2: Settings > Network & internet > Ethernet > IP assignment > Edit > Manual, bật IPv4: nhập IP ' + $ip.address + ', Subnet prefix length ' + $ip.prefix + ', Gateway ' + $ip.gateway + ', Preferred DNS ' + $ip.gateway + '.')
    } else { Add-Item 'ip' 'OK' ('IP tĩnh ' + $ip.address + '/' + $ip.prefix + '.') @() }
    $pf = $Snapshot.pagefile
    if ($null -ne $pf -and -not $pf.auto -and $pf.max_mib -gt 0 -and $pf.max_mib -lt 4096) {
        Add-Item 'pagefile' 'ASK_PAGEFILE' ('Tệp hoán đổi (page file) đang cố định ' + $pf.max_mib + ' MB, quá nhỏ cho PostgreSQL và trình duyệt.') @('Nên chuyển sang "Windows tự quản lý" (System managed); có hiệu lực sau khi khởi động lại máy.')
    } else { Add-Item 'pagefile' 'OK' 'Tệp hoán đổi phù hợp.' @() }
    $ci = $Snapshot.code_integrity
    if ($ci.language_mode -ne 'FullLanguage') {
        Add-Item 'appcontrol' 'STOP' 'Windows đang chạy PowerShell ở chế độ hạn chế (App Control đang chặn script).' @('Không tự tắt Smart App Control hay App Control. Dừng cài và gọi người hỗ trợ (chụp màn hình này gửi kèm).')
    } elseif ($ci.sac_state -eq 1) {
        Add-Item 'appcontrol' 'STOP' 'Smart App Control đang BẬT: sẽ chặn Python, thư viện và trình chạy dịch vụ chưa có chữ ký số.' @('Không tự tắt Smart App Control hay App Control. Dừng cài và gọi người hỗ trợ (chụp màn hình này gửi kèm).', 'Giữ nguyên Microsoft Defender và Tường lửa.')
    } elseif ($ci.sac_state -eq 2) {
        Add-Item 'appcontrol' 'ASK_SAC' 'Smart App Control đang ở chế độ đánh giá; Windows có thể tự BẬT sau này và chặn phần mềm.' @('Không tự tắt Smart App Control. Báo người hỗ trợ trước khi dùng thật; nếu sau này Windows chặn phần mềm thì dừng và gọi người hỗ trợ.')
    } elseif ($ci.usermode -eq 2) {
        Add-Item 'appcontrol' 'STOP' 'Có chính sách App Control for Business chặn ứng dụng ở chế độ người dùng.' @('Nhờ quản trị CNTT cho phép C:\MinhDuc, Python 3.12 và PostgreSQL 17 rồi chạy lại.')
    } else {
        $note = 'Không có chính sách chặn ứng dụng ở chế độ người dùng.'
        if ($ci.kernel -eq 2) { $note += ' (Dòng "App Control for Business policy: Enforced" trong System Information là danh sách chặn trình điều khiển của Microsoft, không chặn phần mềm này.)' }
        Add-Item 'appcontrol' 'OK' $note @()
    }
    if ($Snapshot.port_conflict) {
        Add-Item 'ports' 'STOP' ('Cổng ' + $Snapshot.port_conflict + ' đang bị phần mềm khác dùng.') @('Tắt phần mềm đang dùng cổng này hoặc liên hệ người hỗ trợ.')
    }
    return @($checks.ToArray())
}

function Get-PrecheckSnapshot {
    param([string]$PgPort = '5432')
    $os = Get-CimInstance Win32_OperatingSystem
    $installed = 0
    try { $installed = (Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum).Sum } catch { }
    if (-not $installed) { $installed = [double]$os.TotalVisibleMemorySize * 1024 }
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $internet = $false
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $r = Invoke-WebRequest -Uri 'https://www.python.org/' -Method Head -UseBasicParsing -TimeoutSec 20
        $internet = ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { $internet = $false }
    $ip = $null
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | Sort-Object { $_.RouteMetric + $_.InterfaceMetric } | Select-Object -First 1
        $addr = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction Stop | Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1
        $iface = Get-NetIPInterface -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction Stop
        $ip = [pscustomobject]@{ address = $addr.IPAddress; prefix = [int]$addr.PrefixLength; dhcp = ([string]$iface.Dhcp -eq 'Enabled'); gateway = $route.NextHop; interface_index = $route.InterfaceIndex }
    } catch { }
    $cs = Get-CimInstance Win32_ComputerSystem
    $maxMib = 0
    try { $maxMib = [int](@(Get-CimInstance Win32_PageFileSetting | Measure-Object MaximumSize -Maximum)[0].Maximum) } catch { }
    $sac = $null
    try { $sac = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -Name VerifiedAndReputablePolicyState -ErrorAction Stop).VerifiedAndReputablePolicyState } catch { }
    $um = $null; $kernel = $null
    try {
        $dg = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard -ErrorAction Stop
        $um = $dg.UsermodeCodeIntegrityPolicyEnforcementStatus; $kernel = $dg.CodeIntegrityPolicyEnforcementStatus
    } catch { }
    $paths = Get-MinhDucPaths
    $already = (Test-Path -LiteralPath $paths.VenvPython) -and (Test-Path -LiteralPath (Join-Path $paths.PgBin 'postgres.exe'))
    $conflict = $null
    try {
        $pgListen = @(Get-NetTCPConnection -State Listen -LocalPort ([int]$PgPort) -ErrorAction Stop)
        if ($pgListen.Count -gt 0 -and -not (Get-Service -Name $script:Names.PgService -ErrorAction SilentlyContinue)) { $conflict = $PgPort }
    } catch { }
    try {
        $webListen = @(Get-NetTCPConnection -State Listen -LocalPort $script:Names.Port -ErrorAction Stop)
        if ($webListen.Count -gt 0 -and -not (Get-Service -Name $script:Names.Service -ErrorAction SilentlyContinue)) { $conflict = $script:Names.Port }
    } catch { }
    return [pscustomobject]@{
        os = [pscustomobject]@{ caption = [string]$os.Caption; architecture = [string]$os.OSArchitecture; build = [int]$os.BuildNumber }
        ram_gib = [math]::Round($installed / 1GB, 1)
        free_c_gib = [math]::Round($disk.FreeSpace / 1GB, 1)
        internet = $internet
        already_installed = $already
        ip = $ip
        pagefile = [pscustomobject]@{ auto = [bool]$cs.AutomaticManagedPagefile; max_mib = $maxMib }
        code_integrity = [pscustomobject]@{ language_mode = [string]$ExecutionContext.SessionState.LanguageMode; sac_state = $sac; usermode = $um; kernel = $kernel }
        port_conflict = $conflict
    }
}

function Set-PagefileSystemManaged {
    $cs = Get-CimInstance Win32_ComputerSystem
    Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $true } | Out-Null
}

# ---------------------------------------------------------------------------
# Chạy chương trình ngoài an toàn với PowerShell 5.1 (stderr không làm dừng giữa chừng)
# ---------------------------------------------------------------------------
function Invoke-Native {
    param([Parameter(Mandatory = $true)][string]$FilePath, [string[]]$Arguments = @(), [switch]$Quiet, [int[]]$OkCodes = @(0), [string]$WorkingDirectory = '')
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $output = New-Object System.Collections.Generic.List[string]
    try {
        if ($WorkingDirectory) { Push-Location -LiteralPath $WorkingDirectory }
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            $line = [string]$_
            $output.Add($line)
            if (-not $Quiet) { Write-Host ('    ' + $line) }
        }
        $code = $LASTEXITCODE
    } finally {
        if ($WorkingDirectory) { Pop-Location }
        $ErrorActionPreference = $old
    }
    return [pscustomobject]@{ Code = $code; Ok = ($OkCodes -contains $code); Output = @($output.ToArray()) }
}

function Invoke-Python {
    # Chạy python trong thư mục mã (để "-m scripts.xxx" tìm được gói).
    param([Parameter(Mandatory = $true)]$Paths, [string[]]$Arguments, [switch]$Quiet, [switch]$Base,
          [int[]]$OkCodes = @(0), [string]$WorkingDirectory = $Paths.Code)
    $exe = if ($Base) { $Paths.BasePython } else { $Paths.VenvPython }
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    return Invoke-Native -FilePath $exe -Arguments $Arguments -Quiet:$Quiet -OkCodes $OkCodes -WorkingDirectory $WorkingDirectory
}

function ConvertFrom-PythonJson($Result) {
    $line = @($Result.Output | Where-Object { $_ -match '^\s*[\{\[]' } | Select-Object -Last 1)
    if ($line.Count -eq 0) { return $null }
    return ($line[0] | ConvertFrom-Json)
}

# ---------------------------------------------------------------------------
# Tải tệp có phiên bản ghim, kiểm SHA256 trước khi chạy
# ---------------------------------------------------------------------------
function Get-PinnedFile {
    param([Parameter(Mandatory = $true)][hashtable]$Pin, [Parameter(Mandatory = $true)][string]$CacheDir, [string[]]$LocalDirs = @())
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    # Cho phép đặt sẵn bộ cài (máy không có Internet): thư mục "taive" cạnh CAI_DAT.bat.
    foreach ($dir in @($LocalDirs + $CacheDir)) {
        if (-not $dir) { continue }
        $candidate = Join-Path $dir $Pin.File
        if (Test-Path -LiteralPath $candidate) {
            if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Pin.Sha256) { return $candidate }
            Write-Luu ('Tệp ' + $candidate + ' có mã SHA256 sai, bỏ qua.')
        }
    }
    $target = Join-Path $CacheDir $Pin.File
    $partial = $target + '.dangtai'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Write-Thongtin ('Đang tải ' + $Pin.File + ' ...')
    $old = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'  # tải nhanh hơn nhiều trên PowerShell 5.1
    try { Invoke-WebRequest -Uri $Pin.Url -OutFile $partial -UseBasicParsing -TimeoutSec 1800 }
    finally { $ProgressPreference = $old }
    $hash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $Pin.Sha256) {
        Remove-Item -LiteralPath $partial -Force
        Stop-CaiDat ('Tệp tải về ' + $Pin.File + ' có mã kiểm tra SHA256 không khớp; đã xóa, không chạy.') @('Có thể do mạng lỗi hoặc tệp bị thay đổi. Chạy lại sau ít phút; nếu vẫn lỗi, báo người hỗ trợ.')
    }
    Move-Item -LiteralPath $partial -Destination $target -Force
    Write-Dat ('Đã tải và kiểm SHA256: ' + $Pin.File)
    return $target
}

# ---------------------------------------------------------------------------
# Phân quyền NTFS bằng SID (không phụ thuộc ngôn ngữ Windows)
# ---------------------------------------------------------------------------
$script:Sid = @{ Admins = '*S-1-5-32-544'; System = '*S-1-5-18'; Users = '*S-1-5-32-545'; Everyone = '*S-1-1-0'; AuthUsers = '*S-1-5-11' }

function Set-SecureAcl {
    # Bỏ thừa kế, chỉ Administrators + SYSTEM toàn quyền; thêm người đọc/ghi được chỉ định.
    param([Parameter(Mandatory = $true)][string]$Path, [string[]]$Readers = @(), [string[]]$Writers = @(), [switch]$Directory)
    $inherit = if ($Directory) { '(OI)(CI)' } else { '' }
    $icaclsArgs = @($Path, '/inheritance:r', '/grant:r', ($script:Sid.Admins + ':' + $inherit + 'F'), '/grant:r', ($script:Sid.System + ':' + $inherit + 'F'))
    foreach ($r in $Readers) { $icaclsArgs += @('/grant:r', ($r + ':' + $inherit + 'RX')) }
    foreach ($w in $Writers) { $icaclsArgs += @('/grant:r', ($w + ':' + $inherit + 'M')) }
    $result = Invoke-Native -FilePath 'icacls.exe' -Arguments $icaclsArgs -Quiet
    if (-not $result.Ok) { Stop-CaiDat ('Không đặt được quyền truy cập cho ' + $Path) @(($result.Output -join ' ')) }
    # Gỡ các quyền rộng có thể còn sót (Users, Everyone, Authenticated Users).
    foreach ($broad in @($script:Sid.Users, $script:Sid.Everyone, $script:Sid.AuthUsers)) {
        if ($Readers -notcontains $broad) { Invoke-Native -FilePath 'icacls.exe' -Arguments @($Path, '/remove:g', $broad) -Quiet | Out-Null }
    }
}

function Test-AccountCanRead {
    # ĐẠT khi ACL của tệp cho tài khoản (theo SID) quyền đọc và không có quy tắc Deny đọc.
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Account)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $sid = (New-Object Security.Principal.NTAccount($Account)).Translate([Security.Principal.SecurityIdentifier]).Value
    $read = [Security.AccessControl.FileSystemRights]::ReadData
    $allow = $false; $deny = $false
    foreach ($rule in (Get-Acl -LiteralPath $Path).Access) {
        try { $ruleSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } catch { continue }
        if ($ruleSid -ne $sid -or (($rule.FileSystemRights -band $read) -eq 0)) { continue }
        if ([string]$rule.AccessControlType -eq 'Deny') { $deny = $true } else { $allow = $true }
    }
    return ($allow -and -not $deny)
}

function Test-SecureAcl {
    # ĐẠT khi Users / Everyone / Authenticated Users không có quyền đọc.
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ Ok = $false; Detail = ('Không thấy ' + (Split-Path $Path -Leaf)) } }
    $broad = @('S-1-5-32-545', 'S-1-1-0', 'S-1-5-11')
    $acl = Get-Acl -LiteralPath $Path
    foreach ($rule in $acl.Access) {
        try { $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = [string]$rule.IdentityReference }
        if ($broad -contains $sid -and $rule.AccessControlType -eq 'Allow') {
            return [pscustomobject]@{ Ok = $false; Detail = ((Split-Path $Path -Leaf) + ' đang cho nhóm rộng đọc: ' + $rule.IdentityReference) }
        }
    }
    return [pscustomobject]@{ Ok = $true; Detail = ((Split-Path $Path -Leaf) + ': chỉ quản trị/SYSTEM/dịch vụ') }
}

# ---------------------------------------------------------------------------
# Tệp cấu hình KEY=VALUE (chỉ đọc giá trị không bí mật khi cần)
# ---------------------------------------------------------------------------
function Set-EnvValue {
    # Đặt một khóa KEY=VALUE (không bí mật) trong tệp cấu hình, ghi tại chỗ để giữ nguyên quyền tệp.
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Key, [Parameter(Mandatory = $true)][string]$Value)
    $lines = @([IO.File]::ReadAllLines($Path, [Text.Encoding]::UTF8))
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -like ($Key + '=*')) { $lines[$i] = $Key + '=' + $Value; $found = $true } }
    if (-not $found) { $lines += ($Key + '=' + $Value) }
    [IO.File]::WriteAllText($Path, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
}

function Read-EnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($raw in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $i = $line.IndexOf('=')
        if ($i -gt 0) { $values[$line.Substring(0, $i)] = $line.Substring($i + 1) }
    }
    return $values
}

# ---------------------------------------------------------------------------
# Dịch vụ Windows (WinSW)
# ---------------------------------------------------------------------------
function New-ServiceXml {
    param([Parameter(Mandatory = $true)]$Paths)
    $esc = { param($s) [System.Security.SecurityElement]::Escape([string]$s) }
    $serviceArgs = '-m scripts.with_env "' + $Paths.ClinicEnv + '" scripts.run_lan'
    $logDir = Join-Path $Paths.Logs 'service'
    return @"
<service>
  <id>$($script:Names.Service)</id>
  <name>Phong kham Minh Duc - web</name>
  <description>May chu web noi bo Phong kham da khoa Minh Duc (HTTPS, chi mang LAN).</description>
  <executable>$(& $esc $Paths.VenvPython)</executable>
  <arguments>$(& $esc $serviceArgs)</arguments>
  <workingdirectory>$(& $esc $Paths.Code)</workingdirectory>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <depend>$($script:Names.PgService)</depend>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <onfailure action="restart" delay="60 sec"/>
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>$($script:ServiceStopTimeoutSec) sec</stoptimeout>
  <logpath>$(& $esc $logDir)</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>5120</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
  <env name="PYTHONUNBUFFERED" value="1"/>
  <env name="PYTHONIOENCODING" value="utf-8"/>
  <env name="PYTHONUTF8" value="1"/>
  <env name="PYTHONDONTWRITEBYTECODE" value="1"/>
</service>
"@
}

function Set-RecoveryServiceStartMode($Service, [string]$Mode) {
    $result = Invoke-CimMethod -InputObject $Service -MethodName ChangeStartMode -Arguments @{ StartMode = $Mode } -ErrorAction Stop
    if ($result.ReturnValue -ne 0) { throw ('Không đổi được chế độ khởi động dịch vụ sang ' + $Mode + ', mã ' + $result.ReturnValue) }
}

function Get-MinhDucDelayedAutoStart([string]$Name) {
    $key = Get-Item -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\' + $Name) -ErrorAction Stop
    try { return ($key.GetValue('DelayedAutoStart', 0) -ne 0) }
    finally { $key.Dispose() }
}

function Open-MinhDucServiceStartModeLock([string]$Path) {
    # Windows nhả khóa khi tiến trình thoát, kể cả khi finally không chạy.
    try { return [IO.File]::Open(($Path + '.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch [IO.IOException] {
        $reason = $_.Exception.GetBaseException().HResult -band 0xFFFF
        if ($reason -in @(11, 32, 33)) {
            $busy = [InvalidOperationException]::new('Đang có bảo trì khác. Hãy chờ lần bảo trì đó kết thúc rồi thử lại.')
            $busy.Data['MinhDucExit'] = 52
            throw $busy
        }
        throw
    }
}

function Get-MinhDucServiceStartModeMarkerFile([string]$Path) {
    try { return Get-Item -LiteralPath $Path -Force -ErrorAction Stop }
    catch [Management.Automation.ItemNotFoundException] { return $null }
}

function Write-MinhDucServiceStartModeMarker([string]$Path, $Marker, [switch]$Replace) {
    $temp = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($Marker | ConvertTo-Json -Compress))
        $file = [IO.File]::Open($temp, 'CreateNew', 'Write', 'None')
        try {
            $file.Write($bytes, 0, $bytes.Length)
            $file.Flush($true)
        } finally { $file.Dispose() }
        if ($Replace) { [IO.File]::Replace($temp, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temp, $Path) }
    } finally {
        if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
    }
}

function Read-MinhDucServiceStartModeMarker([string]$Name, $Paths) {
    # Bên gọi phải giữ khóa suốt lúc đọc, sửa SCM và xóa dấu.
    $path = $Paths.ServiceStartModePending
    $markerFile = Get-MinhDucServiceStartModeMarkerFile $path
    if (-not $markerFile) { return }

    $invalid = 'Tệp đánh dấu chế độ khởi động bị hỏng hoặc thiếu thông tin. Giữ nguyên tệp.'
    try {
        $json = [IO.File]::ReadAllText($markerFile.FullName)
        if (-not $json.TrimStart().StartsWith('{')) { throw $invalid }
        $marker = ConvertFrom-Json -InputObject $json -ErrorAction Stop
    }
    catch { throw $invalid }
    $timestamp = [datetime]::MinValue
    if ($marker -isnot [pscustomobject] -or
        @('Service', 'StartMode', 'DelayedAutoStart', 'CreatedAt', 'Script' | Where-Object { $_ -cnotin $marker.PSObject.Properties.Name }).Count -gt 0 -or
        $marker.Service -isnot [string] -or $marker.Service -cne $Name -or
        $marker.StartMode -isnot [string] -or $marker.StartMode -cnotin @('Automatic', 'Manual') -or
        $marker.DelayedAutoStart -isnot [bool] -or
        $marker.Script -isnot [string] -or $marker.Script -cnotin @('CapNhat.ps1', 'GiaHanChungChi.ps1') -or
        $marker.CreatedAt -isnot [string] -or
        -not [datetime]::TryParseExact($marker.CreatedAt, "dd/MM/yyyy HH:mm:ss 'UTC+7'", [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$timestamp)) { throw $invalid }

    $fields = @('Status', 'TaskEnabled', 'FirewallRule')
    $present = @($fields | Where-Object { $_ -cin $marker.PSObject.Properties.Name })
    if ($present.Count) {
        if ($present.Count -ne $fields.Count -or $marker.Status -isnot [string] -or $marker.Status -cnotin @('dang_bao_tri','quay_ve_that_bai','da_quay_ve') -or
            $marker.TaskEnabled -isnot [pscustomobject] -or $marker.FirewallRule -isnot [string] -or
            $marker.FirewallRule -cnotin @('', (Get-MinhDucNames).FirewallMaintenance)) { throw $invalid }
        $names = Get-MinhDucNames
        foreach ($task in $marker.TaskEnabled.PSObject.Properties) {
            if ($task.Name -cnotin @($names.BackupTask, ($names.BackupTask + ' - Chay bu')) -or $task.Value -isnot [bool]) {
                throw $invalid
            }
        }
    }
    if ('Phase' -cnotin $marker.PSObject.Properties.Name) {
        # Bản cũ chỉ ghi dấu CapNhat khi quay về sau khi đã thay mã hoặc dữ liệu.
        $phase = if ($marker.Script -eq 'CapNhat.ps1') { 'da_doi_du_lieu' } else { 'chua_doi_du_lieu' }
        $marker | Add-Member -NotePropertyName Phase -NotePropertyValue $phase
        if ($phase -eq 'da_doi_du_lieu' -and $present.Count -and $marker.Status -eq 'da_quay_ve') {
            # Chỉ tin xác nhận quay về của định dạng có Phase.
            $marker.Status = 'dang_bao_tri'
        }
    } elseif ($marker.Phase -isnot [string] -or $marker.Phase -cnotin @('chua_doi_du_lieu', 'da_doi_du_lieu', 'da_chot') -or
        ($marker.Phase -ne 'chua_doi_du_lieu' -and ($present.Count -eq 0 -or $marker.Script -ne 'CapNhat.ps1' -or -not $marker.FirewallRule))) {
        throw $invalid
    }
    return $marker
}

function Restore-MinhDucServiceStartup([string]$Name, $Marker) {
    $filter = "Name='$Name'"
    $config = Get-CimInstance Win32_Service -Filter $filter -ErrorAction Stop
    if (-not $config) { throw "Không tìm thấy dịch vụ $Name để trả chế độ khởi động." }
    $expected = if ($marker.StartMode -eq 'Automatic') { 'Auto' } else { 'Manual' }
    if ($config.StartMode -ne $expected) { Set-RecoveryServiceStartMode $config $marker.StartMode }
    if ((Get-MinhDucDelayedAutoStart $Name) -ne $marker.DelayedAutoStart) {
        if ($marker.StartMode -eq 'Automatic') {
            $mode = if ($marker.DelayedAutoStart) { 'delayed-auto' } else { 'auto' }
            $result = Invoke-Native -FilePath 'sc.exe' -Arguments @('config', $Name, 'start=', $mode) -Quiet
            if (-not $result.Ok) { throw ('Không trả được DelayedAutoStart, mã ' + $result.Code) }
        } else {
            # Với Manual, Windows không dùng cờ này. Giữ lại giá trị đã lưu.
            Set-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\' + $Name) -Name 'DelayedAutoStart' -Value ([int]$marker.DelayedAutoStart) -Type DWord -ErrorAction Stop
        }
    }
    $actual = Get-CimInstance Win32_Service -Filter $filter -ErrorAction Stop
    if (-not $actual -or $actual.StartMode -ne $expected -or (Get-MinhDucDelayedAutoStart $Name) -ne $marker.DelayedAutoStart) {
        throw 'Kiểm lại chế độ khởi động hoặc DelayedAutoStart chưa đạt. Giữ nguyên tệp đánh dấu.'
    }
}

function Restore-MinhDucServiceStartMode {
    param([string]$Name, $Paths, [string]$ScriptName, [switch]$VerifiedRollback, [object[]]$BackupTaskSnapshot,
          [switch]$AtStartup, [hashtable]$RecoveryInfo)
    # Bên gọi giữ khóa đến khi đọc lại cấu hình và xóa dấu.
    $marker = Read-MinhDucServiceStartModeMarker $Name $Paths
    if (-not $marker) { return }
    if ($null -ne $RecoveryInfo) { $RecoveryInfo.Marker = $marker }
    $extended = 'Status' -cin $marker.PSObject.Properties.Name
    if (-not $VerifiedRollback) {
        $blocked = if ($extended -and $marker.Status -eq 'quay_ve_that_bai') {
            'Quay về bản cũ chưa đạt (quay_ve_that_bai). Giữ khóa truy cập phần mềm.'
        } elseif ($marker.Phase -eq 'da_doi_du_lieu' -and ($AtStartup -or -not $extended -or $marker.Status -ne 'da_quay_ve')) {
            'Cập nhật bị ngắt sau khi đã thay dữ liệu.'
        }
        if ($blocked) {
            $blocked += ' KHÔNG dùng phần mềm. Báo người hỗ trợ.'
            # Nếu tiến trình bị ngắt ngay trong Start-Service, SCM có thể còn Manual.
            try {
                $config = Get-CimInstance Win32_Service -Filter ("Name='" + $Name + "'") -ErrorAction Stop
                if ($config -and $config.StartMode -eq 'Manual') { Set-RecoveryServiceStartMode $config 'Disabled' }
            } catch { $blocked += ' Chưa khóa lại được chế độ khởi động dịch vụ: ' + $_.Exception.Message }
            throw $blocked
        }
    }

    $step = 'Trả và kiểm lại lịch sao lưu'
    try {
        if ($VerifiedRollback) {
            # HTTPS bản cũ đã đạt. Đăng ký từ XML gốc để trả cả cách Task Scheduler
            # biểu diễn các tùy chọn mặc định, rồi kiểm lại chữ ký đầy đủ.
            Restore-MinhDucBackupTasks -Snapshot $BackupTaskSnapshot -RequireBoth
        } elseif ($extended) {
            $tasks = @(Get-MinhDucBackupTaskSnapshot)
            foreach ($saved in $marker.TaskEnabled.PSObject.Properties) {
                if ($saved.Name -cnotin @($tasks | ForEach-Object { $_.Name })) {
                    throw ('Thiếu lịch sao lưu cần trả lại: ' + $saved.Name)
                }
            }
            foreach ($task in $tasks) {
                $saved = $marker.TaskEnabled.PSObject.Properties[$task.Name]
                # Lịch chạy bù được tạo mới khi nâng cấp từ bản chỉ có lịch hằng ngày.
                $enabled = -not $saved -or $saved.Value
                if ($enabled) { Enable-ScheduledTask -TaskName $task.Name -TaskPath '\' -ErrorAction Stop | Out-Null }
                else { Disable-ScheduledTask -TaskName $task.Name -TaskPath '\' -ErrorAction Stop | Out-Null }
                $actual = Get-MinhDucScheduledTask -Name $task.Name
                if (-not $actual -or [bool]$actual.Settings.Enabled -ne $enabled) {
                    throw ('Trạng thái lịch sao lưu chưa được trả lại: ' + $task.Name)
                }
            }
        }
        if ($VerifiedRollback -and $extended) {
            $step = 'Ghi xác nhận đã quay về bản cũ'
            $marker.Status = 'da_quay_ve'
            Write-MinhDucServiceStartModeMarker $Paths.ServiceStartModePending $marker -Replace
        }
        $step = 'Gỡ và kiểm lại tường lửa bảo trì'
        if ($extended -and $marker.FirewallRule) { Remove-MinhDucMaintenanceFirewall $marker.FirewallRule }
        $step = 'Trả và kiểm lại chế độ khởi động dịch vụ'
        Restore-MinhDucServiceStartup $Name $marker
        $step = 'Xóa tệp đánh dấu bảo trì'
        Remove-Item -LiteralPath $Paths.ServiceStartModePending -Force -ErrorAction Stop
        if (Get-MinhDucServiceStartModeMarkerFile $Paths.ServiceStartModePending) { throw 'Chưa xóa được tệp đánh dấu bảo trì.' }
    } catch {
        throw ($step + ' chưa đạt: ' + $_.Exception.Message)
    }

    $detail = "Đã trả chế độ khởi động dịch vụ $Name về $($marker.StartMode) (DelayedAutoStart=$($marker.DelayedAutoStart)). $($marker.Script) ghi dấu lúc $($marker.CreatedAt)."
    if ($extended) { $detail += ' Đã kiểm lại trạng thái bảo trì.' }
    $now = [datetime]::UtcNow.AddHours(7).ToString("dd/MM/yyyy HH:mm:ss 'UTC+7'", [Globalization.CultureInfo]::InvariantCulture)
    try {
        Add-Content -LiteralPath (Join-Path $Paths.Journal 'service-startmode.log') -Value "[$now] $ScriptName - $detail" -Encoding UTF8 -ErrorAction Stop
    } catch { Write-Warning ('Đã trả cấu hình bảo trì. Chưa ghi được nhật ký: ' + $_.Exception.Message) -WarningAction Continue }
    if ($ScriptName -eq 'CapNhat.ps1') { Write-Dat ('[S2F2-VENV] ' + $detail) }
    else { Write-Dat $detail }
    return $detail
}

function Resume-MinhDucServiceStartMode {
    param([Parameter(Mandatory=$true)]$Paths, [Parameter(Mandatory=$true)][string]$ScriptName,
          [switch]$AtStartup, [hashtable]$RecoveryInfo, [scriptblock]$AfterRestore)
    $path = $Paths.ServiceStartModePending
    if (-not (Get-MinhDucServiceStartModeMarkerFile $path)) { return }
    $lock = Open-MinhDucServiceStartModeLock $Paths.MaintenanceLockBase
    try {
        $detail = Restore-MinhDucServiceStartMode (Get-MinhDucNames).Service $Paths $ScriptName -AtStartup:$AtStartup -RecoveryInfo $RecoveryInfo
        if ($detail -and $AfterRestore) { & $AfterRestore | Out-Null }
        return $detail
    } finally { $lock.Dispose() }
}

function Invoke-WithMinhDucServiceStartupDisabled {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)]$Paths,
        [Parameter(Mandatory=$true)][ValidateSet('CapNhat.ps1','GiaHanChungChi.ps1')][string]$ScriptName,
        [Parameter(Mandatory=$true)][scriptblock]$Action,
        [switch]$AllowAlreadyDisabled
    )
    $path = $Paths.ServiceStartModePending
    $lock = Open-MinhDucServiceStartModeLock $Paths.MaintenanceLockBase
    try {
        if (Get-MinhDucServiceStartModeMarkerFile $path) {
            throw 'Còn tệp đánh dấu chế độ khởi động. Báo người hỗ trợ hoặc chạy KIEM_TRA.bat trước khi bảo trì lại.'
        }
        try {
            $startupOnly = @{ Name = $Name; Paths = $Paths; ScriptName = $ScriptName; TaskEnabled = $null }
            $config = Disable-MinhDucServiceStartup -Window $startupOnly -AllowAlreadyDisabled:$AllowAlreadyDisabled
            & $Action $config
        } finally {
            Restore-MinhDucServiceStartMode $Name $Paths $ScriptName | Out-Null
        }
    } finally { $lock.Dispose() }
}

function Disable-MinhDucServiceStartup {
    param([Parameter(Mandatory=$true)]$Window, [switch]$AllowAlreadyDisabled)
    $Name = $Window.Name
    $path = $Window.Paths.ServiceStartModePending
    if (Get-MinhDucServiceStartModeMarkerFile $path) {
        throw 'Còn tệp đánh dấu chế độ khởi động. Báo người hỗ trợ hoặc chạy KIEM_TRA.bat trước khi bảo trì lại.'
    }
    $config = Get-CimInstance Win32_Service -Filter ("Name='" + $Name + "'") -ErrorAction Stop
    if ($AllowAlreadyDisabled -and $config -and $config.StartMode -eq 'Disabled') { return $config }
    $startupModes = @{ Auto = 'Automatic'; Manual = 'Manual' }
    if (-not $config -or -not $startupModes.ContainsKey([string]$config.StartMode)) {
        throw 'Dịch vụ web đang bị vô hiệu hóa hoặc không xác định được chế độ khởi động.'
    }
    $marker = [ordered]@{
        Service = $Name
        StartMode = $startupModes[$config.StartMode]
        DelayedAutoStart = Get-MinhDucDelayedAutoStart $Name
        CreatedAt = [datetime]::UtcNow.AddHours(7).ToString("dd/MM/yyyy HH:mm:ss 'UTC+7'", [Globalization.CultureInfo]::InvariantCulture)
        Script = $Window.ScriptName
        Phase = 'chua_doi_du_lieu'
    }
    if ($null -ne $Window.TaskEnabled) {
        $marker.Status = 'dang_bao_tri'
        $marker.TaskEnabled = $Window.TaskEnabled
        $marker.FirewallRule = if ($Window.GuardHttps) { (Get-MinhDucNames).FirewallMaintenance } else { '' }
    }
    Write-MinhDucServiceStartModeMarker $path $marker
    # Chặn SCM chạy lại WinSW trong khi đang chờ tiến trình cũ thoát.
    Set-RecoveryServiceStartMode $config 'Disabled'
    return $config
}

function Enter-MinhDucMaintenanceWindow {
    param([string]$Name, $Paths, [ValidateSet('CapNhat.ps1','GiaHanChungChi.ps1')][string]$ScriptName, [switch]$GuardHttps,
          [IO.FileStream]$Lock)
    # Gia hạn giữ khóa qua cả lần ghi kết quả sau khi trả cấu hình.
    $ownsLock = -not $Lock
    if ($ownsLock) { $Lock = Open-MinhDucServiceStartModeLock $Paths.MaintenanceLockBase }
    try {
        Restore-MinhDucServiceStartMode $Name $Paths $ScriptName | Out-Null
        return @{
            Lock = $Lock; OwnsLock = $ownsLock; Name = $Name; Paths = $Paths; ScriptName = $ScriptName
            ServiceConfig = $null; RestoreStartup = $false; TasksSuspended = $false; TaskEnabled = @{}
            GuardHttps = [bool]$GuardHttps; FirewallReady = $false; SuspendedBackupTasks = $null
        }
    } catch {
        if ($ownsLock) { $Lock.Dispose() }
        throw
    }
}

function Suspend-MinhDucMaintenanceWindow {
    param([Parameter(Mandatory=$true)]$Window, [switch]$AllowAlreadyDisabled)
    if (-not $Window.TasksSuspended) {
        foreach ($task in @(Get-MinhDucBackupTaskSnapshot)) {
            if (-not $Window.TaskEnabled.ContainsKey($task.Name)) {
                $Window.TaskEnabled[$task.Name] = $task.Enabled
            }
        }
    }
    if (-not $Window.ServiceConfig) {
        $Window.RestoreStartup = $true
        $Window.ServiceConfig = Disable-MinhDucServiceStartup -Window $Window -AllowAlreadyDisabled:$AllowAlreadyDisabled
    } elseif ($Window.GuardHttps) {
        $config = Get-CimInstance Win32_Service -Filter ("Name='" + $Window.Name + "'") -ErrorAction Stop
        if ($config.StartMode -ne 'Disabled') { Set-RecoveryServiceStartMode $config 'Disabled' }
    }
    if ($Window.GuardHttps -and -not $Window.FirewallReady) {
        Enable-MinhDucMaintenanceFirewall -Paths $Window.Paths
        $Window.FirewallReady = $true
    }
    $Window.TasksSuspended = $true
    Suspend-MinhDucBackupTasks -WaitForIdle
    if ($Window.GuardHttps -and $null -eq $Window.SuspendedBackupTasks) {
        # Lưu XML Disabled do Task Scheduler xuất, kể cả thứ tự và tùy chọn mặc định.
        $snapshot = @(Get-MinhDucBackupTaskSnapshot)
        if ($snapshot.Count -ne $Window.TaskEnabled.Count -or
            @($snapshot | Where-Object { $_.Enabled -or -not $Window.TaskEnabled.ContainsKey($_.Name) }).Count) {
            throw 'Lịch sao lưu tạm dừng không khớp danh sách ban đầu.'
        }
        $Window.SuspendedBackupTasks = $snapshot
    }
}

function Start-MinhDucMaintenanceService {
    param([Parameter(Mandatory=$true)]$Window)
    if (-not $Window.FirewallReady) { throw 'Chưa xác nhận tường lửa chặn máy trạm trong bảo trì.' }
    Assert-MinhDucMaintenanceFirewall -Paths $Window.Paths
    $config = Get-CimInstance Win32_Service -Filter ("Name='" + $Window.Name + "'") -ErrorAction Stop
    if ($config.StartMode -ne 'Manual') { Set-RecoveryServiceStartMode $config 'Manual' }
    try {
        Start-Service -Name $Window.Name -ErrorAction Stop
    } finally {
        # Chỉ cho SCM khởi động thủ công trong lệnh Start-Service. Trong lúc
        # kiểm HTTPS, dịch vụ đang chạy nhưng vẫn phải khóa khởi động lại.
        Set-RecoveryServiceStartMode $config 'Disabled'
    }
}

function Set-MinhDucUpdatePhase {
    param(
        [Parameter(Mandatory=$true)]$Window,
        [Parameter(Mandatory=$true)][ValidateSet('da_doi_du_lieu', 'da_chot')][string]$Phase
    )
    $marker = Read-MinhDucServiceStartModeMarker $Window.Name $Window.Paths
    if (-not $marker -or -not $Window.FirewallReady -or $marker.Script -ne 'CapNhat.ps1' -or
        $marker.Status -ne 'dang_bao_tri' -or -not $marker.FirewallRule) {
        throw 'Thiếu dấu hoặc tường lửa trước khi ghi giai đoạn cập nhật.'
    }
    $previous = if ($Phase -eq 'da_chot') { 'da_doi_du_lieu' } else { 'chua_doi_du_lieu' }
    if ($marker.Phase -ne $previous) { throw ('Không thể chuyển giai đoạn cập nhật từ ' + $marker.Phase + ' sang ' + $Phase) }
    $marker.Phase = $Phase
    Write-MinhDucServiceStartModeMarker $Window.Paths.ServiceStartModePending $marker -Replace
}

function Set-MinhDucRollbackPending {
    param([Parameter(Mandatory=$true)]$Window)
    $marker = Read-MinhDucServiceStartModeMarker $Window.Name $Window.Paths
    if (-not $marker -or -not $Window.FirewallReady) { throw 'Thiếu dấu hoặc tường lửa trước khi quay về bản cũ.' }
    if ($marker.Status -ne 'quay_ve_that_bai') {
        $marker.Status = 'quay_ve_that_bai'
        Write-MinhDucServiceStartModeMarker $Window.Paths.ServiceStartModePending $marker -Replace
    }
}

function Hold-MinhDucFailedMaintenanceWindow {
    param([Parameter(Mandatory=$true)]$Window)
    try {
        Set-MinhDucRollbackPending -Window $Window
    } finally {
        # Giữ khóa SCM và lịch kể cả khi ghi dấu lại gặp lỗi. Chỉ dừng dịch vụ của phần mềm.
        try {
            $Window.FirewallReady = $false
            Suspend-MinhDucMaintenanceWindow -Window $Window -AllowAlreadyDisabled
        } finally {
            $service = Get-Service -Name $Window.Name -ErrorAction Stop
            if ($service.Status -ne 'Stopped') {
                Stop-Service -InputObject $service -NoWait -ErrorAction Stop
                $service.WaitForStatus('Stopped', (Get-MinhDucServiceStopWait))
            }
        }
    }
}

function Resume-MinhDucMaintenanceWindow {
    param([Parameter(Mandatory=$true)]$Window, [switch]$VerifiedRollback, [object[]]$BackupTaskSnapshot)
    if ($Window.RestoreStartup) {
        Restore-MinhDucServiceStartMode $Window.Name $Window.Paths $Window.ScriptName -VerifiedRollback:$VerifiedRollback -BackupTaskSnapshot $BackupTaskSnapshot | Out-Null
        $Window.RestoreStartup = $false
        $Window.ServiceConfig = $null
        $Window.TasksSuspended = $false
        $Window.TaskEnabled.Clear()
        $Window.SuspendedBackupTasks = $null
    }
}

function Exit-MinhDucMaintenanceWindow {
    param([Parameter(Mandatory=$true)]$Window, [switch]$KeepPending)
    try { if (-not $KeepPending) { Resume-MinhDucMaintenanceWindow -Window $Window } }
    finally { if ($Window.OwnsLock) { $Window.Lock.Dispose() } }
}

function Stop-MinhDucService {
    param([Parameter(Mandatory=$true)]$Window)
    Suspend-MinhDucMaintenanceWindow -Window $Window
    $service = Get-Service -Name $Window.Name -ErrorAction Stop
    $service.Refresh()
    if ($service.Status -notin @('Stopped', 'StopPending')) {
        try {
            Stop-Service -InputObject $service -NoWait -ErrorAction Stop
        } catch {
            $service.Refresh()
            if ($service.Status -notin @('Stopped', 'StopPending')) { throw }
        }
    }
    $service.WaitForStatus('Stopped', (Get-MinhDucServiceStopWait))
    Wait-MinhDucVenvPythonExit -Venv $Window.Paths.Venv -ClinicEnv $Window.Paths.ClinicEnv
    $service.Refresh()
    if ($service.Status -ne 'Stopped') { throw 'Dịch vụ đã chạy lại trong lúc chờ Python thoát.' }
}

function Restart-MinhDucService {
    param([Parameter(Mandatory=$true)]$Window)
    Stop-MinhDucService -Window $Window
    $service = Get-Service -Name $Window.Name -ErrorAction Stop
    Resume-MinhDucMaintenanceWindow -Window $Window
    try {
        # Start-Service báo cảnh báo khi còn StartPending. Chuyển sang chờ có thời hạn.
        Start-Service -InputObject $service -WarningAction Stop -ErrorAction Stop
    } catch [Management.Automation.ActionPreferenceStopException] {
        $service.Refresh()
        if ($service.Status -notin @('StartPending', 'Running')) { throw }
    }
    $service.WaitForStatus('Running', (New-TimeSpan -Seconds 30))
}

function Get-MinhDucMaintenanceFirewallScope($Paths) {
    $cfg = Read-EnvFile -Path $Paths.ClinicEnv
    $ip = [Net.IPAddress]::None
    $origin = $null
    if (-not [Net.IPAddress]::TryParse($cfg['CLINIC_BIND_IP'], [ref]$ip) -or
        $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        -not [uri]::TryCreate($cfg['CLINIC_ORIGIN'], [UriKind]::Absolute, [ref]$origin) -or
        $origin.Scheme -ne 'https' -or $origin.Host -ne $ip.ToString() -or $origin.Port -ne $script:Names.Port -or
        [Net.IPAddress]::IsLoopback($ip) -or $ip -eq [Net.IPAddress]::Any -or $ip -eq [Net.IPAddress]::Broadcast) {
        throw 'Không xác định được địa chỉ IPv4 và cổng HTTPS của Minh Đức để khóa máy trạm.'
    }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $ip.ToString() -ErrorAction Stop)) {
        throw 'Địa chỉ HTTPS chưa được gán trên máy chủ.'
    }
    # Uvicorn chỉ lắng nghe trên IPv4 đã cấu hình. Kết nối trực tiếp từ máy chủ
    # đến chính địa chỉ đó có cùng IP nguồn, nằm ngoài hai khoảng chặn.
    $bytes = $ip.GetAddressBytes()
    [Array]::Reverse($bytes)
    $address = [BitConverter]::ToUInt32($bytes, 0)
    $remote = foreach ($limit in @(($address - 1), ($address + 1))) {
        $bytes = [BitConverter]::GetBytes([uint32]$limit)
        [Array]::Reverse($bytes)
        ([Net.IPAddress]::new($bytes)).ToString()
    }
    return @{ IP = $ip.ToString(); Remote = @('0.0.0.0-' + $remote[0]; $remote[1] + '-255.255.255.255') }
}

function Get-MinhDucMaintenanceFirewall([string]$Name, [string]$PolicyStore) {
    try { Get-NetFirewallRule -Name $Name -PolicyStore $PolicyStore -ErrorAction Stop }
    catch { if ($_.CategoryInfo.Category -ne 'ObjectNotFound') { throw } }
}

function Assert-MinhDucMaintenanceFirewall {
    param([Parameter(Mandatory=$true)]$Paths)
    $scope = Get-MinhDucMaintenanceFirewallScope $Paths
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)
    if ($profiles.Count -ne 3 -or @($profiles | Where-Object { $_.Enabled -ne 'True' -or $_.AllowLocalFirewallRules -eq 'False' }).Count) {
        throw 'Windows Firewall phải bật và áp dụng quy tắc cục bộ trên mọi hồ sơ mạng trong lúc bảo trì.'
    }
    $rule = Get-MinhDucMaintenanceFirewall $script:Names.FirewallMaintenance ActiveStore
    if (-not $rule -or $rule.Group -ne $script:Names.FirewallGrp -or $rule.Enabled -ne 'True' -or
        $rule.Direction -ne 'Inbound' -or $rule.Action -ne 'Block' -or $rule.Profile -ne 'Any') {
        throw 'Quy tắc chặn HTTPS bảo trì chưa có hiệu lực.'
    }
    $address = $rule | Get-NetFirewallAddressFilter -ErrorAction Stop
    $port = $rule | Get-NetFirewallPortFilter -ErrorAction Stop
    if (@($address.LocalAddress).Count -ne 1 -or @($address.LocalAddress)[0] -notin @($scope.IP, ($scope.IP + '/32')) -or
        @($address.RemoteAddress).Count -ne 2 -or (Compare-Object $scope.Remote @($address.RemoteAddress)) -or
        $port.Protocol -notin @('TCP', '6') -or (@($port.LocalPort) -join ',') -ne [string]$script:Names.Port) {
        throw 'Phạm vi quy tắc chặn HTTPS bảo trì không đúng cổng hoặc địa chỉ đã xác nhận.'
    }
}

function Enable-MinhDucMaintenanceFirewall {
    param([Parameter(Mandatory=$true)]$Paths)
    $scope = Get-MinhDucMaintenanceFirewallScope $Paths
    $name = $script:Names.FirewallMaintenance
    if (-not (Get-MinhDucMaintenanceFirewall $name PersistentStore)) {
        New-NetFirewallRule -Name $name -DisplayName $name -Group $script:Names.FirewallGrp -Direction Inbound -Action Block -Profile Any `
            -Protocol TCP -LocalAddress $scope.IP -LocalPort $script:Names.Port -RemoteAddress $scope.Remote -ErrorAction Stop | Out-Null
    }
    Assert-MinhDucMaintenanceFirewall -Paths $Paths
}

function Remove-MinhDucMaintenanceFirewall([string]$Name) {
    if ($Name -cne $script:Names.FirewallMaintenance) { throw 'Tên quy tắc tường lửa bảo trì không hợp lệ.' }
    $rule = Get-MinhDucMaintenanceFirewall $Name PersistentStore
    if ($rule) {
        if ($rule.Group -ne $script:Names.FirewallGrp) { throw 'Quy tắc tường lửa nằm ngoài nhóm MinhDuc.' }
        $rule | Remove-NetFirewallRule -ErrorAction Stop
    }
    if ((Get-MinhDucMaintenanceFirewall $Name PersistentStore) -or (Get-MinhDucMaintenanceFirewall $Name ActiveStore)) {
        throw 'Chưa gỡ được quy tắc tường lửa bảo trì.'
    }
}

function Show-ServiceDiagnostics {
    # In vài dòng cuối nhật ký dịch vụ để người hỗ trợ đọc (nhật ký không ghi mật khẩu).
    param([Parameter(Mandatory = $true)]$Paths)
    $svc = Get-Service -Name $script:Names.Service -ErrorAction SilentlyContinue
    if ($svc) { Write-Thongtin ('Trạng thái dịch vụ: ' + $svc.Status) }
    $files = @(Get-ChildItem -LiteralPath (Join-Path $Paths.Logs 'service') -Filter '*.log' -ErrorAction SilentlyContinue) +
             @(Get-ChildItem -LiteralPath $Paths.Logs -Filter 'server.log' -ErrorAction SilentlyContinue)
    foreach ($f in $files) {
        Write-Thongtin ('--- ' + $f.Name + ' (20 dòng cuối) ---')
        Get-Content -LiteralPath $f.FullName -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Thongtin ('    ' + $_) }
    }
    Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Service Control Manager'; StartTime = (Get-Date).AddMinutes(-15) } -MaxEvents 5 -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -match $script:Names.Service } | ForEach-Object { Write-Thongtin ('    [SCM] ' + $_.Message) }
}

function Wait-Https {
    param([Parameter(Mandatory = $true)][string]$Origin, [int]$Seconds = 90, [switch]$LocalOnly)
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            if ($LocalOnly) {
                $request = [Net.HttpWebRequest]::Create($Origin + '/api/health')
                $request.Proxy = $null
                $request.AllowAutoRedirect = $false
                $request.Timeout = 10000
                $request.ReadWriteTimeout = 10000
                $response = $request.GetResponse()
                try {
                    $reader = [IO.StreamReader]::new($response.GetResponseStream())
                    try { if ($response.StatusCode -eq 200 -and $reader.ReadToEnd() -match 'lan-pilot') { return $true } }
                    finally { $reader.Dispose() }
                } finally { $response.Dispose() }
            } else {
                $r = Invoke-WebRequest -Uri ($Origin + '/api/health') -UseBasicParsing -TimeoutSec 10
                if ($r.StatusCode -eq 200 -and $r.Content -match 'lan-pilot') { return $true }
            }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}

# ---------------------------------------------------------------------------
# Thu thập dữ kiện Windows cho báo cáo sức khỏe (không có mật khẩu/bệnh nhân)
# ---------------------------------------------------------------------------
function Get-WindowsFacts {
    param([Parameter(Mandatory = $true)]$Paths)
    $facts = [ordered]@{}
    foreach ($pair in @(@('service', $script:Names.Service), @('postgres_service', $script:Names.PgService))) {
        $svc = Get-Service -Name $pair[1] -ErrorAction SilentlyContinue
        if ($svc) { $facts[$pair[0]] = [ordered]@{ status = [string]$svc.Status; start = [string]$svc.StartType } }
        else { $facts[$pair[0]] = [ordered]@{ status = 'Chưa cài'; start = '-' } }
    }
    try { $facts['pg_listeners'] = @(Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction Stop | ForEach-Object { [string]$_.LocalAddress } | Sort-Object -Unique) }
    catch { $facts['pg_listeners'] = @() }
    $fw = [ordered]@{ exists = $false; enabled = $false; scoped = $false; port = [string]$script:Names.Port; remote = '-' }
    $rule = Get-NetFirewallRule -DisplayName $script:Names.FirewallWeb -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($rule) {
        $addr = $rule | Get-NetFirewallAddressFilter
        $port = $rule | Get-NetFirewallPortFilter
        $remote = @($addr.RemoteAddress) -join ','
        $fw = [ordered]@{ exists = $true; enabled = ([string]$rule.Enabled -eq 'True'); port = (@($port.LocalPort) -join ',')
                          remote = $remote; scoped = ($remote -and $remote -notmatch 'Any' -and (@($port.LocalPort) -join ',') -eq [string]$script:Names.Port) }
    }
    $facts['firewall'] = $fw
    $task = Get-ScheduledTask -TaskName $script:Names.BackupTask -ErrorAction SilentlyContinue
    if ($task) {
        $info = $task | Get-ScheduledTaskInfo
        $last = switch ([int64]$info.LastTaskResult) { 0 { 'thành công' } 267011 { 'chưa chạy lần nào' } 267009 { 'đang chạy' } default { 'lỗi mã ' + $info.LastTaskResult } }
        $facts['backup_task'] = [ordered]@{ exists = $true; enabled = ([string]$task.State -ne 'Disabled'); last_result = $last
                                            next_run = $(if ($info.NextRunTime) { $info.NextRunTime.ToString('dd/MM/yyyy HH:mm') } else { '-' }) }
    } else { $facts['backup_task'] = [ordered]@{ exists = $false } }
    $os = Get-CimInstance Win32_OperatingSystem
    $facts['memory'] = [ordered]@{ total_mib = [int]($os.TotalVisibleMemorySize / 1024); available_mib = [int]($os.FreePhysicalMemory / 1024) }
    $cs = Get-CimInstance Win32_ComputerSystem
    $settings = @(Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue)
    $fixed = @($settings | Where-Object { [int]$_.MaximumSize -gt 0 })
    if ($cs.AutomaticManagedPagefile) { $pf = [ordered]@{ auto = $true; detail = 'Windows tự quản lý cho mọi ổ' } }
    elseif ($settings.Count -gt 0 -and $fixed.Count -eq 0) { $pf = [ordered]@{ auto = $true; detail = 'Windows tự quản lý kích thước (System managed size)' } }
    elseif ($settings.Count -eq 0) { $pf = [ordered]@{ auto = $false; detail = 'Không có tệp hoán đổi' } }
    else { $pf = [ordered]@{ auto = $false; detail = ('Cố định, tối đa ' + (($fixed | Measure-Object MaximumSize -Sum).Sum) + ' MB') } }
    $facts['pagefile'] = $pf
    $aclOk = $true; $details = @()
    foreach ($p in @($Paths.ClinicEnv, $Paths.Admin, (Join-Path $Paths.Tls 'server.key'))) {
        $t = Test-SecureAcl -Path $p
        if (-not $t.Ok) { $aclOk = $false }
        $details += $t.Detail
    }
    $facts['env_acl_ok'] = $aclOk
    $facts['env_acl_detail'] = ($details -join '; ')
    $facts['external_declared'] = ((Test-Path -LiteralPath $Paths.ExternalCfg) -and (Read-EnvFile -Path $Paths.ClinicEnv)['CLINIC_EXTERNAL_BACKUP'] -eq '1')
    $facts['windows'] = ([string]$os.Caption + ' (bản ' + $os.BuildNumber + ')')
    $py = if (Test-Path -LiteralPath $Paths.BasePython) { (Invoke-Native -FilePath $Paths.BasePython -Arguments @('--version') -Quiet).Output -join '' } else { 'chưa cài' }
    $facts['python_version'] = ($py -replace 'Python ', '')
    $pgExe = Join-Path $Paths.PgBin 'postgres.exe'
    $pg = if (Test-Path -LiteralPath $pgExe) { (Invoke-Native -FilePath $pgExe -Arguments @('--version') -Quiet).Output -join '' } else { 'chưa cài' }
    $facts['postgres_version'] = ($pg -replace '^.*\) ', '')
    return $facts
}

function Invoke-HealthReport {
    # Bước m và KIEM_TRA: in ĐẠT/KHÔNG ĐẠT từng mục, lưu tệp .txt.
    param([Parameter(Mandatory = $true)]$Paths, [Parameter(Mandatory = $true)][string]$Output,
          [string]$Title = 'KẾT QUẢ KIỂM TRA SỨC KHỎE', $ServiceStartupCheck)
    $factsFile = Join-Path $env:TEMP ('minhduc-facts-' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        (Get-WindowsFacts -Paths $Paths | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $factsFile -Encoding UTF8
        $r = Invoke-Python -Paths $Paths -Quiet -OkCodes @(0, 1) -Arguments @('-m', 'scripts.with_env', $Paths.ClinicEnv, 'scripts.install_health',
            '--windows-facts', $factsFile, '--state', $Paths.BackupState, '--output', $Output, '--title', $Title)
    } finally { Remove-Item -LiteralPath $factsFile -Force -ErrorAction SilentlyContinue }
    if ($ServiceStartupCheck) {
        $lines = if (Test-Path -LiteralPath $Output) { Get-Content -LiteralPath $Output -Encoding UTF8 }
        $inserted = $false
        $report = foreach ($line in $lines) {
            if ($line -match '^Tổng: (\d+)/(\d+) mục ĐẠT\.$') {
                $inserted = $true
                $passed = [int]$Matches[1] + [int]$ServiceStartupCheck.Ok
                $total = [int]$Matches[2] + 1
                $ServiceStartupCheck.Row
                ''
                "Tổng: $passed/$total mục ĐẠT."
                if (-not $ServiceStartupCheck.Ok -and $r.Code -eq 0) { 'Có mục KHÔNG ĐẠT: gửi tệp này cho người hỗ trợ.' }
            } else { $line }
        }
        if ($inserted) { Set-Content -LiteralPath $Output -Value $report -Encoding UTF8 }
        else { Add-Content -LiteralPath $Output -Value $ServiceStartupCheck.Row -Encoding UTF8 }
    }
    if (Test-Path -LiteralPath $Output) {
        foreach ($line in (Get-Content -LiteralPath $Output -Encoding UTF8)) {
            if ($line -match '^\[ĐẠT') { Write-Host $line -ForegroundColor Green }
            elseif ($line -match '^\[KHÔNG') { Write-Host $line -ForegroundColor Red }
            else { Write-Host $line }
        }
    } else {
        Write-Loi 'Không tạo được báo cáo sức khỏe.'
        $r.Output | ForEach-Object { Write-Host ('    ' + $_) }
    }
    return ($r.Code -eq 0 -and (-not $ServiceStartupCheck -or $ServiceStartupCheck.Ok))
}

function Find-Browser {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'))
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    return $null
}

function New-AppShortcut {
    # Biểu tượng trên Desktop chung (mọi tài khoản Windows của máy đều thấy).
    param([Parameter(Mandatory = $true)][string]$Url, [string]$Icon = '')
    $browser = Find-Browser
    if (-not $browser) { Write-Luu 'Chưa thấy Chrome hoặc Edge; cài Google Chrome rồi chạy lại để tạo biểu tượng.'; return $null }
    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $link = Join-Path $desktop $script:Names.Shortcut
    # WScript.Shell chỉ lưu được tên tệp theo bảng mã ANSI: lưu tên không dấu rồi đổi tên.
    $tmp = Join-Path $desktop 'MinhDuc-tam.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($tmp)
    $sc.TargetPath = $browser
    $sc.Arguments = '--app=' + $Url
    $sc.Description = 'Phần mềm quản lý Phòng khám đa khoa Minh Đức'
    if ($Icon -and (Test-Path -LiteralPath $Icon)) { $sc.IconLocation = $Icon }
    $sc.Save()
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
    Move-Item -LiteralPath $tmp -Destination $link -Force
    if ($browser -notmatch 'chrome.exe') { Write-Luu 'Chưa có Chrome; biểu tượng đang mở bằng Microsoft Edge.' }
    return $link
}

function Get-MinhDucScheduledTask {
    param([string]$Name)
    try { return Get-ScheduledTask -TaskName $Name -TaskPath '\' -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return $null }
        throw
    }
}

function Set-MinhDucStartupRecoveryTask {
    param([Parameter(Mandatory = $true)]$Paths)
    $scriptPath = Join-Path $Paths.Code 'deploy\windows\TuGoBaoTri.ps1'
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { throw ('Thiếu tệp tự gỡ bảo trì: ' + $scriptPath) }
    $engine = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ThuMucMa "{1}" -ThuMucDuLieu "{2}"' -f $scriptPath, $Paths.Code, $Paths.Data
    $action = New-ScheduledTaskAction -Execute $engine -Argument $arguments -WorkingDirectory $Paths.Code
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT1M'
    $principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $script:Names.StartupRecoveryTask -TaskPath '\' -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Description 'Tự gỡ bảo trì khi bật máy, nếu trạng thái cho phép.' -Force -ErrorAction Stop | Out-Null
}

# Snapshot only the two backup tasks managed by this installer. No other task is touched.
function Get-MinhDucBackupTaskSnapshot {
    foreach ($name in @($script:Names.BackupTask, ($script:Names.BackupTask + ' - Chay bu'))) {
        $task = Get-MinhDucScheduledTask -Name $name
        if ($task) {
            [pscustomobject]@{
                Name = $name
                Enabled = [bool]$task.Settings.Enabled
                Xml = Export-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
            }
        }
    }
}

function Get-MinhDucBackupTaskSignature([string]$Xml) {
    [xml]$document = $Xml
    return ($document.Task.Actions.OuterXml + $document.Task.Triggers.OuterXml + $document.Task.Settings.OuterXml + $document.Task.Principals.OuterXml)
}

function ConvertTo-MinhDucDisabledTaskXml([string]$Xml) {
    [xml]$document = $Xml
    $settings = $document.Task.Settings
    $enabled = $settings.SelectSingleNode("*[local-name()='Enabled']")
    if ($enabled -and $enabled.InnerText -in @('false', '0')) { return $Xml }
    if (-not $enabled) {
        $enabled = $document.CreateElement('Enabled', $settings.NamespaceURI)
        [void]$settings.AppendChild($enabled)
    }
    $enabled.InnerText = 'false'
    return $document.OuterXml
}

function Restore-MinhDucBackupTasks {
    param([AllowEmptyCollection()][object[]]$Snapshot = @(), [switch]$Disabled, [switch]$RequireBoth)
    if ($RequireBoth -and ($Snapshot.Count -notin @(1,2) -or @($Snapshot | Where-Object { $_.Name -eq $script:Names.BackupTask }).Count -ne 1)) {
        throw 'Snapshot lịch ban đầu không hợp lệ trước khi đăng ký lại.'
    }
    if ($Disabled) {
        $Snapshot = @(foreach ($old in $Snapshot) {
            [pscustomobject]@{ Name = $old.Name; Xml = (ConvertTo-MinhDucDisabledTaskXml $old.Xml) }
        })
    }
    try {
        foreach ($old in $Snapshot) {
            Register-ScheduledTask -TaskName $old.Name -TaskPath '\' -Xml $old.Xml -Force -ErrorAction Stop | Out-Null
        }
    } catch {
        $originalFailure = $_
        foreach ($old in $Snapshot) {
            try {
                if (-not $Disabled -and (Get-MinhDucScheduledTask -Name $old.Name)) {
                    $enabled = ([xml]$old.Xml).Task.Settings.SelectSingleNode("*[local-name()='Enabled']")
                    if ($enabled -and $enabled.InnerText -in @('false', '0')) {
                        Disable-ScheduledTask -TaskName $old.Name -TaskPath '\' -ErrorAction Stop | Out-Null
                    } else {
                        Enable-ScheduledTask -TaskName $old.Name -TaskPath '\' -ErrorAction Stop | Out-Null
                    }
                }
            } catch {
                Write-Loi ('Không trả được trạng thái lịch sao lưu ' + $old.Name + ': ' + $_.Exception.Message)
            }
        }
        throw $originalFailure
    }
    # Never remove a working task before every saved task has registered.
    foreach ($current in @(Get-MinhDucBackupTaskSnapshot)) {
        if (@($Snapshot | ForEach-Object { $_.Name }) -notcontains $current.Name) {
            Unregister-ScheduledTask -TaskName $current.Name -TaskPath '\' -Confirm:$false -ErrorAction Stop
        }
    }
    Assert-MinhDucBackupTaskSnapshot -Snapshot $Snapshot -Disabled:$Disabled -RequireBoth:$RequireBoth
}

function Assert-MinhDucBackupTaskSnapshot {
    param([AllowEmptyCollection()][object[]]$Snapshot = @(), [switch]$RequireBoth, [switch]$Disabled)
    $restored = @(Get-MinhDucBackupTaskSnapshot)
    # Historical switch name: require the complete ORIGINAL layout, including legacy daily-only.
    if ($RequireBoth -and ($Snapshot.Count -notin @(1,2) -or @($Snapshot | Where-Object { $_.Name -eq $script:Names.BackupTask }).Count -ne 1)) { throw 'Snapshot lịch ban đầu không hợp lệ trước khi xác nhận quay về.' }
    if ($restored.Count -ne $Snapshot.Count) { throw 'Khôi phục lịch sao lưu thiếu tác vụ.' }
    foreach ($old in $Snapshot) {
        $task = Get-MinhDucScheduledTask -Name $old.Name
        if ($Disabled) {
            if (-not $task -or [string]$task.State -ne 'Disabled' -or $task.Settings.Enabled) { throw ('Lịch sao lưu chưa Disabled: ' + $old.Name) }
        } else {
            $enabled = ([xml]$old.Xml).Task.Settings.SelectSingleNode("*[local-name()='Enabled']")
            if ($enabled -and $enabled.InnerText -in @('false', '0')) {
                if (-not $task -or [string]$task.State -ne 'Disabled' -or $task.Settings.Enabled) {
                    throw ('Lịch sao lưu chưa Disabled: ' + $old.Name)
                }
            } elseif (-not $task -or [string]$task.State -notin @('Ready', 'Running', 'Queued') -or -not $task.Settings.Enabled) {
                throw ('Lịch sao lưu chưa Ready/Running/Queued và Enabled: ' + $old.Name)
            }
        }
        $actual = @($restored | Where-Object { $_.Name -eq $old.Name })
        if ($actual.Count -ne 1 -or (Get-MinhDucBackupTaskSignature $actual[0].Xml) -ne (Get-MinhDucBackupTaskSignature $old.Xml)) {
            throw 'Khôi phục lịch sao lưu không khớp action/trigger/cài đặt cũ.'
        }
    }
}

function Test-MinhDucBackupTasks {
    param([Parameter(Mandatory = $true)]$Paths)
    $tasks = @(Get-MinhDucBackupTaskSnapshot)
    if ($tasks.Count -ne 2) { throw 'Phải có đúng hai tác vụ sao lưu mới.' }
    foreach ($mode in @('daily','catchup')) {
        $name = $script:Names.BackupTask
        if ($mode -eq 'catchup') { $name += ' - Chay bu' }
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
        $actions = @($task.Actions); $triggers = @($task.Triggers)
        $expected = Get-MinhDucBackupJobArguments -Paths $Paths -Mode $mode
        if ($actions.Count -ne 1 -or $actions[0].Execute -ne $Paths.VenvPython -or $actions[0].WorkingDirectory -ne $Paths.Code -or $actions[0].Arguments -ne $expected) {
            throw ('Action sao lưu không đúng: ' + $name)
        }
        if ($triggers.Count -ne 1 -or $task.Settings.StartWhenAvailable) { throw ('Trigger sao lưu không đúng: ' + $name) }
        if ($mode -eq 'daily') {
            if ($triggers[0].CimClass.CimClassName -ne 'MSFT_TaskDailyTrigger' -or $triggers[0].DaysInterval -ne 1 -or ([datetime]$triggers[0].StartBoundary).TimeOfDay -ne [timespan]'20:00') {
                throw 'Lịch hằng ngày phải chạy đúng 20:00.'
            }
        } elseif ($triggers[0].CimClass.CimClassName -ne 'MSFT_TaskBootTrigger' -or $triggers[0].Delay -ne 'PT2M') {
            throw 'Chạy bù phải là trigger khởi động, trễ hai phút.'
        }
    }
    return $true
}

function Get-MinhDucBackupJobArguments {
    param([Parameter(Mandatory = $true)]$Paths, [ValidateSet('daily','catchup')][string]$Mode)
    $alert = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) $script:Names.AlertFile
    return (@('-m', 'scripts.with_env', ('"' + $Paths.ClinicEnv + '"'), 'scripts.backup_job', ('--' + $Mode), '--key', ('"' + $Paths.BackupKey + '"'),
        '--directory', ('"' + $Paths.Backups + '"'), '--state', ('"' + $Paths.BackupState + '"'),
        '--external-config', ('"' + $Paths.ExternalCfg + '"'), '--alert-file', ('"' + $alert + '"')) -join ' ')
}

function Set-MinhDucBackupTasks {
    param([Parameter(Mandatory = $true)]$Paths, [switch]$Disabled)
    $before = @(Get-MinhDucBackupTaskSnapshot)
    try {
        # -Force cập nhật từng tên tại chỗ. Nếu mất điện giữa hai lần đăng ký,
        # lịch đã có từ trước vẫn tồn tại để KIEM_TRA trả trạng thái Enabled.
        $principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Disable:$Disabled
        $dailyAction = New-ScheduledTaskAction -Execute $Paths.VenvPython -Argument (Get-MinhDucBackupJobArguments -Paths $Paths -Mode daily) -WorkingDirectory $Paths.Code
        $daily = New-ScheduledTaskTrigger -Daily -At '20:00'
        Register-ScheduledTask -TaskName $script:Names.BackupTask -TaskPath '\' -Action $dailyAction -Trigger $daily -Principal $principal -Settings $settings -Description 'Sao luu 20:00, luon chay ke ca trong gio lam.' -Force -ErrorAction Stop | Out-Null
        $catchupAction = New-ScheduledTaskAction -Execute $Paths.VenvPython -Argument (Get-MinhDucBackupJobArguments -Paths $Paths -Mode catchup) -WorkingDirectory $Paths.Code
        $catchup = New-ScheduledTaskTrigger -AtStartup
        $catchup.Delay = 'PT2M'
        # CI fault injection replaces this one registration, never the restore path.
        Register-ScheduledTask -TaskName ($script:Names.BackupTask + ' - Chay bu') -TaskPath '\' -Action $catchupAction -Trigger $catchup -Principal $principal -Settings $settings -Description 'Chay bu sau khoi dong, xet gio lam/48 gio.' -Force -ErrorAction Stop | Out-Null
        [void](Test-MinhDucBackupTasks -Paths $Paths)
        if ($Disabled) {
            foreach ($name in @($script:Names.BackupTask, ($script:Names.BackupTask + ' - Chay bu'))) {
                $task = Get-MinhDucScheduledTask -Name $name
                if ([string]$task.State -ne 'Disabled' -or $task.Settings.Enabled) { throw ('Lịch sao lưu chưa Disabled: ' + $name) }
            }
        }
    } catch {
        $failure = $_
        try { Restore-MinhDucBackupTasks -Snapshot $before -Disabled:$Disabled }
        catch { throw ('Đăng ký lịch sao lưu lỗi và KHÔNG khôi phục được lịch cũ: ' + $_.Exception.Message) }
        throw ('Đăng ký lịch sao lưu thất bại; đã khôi phục action/trigger cũ: ' + $failure.Exception.Message)
    }
}

function Suspend-MinhDucBackupTasks {
    param([switch]$WaitForIdle)
    $snapshot = @(Get-MinhDucBackupTaskSnapshot)
    foreach ($task in $snapshot) {
        Disable-ScheduledTask -TaskName $task.Name -TaskPath '\' -ErrorAction Stop | Out-Null
        Write-Thongtin ('Tạm dừng lịch sao lưu: ' + $task.Name)
    }
    if ($WaitForIdle -and $snapshot.Count) {
        # Task.State có thể là Disabled trong khi một phiên chạy trước đó còn hoạt động.
        $scheduler = New-Object -ComObject 'Schedule.Service'
        $scheduler.Connect()
        $folder = $scheduler.GetFolder('\')
        $deadline = (Get-Date).AddSeconds(30)
        foreach ($task in $snapshot) {
            $registered = $folder.GetTask($task.Name)
            if ($registered.Enabled) { throw ('Chưa tạm dừng được lịch sao lưu: ' + $task.Name) }
            while ($registered.GetInstances(0).Count -gt 0) {
                if ((Get-Date) -ge $deadline) { throw ('Lịch sao lưu còn chạy, hãy thử lại sau: ' + $task.Name) }
                Start-Sleep -Milliseconds 250
            }
        }
    }
}

function Get-MinhDucPythonScriptLabel {
    param([string]$CommandLine)
    $parts = @([regex]::Matches($CommandLine, '"[^"\r\n]*"|[^\s]+') | ForEach-Object { $_.Value.Trim('"') })
    if ($parts.Count -gt 2 -and $parts[1] -eq '-m' -and $parts[2] -match '^[a-zA-Z_][a-zA-Z0-9_.]*$') { return ('module=' + $parts[2]) }
    if ($parts.Count -gt 1 -and $parts[1] -match '^[a-zA-Z0-9_ .:/\\-]+\.py$') { return ('script=' + ($parts[1] -split '[/\\]')[-1]) }
    return 'script/module=[đã che]'
}

function Get-MinhDucProcessParents {
    param($Process, [hashtable]$Processes)
    $seen = @{ ([int]$Process.ProcessId) = $true }
    while ($Process.ParentProcessId -and $Processes.ContainsKey([int]$Process.ParentProcessId)) {
        $parent = $Processes[[int]$Process.ParentProcessId]
        if ($seen.ContainsKey([int]$parent.ProcessId) -or -not $Process.CreationDate -or
            -not $parent.CreationDate -or $parent.CreationDate -gt $Process.CreationDate) { break }
        $parent
        $seen[[int]$parent.ProcessId] = $true
        $Process = $parent
    }
}

function Write-MinhDucVenvLockDiagnostics {
    param([string]$Venv, [string]$Context, [object[]]$ObservedProcesses = @())
    $prefix = '[S2F2-VENV] '
    Write-Host ($prefix + $Context)
    $processes = @{}
    $observed = @{}
    foreach ($item in $ObservedProcesses) {
        $processes[[int]$item.ProcessId] = $item
        $observed[[int]$item.ProcessId] = $true
    }
    $loaded = @{}
    $unreadable = 0
    try {
        foreach ($process in Get-Process -ErrorAction Stop) {
            $modules = @()
            try { $modules = @($process.Modules | Where-Object { $_ }) } catch { }
            if (-not $modules.Count) { $unreadable++ }
            $rust = @($modules | Where-Object { $_.ModuleName -eq '_rust.pyd' } | ForEach-Object { $_.FileName })
            if ($rust.Count) {
                $loaded[$process.Id] = $rust
                if (-not $processes.ContainsKey($process.Id)) {
                    $path = $null
                    try { $path = $process.Path } catch { }
                    $processes[$process.Id] = [pscustomobject]@{
                        ProcessId = $process.Id
                        Name = $process.ProcessName
                        ParentProcessId = $null
                        CreationDate = $null
                        ExecutablePath = $path
                        CommandLine = $null
                    }
                }
            }
        }
    } catch { Write-Host ($prefix + 'Không quét hết tiến trình bằng Get-Process.') }
    try {
        foreach ($item in Get-CimInstance Win32_Process -ErrorAction Stop) {
            $processId = [int]$item.ProcessId
            if (-not $observed.ContainsKey($processId)) { $processes[$processId] = $item }
        }
    } catch { Write-Host ($prefix + 'Không đọc hết thông tin từ CIM Win32_Process.') }

    $venvPath = [regex]::Escape($Venv.Replace('/','\').TrimEnd('\'))
    $pathPattern = $venvPath + '(?:-quay-ve-[^\\\s"'']+)?(?=[\\\s"'']|$)'
    $count = 0
    foreach ($processId in ($processes.Keys | Sort-Object)) {
        $item = $processes[$processId]
        $path = [string]$item.ExecutablePath
        $commandLine = [string]$item.CommandLine
        $matchesPath = $path.Replace('/','\') -match $pathPattern -or $commandLine.Replace('/','\') -match $pathPattern
        if (-not ($matchesPath -or $loaded.ContainsKey($processId) -or $observed.ContainsKey($processId))) { continue }

        # Nhật ký máy phòng khám chỉ ghi tên script/module để tránh lộ đối số.
        if (-not $commandLine) {
            $commandLine = '[không đọc được]'
        } elseif ($env:GITHUB_ACTIONS -eq 'true' -and $env:RUNNER_TEMP) {
            $commandLine = $commandLine -replace '(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s"@]+@', '$1[đã che]@'
            $commandLine = $commandLine -replace '(?i)(?<!\S)(-{1,2}|/)[\w-]*(password|passwd|pwd|secret|token|credential|key)[\w-]*(?:[=:]|\s+)(?:"[^"]*"|\S+)', '[đã che tham số bí mật]'
            $commandLine = $commandLine -replace '(?i)(?<!\S)(-c|-command|-encodedcommand)\s+.*', '$1 [đã che mã lệnh]'
        } else {
            $commandLine = Get-MinhDucPythonScriptLabel -CommandLine $commandLine
        }
        $modules = $item.PSObject.Properties['LoadedVenvModules']
        $record = [ordered]@{
            PID = $processId
            ParentPID = $item.ParentProcessId
            Name = $item.Name
            ExecutablePath = $path
            CommandLine = $commandLine
            LoadedRust = @($loaded[$processId] | Where-Object { $_ })
            LoadedVenvModules = @(if ($modules) { $modules.Value })
            Ancestors = @(Get-MinhDucProcessParents -Process $item -Processes $processes | ForEach-Object {
                @{ PID = $_.ProcessId; ParentPID = $_.ParentProcessId; Name = $_.Name; ExecutablePath = $_.ExecutablePath }
            })
            MatchesVenvPath = $matchesPath
            ObservedInWait = $observed.ContainsKey($processId)
        }
        Write-Host ($prefix + ($record | ConvertTo-Json -Compress))
        $count++
    }
    Write-Host ($prefix + ('Ứng viên={0}; tiến trình thiếu danh sách module={1}.' -f $count, $unreadable))
}

function Test-MinhDucVenvPythonPath {
    param([string]$ExecutablePath, [string]$Venv)
    if (-not $ExecutablePath) { return $false }
    $root = [IO.Path]::GetFullPath($Venv).TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
    $path = [IO.Path]::GetFullPath($ExecutablePath)
    return $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -and ([IO.Path]::GetFileName($path) -in @('python.exe','pythonw.exe'))
}

function Test-MinhDucProcessIdentity {
    param($Before, $Now)
    return $Now -and $Before.CreationDate -and $Now.CreationDate -and $Before.ExecutablePath -eq $Now.ExecutablePath -and $Before.CommandLine -eq $Now.CommandLine -and $Before.CreationDate -eq $Now.CreationDate
}

function Get-MinhDucVenvProcessTree {
    param([string]$Venv, [hashtable]$Known = @{}, [string]$ClinicEnv = 'C:\ProgramData\MinhDuc\clinic.env')
    $root = [IO.Path]::GetFullPath($Venv).TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
    $all = @{}
    $venvExecutables = @{}
    $venvPython = @{}
    foreach ($item in Get-CimInstance Win32_Process -ErrorAction Stop) {
        $processId = [int]$item.ProcessId
        $all[$processId] = $item
        if ($item.ExecutablePath -and $item.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
            $venvExecutables[$processId] = $true
        }
        if ((Test-MinhDucVenvPythonPath -ExecutablePath $item.ExecutablePath -Venv $Venv) -or
            ($Known.ContainsKey($processId) -and (Test-MinhDucProcessIdentity $Known[$processId] $item))) {
            $venvPython[$processId] = $true
        }
    }

    # Get-Process supplies loaded image paths, including base Python after its launcher has exited.
    $loaded = Get-MinhDucVenvModules -Root $root
    foreach ($processId in $loaded.Keys) {
        if (-not $all.ContainsKey($processId)) { $all[$processId] = $loaded[$processId] }
    }
    foreach ($item in $all.Values) {
        $processId = [int]$item.ProcessId
        $parents = @(Get-MinhDucProcessParents -Process $item -Processes $all)
        $fromVenv = $venvExecutables.ContainsKey($processId)
        $fromVenvPython = $venvPython.ContainsKey($processId)
        foreach ($parent in $parents) {
            $fromVenv = $fromVenv -or $venvExecutables.ContainsKey([int]$parent.ProcessId)
            $fromVenvPython = $fromVenvPython -or $venvPython.ContainsKey([int]$parent.ProcessId)
        }
        $modules = @()
        if ($loaded.ContainsKey($processId)) { $modules = $loaded[$processId].LoadedVenvModules }
        if ($fromVenvPython) { $Known[$processId] = $item }

        # A module match is evidence of a lock, never authorization to stop its owner.
        $parts = @([regex]::Matches([string]$item.CommandLine, '"[^"\r\n]*"|[^\s]+') | ForEach-Object { $_.Value.Trim('"') })
        $withEnv = $false
        if ($item.Name -in @('python.exe','pythonw.exe')) {
            for ($i=1; $i -lt $parts.Count-2; $i++) {
                if ($parts[$i] -ceq '-c' -or -not $parts[$i].StartsWith('-')) { break }
                if ($parts[$i] -ceq '-m') {
                    $withEnv = $parts[$i+1] -ceq 'scripts.with_env' -and $parts[$i+2].Replace('/','\') -ieq $ClinicEnv.Replace('/','\')
                    break
                }
            }
        }
        if ($fromVenv -or $fromVenvPython -or $withEnv -or $modules.Count) {
            $item | Add-Member -NotePropertyMembers @{
                CanStop = $fromVenvPython -or $withEnv
                TreeDepth = $parents.Count
                LoadedVenvModules = $modules
            } -Force -PassThru
        }
    }
}

function Get-MinhDucVenvModules {
    param([string]$Root)
    $loaded = @{}
    foreach ($process in Microsoft.PowerShell.Management\Get-Process -ErrorAction Stop) {
        try {
            $paths = @($process.Modules | Where-Object { $_ -and $_.FileName -and $_.FileName.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object FileName)
            if ($paths.Count) {
                $image = $null
                try { $image = $process.Path } catch { }
                $loaded[[int]$process.Id] = [pscustomobject]@{
                    ProcessId = $process.Id; Name = $process.ProcessName; ParentProcessId = $null
                    CreationDate = $null; ExecutablePath = $image; CommandLine = $null
                    LoadedVenvModules = $paths
                }
            }
        } catch {
            # A process may have exited or be protected. The file operations still check for locks.
        } finally { $process.Dispose() }
    }
    return $loaded
}

function Wait-MinhDucVenvPythonExit {
    param(
        [Parameter(Mandatory=$true)][string]$Venv, [ValidateRange(0,30)][int]$Seconds=30,
        [switch]$LogLockDiagnostics, [hashtable]$Known = @{}, [string]$ClinicEnv = 'C:\ProgramData\MinhDuc\clinic.env'
    )
    $scan = @{ Venv = $Venv; Known = $Known; ClinicEnv = $ClinicEnv }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        $remaining = @(Get-MinhDucVenvProcessTree @scan)
        if (-not $remaining.Count) {
            Start-Sleep -Seconds 2
            $remaining = @(Get-MinhDucVenvProcessTree @scan)
            if (-not $remaining.Count) { return }
        }
        $outside = @($remaining | Where-Object { -not $_.CanStop })
        if ($outside.Count -or $watch.Elapsed.TotalSeconds -ge $Seconds) { break }
        Start-Sleep -Milliseconds 200
    } while ($true)
    if ($outside.Count) {
        $message = 'Phát hiện tiến trình ngoài phạm vi được phép dừng; PID=' + ($outside.ProcessId -join ',') + '; dừng phục hồi.'
        if ($LogLockDiagnostics) { Write-MinhDucVenvLockDiagnostics -Venv $Venv -Context $message -ObservedProcesses $outside }
        $failure = [InvalidOperationException]::new($message)
        $failure.Data['MinhDucExternalProcess'] = $true
        throw $failure
    }
    $unverified = @()
    $logged = $false
    foreach ($candidate in ($remaining | Sort-Object TreeDepth -Descending)) {
        if ($watch.Elapsed.TotalSeconds -ge 58) { break } # Giữ hai giây cho lần quét xác nhận.
        try { $process = Get-Process -Id $candidate.ProcessId -ErrorAction Stop }
        catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
            if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { continue }
            throw
        }
        # Giữ handle của chính tiến trình đã kiểm để tránh dừng nhầm khi PID được cấp lại.
        if ($process -is [Diagnostics.Process]) {
            try { $null = $process.Handle }
            catch { if ($process.HasExited) { continue }; throw }
        }
        # Refresh CIM identity immediately before stopping: PID alone is never trusted.
        $now = @(Get-CimInstance Win32_Process -Filter ("ProcessId=" + $candidate.ProcessId) -ErrorAction Stop | Where-Object { $_.ProcessId -eq $candidate.ProcessId })
        if (-not $candidate.CreationDate -or ($now.Count -eq 1 -and -not $now[0].CreationDate)) {
            Write-Luu ('Không xác minh được CreationDate; không dừng PID=' + $candidate.ProcessId)
            $unverified += $candidate
            continue
        }
        if ($now.Count -ne 1 -or -not (Test-MinhDucProcessIdentity $candidate $now[0]) -or $process.Path -ne $candidate.ExecutablePath) { continue }
        if ($LogLockDiagnostics -and -not $logged) {
            Write-MinhDucVenvLockDiagnostics -Venv $Venv -Context 'Cây tiến trình Python trước khi dừng.' -ObservedProcesses $remaining
            $logged = $true
        }
        Write-Luu ('Quá hạn chờ Python 30 giây; dừng tiến trình ' + $process.ProcessName + '; PID=' + $process.Id + '; ExecutablePath=' + $now[0].ExecutablePath + '; ' + (Get-MinhDucPythonScriptLabel -CommandLine $now[0].CommandLine))
        try {
            $exitWait = [int][Math]::Min(5000, 58000 - $watch.ElapsedMilliseconds)
            if ($exitWait -le 0) { break }
            if ($process -is [Diagnostics.Process] -and $process.HasExited) { continue }
            Stop-Process -InputObject $process -Force -ErrorAction Stop
            if (-not $process.WaitForExit($exitWait)) { throw 'Python trong môi trường phòng khám chưa thoát; dừng phục hồi.' }
        } catch {
            if ($LogLockDiagnostics) {
                Write-MinhDucVenvLockDiagnostics -Venv $Venv -Context ('Lỗi khi dừng hoặc chờ tiến trình thoát: ' + $_.Exception.Message) -ObservedProcesses @($candidate)
            }
            throw
        }
    }
    $left = @(Get-MinhDucVenvProcessTree @scan)
    if ($unverified.Count -or $left.Count) {
        if ($LogLockDiagnostics) {
            Write-MinhDucVenvLockDiagnostics -Venv $Venv -Context 'Còn tiến trình giữ môi trường Python hoặc chưa xác minh được.' -ObservedProcesses @($unverified + $left)
        }
        $failure = [InvalidOperationException]::new('Còn tiến trình đang giữ môi trường phòng khám; dừng phục hồi.')
        if ($left | Where-Object { -not $_.CanStop }) { $failure.Data['MinhDucExternalProcess'] = $true }
        throw $failure
    }
    Start-Sleep -Seconds 2
    $left = @(Get-MinhDucVenvProcessTree @scan)
    if ($left.Count) {
        if ($LogLockDiagnostics) {
            Write-MinhDucVenvLockDiagnostics -Venv $Venv -Context 'Có tiến trình xuất hiện lại sau lần quét rỗng.' -ObservedProcesses $left
        }
        $failure = [InvalidOperationException]::new('Có tiến trình xuất hiện lại sau lần quét rỗng; dừng phục hồi.')
        if ($left | Where-Object { -not $_.CanStop }) { $failure.Data['MinhDucExternalProcess'] = $true }
        throw $failure
    }
}

function Invoke-MinhDucAccessRetry {
    param([Parameter(Mandatory=$true)][scriptblock]$Action, [scriptblock]$RetryResult)
    for ($attempt=1; $attempt -le 5; $attempt++) {
        try {
            $result = & $Action
            if ($RetryResult -and (& $RetryResult $result) -and $attempt -lt 5) {
                Start-Sleep -Seconds 2
                continue
            }
            return $result
        }
        catch {
            $denied = $_.Exception -is [UnauthorizedAccessException] -or ($_.Exception.HResult -band 65535) -eq 5 -or $_.CategoryInfo.Category -eq 'PermissionDenied'
            if (-not $denied -or $attempt -eq 5) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

# Phục hồi theo giao dịch: luôn giữ một bản nguyên vẹn cho đến khi xóa xong.
function Restore-MinhDucOldVenv {
    param([Parameter(Mandatory=$true)][string]$Venv, [Parameter(Mandatory=$true)][string]$OldVenv, [switch]$LogLockDiagnostics)
    $parent = Split-Path -Parent $Venv
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $pending = New-Object 'System.Collections.Generic.List[string]'
    for ($attempt=1; $attempt -le 10; $attempt++) {
        Write-Luu ('Trả môi trường Python: lần thử ' + $attempt + '/10')
        $tag = [guid]::NewGuid().ToString('N')
        $temp = Join-Path $parent ('.venv-quay-ve-' + $tag)
        $snapshot = Join-Path $parent ('.venv-du-phong-' + $tag)
        $moved = $false; $installed = $false; $saved = $false
        try {
            foreach ($pendingPath in @($pending.ToArray())) {
                Remove-Item -LiteralPath $pendingPath -Recurse -Force -ErrorAction Stop
                [void]$pending.Remove($pendingPath)
            }
            if (-not (Test-Path -LiteralPath $OldVenv -PathType Container)) { throw 'Thiếu môi trường Python cũ.' }
            if (Test-Path -LiteralPath $Venv) {
                # Phát hiện tệp đang mở trước khi chuyển hoặc xóa bất kỳ nội dung nào.
                foreach ($file in Get-ChildItem -LiteralPath $Venv -Recurse -File -Force -ErrorAction Stop) {
                    try { $handle = [IO.File]::Open($file.FullName, 'Open', 'Read', 'None'); $handle.Dispose() }
                    catch { throw [IO.IOException]::new(('Không truy cập được tệp: ' + $file.FullName), $_.Exception) }
                }
                Copy-Item -LiteralPath $Venv -Destination $snapshot -Recurse -Force -ErrorAction Stop
                $saved = $true
                Rename-Item -LiteralPath $Venv -NewName (Split-Path $temp -Leaf) -ErrorAction Stop
                $moved = $true
            }
            Rename-Item -LiteralPath $OldVenv -NewName (Split-Path $Venv -Leaf) -ErrorAction Stop
            $installed = $true
            if ($moved) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction Stop }
            if ($saved) {
                try { Remove-Item -LiteralPath $snapshot -Recurse -Force -ErrorAction Stop }
                catch { Write-Luu ('Không xóa được bản dự phòng môi trường tại ' + $snapshot + ': ' + $_.Exception.Message) }
            }
            return
        } catch {
            $failure = $_
            $exception = $failure.Exception
            $retryable = $false
            while ($exception) {
                if ($exception -is [IO.IOException] -or $exception -is [UnauthorizedAccessException]) { $retryable = $true; break }
                $exception = $exception.InnerException
            }
            if ($LogLockDiagnostics -and $retryable) {
                try {
                    Write-MinhDucVenvLockDiagnostics -Venv $Venv -Context ('Lần trả Python {0}/10; thư mục tạm={1}; đích={2}; lỗi={3}' -f $attempt, $temp, $failure.TargetObject, $failure.Exception.Message)
                } catch { Write-Host '[S2F2-VENV] Không ghi hết thông tin chẩn đoán khóa môi trường Python.' }
            }
            # Nếu xóa dở, dùng bản sao nguyên vẹn để trả lại đúng .venv ban đầu.
            try {
                if ($installed) { Rename-Item -LiteralPath $Venv -NewName (Split-Path $OldVenv -Leaf) -ErrorAction Stop }
                if ($moved) {
                    if (-not $saved) { throw 'Thiếu bản dự phòng môi trường.' }
                    Rename-Item -LiteralPath $snapshot -NewName (Split-Path $Venv -Leaf) -ErrorAction Stop
                    $saved = $false
                }
                if (Test-Path -LiteralPath $temp) {
                    try { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction Stop }
                    catch {
                        $pending.Add($temp)
                        Write-Luu ('Giữ thư mục tạm còn khóa: ' + $temp + ': ' + $_.Exception.Message)
                    }
                }
                if (Test-Path -LiteralPath $snapshot) { Remove-Item -LiteralPath $snapshot -Recurse -Force -ErrorAction Stop }
            } catch { throw ('Không trả lại được môi trường ban đầu; giữ bản dự phòng ' + $snapshot + ' và thư mục tạm ' + $temp + ': ' + $_.Exception.Message) }
            if (-not $retryable -or $attempt -eq 10 -or $watch.Elapsed.TotalSeconds + $attempt -gt 60) {
                throw ('Không thể trả môi trường Python; tệp hoặc đường dẫn bị khóa: ' + $failure.Exception.Message)
            }
            Start-Sleep -Seconds $attempt
        }
    }
}

Export-ModuleMember -Function * -Variable @()
