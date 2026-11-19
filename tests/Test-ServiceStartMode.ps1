[CmdletBinding()]
param([string]$InterruptIn = '', [switch]$AfterDataChange, [ValidateSet('CapNhat.ps1','GiaHanChungChi.ps1')][string]$SourceScript = 'CapNhat.ps1')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$windows = Join-Path $PSScriptRoot '../deploy/windows'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $windows 'MinhDuc.Install.psm1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Set-RecoveryServiceStartMode', 'Open-MinhDucServiceStartModeLock', 'Get-MinhDucServiceStartModeMarkerFile',
                    'Write-MinhDucServiceStartModeMarker', 'Restore-MinhDucServiceStartMode', 'Resume-MinhDucServiceStartMode',
                    'Read-MinhDucServiceStartModeMarker', 'Restore-MinhDucServiceStartup',
                    'Invoke-WithMinhDucServiceStartupDisabled', 'Disable-MinhDucServiceStartup', 'Invoke-HealthReport',
                    'Enter-MinhDucMaintenanceWindow', 'Suspend-MinhDucMaintenanceWindow', 'Set-MinhDucUpdatePhase')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}

function Get-MinhDucNames { return @{ Service = 'MinhDuc'; BackupTask = 'daily'; FirewallMaintenance = 'fake HTTPS rule' } }
function Get-MinhDucBackupTaskSnapshot {
    foreach ($name in $fixture.Tasks.Keys) { @{ Name = $name; Enabled = $fixture.Tasks[$name] } }
}
function Get-MinhDucScheduledTask { param($Name) @{ Settings = @{ Enabled = $fixture.Tasks[$Name] } } }
function Enable-ScheduledTask {
    param($TaskName, $TaskPath, $ErrorAction)
    if ($fixture.FailTasks) { throw 'Bật lịch lỗi giả lập.' }
    $fixture.Tasks[$TaskName] = $true
}
function Enable-MinhDucMaintenanceFirewall { param($Paths) $fixture.Firewall = $true }
function Suspend-MinhDucBackupTasks {
    param([switch]$WaitForIdle)
    foreach ($name in @($fixture.Tasks.Keys)) { $fixture.Tasks[$name] = $false }
}
function Disable-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $fixture.Tasks[$TaskName] = $false }
function Remove-MinhDucMaintenanceFirewall {
    param($Name)
    if ($Name -ne 'fake HTTPS rule' -or -not $fixture.Tasks.daily -or $fixture.Tasks['daily - Chay bu']) {
        throw 'Đã gỡ quy tắc khác hoặc gỡ trước khi trả lịch.'
    }
    if ($fixture.FailFirewall) { throw 'Gỡ tường lửa lỗi giả lập.' }
    if ($fixture.RequireStartupLast -and (Get-Service).StartType -ne 'Disabled') { throw 'Đã trả khởi động trước khi gỡ tường lửa.' }
    $fixture.Firewall = $false
}
$fixture = @{ IgnoreScmChange = $false; FailTasks = $false; FailFirewall = $false; RequireStartupLast = $false; RecoveryInProgress = $false }

function Get-MinhDucPaths {
    param($Code, $Data)
    @{
        Journal = $Data
        ServiceStartModePending = Join-Path $Data 'service-startmode-pending.json'
        MaintenanceLockBase = Join-Path $Data 'service-startmode-pending.json'
        VenvPython = Join-Path $Data 'python.exe'
        ClinicEnv = Join-Path $Data 'clinic.env'
        BackupState = Join-Path $Data 'backup-status.json'
    }
}
function Get-MinhDucDelayedAutoStart($Name) {
    return ((Get-Content -LiteralPath $fixture.ScmFile -Raw | ConvertFrom-Json).Delayed)
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($ClassName -ne 'Win32_Service' -or $Filter -ne "Name='MinhDuc'") { throw 'Truy vấn nhầm dịch vụ.' }
    $state = Get-Content -LiteralPath $fixture.ScmFile -Raw | ConvertFrom-Json
    return @{ StartMode = $state.Mode }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName, $Arguments, $ErrorAction)
    if ($MethodName -ne 'ChangeStartMode') { throw 'Sai phương thức SCM.' }
    $state = Get-Content -LiteralPath $fixture.ScmFile -Raw | ConvertFrom-Json
    if ($Arguments.StartMode -eq 'Disabled') {
        $marker = Get-Content -LiteralPath $fixture.Paths.ServiceStartModePending -Raw | ConvertFrom-Json
        $original = if ($state.Mode -eq 'Auto' -or $fixture.RecoveryInProgress) { 'Automatic' } else { 'Manual' }
        if ($marker.Service -ne 'MinhDuc' -or $marker.StartMode -ne $original -or $marker.DelayedAutoStart -ne $state.Delayed -or
            $marker.Script -ne $SourceScript -or -not $marker.CreatedAt) { throw 'Chưa ghi đủ dấu trước khi khóa dịch vụ.' }
        $state.Mode = 'Disabled'
        # Mô phỏng hệ thống làm mất cờ khi đổi chế độ, để kiểm đường trả lại cờ.
        $state.Delayed = $false
    } elseif (-not $fixture.IgnoreScmChange) {
        $state.Mode = if ($Arguments.StartMode -eq 'Automatic') { 'Auto' } else { $Arguments.StartMode }
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
    return @{ ReturnValue = 0 }
}
function Invoke-Native {
    param($FilePath, $Arguments, [switch]$Quiet)
    if ($FilePath -ne 'sc.exe' -or ($Arguments -join ' ') -ne 'config MinhDuc start= delayed-auto') { throw 'Sai lệnh trả cờ khởi động trễ.' }
    @{ Mode = 'Auto'; Delayed = $true } | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
    return @{ Ok = $true }
}
function Get-Service {
    param($Name, $ErrorAction)
    $mode = (Get-Content -LiteralPath $fixture.ScmFile -Raw | ConvertFrom-Json).Mode
    return @{ StartType = $(if ($mode -eq 'Auto') { 'Automatic' } else { $mode }) }
}
function Get-WindowsFacts { param($Paths) return @{} }
function Invoke-Python {
    param($Paths, $Arguments, $OkCodes, [switch]$Quiet)
    $output = $Arguments[[array]::IndexOf($Arguments, '--output') + 1]
    Set-Content -LiteralPath $output -Encoding UTF8 -Value @('[ĐẠT] Mục sẵn có', '', 'Tổng: 1/1 mục ĐẠT.')
    return @{ Code = 0 }
}
function Write-Dat($Text) { Write-Host $Text }

if ($InterruptIn) {
    $fixture.Paths = Get-MinhDucPaths -Data $InterruptIn
    $fixture.ScmFile = Join-Path $InterruptIn 'scm.json'
    if ($AfterDataChange) {
        $fixture.Tasks = @{ daily = $true; 'daily - Chay bu' = $false }
        $window = Enter-MinhDucMaintenanceWindow -Name MinhDuc -Paths $fixture.Paths -ScriptName 'CapNhat.ps1' -GuardHttps
        Suspend-MinhDucMaintenanceWindow -Window $window
        Set-MinhDucUpdatePhase -Window $window -Phase da_doi_du_lieu
        [Diagnostics.Process]::GetCurrentProcess().Kill()
    }
    Invoke-WithMinhDucServiceStartupDisabled -Name MinhDuc -Paths $fixture.Paths -ScriptName $SourceScript -Action {
        [Diagnostics.Process]::GetCurrentProcess().Kill()
    }
    throw 'Tiến trình chưa bị ngắt.'
}

$root = Join-Path ([IO.Path]::GetTempPath()) ('minhduc-startmode-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $root | Out-Null
if (-not $env:TEMP) { $env:TEMP = [IO.Path]::GetTempPath() }
$fixture.Paths = Get-MinhDucPaths -Data $root
$fixture.ScmFile = Join-Path $root 'scm.json'
$pending = $fixture.Paths.ServiceStartModePending
$report = Join-Path $root 'report.txt'
$entry = Join-Path $root 'KiemTra.ps1'
$source = Get-Content -LiteralPath (Join-Path $windows 'KiemTra.ps1') -Raw -Encoding UTF8
Set-Content -LiteralPath $entry -Value ($source -replace '(?m)^Import-Module .*$', '') -Encoding UTF8
$null = New-Item -ItemType File -Path $fixture.Paths.ClinicEnv, $fixture.Paths.VenvPython

function Run-Check {
    & $entry -KhongHoi -ThuMucMa $root -ThuMucDuLieu $root -TepKetQua $report
    $script:CheckExit = $LASTEXITCODE
    $script:CheckReport = Get-Content -LiteralPath $report -Raw -Encoding UTF8
}

try {
    $engine = (Get-Process -Id $PID).Path
    foreach ($scenario in @(
        @{ Mode = 'Auto'; Delayed = $true; Script = 'CapNhat.ps1'; Legacy = $false },
        @{ Mode = 'Manual'; Delayed = $false; Script = 'GiaHanChungChi.ps1'; Legacy = $true }
    )) {
        @{ Mode = $scenario.Mode; Delayed = $scenario.Delayed } | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
        # Child dies inside the guard, so PowerShell cannot execute finally.
        $worker = Start-Process -FilePath $engine -ArgumentList @('-NoProfile', '-File', ('"' + $PSCommandPath + '"'),
            '-InterruptIn', ('"' + $root + '"'), '-SourceScript', $scenario.Script) -PassThru
        if (-not $worker.WaitForExit(15000)) { $worker.Kill(); throw 'Tiến trình kiểm thử chưa thoát.' }
        if ($worker.ExitCode -eq 0 -or -not (Test-Path -LiteralPath $pending) -or (Get-Service).StartType -ne 'Disabled') {
            throw 'Chưa mô phỏng được tiến trình bị ngắt khi dịch vụ đang Disabled.'
        }
        if ($scenario.Legacy) {
            $legacy = Get-Content -LiteralPath $pending -Raw | ConvertFrom-Json
            $legacy.PSObject.Properties.Remove('Phase')
            Write-MinhDucServiceStartModeMarker $pending $legacy -Replace
            if ((Read-MinhDucServiceStartModeMarker MinhDuc $fixture.Paths).Phase -ne 'chua_doi_du_lieu') {
                throw 'Dấu gia hạn cũ phải được nhận là chưa đổi dữ liệu.'
            }
        }
        Run-Check
        $state = Get-Content -LiteralPath $fixture.ScmFile -Raw | ConvertFrom-Json
        $log = Get-Content -LiteralPath (Join-Path $root 'service-startmode.log') -Raw -Encoding UTF8
        if ($script:CheckExit -ne 0 -or $state.Mode -ne $scenario.Mode -or $state.Delayed -ne $scenario.Delayed -or
            (Test-Path -LiteralPath $pending) -or $script:CheckReport -notmatch '\[ĐẠT\] Dịch vụ web không bị vô hiệu hóa' -or
            $script:CheckReport -notmatch 'Tổng: 2/2 mục ĐẠT' -or $log -notmatch "KiemTra\.ps1.*$([regex]::Escape($scenario.Script))") {
            throw 'Lần chạy sau chưa trả đủ chế độ gốc, ghi nhật ký và xóa tệp đánh dấu.'
        }
    }

    @{ Mode = 'Disabled'; Delayed = $false } | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
    $before = Get-FileHash -LiteralPath $fixture.ScmFile
    Run-Check
    if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch '\[KHÔNG ĐẠT\] Dịch vụ web không bị vô hiệu hóa.*người hỗ trợ' -or
        $script:CheckReport -notmatch 'Tổng: 1/2 mục ĐẠT' -or (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $before.Hash -or
        (Test-Path -LiteralPath $pending)) { throw 'KIEM_TRA không báo đúng hoặc đã sửa Disabled khi thiếu dấu.' }

    Invoke-WithMinhDucServiceStartupDisabled -Name MinhDuc -Paths $fixture.Paths -ScriptName 'CapNhat.ps1' -AllowAlreadyDisabled -Action {
        param($config)
        if ($config.StartMode -ne 'Disabled' -or (Test-Path -LiteralPath $pending)) { throw 'Quay về đã sửa chế độ Disabled có sẵn.' }
    }
    if ((Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $before.Hash -or (Test-Path -LiteralPath $pending)) {
        throw 'Quay về đã ghi dấu hoặc sửa chế độ Disabled có sẵn.'
    }

    foreach ($invalid in @('{', '{"Service":"MinhDuc","StartMode":"Automatic"}',
        '{"Service":"Khac","StartMode":"Manual","DelayedAutoStart":false,"CreatedAt":"19/11/2026 00:00:00 UTC+7","Script":"CapNhat.ps1"}')) {
        Set-Content -LiteralPath $pending -Value $invalid -Encoding UTF8
        $markerHash = (Get-FileHash -LiteralPath $pending).Hash
        Run-Check
        if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch '\[KHÔNG ĐẠT\].*hỏng hoặc thiếu thông tin' -or
            (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $before.Hash -or
            (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash) { throw 'KIEM_TRA đã sửa dịch vụ hoặc dấu không hợp lệ.' }
    }

    $legacy = [ordered]@{
        Service = 'MinhDuc'; StartMode = 'Manual'; DelayedAutoStart = $false; CreatedAt = '19/11/2026 00:00:00 UTC+7'
    }
    foreach ($legacyScript in @('CapNhat.ps1', '', 'Khac.ps1')) {
        if ($legacyScript) { $legacy.Script = $legacyScript } else { $legacy.Remove('Script') }
        Write-MinhDucServiceStartModeMarker $pending $legacy -Replace
        $markerHash = (Get-FileHash -LiteralPath $pending).Hash
        $expectedError = 'hỏng hoặc thiếu thông tin'
        if ($legacyScript -eq 'CapNhat.ps1') {
            if ((Read-MinhDucServiceStartModeMarker MinhDuc $fixture.Paths).Phase -ne 'da_doi_du_lieu') {
                throw 'Dấu cập nhật cũ phải được nhận là đã đổi dữ liệu.'
            }
            $expectedError = 'Cập nhật bị ngắt sau khi đã thay dữ liệu'
        }
        Run-Check
        if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch ("\[KHÔNG ĐẠT\].*" + $expectedError) -or
            (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $before.Hash -or
            (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash) { throw "KIEM_TRA đã mở khóa với dấu cũ ($legacyScript)." }
    }
    $legacy.Script = 'CapNhat.ps1'
    $legacy.Status = 'da_quay_ve'
    $legacy.TaskEnabled = @{ daily = $true }
    $legacy.FirewallRule = 'fake HTTPS rule'
    Write-MinhDucServiceStartModeMarker $pending $legacy -Replace
    $markerHash = (Get-FileHash -LiteralPath $pending).Hash
    Run-Check
    if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch 'Cập nhật bị ngắt sau khi đã thay dữ liệu' -or
        (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $before.Hash -or
        (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash) { throw 'Dấu cập nhật thiếu Phase đã được mở tự động.' }

    Set-Content -LiteralPath $pending -Value '{"Service":"MinhDuc","StartMode":"Manual","DelayedAutoStart":false,"CreatedAt":"19/11/2026 00:00:00 UTC+7","Script":"CapNhat.ps1","Phase":"chua_doi_du_lieu"}' -Encoding UTF8
    $fixture.IgnoreScmChange = $true
    Run-Check
    if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch 'Kiểm lại chế độ khởi động.*chưa đạt' -or
        -not (Test-Path -LiteralPath $pending)) { throw 'Đã xóa dấu dù đọc lại chế độ chưa đúng.' }
    Remove-Item -LiteralPath $fixture.Paths.ClinicEnv, $fixture.Paths.VenvPython
    $fixture.IgnoreScmChange = $false
    $fixture.Tasks = @{ daily = $false; 'daily - Chay bu' = $false }
    $fixture.Firewall = $true
    $marker = [ordered]@{
        Service = 'MinhDuc'; StartMode = 'Automatic'; DelayedAutoStart = $true
        CreatedAt = '19/11/2026 00:00:00 UTC+7'; Script = 'CapNhat.ps1'
        Phase = 'chua_doi_du_lieu'; Status = 'quay_ve_that_bai'; TaskEnabled = @{ daily = $true; 'daily - Chay bu' = $false }; FirewallRule = 'fake HTTPS rule'
    }
    Write-MinhDucServiceStartModeMarker $pending $marker -Replace
    $markerHash = (Get-FileHash -LiteralPath $pending).Hash
    Run-Check
    if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch '\[KHÔNG ĐẠT\].*quay_ve_that_bai.*người hỗ trợ' -or
        (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash -or (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $before.Hash -or
        $fixture.Tasks.Values -contains $true -or -not $fixture.Firewall) { throw 'KIEM_TRA đã mở cửa sổ quay về lỗi hoặc bỏ qua vì thiếu Python/config.' }

    $marker.Status = 'dang_bao_tri'
    Write-MinhDucServiceStartModeMarker $pending $marker -Replace
    # Directory at the log path triggers a real write failure after the marker is cleared.
    $logPath = Join-Path $root 'service-startmode.log'
    Remove-Item -LiteralPath $logPath
    New-Item -ItemType Directory -Path $logPath | Out-Null
    Run-Check
    $state = Get-Content -LiteralPath $fixture.ScmFile -Raw | ConvertFrom-Json
    if ($script:CheckExit -ne 2 -or $script:CheckReport -notmatch '\[ĐẠT\] Dịch vụ web.*Đã trả' -or
        $state.Mode -ne 'Auto' -or -not $state.Delayed -or -not $fixture.Tasks.daily -or $fixture.Tasks['daily - Chay bu'] -or
        $fixture.Firewall -or (Test-Path -LiteralPath $pending)) { throw 'Chưa trả đủ bảo trì, hoặc lỗi ghi nhật ký làm kẹt tệp đánh dấu.' }
    $fixture.Tasks = @{ daily = $false; 'daily - Chay bu' = $false }
    $fixture.Firewall = $true
    @{ Mode = 'Auto'; Delayed = $true } | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
    $worker = Start-Process -FilePath $engine -ArgumentList @('-NoProfile', '-File', ('"' + $PSCommandPath + '"'),
        '-InterruptIn', ('"' + $root + '"'), '-AfterDataChange') -PassThru
    if (-not $worker.WaitForExit(15000)) { $worker.Kill(); throw 'Tiến trình kiểm thử chưa thoát.' }
    $marker = Read-MinhDucServiceStartModeMarker MinhDuc $fixture.Paths
    if ($worker.ExitCode -eq 0 -or $marker.Phase -ne 'da_doi_du_lieu' -or $marker.Status -ne 'dang_bao_tri' -or
        (Get-Service).StartType -ne 'Disabled') { throw 'Thiếu dấu gián đoạn sau khi đã đổi dữ liệu.' }
    $markerHash = (Get-FileHash -LiteralPath $pending).Hash
    $scmHash = (Get-FileHash -LiteralPath $fixture.ScmFile).Hash
    Run-Check
    if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch '\[KHÔNG ĐẠT\].*Cập nhật bị ngắt sau khi đã thay dữ liệu.*KHÔNG dùng phần mềm.*người hỗ trợ' -or
        (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash -or (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $scmHash -or
        $fixture.Tasks.Values -contains $true -or -not $fixture.Firewall) { throw 'KIEM_TRA đã đổi cấu hình khi dữ liệu chưa được xác nhận.' }

    # Gián đoạn ngay sau khi SCM đã chuyển Manual trong Start-Service.
    @{ Mode = 'Manual'; Delayed = $true } | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
    $fixture.RecoveryInProgress = $true
    Run-Check
    $fixture.RecoveryInProgress = $false
    if ($script:CheckExit -ne 1 -or (Get-Service).StartType -ne 'Disabled' -or
        (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash -or $fixture.Tasks.Values -contains $true -or -not $fixture.Firewall) {
        throw 'KIEM_TRA không khóa lại được Manual sau gián đoạn khi bật web.'
    }
    $scmHash = (Get-FileHash -LiteralPath $fixture.ScmFile).Hash

    $window = @{ Name = 'MinhDuc'; Paths = $fixture.Paths; FirewallReady = $true }
    Set-MinhDucUpdatePhase -Window $window -Phase da_chot
    $markerHash = (Get-FileHash -LiteralPath $pending).Hash
    $fixture.RequireStartupLast = $true
    foreach ($fault in 'FailTasks', 'FailFirewall') {
        $fixture[$fault] = $true
        Run-Check
        $expected = if ($fault -eq 'FailTasks') { 'lịch sao lưu' } else { 'tường lửa' }
        if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch $expected -or
            (Get-FileHash -LiteralPath $pending).Hash -ne $markerHash -or (Get-FileHash -LiteralPath $fixture.ScmFile).Hash -ne $scmHash -or
            -not $fixture.Firewall -or $fixture.Tasks.daily -ne ($fault -eq 'FailFirewall') -or $fixture.Tasks['daily - Chay bu']) {
            throw "Lỗi $fault không được phép trả startup hoặc xóa dấu."
        }
        $fixture[$fault] = $false
    }
    Run-Check
    if ($script:CheckExit -ne 2 -or (Get-Service).StartType -ne 'Automatic' -or -not (Get-MinhDucDelayedAutoStart MinhDuc) -or
        $fixture.Firewall -or -not $fixture.Tasks.daily -or $fixture.Tasks['daily - Chay bu'] -or
        (Test-Path -LiteralPath $pending)) { throw 'KIEM_TRA chưa trả đủ cấu hình sau khi đã chốt.' }
    Write-Output 'PASS: service startup recovery; data change holds maintenance; committed release retries tasks then firewall then startup'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
