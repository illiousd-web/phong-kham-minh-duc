# Chạy luồng gia hạn thật với SCM và chứng chỉ giả lập, không đụng dịch vụ Windows.
$ErrorActionPreference = 'Stop'
$windows = Join-Path $PSScriptRoot '../deploy/windows'
$tokens = $null
$errors = $null
$module = [Management.Automation.Language.Parser]::ParseFile((Join-Path $windows 'MinhDuc.Install.psm1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Stop-CaiDat', 'Set-RecoveryServiceStartMode', 'Stop-MinhDucService', 'Restart-MinhDucService', 'Wait-MinhDucVenvPythonExit', 'Resume-MinhDucServiceStartMode',
                    'Open-MinhDucServiceStartModeLock', 'Get-MinhDucServiceStartModeMarkerFile', 'Write-MinhDucServiceStartModeMarker', 'Restore-MinhDucServiceStartMode',
                    'Read-MinhDucServiceStartModeMarker', 'Restore-MinhDucServiceStartup', 'Disable-MinhDucServiceStartup', 'Enter-MinhDucMaintenanceWindow', 'Suspend-MinhDucMaintenanceWindow',
                    'Resume-MinhDucMaintenanceWindow', 'Exit-MinhDucMaintenanceWindow')) {
    $definition = $module.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}

function Get-MinhDucNames { @{ Service = 'MinhDuc'; ServiceAcct = 'fake'; BackupTask = 'daily'; FirewallMaintenance = 'test' } }
function Get-MinhDucDelayedAutoStart { param($Name) return $false }
function Get-MinhDucPaths {
    param($Code, $Data)
    @{ Tls = $Data; Venv = $Code; Journal = $Data; MaintenanceLockBase = (Join-Path $Data 'service-startmode-pending.json'); ServiceStartModePending = (Join-Path $Data 'service-startmode-pending.json'); CaKey = (Join-Path $Data 'ca.key'); ClinicEnv = (Join-Path $Data 'clinic.env') }
}
function Get-MinhDucBackupTaskSnapshot {
    foreach ($name in $test.tasks.Keys) { @{ Name = $name; Enabled = $test.tasks[$name] } }
}
function Get-MinhDucScheduledTask { param($Name) @{ Settings = @{ Enabled = $test.tasks[$Name] } } }
function Suspend-MinhDucBackupTasks {
    param([switch]$WaitForIdle)
    foreach ($name in @($test.tasks.Keys)) { $test.tasks[$name] = $false }
}
function Enable-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $test.tasks[$TaskName] = $true }
function Read-EnvFile { param($Path) @{ CLINIC_ORIGIN = 'https://127.0.0.1:8443'; CLINIC_BIND_IP = '127.0.0.1' } }
function ConvertFrom-PythonJson($Result) { $Result.Json }
function Read-CoKhong { param($Text, [switch]$KhongHoi, $MacDinh) return (-not $test.case.Skip) }
function Set-SecureAcl { param($Path, [switch]$Directory, $Readers) }
function Invoke-Native { param($FilePath, $Arguments, [switch]$Quiet) }
function Test-AccountCanRead { param($Path, $Account) return $true }
function Write-Buoc($Text) {}
function Write-Dat($Text) {}
function Write-Luu($Text) {}
function Write-Loi($Text) {}
function Write-Thongtin($Text) {}

$exitWindow = ${function:Exit-MinhDucMaintenanceWindow}
function Exit-MinhDucMaintenanceWindow {
    param($Window)
    $status = (Get-Content -LiteralPath $test.resultFile -Raw -Encoding UTF8 | ConvertFrom-Json).status
    $test.resultBeforeExit = $status -ne 'dang_gia_han'
    & $exitWindow -Window $Window
    if ($test.case.ExitFault) { throw 'Lỗi trả cấu hình giả lập' }
}

function Invoke-Python {
    param($Paths, $Arguments, [switch]$Quiet, $OkCodes)
    switch ($Arguments[2]) {
        'check' { return @{ Ok = $true; Json = @{ ok = $test.case.State -eq 'ok'; code = $test.case.State; reason = 'test' } } }
        'prepare' {
            return @{ Ok = $true; Json = @{ serial = 'new'; not_after = '2027-11-19'; ca_fingerprint = 'cafinger'; files = @() } }
        }
        'verify' { $test.steps.Add('verify') }
        'commit' {
            if ($test.startup -ne 'Disabled' -or $test.tasks.Values -contains $true) { throw 'Thay chứng chỉ ngoài cửa sổ bảo trì.' }
            $test.steps.Add('commit')
            Set-Content -LiteralPath $test.cert -Value 'new'
            if ($test.case.BadCommit) { return @{ Ok = $false; Output = @('Lỗi thay tệp giả lập') } }
        }
        'rollback' {
            if ($test.startup -ne 'Disabled' -or $test.tasks.Values -contains $true) { throw 'Trả chứng chỉ ngoài cửa sổ bảo trì.' }
            $test.steps.Add('rollback')
            if ($test.case.State -eq 'missing') { Remove-Item -LiteralPath $test.cert }
            else { Set-Content -LiteralPath $test.cert -Value $test.old }
        }
        'served' {
            if ($test.served) { return @{ Ok = $true; Json = @{ serial = $test.served } } }
            return @{ Ok = $false }
        }
        default { throw ('Lệnh chứng chỉ bất ngờ: ' + $Arguments[2]) }
    }
    return @{ Ok = $true }
}

function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($ClassName -ne 'Win32_Service' -or $Filter -ne "Name='MinhDuc'") { throw 'Truy vấn nhầm dịch vụ' }
    if ($test.watchResultAtStartup) {
        $test.statusAtStartup = (Get-Content -LiteralPath $test.watchResultAtStartup -Raw -Encoding UTF8 | ConvertFrom-Json).status
    }
    $startMode = if ($test.startup -eq 'Automatic') { 'Auto' } else { $test.startup }
    return @{ StartMode = $startMode }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName, $Arguments, $ErrorAction)
    if ($MethodName -ne 'ChangeStartMode') { throw 'Gọi nhầm phương thức SCM' }
    $test.startup = $Arguments.StartMode
    return @{ ReturnValue = 0 }
}
function Get-Service {
    param($Name, $ErrorAction)
    $service = [pscustomobject]@{ Status = $test.status }
    $service | Add-Member ScriptMethod Refresh { $this.Status = $test.status }
    $service | Add-Member ScriptMethod WaitForStatus {
        param($target, $timeout)
        if ($timeout.TotalSeconds -ne 30) { throw 'Sai giới hạn chờ trạng thái SCM' }
        if ($target -eq 'Stopped') {
            if ($test.startup -ne 'Disabled' -or $test.status -notin @('StopPending', 'Stopped')) { throw 'Chờ dừng sai trạng thái' }
            $test.stoppedWaits++
        } elseif ($target -ne 'Running' -or $test.status -ne 'StartPending' -or $test.startup -ne $test.originalStartup) {
            throw 'Chờ chạy sai trạng thái'
        }
        $test.status = $target
        $this.Status = $target
    }
    return $service
}
function Stop-Service {
    param($InputObject, [switch]$NoWait, $ErrorAction)
    if ($test.startup -ne 'Disabled') { throw 'Phải khóa tự khởi động trước khi yêu cầu SCM dừng' }
    if (-not $NoWait -or $InputObject.Status -ne 'Running') { throw 'Lệnh dừng phải yêu cầu SCM rồi trả quyền chờ cho bộ cài' }
    $test.status = 'StopPending'
    $test.served = $null
    # SCM có thể báo lỗi trong khi WinSW đã bắt đầu dừng.
    throw 'Service stop failed'
}
function Get-MinhDucVenvProcessTree {
    param($Venv, $ClinicEnv, $Known)
    if ($test.status -ne 'Stopped' -or $test.startup -ne 'Disabled') { throw 'Quét Python trước khi SCM dừng hoặc sau khi mở tự khởi động' }
    $test.processScans++
    if ($test.case.Outside) { [pscustomobject]@{ ProcessId = 12345; CanStop = $false } }
}
function Start-Sleep { param($Seconds, $Milliseconds) }
function Stop-Process { throw 'Không được dừng tiến trình ngoài phần mềm' }
function Start-Service {
    [CmdletBinding()]
    param($InputObject)
    if ($test.status -ne 'Stopped' -or $test.startup -ne $test.originalStartup -or
        $test.processScans -ne (2 * $test.stoppedWaits)) { throw 'Khởi động trước khi Python thoát hoặc chưa trả chế độ gốc' }
    if ($test.tasks.Values -contains $false) { throw 'Lịch sao lưu chưa được trả trước khi khởi động.' }
    $test.starts++
    $onDisk = Get-Content -LiteralPath $test.cert -Raw
    $onDisk = $onDisk.Trim()
    $test.steps.Add('start:' + $onDisk)
    if ($test.starts -le $test.case.FailStarts) { throw 'Start-Service failed' }
    $test.status = 'StartPending'
    if ($onDisk -ne 'hong') { $test.served = $onDisk }
    Write-Warning 'Service is still starting'
}
function Wait-Https {
    param($Origin, $Seconds)
    if ($Seconds -ne 120) { throw 'Giới hạn chờ HTTPS đã đổi' }
    return $test.status -eq 'Running' -and $null -ne $test.served
}

$root = Join-Path ([IO.Path]::GetTempPath()) ('minhduc-cert-restart-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $root | Out-Null
try {
    # Thay đúng hai điểm phụ thuộc nền tảng. Các bước gia hạn, phục hồi và mã thoát dùng mã thật.
    $entry = Join-Path $root 'GiaHanChungChi.ps1'
    $source = Get-Content -LiteralPath (Join-Path $windows 'GiaHanChungChi.ps1') -Raw -Encoding UTF8
    $source = $source -replace '(?m)^    Import-Module .*$', '' -replace '(?m)^    \$admin = .*$', '    $$admin = $$true'
    Set-Content -LiteralPath $entry -Value $source -Encoding UTF8

    $cases = @(
        @{ Name = 'slow'; State = 'ok'; FailStarts = 0; Exit = 0; Result = 'thanh_cong'; Served = 'new'; Steps = 'verify,commit,start:new' }
        @{ Name = 'skipped'; State = 'ok'; Skip = $true; Exit = 0; Result = 'bo_qua'; Served = 'old'; Steps = '' }
        @{ Name = 'damaged'; State = 'hong'; FailStarts = 1; Exit = 0; Result = 'thanh_cong'; Served = 'new'; Steps = 'verify,commit,start:new,start:new' }
        @{ Name = 'missing'; State = 'missing'; FailStarts = 1; Exit = 0; Result = 'thanh_cong'; Served = 'new'; Steps = 'verify,commit,start:new,start:new' }
        @{ Name = 'ordinary'; State = 'ok'; FailStarts = 1; Exit = 50; Result = 'da_tra_chung_chi_cu'; Served = 'old'; Steps = 'verify,commit,start:new,rollback,start:old' }
        @{ Name = 'twice'; State = 'hong'; FailStarts = 2; Exit = 51; Result = 'khoi_phuc_that_bai'; Steps = 'verify,commit,start:new,start:new,rollback,start:hong' }
        @{ Name = 'commit'; State = 'hong'; BadCommit = $true; FailStarts = 0; Exit = 51; Result = 'khoi_phuc_that_bai'; Steps = 'verify,commit,rollback,start:hong' }
        @{ Name = 'outside'; State = 'hong'; Outside = $true; Exit = 51; Result = 'khoi_phuc_that_bai'; Steps = 'verify,commit' }
        @{ Name = 'cleanup-after-https'; State = 'ok'; ExitFault = $true; Exit = 8; Result = 'thanh_cong_can_kiem_tra'; Served = 'new'; Steps = 'verify,commit,start:new'; Detail = 'hạn mới' }
        @{ Name = 'cleanup-after-50'; State = 'ok'; FailStarts = 1; ExitFault = $true; Exit = 50; Result = 'da_tra_chung_chi_cu'; Served = 'old'; Steps = 'verify,commit,start:new,rollback,start:old'; Detail = 'Start-Service failed' }
        @{ Name = 'cleanup-after-51'; State = 'hong'; BadCommit = $true; ExitFault = $true; Exit = 51; Result = 'khoi_phuc_that_bai'; Steps = 'verify,commit,rollback,start:hong'; Detail = 'Lỗi thay tệp giả lập' }
    )
    foreach ($case in $cases) {
        $test = @{ case = $case }
        $data = Join-Path $root $case.Name
        New-Item -ItemType Directory -Path $data | Out-Null
        foreach ($file in @('ca.crt', 'ca.key', 'clinic.env')) { New-Item -ItemType File -Path (Join-Path $data $file) | Out-Null }
        $test.cert = Join-Path $data 'server.crt'
        $test.resultFile = Join-Path $data 'ket-qua-gia-han.json'
        $test.old = if ($case.State -eq 'hong') { 'hong' } else { 'old' }
        if ($case.State -ne 'missing') { Set-Content -LiteralPath $test.cert -Value $test.old }
        $test.served = 'old'
        $test.originalStartup = if ($case.Outside) { 'Manual' } else { 'Automatic' }
        $test.startup = $test.originalStartup
        $test.tasks = @{ daily = $true; 'daily - Chay bu' = $true }
        $test.status = 'Running'
        $test.stoppedWaits = 0
        $test.processScans = 0
        $test.starts = 0
        $test.steps = New-Object 'System.Collections.Generic.List[string]'
        & $entry -KhongHoi -ThuMucMa $data -ThuMucDuLieu $data
        $exitCode = $LASTEXITCODE
        $result = Get-Content -LiteralPath (Join-Path $data 'ket-qua-gia-han.json') -Raw | ConvertFrom-Json
        if ($exitCode -ne $case.Exit -or $result.status -ne $case.Result -or $test.served -ne $case.Served -or
            ($test.steps -join ',') -ne $case.Steps -or $test.startup -ne $test.originalStartup) {
            throw ("Sai kết quả $($case.Name): $exitCode / $($result.status), HTTPS=$test.served, startup=$test.startup, bước=$test.steps")
        }
        if ($test.tasks.Values -contains $false) { throw 'Lịch sao lưu còn Disabled sau gia hạn.' }
        if ($test.resultBeforeExit) { throw "Đã ghi kết quả trước khi trả cấu hình ở ca $($case.Name)." }
        if ($case.ExitFault -and ($result.detail -notlike "*$($case.Detail)*" -or $result.detail -notlike '*Lỗi trả cấu hình giả lập*')) {
            throw "Kết quả $($case.Name) thiếu chi tiết gốc hoặc lỗi trả cấu hình."
        }
    }
    foreach ($early in @(
        @{ Name = 'blocked-marker'; Code = 1; Detail = 'Cập nhật bị ngắt sau khi đã thay dữ liệu' },
        @{ Name = 'missing-config'; Code = 2; Detail = 'thiếu tệp cấu hình' },
        @{ Name = 'busy-window'; Code = 52; Detail = 'Đang có bảo trì khác' },
        @{ Name = 'requires-admin'; Code = 30; Detail = 'Cần quyền Administrator' }
    )) {
        $data = Join-Path $root $early.Name
        New-Item -ItemType Directory -Path $data | Out-Null
        $paths = Get-MinhDucPaths -Code $data -Data $data
        $resultFile = Join-Path $paths.Journal 'ket-qua-gia-han.json'
        '{"status":"thanh_cong","detail":"ket qua cu"}' | Set-Content -LiteralPath $resultFile -Encoding UTF8
        $test = @{ startup = 'Disabled' }
        if ($early.Name -ne 'missing-config') { New-Item -ItemType File -Path $paths.ClinicEnv | Out-Null }
        if ($early.Name -eq 'blocked-marker') {
            $test.watchResultAtStartup = $resultFile
            $marker = @{
                Service = 'MinhDuc'; StartMode = 'Automatic'; DelayedAutoStart = $false
                CreatedAt = '19/11/2026 00:00:00 UTC+7'; Script = 'CapNhat.ps1'
            }
            Write-MinhDucServiceStartModeMarker $paths.ServiceStartModePending $marker
            $markerHash = (Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash
        }
        $lock = $null
        if ($early.Name -eq 'busy-window') { $lock = Open-MinhDucServiceStartModeLock $paths.MaintenanceLockBase }
        if ($early.Name -eq 'requires-admin') {
            Set-Content -LiteralPath $entry -Value ($source.Replace('$admin = $true', '$admin = $false')) -Encoding UTF8
        }
        try { & $entry -KhongHoi -ThuMucMa $data -ThuMucDuLieu $data }
        finally { if ($lock) { $lock.Dispose() } }
        $exitCode = $LASTEXITCODE
        $result = Get-Content -LiteralPath $resultFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($exitCode -ne $early.Code -or $result.status -ne 'dung' -or $result.detail -notlike "*$($early.Detail)*") {
            throw "Lỗi sớm $($early.Name) không ghi đúng kết quả. Mã $exitCode, trạng thái $($result.status), chi tiết $($result.detail)."
        }
        if ($early.Name -eq 'blocked-marker') {
            if ($test.statusAtStartup -ne 'dang_gia_han') { throw 'Phải ghi dang_gia_han trước khi kiểm dấu bảo trì.' }
            if ((Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash -ne $markerHash -or $test.startup -ne 'Disabled') {
                throw 'Gia hạn đã thay đổi dấu hoặc chế độ khởi động của phiên cập nhật bị khóa.'
            }
        }
    }
    Write-Output 'PASS: certificate restart'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force
}
