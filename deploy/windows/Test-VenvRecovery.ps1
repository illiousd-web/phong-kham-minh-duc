# Test real helper definitions with synthetic process objects; never kill a process.
$ErrorActionPreference='Stop'
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
