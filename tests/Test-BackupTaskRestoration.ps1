# Exercise real snapshot, suspension, verification and release logic with scheduler XML exports.
$ErrorActionPreference = 'Stop'
$module = Import-Module (Join-Path $PSScriptRoot '../deploy/windows/MinhDuc.Install.psm1') -Force -DisableNameChecking -PassThru
& $module {
    $daily = (Get-MinhDucNames).BackupTask
    $catchup = $daily + ' - Chay bu'
    $fixture = @{ Tasks = @{}; Mode = 'Auto'; Firewall = $false }
    function Get-MinhDucScheduledTask { param($Name) $fixture.Tasks[$Name] }
    function Export-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $fixture.Tasks[$TaskName].Xml }
    function Register-ScheduledTask {
        param($TaskName, $TaskPath, $Xml, [switch]$Force, $ErrorAction)
        [xml]$doc = $Xml
        $settings = $doc.Task.Settings
        $enabledNode = $settings.SelectSingleNode('Enabled')
        $enabled = -not $enabledNode -or $enabledNode.InnerText -ne 'false'
        if ($enabledNode) { [void]$settings.RemoveChild($enabledNode) }
        if (-not $enabled) {
            # Model an export that omits default Enabled=true and emits false in its own order.
            $node = $doc.CreateElement('Enabled')
            $node.InnerText = 'false'
            [void]$settings.InsertBefore($node, $settings.SelectSingleNode('Hidden'))
        }
        $fixture.Tasks[$TaskName] = [pscustomobject]@{
            Settings = @{ Enabled = $enabled }; Xml = $doc.OuterXml
            State = if ($enabled) { 'Ready' } else { 'Disabled' }
        }
    }
    function Disable-ScheduledTask {
        param($TaskName, $TaskPath, $ErrorAction)
        Register-ScheduledTask -TaskName $TaskName -Xml (ConvertTo-MinhDucDisabledTaskXml $fixture.Tasks[$TaskName].Xml)
    }
    function Enable-ScheduledTask {
        param($TaskName, $TaskPath, $ErrorAction)
        [xml]$doc = $fixture.Tasks[$TaskName].Xml
        $settings = $doc.Task.Settings
        $node = $settings.SelectSingleNode('Enabled')
        if ($node) { [void]$settings.RemoveChild($node) }
        Register-ScheduledTask -TaskName $TaskName -Xml $doc.OuterXml
    }
    function Unregister-ScheduledTask { param($TaskName, $TaskPath, $Confirm, $ErrorAction) $fixture.Tasks.Remove($TaskName) }
    function Suspend-MinhDucBackupTasks {
        param([switch]$WaitForIdle)
        foreach ($name in @($fixture.Tasks.Keys)) { Disable-ScheduledTask -TaskName $name }
    }
    function Get-CimInstance { param($ClassName, $Filter, $ErrorAction) @{ StartMode = $fixture.Mode } }
    function Invoke-CimMethod {
        param($InputObject, $MethodName, $Arguments, $ErrorAction)
        $fixture.Mode = if ($Arguments.StartMode -eq 'Automatic') { 'Auto' } else { $Arguments.StartMode }
        return @{ ReturnValue = 0 }
    }
    function Get-MinhDucDelayedAutoStart { param($Name) return $false }
    function Enable-MinhDucMaintenanceFirewall { param($Paths) $fixture.Firewall = $true }
    function Remove-MinhDucMaintenanceFirewall { param($Name) $fixture.Firewall = $false }

    $dir = New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ('minhduc-task-xml-' + [guid]::NewGuid()))
    $paths = @{
        Journal = $dir.FullName
        ServiceStartModePending = Join-Path $dir.FullName 'pending.json'
        MaintenanceLockBase = Join-Path $dir.FullName 'pending.json'
    }
    $oldXml = '<Task><Actions><Exec><Arguments>--scheduled</Arguments></Exec></Actions><Triggers><CalendarTrigger/></Triggers><Settings><StartWhenAvailable>true</StartWhenAvailable><Hidden>false</Hidden></Settings><Principals><Principal id="old"/></Principals></Task>'
    $newXml = $oldXml.Replace('--scheduled', '--daily').Replace('>true<', '>false<').Replace('id="old"', 'id="new"')
    try {
        foreach ($layout in 'LegacyEnabled', 'LegacyDisabled', 'Mixed') {
            foreach ($rollback in $true, $false) {
                $fixture.Tasks.Clear()
                Register-ScheduledTask -TaskName $daily -Xml $oldXml
                if ($layout -eq 'LegacyDisabled') { Disable-ScheduledTask -TaskName $daily }
                if ($layout -eq 'Mixed') { Register-ScheduledTask -TaskName $catchup -Xml (ConvertTo-MinhDucDisabledTaskXml $oldXml) }
                $original = @(Get-MinhDucBackupTaskSnapshot)
                $window = Enter-MinhDucMaintenanceWindow -Name (Get-MinhDucNames).Service -Paths $paths -ScriptName 'CapNhat.ps1' -GuardHttps
                try {
                    Suspend-MinhDucMaintenanceWindow -Window $window
                    $suspended = $window.SuspendedBackupTasks
                    Set-MinhDucUpdatePhase -Window $window -Phase da_doi_du_lieu
                    foreach ($name in $daily, $catchup) {
                        Register-ScheduledTask -TaskName $name -Xml (ConvertTo-MinhDucDisabledTaskXml $newXml)
                    }
                    if ($rollback) {
                        Suspend-MinhDucMaintenanceWindow -Window $window
                        Set-MinhDucRollbackPending -Window $window
                        Restore-MinhDucBackupTasks -Snapshot $window.SuspendedBackupTasks -Disabled
                        Assert-MinhDucBackupTaskSnapshot -Snapshot $suspended -Disabled -RequireBoth
                        if (-not $fixture.Firewall -or $fixture.Mode -ne 'Disabled') { throw 'Đã mở bảo trì trước kiểm HTTPS.' }
                        Resume-MinhDucMaintenanceWindow -Window $window -VerifiedRollback -BackupTaskSnapshot $original
                        Assert-MinhDucBackupTaskSnapshot -Snapshot $original -RequireBoth
                    } else {
                        Set-MinhDucUpdatePhase -Window $window -Phase da_chot
                        Resume-MinhDucMaintenanceWindow -Window $window
                        if ($fixture.Tasks.Count -ne 2 -or $fixture.Tasks[$catchup].Settings.Enabled -ne ($layout -ne 'Mixed')) {
                            throw 'Trạng thái lịch chạy bù sau cập nhật không đúng.'
                        }
                    }
                    foreach ($task in $original) {
                        if ($fixture.Tasks[$task.Name].Settings.Enabled -ne $task.Enabled) {
                            throw "Sai trạng thái Enabled sau ca $layout, rollback=$rollback."
                        }
                    }
                    if ($rollback -and $layout -eq 'Mixed') {
                        foreach ($state in 'Running', 'Queued') {
                            $fixture.Tasks[$daily].State = $state
                            Assert-MinhDucBackupTaskSnapshot -Snapshot $original -RequireBoth
                        }
                        # State và Settings.Enabled phải nhất quán với XML cũ.
                        foreach ($invalid in @(
                            @{ Name = $daily; State = 'Unknown'; Enabled = $true },
                            @{ Name = $daily; State = 'Running'; Enabled = $false },
                            @{ Name = $catchup; State = 'Queued'; Enabled = $false }
                        )) {
                            $task = $fixture.Tasks[$invalid.Name]
                            $task.State = $invalid.State
                            $task.Settings.Enabled = $invalid.Enabled
                            $rejected = $false
                            try { Assert-MinhDucBackupTaskSnapshot -Snapshot $original -RequireBoth }
                            catch { $rejected = $_.Exception.Message -like 'Lịch sao lưu chưa *' }
                            if (-not $rejected) { throw "Đã nhận lịch không hợp lệ $($invalid.Name): $($invalid.State), Enabled=$($invalid.Enabled)." }
                            $old = $original | Where-Object Name -eq $invalid.Name
                            Register-ScheduledTask -TaskName $old.Name -Xml $old.Xml
                        }
                    }
                } finally { Exit-MinhDucMaintenanceWindow -Window $window -KeepPending }
            }
        }
    } finally { Remove-Item -LiteralPath $dir.FullName -Recurse -Force }
    Write-Output 'PASS: scheduler XML round-trip, legacy and mixed Enabled states after rollback and success'
}
