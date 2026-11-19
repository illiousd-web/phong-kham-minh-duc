# Destructive fault drills ONLY on the synthetic hosted Windows CI installation.
[CmdletBinding()]
param([ValidateSet('Database','Service')][string]$Mode)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) { throw 'CI-only synthetic recovery drill; do not run on a clinic machine.' }
Import-Module C:\MinhDuc\deploy\windows\MinhDuc.Install.psm1 -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
if ($Mode -eq 'Database') {
    & (Join-Path $PSScriptRoot '../../tests/Test-VenvRollbackTree.ps1') -RealVenvLock
}
$serviceKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\' + $names.Service
$startupBefore = Get-ItemProperty -LiteralPath $serviceKey
$backupTasksBefore = @(Get-MinhDucBackupTaskSnapshot)
try {
    Suspend-MinhDucBackupTasks -WaitForIdle
    $backupTasksBeforeDisabled = @(Get-MinhDucBackupTaskSnapshot)
    Assert-MinhDucBackupTaskSnapshot -Snapshot $backupTasksBeforeDisabled -Disabled -RequireBoth
} finally { Restore-MinhDucBackupTasks -Snapshot $backupTasksBefore -RequireBoth }
$files = @((Join-Path $paths.Code 'scripts\install_db.py'), (Join-Path $paths.Code 'app\main.py'))
$original = @{}
foreach ($file in $files) { $original[$file] = [IO.File]::ReadAllBytes($file) }
$failedResult = $null
$origin = (Read-EnvFile -Path $paths.ClinicEnv)['CLINIC_ORIGIN']
$beforeResult = Invoke-Python -Paths $paths -Quiet -Arguments @('-m','scripts.install_db','--clinic-env',$paths.ClinicEnv,'--owner-env',$paths.OwnerEnv,'fingerprint')
if (-not $beforeResult.Ok) { throw 'Cannot capture pre-drill database fingerprint' }
$before = ConvertFrom-PythonJson $beforeResult
try {
    if ($Mode -eq 'Database') {
        $file = $files[0]
        $source = [IO.File]::ReadAllText($file)
        $needle = "            result = rollback_database("
        if (-not $source.Contains($needle)) { throw 'Rollback CLI injection location missing' }
        # This source is captured in the OLD-code snapshot. The real CLI will exit 23.
        [IO.File]::WriteAllText($file, $source.Replace($needle, ("            return 23  # CI rollback failure`n" + $needle)), (New-Object Text.UTF8Encoding($false)))
    } else {
        # The running old process remains healthy until stopped; the copied-back old
        # source will then fail to start, proving that Wait-Https gates the result.
        [IO.File]::AppendAllText($files[1], "`nraise RuntimeError('CI old service cannot start')`n", (New-Object Text.UTF8Encoding($false)))
    }
    $resultPath = Join-Path $paths.Updates 'ket-qua-cap-nhat.json'
    Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
    $attempt = Invoke-Native -FilePath 'cmd.exe' -Arguments @('/c',(Join-Path $paths.Code 'deploy\windows\CAP_NHAT.bat'),'-KhongHoi','-TepZip',(Join-Path $env:RUNNER_TEMP 'minhduc-broken.zip')) -Quiet -WorkingDirectory $paths.Code
    Write-Output ('Fault-drill child exit: ' + $attempt.Code)
    $attempt.Output | ForEach-Object { Write-Output $_ }
    # Read the recovery record before asserting the exit code so CI cleanup can
    # restore the exact backup even when a wrapper exit-code assertion fails.
    $failedResult = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    Write-Output ('Fault-drill recovery status: ' + $failedResult.status)
    $failedResult.rollback_errors | ForEach-Object { Write-Output ('Recovery error: ' + $_) }
    if ($attempt.Code -eq 0) { throw 'Failed recovery must have a nonzero process exit' }
    if ($failedResult.status -ne 'quay_ve_that_bai') { throw ('Recovery falsely reported: ' + $failedResult.status) }
    if (@($failedResult.rollback_errors).Count -eq 0) { throw 'Recovery did not retain failed steps' }
    if ($Mode -eq 'Database' -and ($failedResult.rollback_errors -join ' ') -notmatch '23') { throw 'CLI exit 23 was not recorded as a recovery failure' }
    if ($Mode -eq 'Service' -and ($failedResult.rollback_errors -join ' ') -notmatch 'HTTPS') { throw 'Service/HTTPS failure was not recorded' }
    $service = Get-Service -Name $names.Service
    $marker = Read-MinhDucServiceStartModeMarker $names.Service $paths
    if ($service.StartType -ne 'Disabled' -or $service.Status -ne 'Stopped' -or $marker.Status -ne 'quay_ve_that_bai') {
        throw 'Failed rollback did not keep the service disabled and its marker locked'
    }
    $tasks = @(Get-MinhDucBackupTaskSnapshot)
    if ($tasks.Count -ne $backupTasksBefore.Count) { throw 'Backup tasks disappeared during failed rollback' }
    foreach ($item in $tasks) {
        $task = Get-MinhDucScheduledTask -Name $item.Name
        if ($task.State -ne 'Disabled' -or $task.Settings.Enabled) { throw 'Failed rollback enabled a backup task' }
    }
    Assert-MinhDucMaintenanceFirewall -Paths $paths
    $markerHash = (Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash
    $report = Join-Path $env:RUNNER_TEMP ('kiem-tra-quay-ve-that-bai-' + $Mode + '.txt')
    & (Join-Path $paths.Code 'deploy/windows/KiemTra.ps1') -KhongHoi -TepKetQua $report
    $check = Get-Content -LiteralPath $report -Raw -Encoding UTF8
    if ($LASTEXITCODE -ne 1 -or $check -notmatch '\[KHÔNG ĐẠT\].*quay_ve_that_bai.*người hỗ trợ' -or
        (Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash -ne $markerHash -or
        (Get-Service -Name $names.Service).StartType -ne 'Disabled') { throw 'KIEM_TRA must report failure and keep the update locked' }
    Assert-MinhDucBackupTaskSnapshot -Snapshot $tasks -Disabled
    Assert-MinhDucMaintenanceFirewall -Paths $paths
    Write-Output ('PASS: ' + $Mode + ' fault -> quay_ve_that_bai and nonzero exit, with failed steps retained')
} catch {
    Write-Output ('PRIMARY FAULT-DRILL FAILURE: ' + $_.Exception.Message)
    throw
} finally {
    # Repair the disposable test VM explicitly; this is not product auto-recovery.
    $lock = Open-MinhDucServiceStartModeLock $paths.MaintenanceLockBase
    try {
        $marker = Read-MinhDucServiceStartModeMarker $names.Service $paths
        if (-not $marker) { throw 'Expected the fault drill to leave a marker for manual recovery' }
        Set-Service -Name $names.Service -StartupType Disabled -ErrorAction Stop
        Stop-Service -Name $names.Service -ErrorAction Stop
        Wait-MinhDucVenvPythonExit -Venv $paths.Venv -ClinicEnv $paths.ClinicEnv
        Suspend-MinhDucBackupTasks -WaitForIdle
        foreach ($file in $files) { [IO.File]::WriteAllBytes($file, $original[$file]) }
        if ($null -ne $failedResult -and $failedResult.backup) {
            $restored = Invoke-Python -Paths $paths -Quiet -Arguments @('-m','scripts.install_db','--clinic-env',$paths.ClinicEnv,'--owner-env',$paths.OwnerEnv,'--super-env',$paths.SuperEnv,'rollback','--file',$failedResult.backup,'--key',$paths.BackupKey)
            if (-not $restored.Ok) { throw 'Manual CI repair could not restore database' }
            Set-SecureAcl -Path $paths.Attachments -Directory -Writers @($names.ServiceAcct)
            if (Test-Path -LiteralPath $paths.Settings) { Set-SecureAcl -Path $paths.Settings -Directory -Writers @($names.ServiceAcct) }
        }
        Restore-MinhDucBackupTasks -Snapshot $backupTasksBeforeDisabled -Disabled -RequireBoth
        Set-Service -Name $names.Service -StartupType Manual -ErrorAction Stop
        Start-Service -Name $names.Service -ErrorAction Stop
        if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { throw 'Manual CI repair did not bring HTTPS back' }
        # Giữ lịch tắt đến khi HTTPS đạt, rồi trả và kiểm đầy đủ XML gốc.
        Restore-MinhDucServiceStartMode $names.Service $paths 'CapNhat.ps1' -VerifiedRollback -BackupTaskSnapshot $backupTasksBefore | Out-Null
    } finally { $lock.Dispose() }
    $startupAfter = Get-ItemProperty -LiteralPath $serviceKey
    if ($startupBefore.Start -ne $startupAfter.Start -or $startupBefore.DelayedAutoStart -ne $startupAfter.DelayedAutoStart) {
        throw 'The rollback did not restore the original service startup configuration'
    }
    Assert-MinhDucBackupTaskSnapshot -Snapshot $backupTasksBefore -RequireBoth
    $afterResult = Invoke-Python -Paths $paths -Quiet -Arguments @('-m','scripts.install_db','--clinic-env',$paths.ClinicEnv,'--owner-env',$paths.OwnerEnv,'fingerprint')
    if (-not $afterResult.Ok -or (ConvertFrom-PythonJson $afterResult).sha256 -ne $before.sha256) { throw 'Manual CI repair changed schema/functions/ACLs' }
    if (-not (Test-MinhDucBackupTasks -Paths $paths)) { throw 'Backup tasks changed during failed recovery' }
    & C:\MinhDuc\.venv\Scripts\python.exe .github\scripts\windows_e2e.py login
    if ($LASTEXITCODE) { throw 'Login failed after manual CI repair' }
    Write-Output 'PASS: disposable CI installation repaired and verified after fault drill'
}
