# Execute the real recovery function against synthetic files and command doubles.
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'CapNhat.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Updater parse failed' }
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-QuayVe' }, $true)
Invoke-Expression $definition.Extent.Text
function Invoke-Native {
    param($FilePath, $Arguments, [switch]$Quiet, $OkCodes)
    if ($script:mode -eq 'Code') { return [pscustomobject]@{ Ok = $false; Code = 16; Output = @() } }
    Copy-Item -Path (Join-Path $OldCode '*') -Destination $P.Code -Recurse -Force
    return [pscustomobject]@{ Ok = $true; Code = 1; Output = @() }
}
function Invoke-Python {
    param($Paths, $Arguments, [switch]$Quiet)
    if ($Arguments -contains 'rollback') {
        $script:calls.Add('Database')
        if ($script:mode -in @('Database','DatabaseAndTasks')) { return [pscustomobject]@{ Ok = $false; Code = 23; Output = @() } }
        $script:fp = 'baseline'
    }
    return [pscustomobject]@{ Ok = $true; Code = 0; Output = @() }
}
function Get-Fingerprint { return $script:fp }
function Set-SecureAcl { param($Path, [switch]$Directory, $Writers) }
function Restore-MinhDucBackupTasks {
    param($Snapshot)
    $script:calls.Add('Tasks')
    if ($script:mode -in @('Tasks','DatabaseAndTasks')) { throw 'Lỗi lịch giả lập' }
}
function Stop-Service { param($Name, [switch]$Force, $ErrorAction)
    if ($script:mode -eq 'Stop') { throw 'Không dừng được dịch vụ giả lập' }
    $script:serviceStatus = 'Stopped'
}
function Start-Service { param($Name, $ErrorAction) $script:serviceStatus = 'Running' }
function Get-Service {
    param($Name, $ErrorAction)
    $value = [pscustomobject]@{ Status = $script:serviceStatus }
    $value | Add-Member ScriptMethod WaitForStatus { param($status,$timeout) $this.Status = $script:serviceStatus }
    $value | Add-Member ScriptMethod Refresh { $this.Status = $script:serviceStatus }
    return $value
}
function Read-EnvFile { param($Path) return @{ CLINIC_ORIGIN = 'https://127.0.0.1:8443' } }
function Wait-Https { param($Origin,$Seconds) $script:calls.Add('Https'); return ($script:mode -ne 'Service') }
$root = Join-Path ([IO.Path]::GetTempPath()) ('s1-rollback-fake-' + [guid]::NewGuid().ToString('N'))
try {
    foreach ($script:mode in @('Success','Code','Venv','Database','Tasks','Service','DatabaseAndTasks','Stop')) {
        $homeForCase = Join-Path $root $script:mode
        $OldCode = Join-Path $homeForCase 'old'
        $P = [pscustomobject]@{ Code = (Join-Path $homeForCase 'live'); Venv = (Join-Path $homeForCase 'live\.venv'); VenvPython = (Join-Path $homeForCase 'live\.venv\Scripts\python.exe'); ClinicEnv = 'fake'; OwnerEnv = 'fake'; SuperEnv = 'fake'; Attachments = (Join-Path $homeForCase 'attachments'); Settings = (Join-Path $homeForCase 'settings'); BackupKey = 'fake' }
        $OldVenv = Join-Path $P.Code '.venv-cu'
        foreach ($folder in @((Join-Path $OldCode 'app'),(Join-Path $P.Code 'app'),(Join-Path $OldVenv 'Scripts'),(Join-Path $P.Venv 'Scripts'),$P.Attachments,$P.Settings)) { New-Item -ItemType Directory -Force -Path $folder | Out-Null }
        Set-Content -LiteralPath (Join-Path $OldCode 'app\main.py') -Value 'synthetic old'
        Set-Content -LiteralPath (Join-Path $P.Code 'app\main.py') -Value 'synthetic new'
        Set-Content -LiteralPath (Join-Path $OldVenv 'Scripts\python.exe') -Value 'fake executable; never launched'
        if ($script:mode -eq 'Venv') { Remove-Item -LiteralPath $OldVenv -Recurse -Force }
        $State = @{ stopped = $true; code_replaced = $true; venv_moved = $true; migrated = $true; backup_tasks_changed = $true; backup_task_snapshot = @(); backup = 'fake'; fingerprint = 'baseline'; rollback_errors = @() }
        $Names = @{ Service = 'S1-Fake'; ServiceAcct = 'S1-Fake' }
        $script:fp = 'modified'
        $script:serviceStatus = 'Running'
        $script:calls = New-Object System.Collections.Generic.List[string]
        $thrown = $false
        try { Invoke-QuayVe } catch { $thrown = $true }
        if (($script:mode -eq 'Success') -eq $thrown) { throw ('Incorrect success/failure result: ' + $script:mode) }
        if ($script:mode -ne 'Success' -and $State.rollback_errors.Count -eq 0) { throw 'Failure was swallowed' }
        if (-not $script:calls.Contains('Tasks')) { throw 'Recovery stopped before attempting independent task restoration' }
        if ($script:mode -eq 'DatabaseAndTasks' -and $State.rollback_errors.Count -lt 2) { throw 'Recovery did not retain all failures' }
    }
    Write-Output 'PASS: recovery checks code, venv, database, tasks, stop/start and HTTPS; aggregates failures'
} finally { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue }
