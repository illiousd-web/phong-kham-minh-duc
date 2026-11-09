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

$script:Names = @{
    Service      = 'MinhDuc'
    ServiceAcct  = 'NT SERVICE\MinhDuc'
    PgService    = 'postgresql-x64-17'
    PgRoot       = 'C:\Program Files\PostgreSQL\17'
    PythonRoot   = 'C:\Program Files\Python312'
    FirewallWeb  = 'MinhDuc - web HTTPS (LAN)'
    FirewallPg   = 'MinhDuc - chan PostgreSQL tu mang'
    FirewallGrp  = 'MinhDuc'
    BackupTask   = 'MinhDuc - Sao luu 20h'
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
        Logs        = Join-Path $Data 'logs'
        Journal     = Join-Path $Data 'nhatky'
        Tls         = Join-Path $Data 'tls'
        ServiceDir  = Join-Path $Data 'service'
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
        Add-Item 'appcontrol' 'STOP' 'Windows đang chạy PowerShell ở chế độ hạn chế (App Control đang chặn script).' @('Nếu là Smart App Control: mở Windows Security > App & browser control > Smart App Control settings > chọn Off.', 'Nếu máy do công ty/CNTT quản lý: nhờ quản trị CNTT thêm quy tắc cho phép thư mục C:\MinhDuc.')
    } elseif ($ci.sac_state -eq 1) {
        Add-Item 'appcontrol' 'STOP' 'Smart App Control đang BẬT: sẽ chặn Python, thư viện và trình chạy dịch vụ chưa có chữ ký số.' @('Mở Windows Security > App & browser control > Smart App Control settings > chọn Off.', 'Giữ nguyên Microsoft Defender và Tường lửa; chỉ tắt riêng Smart App Control.', 'Hỏi người phụ trách trước nếu không chắc: trên một số bản Windows, bật lại Smart App Control cần cài lại Windows.')
    } elseif ($ci.sac_state -eq 2) {
        Add-Item 'appcontrol' 'ASK_SAC' 'Smart App Control đang ở chế độ đánh giá; Windows có thể tự BẬT sau này và chặn phần mềm.' @('Nên tắt Smart App Control trước khi dùng thật (Windows Security > App & browser control > Smart App Control settings).')
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
    param([Parameter(Mandatory = $true)]$Paths, [string[]]$Arguments, [switch]$Quiet, [switch]$Base, [int[]]$OkCodes = @(0))
    $exe = if ($Base) { $Paths.BasePython } else { $Paths.VenvPython }
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    return Invoke-Native -FilePath $exe -Arguments $Arguments -Quiet:$Quiet -OkCodes $OkCodes -WorkingDirectory $Paths.Code
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
  <stoptimeout>30 sec</stoptimeout>
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
    param([Parameter(Mandatory = $true)][string]$Origin, [int]$Seconds = 90)
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri ($Origin + '/api/health') -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -eq 200 -and $r.Content -match 'lan-pilot') { return $true }
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
        $facts['backup_task'] = [ordered]@{ exists = $true; enabled = ([string]$task.State -ne 'Disabled'); last_result = $info.LastTaskResult
                                            next_run = $(if ($info.NextRunTime) { $info.NextRunTime.ToString('dd/MM/yyyy HH:mm') } else { '-' }) }
    } else { $facts['backup_task'] = [ordered]@{ exists = $false } }
    $os = Get-CimInstance Win32_OperatingSystem
    $facts['memory'] = [ordered]@{ total_mib = [int]($os.TotalVisibleMemorySize / 1024); available_mib = [int]($os.FreePhysicalMemory / 1024) }
    $cs = Get-CimInstance Win32_ComputerSystem
    $max = 0
    try { $max = [int](@(Get-CimInstance Win32_PageFileSetting | Measure-Object MaximumSize -Maximum)[0].Maximum) } catch { }
    $facts['pagefile'] = [ordered]@{ auto = [bool]$cs.AutomaticManagedPagefile
                                     detail = $(if ($cs.AutomaticManagedPagefile) { 'Windows tự quản lý' } else { 'Cố định, tối đa ' + $max + ' MB' }) }
    $aclOk = $true; $details = @()
    foreach ($p in @($Paths.ClinicEnv, $Paths.Admin, (Join-Path $Paths.Tls 'server.key'))) {
        $t = Test-SecureAcl -Path $p
        if (-not $t.Ok) { $aclOk = $false }
        $details += $t.Detail
    }
    $facts['env_acl_ok'] = $aclOk
    $facts['env_acl_detail'] = ($details -join '; ')
    $facts['external_declared'] = (Test-Path -LiteralPath $Paths.ExternalCfg)
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
    param([Parameter(Mandatory = $true)]$Paths, [Parameter(Mandatory = $true)][string]$Output, [string]$Title = 'KẾT QUẢ KIỂM TRA SỨC KHỎE')
    $factsFile = Join-Path $env:TEMP ('minhduc-facts-' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        (Get-WindowsFacts -Paths $Paths | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $factsFile -Encoding UTF8
        $r = Invoke-Python -Paths $Paths -Quiet -OkCodes @(0, 1) -Arguments @('-m', 'scripts.with_env', $Paths.ClinicEnv, 'scripts.install_health',
            '--windows-facts', $factsFile, '--state', $Paths.BackupState, '--output', $Output, '--title', $Title)
    } finally { Remove-Item -LiteralPath $factsFile -Force -ErrorAction SilentlyContinue }
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
    return ($r.Code -eq 0)
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

Export-ModuleMember -Function * -Variable @()
