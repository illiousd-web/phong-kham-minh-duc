# Real Task Scheduler regressions on the disposable hosted Windows installer VM.
[CmdletBinding()]
param([ValidateSet('Legacy','New','Restored')][string]$Mode)
$ErrorActionPreference = 'Stop'
Import-Module C:\MinhDuc\deploy\windows\MinhDuc.Install.psm1 -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
$record = Join-Path $env:RUNNER_TEMP 's1-legacy-backup-task.xml'
if ($Mode -eq 'Legacy') {
    $daily = Get-ScheduledTask -TaskName $names.BackupTask -TaskPath '\' -ErrorAction Stop
    $legacyArguments = $daily.Actions[0].Arguments.Replace('--daily','--scheduled')
    foreach ($old in @(Get-MinhDucBackupTaskSnapshot)) {
        Unregister-ScheduledTask -TaskName $old.Name -TaskPath '\' -Confirm:$false -ErrorAction Stop
    }
    $action = New-ScheduledTaskAction -Execute $paths.VenvPython -Argument $legacyArguments -WorkingDirectory $paths.Code
    $trigger = New-ScheduledTaskTrigger -Daily -At '20:00'
    $principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $names.BackupTask -TaskPath '\' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $old = @(Get-MinhDucBackupTaskSnapshot)
    if ($old.Count -ne 1 -or $legacyArguments -notmatch '--scheduled') { throw 'Expected exactly one legacy scheduled task' }
    [IO.File]::WriteAllText($record, $old[0].Xml, (New-Object Text.UTF8Encoding($true)))
    $fingerprint = & C:\MinhDuc\.venv\Scripts\python.exe -m scripts.install_db --clinic-env C:\ProgramData\MinhDuc\clinic.env --owner-env C:\ProgramData\MinhDuc\quantri\owner.env fingerprint
    if ($LASTEXITCODE) { throw 'Cannot capture database fingerprint before update' }
    [IO.File]::WriteAllText((Join-Path $env:RUNNER_TEMP 's1-before-update-fingerprint.json'), ($fingerprint | Out-String), (New-Object Text.UTF8Encoding($false)))
    Write-Output 'PASS: seeded exactly one old --scheduled daily task'
} elseif ($Mode -eq 'Restored') {
    $actual = @(Get-MinhDucBackupTaskSnapshot)
    $expected = [IO.File]::ReadAllText($record)
    if ($actual.Count -ne 1 -or (Get-MinhDucBackupTaskSignature $actual[0].Xml) -ne (Get-MinhDucBackupTaskSignature $expected)) {
        throw 'Registration failure did not restore the exact old task actions/triggers/settings/principal'
    }
    $result = Get-Content C:\ProgramData\MinhDuc\capnhat\ket-qua-cap-nhat.json -Raw | ConvertFrom-Json
    if ($result.status -ne 'da_quay_ve') { throw ('Expected failed update with rollback: ' + $result.status) }
    & C:\MinhDuc\.venv\Scripts\python.exe .github\scripts\windows_e2e.py login
    if ($LASTEXITCODE) { throw 'Login failed after task-registration rollback' }
    $before = Get-Content (Join-Path $env:RUNNER_TEMP 's1-before-update-fingerprint.json') -Raw | ConvertFrom-Json
    $afterText = & C:\MinhDuc\.venv\Scripts\python.exe -m scripts.install_db --clinic-env C:\ProgramData\MinhDuc\clinic.env --owner-env C:\ProgramData\MinhDuc\quantri\owner.env fingerprint
    if ($LASTEXITCODE) { throw 'Cannot check database fingerprint after rollback' }
    $after = ($afterText | Out-String) | ConvertFrom-Json
    if ($before.sha256 -ne $after.sha256) { throw 'Rollback left changed function definitions or ACLs in the database' }
    Write-Output 'PASS: failed registration restored the old task, function definitions/ACLs and running service'
} else {
    if (-not (Test-MinhDucBackupTasks -Paths $paths)) { throw 'Two-task action/trigger verification failed' }
    Write-Output 'PASS: exactly two new tasks, daily 20:00 and startup catchup, verified from real scheduler'
}
