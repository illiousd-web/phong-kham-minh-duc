# Test real helper definitions with synthetic process objects; never kill a process.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'MinhDuc.Install.psm1'),[ref]$tokens,[ref]$errors)
foreach ($name in @('Test-MinhDucVenvPythonPath','Wait-MinhDucVenvPythonExit','Invoke-MinhDucAccessRetry')) {
    $definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    Invoke-Expression $definition.Extent.Text
}
$venv=Join-Path ([IO.Path]::GetTempPath()) 'fake-clinic/.venv'
$exe=Join-Path $venv 'Scripts/python.exe'
$other=Join-Path ($venv+'-other') 'Scripts/python.exe'
function Start-Sleep { param($Seconds,$Milliseconds) $script:delays.Add(@{Seconds=$Seconds;Milliseconds=$Milliseconds}) }
function Get-CimInstance {
    param($ClassName,$Filter,$ErrorAction)
    $script:queries++
    if ($script:alive -and ($script:case -ne 'Natural' -or $script:queries -eq 1)) { [pscustomobject]@{ProcessId=101;ExecutablePath=$exe} }
    [pscustomobject]@{ProcessId=202;ExecutablePath=$other}
    [pscustomobject]@{ProcessId=303;ExecutablePath=$null}
}
function Get-Process {
    param($Id,$ErrorAction)
    if ($Id -ne 101) { throw 'Touched unrelated PID' }
    $p=[pscustomobject]@{Id=101;Path=$(if($script:case -eq 'Reused'){$other}else{$exe})}
    $p | Add-Member ScriptMethod WaitForExit {param($ms) return $true}
    if ($script:case -eq 'Reused') { $script:alive=$false }
    return $p
}
function Stop-Process { param($InputObject,[switch]$Force,$ErrorAction)
    if ($InputObject.Id -ne 101 -or $InputObject.Path -ne $exe) { throw 'Killed unrelated process' }
    $script:stopped++;$script:alive=$false
}
if (Test-MinhDucVenvPythonPath -ExecutablePath $other -Venv $venv) { throw 'Sibling directory matched' }
if (Test-MinhDucVenvPythonPath -ExecutablePath (Join-Path $venv 'tool.exe') -Venv $venv) { throw 'Other executable matched' }
foreach ($script:case in @('Natural','Timeout','Reused')) {
    $script:alive=$true;$script:queries=0;$script:stopped=0
    $script:delays=New-Object 'System.Collections.Generic.List[object]'
    $seconds=0;if($script:case -eq 'Natural'){$seconds=30}
    Wait-MinhDucVenvPythonExit -Venv $venv -Seconds $seconds
    if (($script:case -eq 'Timeout' -and $script:stopped -ne 1) -or ($script:case -ne 'Timeout' -and $script:stopped -ne 0)) { throw ('Wrong process action: '+$script:case) }
}
foreach ($mode in @('Transient','Denied','Other')) {
    $script:attempts=0;$script:delays=New-Object 'System.Collections.Generic.List[object]';$threw=$false
    try { Invoke-MinhDucAccessRetry {
        $script:attempts++
        if ($mode -eq 'Other') { throw [IO.IOException]::new('synthetic non-access error') }
        if ($mode -eq 'Denied' -or $script:attempts -lt 3) { throw [UnauthorizedAccessException]::new('synthetic access denied') }
    } } catch { $threw=$true }
    $expected=3;if($mode -eq 'Denied'){$expected=5};if($mode -eq 'Other'){$expected=1}
    if($script:attempts -ne $expected -or $threw -ne ($mode -ne 'Transient')){throw ('Wrong retry result: '+$mode)}
    if($script:delays.Count -ne ($expected-1)){throw 'Wrong retry wait count'}
    foreach($delay in $script:delays){if($delay.Seconds -ne 2){throw 'Wrong retry delay'}}
}
Write-Output 'PASS: venv natural exit, timeout kill, unrelated paths, PID reuse; retries 3/5/1 and two-second delays'

# Execute the real updater recovery, including its result/error aggregation.
& {
    $tokens=$null;$errors=$null
    $updater=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'CapNhat.ps1'),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'Updater syntax error'}
    $definition=$updater.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-QuayVe'},$true)
    Invoke-Expression $definition.Extent.Text
    function Get-Service {param($Name,$ErrorAction)
        $s=[pscustomobject]@{Status=$script:serviceStatus}
        $s | Add-Member ScriptMethod WaitForStatus {param($status,$timeout) if($script:serviceStatus -ne $status){throw 'Wrong service wait order'}}
        $s | Add-Member ScriptMethod Refresh {$this.Status=$script:serviceStatus}
        return $s
    }
    function Stop-Service {param($Name,[switch]$Force,$ErrorAction) $script:serviceStatus='Stopped'}
    function Start-Service {param($Name,$ErrorAction) $script:serviceStatus='Running'}
    function Wait-MinhDucVenvPythonExit {param($Venv)
        if($script:serviceStatus -ne 'Stopped'){throw 'Process wait before service stopped'}
        $script:pythonWaited=$true
    }
    function Invoke-Native {param($FilePath,$Arguments,[switch]$Quiet,$OkCodes)
        if(-not $script:pythonWaited){throw 'Copy before Python exit wait'}
        $script:copies++
        if($script:alwaysFail -or $script:copies -le 2){return [pscustomobject]@{Ok=$false;Code=16}}
        Copy-Item -Path (Join-Path $OldCode '*') -Destination $P.Code -Recurse -Force
        return [pscustomobject]@{Ok=$true;Code=1}
    }
    function Invoke-Python {param($Paths,$Arguments,[switch]$Quiet) return [pscustomobject]@{Ok=$true;Code=0}}
    function Read-EnvFile {param($Path) return @{CLINIC_ORIGIN='https://127.0.0.1:8443'}}
    function Wait-Https {param($Origin,$Seconds) return $true}
    $root=Join-Path ([IO.Path]::GetTempPath()) ('robocopy-fake-'+[guid]::NewGuid().ToString('N'))
    try {
        foreach($script:alwaysFail in @($false,$true)) {
            $caseRoot=Join-Path $root ([string]$script:alwaysFail)
            $OldCode=Join-Path $caseRoot 'old'
            $P=[pscustomobject]@{Code=(Join-Path $caseRoot 'live');Venv=(Join-Path $caseRoot '.venv');VenvPython=(Join-Path $caseRoot 'fake.exe');ClinicEnv='fake'}
            foreach($dir in @((Join-Path $OldCode 'app'),(Join-Path $P.Code 'app'))){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
            Set-Content (Join-Path $OldCode 'app/main.py') 'old synthetic'
            Set-Content (Join-Path $P.Code 'app/main.py') 'new synthetic'
            Set-Content $P.VenvPython 'never executed'
            $Names=@{Service='fake';ServiceAcct='fake'}
            $State=@{stopped=$true;code_replaced=$true;venv_moved=$false;migrated=$false;backup_tasks_changed=$false;rollback_errors=@()}
            $script:copies=0;$script:pythonWaited=$false;$script:serviceStatus='Running'
            $script:delays=New-Object 'System.Collections.Generic.List[object]'
            $thrown=$false
            try {Invoke-QuayVe} catch {$thrown=$true}
            $expected=3;if($script:alwaysFail){$expected=5}
            if($script:copies -ne $expected -or $thrown -ne $script:alwaysFail){throw 'Wrong robocopy recovery outcome'}
            if($script:delays.Count -ne ($expected-1)){throw 'Wrong robocopy delay count'}
            foreach($delay in $script:delays){if($delay.Seconds -ne 2){throw 'Wrong robocopy delay'}}
            if($script:alwaysFail){
                if(($State.rollback_errors -join ' ') -notmatch 'Chép trả mã nguồn thất bại, mã 16'){throw 'Lost robocopy failure'}
            } elseif($State.rollback_errors.Count){throw 'Transient robocopy errors reported as final failure'}
        }
    } finally {Remove-Item -LiteralPath $root -Recurse -Force}
}
Write-Output 'PASS: real recovery waits for service/Python before copy; robocopy 16,16,1 succeeds; five 16 failures remain failures'
