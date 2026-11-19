[CmdletBinding()]
param([string]$InterruptIn = '', [ValidateSet('CapNhat.ps1','GiaHanChungChi.ps1')][string]$SourceScript = 'CapNhat.ps1')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$windows = Join-Path $PSScriptRoot '../deploy/windows'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $windows 'MinhDuc.Install.psm1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Set-RecoveryServiceStartMode', 'Open-MinhDucServiceStartModeLock', 'Get-MinhDucServiceStartModeMarkerFile',
                    'Write-MinhDucServiceStartModeMarker', 'Restore-MinhDucServiceStartMode', 'Resume-MinhDucServiceStartMode',
                    'Invoke-WithMinhDucServiceStartupDisabled', 'Disable-MinhDucServiceStartup', 'Invoke-HealthReport')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}

function Get-MinhDucNames { return @{ Service = 'MinhDuc' } }
$fixture = @{ IgnoreScmChange = $false }

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
        $original = if ($state.Mode -eq 'Auto') { 'Automatic' } else { 'Manual' }
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
        @{ Mode = 'Auto'; Delayed = $true; Script = 'CapNhat.ps1' },
        @{ Mode = 'Manual'; Delayed = $false; Script = 'GiaHanChungChi.ps1' }
    )) {
        @{ Mode = $scenario.Mode; Delayed = $scenario.Delayed } | ConvertTo-Json | Set-Content -LiteralPath $fixture.ScmFile -Encoding UTF8
        # Child dies inside the guard, so PowerShell cannot execute finally.
        $worker = Start-Process -FilePath $engine -ArgumentList @('-NoProfile', '-File', ('"' + $PSCommandPath + '"'),
            '-InterruptIn', ('"' + $root + '"'), '-SourceScript', $scenario.Script) -PassThru
        if (-not $worker.WaitForExit(15000)) { $worker.Kill(); throw 'Tiến trình kiểm thử chưa thoát.' }
        if ($worker.ExitCode -eq 0 -or -not (Test-Path -LiteralPath $pending) -or (Get-Service).StartType -ne 'Disabled') {
            throw 'Chưa mô phỏng được tiến trình bị ngắt khi dịch vụ đang Disabled.'
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

    Set-Content -LiteralPath $pending -Value '{"Service":"MinhDuc","StartMode":"Manual","DelayedAutoStart":false,"CreatedAt":"19/11/2026 00:00:00 UTC+7","Script":"CapNhat.ps1"}' -Encoding UTF8
    $fixture.IgnoreScmChange = $true
    Run-Check
    if ($script:CheckExit -ne 1 -or $script:CheckReport -notmatch 'Kiểm lại chế độ khởi động.*chưa đạt' -or
        -not (Test-Path -LiteralPath $pending)) { throw 'Đã xóa dấu dù đọc lại chế độ chưa đúng.' }
    Write-Output 'PASS: service startup recovery'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
