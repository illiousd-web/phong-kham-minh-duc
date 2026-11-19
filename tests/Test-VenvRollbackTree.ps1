param([switch]$RealVenvLock)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
Import-Module (Join-Path $PSScriptRoot '../deploy/windows/MinhDuc.Install.psm1') -Force -DisableNameChecking

if ($RealVenvLock) {
    if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) { throw 'Chỉ kiểm khóa venv thật trên Windows CI giả lập.' }
    $paths = Get-MinhDucPaths
    $serviceName = (Get-MinhDucNames).Service
    $service = Get-Service -Name $serviceName -ErrorAction Stop
    $wasRunning = $service.Status -eq 'Running'
    $root = Join-Path $env:RUNNER_TEMP ('minhduc-venv-' + [guid]::NewGuid())
    $venv = Join-Path $root '.venv'
    $oldVenv = Join-Path $root '.venv-cu'
    $ready = Join-Path $root 'ready.txt'
    $quit = Join-Path $root 'quit.txt'
    $fixture = Join-Path $root 'hold_rust.py'
    $launcher = $null
    try {
        # Lần quét venv thử cũng nhận diện Python đang chạy clinic.env thật.
        Stop-MinhDucService -Name $serviceName -Paths $paths
        New-Item -ItemType Directory -Path $root | Out-Null
        Copy-Item -LiteralPath $paths.Venv -Destination $venv -Recurse
        & $paths.BasePython -m venv --without-pip $oldVenv
        if ($LASTEXITCODE -ne 0) { throw 'Không tạo được môi trường Python cũ cho bài kiểm.' }
        Set-Content -LiteralPath (Join-Path $oldVenv 'old.txt') -Value 'old'
        @'
import os
from pathlib import Path
import time

from cryptography.hazmat.bindings import _rust

root = Path(__file__).parent
ready = root / 'ready.tmp'
ready.write_text(str(os.getpid()), encoding='ascii')
ready.rename(root / 'ready.txt')
deadline = time.monotonic() + 45
while not (root / 'quit.txt').exists() and time.monotonic() < deadline:
    time.sleep(0.1)
'@ | Set-Content -LiteralPath $fixture -Encoding ASCII
        $python = Join-Path $venv 'Scripts/python.exe'
        $launcher = Start-Process -FilePath $python -ArgumentList ('"' + $fixture + '"') -PassThru
        $timer = [Diagnostics.Stopwatch]::StartNew()
        while (-not (Test-Path -LiteralPath $ready)) {
            if ($launcher.HasExited -or $timer.Elapsed.TotalSeconds -gt 15) { throw 'Tiến trình con chưa nạp được _rust.pyd trong venv.' }
            Start-Sleep -Milliseconds 100
        }
        $childId = [int](Get-Content -LiteralPath $ready)
        $tree = @(Get-MinhDucVenvProcessTree -Venv $venv)
        $parent = @($tree | Where-Object { $_.ProcessId -eq $launcher.Id -and $_.ExecutablePath -eq [IO.Path]::GetFullPath($python) })
        $child = @($tree | Where-Object { $_.ProcessId -eq $childId -and $_.ParentProcessId -eq $launcher.Id -and $_.ExecutablePath -eq $paths.BasePython })
        if ($parent.Count -ne 1 -or $child.Count -ne 1 -or -not $child[0].CanStop -or
            -not ($child[0].LoadedVenvModules | Where-Object { $_ -like '*\_rust.pyd' })) { throw 'Không tìm được cây Python và _rust.pyd đã nạp từ venv.' }

        Wait-MinhDucVenvPythonExit -Venv $venv -Seconds 1 -LogLockDiagnostics
        if (-not $launcher.HasExited -or (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { throw 'Cây Python còn chạy sau khi chờ.' }
        Restore-MinhDucOldVenv -Venv $venv -OldVenv $oldVenv -LogLockDiagnostics
        if (-not (Test-Path -LiteralPath (Join-Path $venv 'old.txt')) -or (Test-Path -LiteralPath $oldVenv) -or
            (Get-ChildItem -LiteralPath $root -Filter '.venv-quay-ve-*')) { throw 'Chưa trả đúng môi trường cũ hoặc còn thư mục tạm.' }
        & $python -c 'import sys; print(sys.prefix)'
        if ($LASTEXITCODE -ne 0) { throw 'Môi trường Python cũ không chạy được.' }
        Write-Output 'PASS: Python gốc nạp _rust.pyd trong venv, cây thoát và môi trường cũ được trả.'
    } finally {
        try {
            if ($launcher -and -not $launcher.HasExited) {
                Set-Content -LiteralPath $quit -Value 'quit'
                if (-not $launcher.WaitForExit(5000)) { throw 'Tiến trình kiểm thử chưa thoát.' }
            }
            Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        } finally {
            if ($wasRunning) {
                Start-Service -Name $serviceName -ErrorAction Stop
                $service.WaitForStatus('Running', (New-TimeSpan -Seconds 30))
            }
        }
    }
    return
}

# Dùng định nghĩa thật với snapshot giả lập để kiểm cả trường hợp cấm dừng.
$module = Join-Path $PSScriptRoot '../deploy/windows/MinhDuc.Install.psm1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($module, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in 'Get-MinhDucVenvProcessTree', 'Wait-MinhDucVenvPythonExit', 'Set-RecoveryServiceStartMode') {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}
$venv = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'clinic-test', '.venv')
$venvPython = [IO.Path]::Combine($venv, 'Scripts', 'python.exe')
$basePython = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'base-python', 'python.exe')
$rust = [IO.Path]::Combine($venv, 'Lib', '_rust.pyd')
$envPath = 'C:\Test Clinic\clinic.env'
$rows = @{
    100 = [pscustomobject]@{ ProcessId=100; ParentProcessId=1; CreationDate=2; Name='python.exe'; ExecutablePath=$venvPython; CommandLine='python.exe hold_rust.py' }
    200 = [pscustomobject]@{ ProcessId=200; ParentProcessId=100; CreationDate=2; Name='python.exe'; ExecutablePath=$basePython; CommandLine='python.exe hold_rust.py' }
    300 = [pscustomobject]@{ ProcessId=300; ParentProcessId=200; CreationDate=2; Name='helper.exe'; ExecutablePath='helper.exe'; CommandLine='helper.exe' }
    400 = [pscustomobject]@{ ProcessId=400; ParentProcessId=1; CreationDate=1; Name='python.exe'; ExecutablePath=$basePython; CommandLine=('python.exe -m scripts.with_env "' + $envPath + '" scripts.run_lan') }
    500 = [pscustomobject]@{ ProcessId=500; ParentProcessId=1; CreationDate=1; Name='python.exe'; ExecutablePath=$basePython; CommandLine='python.exe other.py' }
    600 = [pscustomobject]@{ ProcessId=600; ParentProcessId=1; CreationDate=1; Name='tool.exe'; ExecutablePath=([IO.Path]::Combine($venv, 'tool.exe')); CommandLine='tool.exe' }
}
$script:live = @(100,200,300,400,500,600)
$script:moduleOwners = @(200,500)
$script:stopped = New-Object 'System.Collections.Generic.List[int]'
function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) $rows.Values | Where-Object { $_.ProcessId -in $script:live } }
function Get-MinhDucVenvModules {
    param($Root)
    $loaded = @{}
    foreach ($processId in $script:moduleOwners) {
        if ($processId -in $script:live) { $loaded[$processId] = [pscustomobject]@{ LoadedVenvModules = @($rust) } }
    }
    return $loaded
}
function Get-Process {
    param($Id,$ErrorAction)
    $process = [pscustomobject]@{ Id=$Id; ProcessName=$rows[$Id].Name; Path=$rows[$Id].ExecutablePath }
    $process | Add-Member ScriptMethod WaitForExit { param($Milliseconds) return $true } -PassThru
}
function Stop-Process {
    param($InputObject,[switch]$Force,$ErrorAction)
    $script:stopped.Add($InputObject.Id)
    $script:live = @($script:live | Where-Object { $_ -ne $InputObject.Id })
}
function Start-Sleep { param($Seconds,$Milliseconds) }

$found = @(Get-MinhDucVenvProcessTree -Venv $venv -ClinicEnv $envPath)
if ($found.Count -ne 6 -or (($found | Where-Object { -not $_.CanStop }).ProcessId | Sort-Object) -join ',' -ne '500,600') {
    throw 'Phân loại sai tiến trình chỉ nạp module hoặc chỉ có executable trong venv.'
}
try { Wait-MinhDucVenvPythonExit -Venv $venv -ClinicEnv $envPath -Seconds 0; throw 'Đã bỏ qua khóa ngoài phạm vi.' }
catch { if ($_.Exception.Message -notmatch 'ngoài phạm vi.*500') { throw } }
if ($script:stopped.Count) { throw 'Đã dừng tiến trình khi còn khóa ngoài phạm vi.' }

$script:live = @(100,200,300,400,500)
$script:moduleOwners = @(200)
$known = @{}
$null = Get-MinhDucVenvProcessTree -Venv $venv -ClinicEnv $envPath -Known $known
$script:live = @(200,300,500)
$orphan = @(Get-MinhDucVenvProcessTree -Venv $venv -ClinicEnv $envPath -Known $known)
if ($orphan.Count -ne 2 -or @($orphan | Where-Object { -not $_.CanStop }).Count) { throw 'Mất cây Python đã xác minh khi tiến trình chuyển tiếp thoát.' }
$script:live = @(100,200,300,400,500)
Wait-MinhDucVenvPythonExit -Venv $venv -ClinicEnv $envPath -Seconds 0
if (($script:stopped | Where-Object { $_ -ne 400 }) -join ',' -ne '300,200,100' -or 400 -notin $script:stopped -or
    ($script:live -join ',') -ne '500') { throw 'Dừng sai thứ tự hoặc dừng nhầm Python khác.' }
Write-Output 'PASS: kiểm module, chặn khóa ngoài phạm vi và dừng tiến trình con trước cha.'

& {
    $updater = Join-Path $PSScriptRoot '../deploy/windows/CapNhat.ps1'
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($updater, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-QuayVe' }, $true)
    Invoke-Expression $definition.Extent.Text
    $events = New-Object 'System.Collections.Generic.List[string]'
    $service = [pscustomobject]@{ Status='Running'; StartMode='Auto'; ProcessId=8704 }
    $service | Add-Member ScriptMethod WaitForStatus { param($Status,$Timeout) if ($this.Status -ne $Status) { throw 'Sai trạng thái dịch vụ.' } }
    $service | Add-Member ScriptMethod Refresh {}
    function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) $service }
    function Invoke-CimMethod {
        param($InputObject,$MethodName,$Arguments,$ErrorAction)
        $events.Add($Arguments.StartMode)
        $service.StartMode = $Arguments.StartMode
        return @{ ReturnValue = 0 }
    }
    function Get-Service { param($Name,$ErrorAction) $service }
    function Stop-Service {
        param($Name,[switch]$Force,$ErrorAction)
        $events.Add('Stop')
        $service.Status = 'Stopped'
    }
    function Start-Service { param($Name,$ErrorAction) $events.Add('Start'); $service.Status = 'Running' }
    function Get-MinhDucVenvProcessTree { param($Venv,$ClinicEnv,$Known) }
    function Write-MinhDucVenvLockDiagnostics { param($Venv,$Context,$ObservedProcesses) }
    function Suspend-MinhDucBackupTasks {}
    function Restore-MinhDucBackupTasks { param($Snapshot) }
    function Assert-MinhDucBackupTaskSnapshot { param($Snapshot,[switch]$RequireBoth) }
    function Wait-MinhDucVenvPythonExit {
        param($Venv,$ClinicEnv,$Known,[switch]$LogLockDiagnostics)
        if ($service.StartMode -ne 'Disabled' -or $service.Status -ne 'Stopped') { throw 'SCM vẫn có thể khởi động lại dịch vụ.' }
        $events.Add('Wait')
        if ($lockOutside) { throw 'Khóa giả lập ngoài phạm vi.' }
    }
    function Test-Path { param($LiteralPath,$PathType) return $true }
    function Invoke-Python { param($Paths,$Arguments,[switch]$Quiet) $events.Add('Python'); return @{Ok=$true} }
    function Read-EnvFile { param($Path) return @{CLINIC_ORIGIN='https://127.0.0.1'} }
    function Wait-Https { param($Origin,$Seconds) return $true }
    $P = @{ Code=$venv; Venv=$venv; VenvPython=$venvPython; ClinicEnv=$envPath }
    $Names = @{ Service='MinhDuc' }
    foreach ($lockOutside in $false,$true) {
        $events.Clear()
        $service.Status = 'Running'; $service.StartMode = 'Auto'
        $State = @{ stopped=$true; code_replaced=$false; venv_moved=$false; migrated=$false; backup_tasks_changed=$false; backup_task_snapshot=@('old') }
        try { Invoke-QuayVe -GuardServiceStartup }
        catch { if (-not $lockOutside -or $_.Exception.Message -notmatch 'Khóa giả lập ngoài phạm vi') { throw } }
        $expected = if ($lockOutside) { 'Disabled,Stop,Wait,Automatic' } else { 'Disabled,Stop,Wait,Python,Automatic,Start' }
        if (($events -join ',') -ne $expected) { throw ('Sai thứ tự khóa và trả chế độ khởi động: ' + ($events -join ',')) }
    }
}
Write-Output 'PASS: chặn khởi động lại khi quay về và trả chế độ cũ cả khi gặp khóa ngoài phạm vi.'
