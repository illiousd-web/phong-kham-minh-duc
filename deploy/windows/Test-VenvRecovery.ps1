# Test real helper definitions with synthetic process objects; never kill a process.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'MinhDuc.Install.psm1'),[ref]$tokens,[ref]$errors)
foreach ($name in @('Test-MinhDucVenvPythonPath','Wait-MinhDucVenvPythonExit','Invoke-MinhDucAccessRetry','Suspend-MinhDucBackupTasks','Get-MinhDucPythonScriptLabel')) {
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
    if ($script:alive -and ($script:case -ne 'Natural' -or $script:queries -eq 1)) { [pscustomobject]@{ProcessId=101;ExecutablePath=$exe;CommandLine='python.exe -m scripts.backup_job --password abc --token sensitive-token --key secret-key -c hidden-code postgresql://hidden-uri'} }
    [pscustomobject]@{ProcessId=202;ExecutablePath=$other}
    [pscustomobject]@{ProcessId=303;ExecutablePath=$null}
}
function Get-Process {
    param($Id,$ErrorAction)
    if ($Id -ne 101) { throw 'Touched unrelated PID' }
    $p=[pscustomobject]@{Id=101;ProcessName='python';Path=$(if($script:case -eq 'Reused'){$other}else{$exe})}
    $p | Add-Member ScriptMethod WaitForExit {param($ms) return $true}
    if ($script:case -eq 'Reused') { $script:alive=$false }
    return $p
}
function Write-Luu {param($Message) $script:killLog=$Message}
function Stop-Process { param($InputObject,[switch]$Force,$ErrorAction)
    if ($InputObject.Id -ne 101 -or $InputObject.Path -ne $exe) { throw 'Killed unrelated process' }
    $script:stopped++;$script:alive=$false
}
if (Test-MinhDucVenvPythonPath -ExecutablePath $other -Venv $venv) { throw 'Sibling directory matched' }
if (Test-MinhDucVenvPythonPath -ExecutablePath (Join-Path $venv 'tool.exe') -Venv $venv) { throw 'Other executable matched' }
foreach ($script:case in @('Natural','Timeout','Reused')) {
    $script:alive=$true;$script:queries=0;$script:stopped=0
    $script:delays=New-Object 'System.Collections.Generic.List[object]'
    $script:killLog=''
    $seconds=0;if($script:case -eq 'Natural'){$seconds=30}
    Wait-MinhDucVenvPythonExit -Venv $venv -Seconds $seconds
    if (($script:case -eq 'Timeout' -and $script:stopped -ne 1) -or ($script:case -ne 'Timeout' -and $script:stopped -ne 0)) { throw ('Wrong process action: '+$script:case) }
    if($script:case -eq 'Timeout' -and ($script:killLog -notmatch 'PID=101' -or $script:killLog -notmatch 'scripts.backup_job' -or $script:killLog -match 'abc|sensitive-token|secret-key|hidden-code|hidden-uri|postgresql://')){throw 'Missing killed backup PID/command line log'}
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
    $capture=$updater.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Save-InitialBackupTaskSnapshot'},$true)
    Invoke-Expression $capture.Extent.Text
    function Get-Service {param($Name,$ErrorAction)
        $s=[pscustomobject]@{Status=$script:serviceStatus}
        $s | Add-Member ScriptMethod WaitForStatus {param($status,$timeout) if($script:serviceStatus -ne $status){throw 'Wrong service wait order'}}
        $s | Add-Member ScriptMethod Refresh {$this.Status=$script:serviceStatus}
        return $s
    }
    function Stop-Service {param($Name,[switch]$Force,$ErrorAction) $script:serviceStatus='Stopped'}
    function Start-Service {param($Name,$ErrorAction) $script:serviceStatus='Running'}
    $script:Names=@{BackupTask='fake-daily'}
    foreach($helper in @('Get-MinhDucScheduledTask','Get-MinhDucBackupTaskSnapshot','Get-MinhDucBackupTaskSignature','Restore-MinhDucBackupTasks','Assert-MinhDucBackupTaskSnapshot')) {
        $found=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $helper},$true)
        Invoke-Expression $found.Extent.Text
    }
    function Get-ScheduledTask { [CmdletBinding()]param($TaskName,$TaskPath)
        if($script:taskCase -eq 'Scheduler'){throw [UnauthorizedAccessException]::new('scheduler denied')}
        if(-not $script:tasks.ContainsKey($TaskName)){
            $PSCmdlet.ThrowTerminatingError([Management.Automation.ErrorRecord]::new([Exception]::new('missing'),'MSFT_ScheduledTask_NotFound',[Management.Automation.ErrorCategory]::ObjectNotFound,$TaskName))
        }
        return $script:tasks[$TaskName]
    }
    function Export-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) $script:snapshotReads++;return $script:tasks[$TaskName].Xml}
    function Disable-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) $script:disabled++;$script:tasks[$TaskName].Settings.Enabled=$false }
    function Enable-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) $script:enabled.Add($TaskName);$script:tasks[$TaskName].Settings.Enabled=$true }
    function Register-ScheduledTask {param($TaskName,$TaskPath,$Xml,[switch]$Force,$ErrorAction)
        $script:registrations++
        if(($script:taskCase -eq 'RegisterSecond' -and $script:registrations -eq 2) -or ($script:taskCase -eq 'RegisterFirst' -and $script:registrations -eq 1)){throw 'register second failed'}
        $script:tasks[$TaskName]=[pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true};Xml=$Xml}
    }
    function Unregister-ScheduledTask {param($TaskName,$TaskPath,$Confirm,$ErrorAction) $script:removals++;$script:tasks.Remove($TaskName)}
    function Wait-MinhDucVenvPythonExit {param($Venv)
        if($script:serviceStatus -ne 'Stopped'){throw 'Process wait before service stopped'}
        if($script:disabled -ne 2){throw 'Python wait before backup schedules disabled'}
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
        foreach($script:taskCase in @('Normal','CopyFailure','RegisterSecond','RegisterFirst','Scheduler','NoDaily','Legacy')) {
            $script:alwaysFail=$script:taskCase -eq 'CopyFailure'
            $caseRoot=Join-Path $root $script:taskCase
            $OldCode=Join-Path $caseRoot 'old'
            $P=[pscustomobject]@{Code=(Join-Path $caseRoot 'live');Venv=(Join-Path $caseRoot '.venv');VenvPython=(Join-Path $caseRoot 'fake.exe');ClinicEnv='fake'}
            foreach($dir in @((Join-Path $OldCode 'app'),(Join-Path $P.Code 'app'))){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
            Set-Content (Join-Path $OldCode 'app/main.py') 'old synthetic'
            Set-Content (Join-Path $P.Code 'app/main.py') 'new synthetic'
            Set-Content $P.VenvPython 'never executed'
            $Names=@{Service='fake';ServiceAcct='fake';BackupTask='fake-daily'}
            $State=@{stopped=$true;code_replaced=$true;venv_moved=$false;migrated=$false;backup_tasks_changed=$false;backup_tasks_captured=$false;backup_task_snapshot=@();rollback_errors=@()}
            $script:tasks=@{}
            foreach($taskName in @('fake-daily','fake-daily - Chay bu')){
                $script:tasks[$taskName]=[pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true};Xml=('<Task><Actions>'+ $taskName +'</Actions><Triggers/><Settings><Enabled>true</Enabled></Settings><Principals/></Task>')}
            }
            if($script:taskCase -eq 'NoDaily'){$script:tasks.Remove('fake-daily')}
            if($script:taskCase -eq 'Legacy'){$script:tasks.Remove('fake-daily - Chay bu')}
            $script:enabled=New-Object 'System.Collections.Generic.List[string]'
            $script:registrations=0;$script:removals=0
            $script:disabled=0;$script:copies=0;$script:pythonWaited=$false;$script:serviceStatus='Running'
            $script:delays=New-Object 'System.Collections.Generic.List[object]'
            $thrown=$false
            try {
                $script:snapshotReads=0
                Save-InitialBackupTaskSnapshot
                $reads=$script:snapshotReads
                $saved=@($State.backup_task_snapshot)
                if($script:taskCase -eq 'Legacy'){
                    $script:tasks['fake-daily - Chay bu']=[pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true};Xml='<Task><Actions>new task from failed update</Actions><Triggers/><Settings/><Principals/></Task>'}
                }
                Save-InitialBackupTaskSnapshot
                if($script:snapshotReads -ne $reads -or $State.backup_task_snapshot.Count -ne $saved.Count){throw 'Snapshot was recaptured'}
                Invoke-QuayVe
                if($script:taskCase -eq 'Legacy' -and $script:tasks.Count -ne 1){throw 'Legacy layout not restored exactly'}
            } catch {$thrown=$true}
            $expected=3;if($script:alwaysFail){$expected=5}
            if($script:taskCase -in @('Scheduler','NoDaily')) {
                if(-not $thrown -or $script:copies -ne 0){throw 'Scheduler error incorrectly accepted'}
                continue
            }
            if($script:taskCase -in @('RegisterSecond','RegisterFirst')){
                if(-not $thrown -or -not $script:tasks.ContainsKey('fake-daily') -or $script:removals -ne 0){throw 'Registration failure removed working task or reported recovery success'}
                if($script:enabled.Count -ne 2 -or -not $script:enabled.Contains('fake-daily') -or -not $script:enabled.Contains('fake-daily - Chay bu')){throw 'Not every surviving task was enabled'}
                if(($State.rollback_errors -join ' ') -notmatch 'register second failed'){throw 'Original registration error was lost'}
                if($script:serviceStatus -ne 'Running'){throw 'Scheduler failure blocked web service'}
                continue
            }
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

# Inspect argument ASTs, not flags in comments.
$copyCount=0
foreach($file in @('CaiDat.ps1','CapNhat.ps1')) {
    $tokens=$null;$errors=$null
    $tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ('Parse error: '+$file)}
    $commands=$tree.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Invoke-Native' -and ($n.CommandElements | Where-Object {$_.Value -eq 'robocopy.exe'})},$true)
    foreach($command in $commands){
        $copyCount++
        $args=@($command.FindAll({param($n) $n -is [Management.Automation.Language.StringConstantExpressionAst]},$true) | ForEach-Object {$_.Value})
        $retry='/R:2';$wait='/W:2'
        if($command.Extent.Text.Contains('$OldCode, $P.Code')){$retry='/R:0';$wait='/W:0'}
        if(@($args | Where-Object {$_ -like '/R:*'}).Count -ne 1 -or @($args | Where-Object {$_ -like '/W:*'}).Count -ne 1 -or $args -notcontains $retry -or $args -notcontains $wait){throw ('Invalid robocopy bounds: '+$command.Extent.Text)}
    }
}
if($copyCount -ne 4){throw ('Expected four robocopy calls, got '+$copyCount)}
Write-Output 'PASS: four robocopy AST argument bounds; backup schedules disabled before Python wait; killed backup PID/command line logged'

foreach($command in @('python.exe --password abc --token secret --key private -c hidden postgresql://hidden','python.exe -c "abc password"','python.exe -m scripts.backup_job --password=abc')) {
    $safe=Get-MinhDucPythonScriptLabel $command
    if($safe -match 'abc|secret|private|hidden|postgresql://'){throw 'Sensitive argument leaked'}
}
Write-Output 'PASS: missing/denied scheduler fail closed; second registration preserves first task and fails recovery; logs omit secrets'

$tokens=$null;$errors=$null
$flow=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'CapNhat.ps1'),[ref]$tokens,[ref]$errors)
$assignments=$flow.FindAll({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$State.backup_task_snapshot'},$true)
if($assignments.Count -ne 1){throw 'More than one snapshot assignment in updater'}
$text=$flow.Extent.Text
if($text.IndexOf('    Save-InitialBackupTaskSnapshot') -gt $text.IndexOf("Write-Buoc 'Bước 1/8")){throw 'Snapshot captured too late'}
Write-Output 'PASS: one pre-update snapshot capture, no recapture; exact legacy one-task and modern two-task restore'
