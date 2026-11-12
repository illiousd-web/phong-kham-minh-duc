# Destructive fault drills ONLY on the synthetic hosted Windows CI installation.
[CmdletBinding()]
param([ValidateSet('Database','Service')][string]$Mode)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) { throw 'CI-only synthetic recovery drill; do not run on a clinic machine.' }
Import-Module C:\MinhDuc\deploy\windows\MinhDuc.Install.psm1 -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
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
    if ($attempt.Code -eq 0) { throw 'Failed recovery must have a nonzero process exit' }
    $failedResult = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if ($failedResult.status -ne 'quay_ve_that_bai') { throw ('Recovery falsely reported: ' + $failedResult.status) }
    if (@($failedResult.rollback_errors).Count -eq 0) { throw 'Recovery did not retain failed steps' }
    if ($Mode -eq 'Database' -and ($failedResult.rollback_errors -join ' ') -notmatch '23') { throw 'CLI exit 23 was not recorded as a recovery failure' }
    if ($Mode -eq 'Service' -and ($failedResult.rollback_errors -join ' ') -notmatch 'HTTPS') { throw 'Service/HTTPS failure was not recorded' }
    Write-Output ('PASS: ' + $Mode + ' fault -> quay_ve_that_bai and nonzero exit, with failed steps retained')
} finally {
    # Repair the disposable test VM explicitly; this is not product auto-recovery.
    $service = Get-Service -Name $names.Service -ErrorAction Stop
    if ($service.Status -ne 'Stopped') { Stop-Service -Name $names.Service -Force -ErrorAction Stop }
    $service.WaitForStatus('Stopped', (New-TimeSpan -Seconds 30))
    foreach ($file in $files) { [IO.File]::WriteAllBytes($file, $original[$file]) }
    if ($null -ne $failedResult -and $failedResult.backup) {
        $restored = Invoke-Python -Paths $paths -Quiet -Arguments @('-m','scripts.install_db','--clinic-env',$paths.ClinicEnv,'--owner-env',$paths.OwnerEnv,'--super-env',$paths.SuperEnv,'rollback','--file',$failedResult.backup,'--key',$paths.BackupKey)
        if (-not $restored.Ok) { throw 'Manual CI repair could not restore database' }
        Set-SecureAcl -Path $paths.Attachments -Directory -Writers @($names.ServiceAcct)
        if (Test-Path -LiteralPath $paths.Settings) { Set-SecureAcl -Path $paths.Settings -Directory -Writers @($names.ServiceAcct) }
    }
    Start-Service -Name $names.Service -ErrorAction Stop
    if (-not (Wait-Https -Origin $origin -Seconds 120)) { throw 'Manual CI repair did not bring HTTPS back' }
    $afterResult = Invoke-Python -Paths $paths -Quiet -Arguments @('-m','scripts.install_db','--clinic-env',$paths.ClinicEnv,'--owner-env',$paths.OwnerEnv,'fingerprint')
    if (-not $afterResult.Ok -or (ConvertFrom-PythonJson $afterResult).sha256 -ne $before.sha256) { throw 'Manual CI repair changed schema/functions/ACLs' }
    if (-not (Test-MinhDucBackupTasks -Paths $paths)) { throw 'Backup tasks changed during failed recovery' }
    & C:\MinhDuc\.venv\Scripts\python.exe .github\scripts\windows_e2e.py login
    if ($LASTEXITCODE) { throw 'Login failed after manual CI repair' }
    Write-Output 'PASS: disposable CI installation repaired and verified after fault drill'
}
