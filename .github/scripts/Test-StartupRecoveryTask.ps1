# Dùng Task Scheduler và dịch vụ thật trên máy Windows CI dùng dữ liệu giả lập.
[CmdletBinding()]
param([ValidateSet('Registration','PrepareUpdate','Recover')][string]$Mode = 'Recover')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ diễn tập tự gỡ bảo trì trên Windows CI giả lập.'
}
Import-Module C:\MinhDuc\deploy\windows\MinhDuc.Install.psm1 -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
$taskName = $names.StartupRecoveryTask
$task = Get-MinhDucScheduledTask -Name $taskName
if (-not $task -or -not $task.Settings.Enabled) { throw 'Thiếu tác vụ tự gỡ bảo trì đang bật.' }
if ($Mode -eq 'PrepareUpdate') {
    Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
    return
}

$actions = @($task.Actions)
$triggers = @($task.Triggers)
if ($actions.Count -ne 1 -or $actions[0].Execute -ne (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -or
    $actions[0].Arguments -notlike '*-File "C:\MinhDuc\deploy\windows\TuGoBaoTri.ps1"*' -or $actions[0].WorkingDirectory -ne $paths.Code -or
    $triggers.Count -ne 1 -or $triggers[0].CimClass.CimClassName -ne 'MSFT_TaskBootTrigger' -or $triggers[0].Delay -ne 'PT1M' -or
    ($triggers[0].Repetition -and $triggers[0].Repetition.Interval) -or $task.Settings.RestartCount -gt 0 -or
    [Xml.XmlConvert]::ToTimeSpan($task.Settings.ExecutionTimeLimit) -ne [timespan]::FromMinutes(15) -or
    $task.Principal.UserId -notin @('SYSTEM','S-1-5-18','NT AUTHORITY\SYSTEM') -or $task.Principal.LogonType -ne 'ServiceAccount') {
    throw 'Sai cấu hình tác vụ tự gỡ bảo trì đã đăng ký.'
}
Write-Output 'PASS: đã đăng ký tác vụ SYSTEM lúc bật máy, trễ 1 phút, giới hạn 15 phút.'
if ($Mode -eq 'Registration') { return }

$origin = (Read-EnvFile -Path $paths.ClinicEnv)['CLINIC_ORIGIN']
$pending = $paths.ServiceStartModePending
$logPath = Join-Path $paths.Journal 'tu-go-bao-tri.log'
$serviceName = $names.Service
$delayed = Get-MinhDucDelayedAutoStart $serviceName
$backupTasks = @(Get-MinhDucBackupTaskSnapshot)
$service = Get-Service -Name $serviceName
if ((Test-Path -LiteralPath $pending) -or $service.StartType -ne 'Automatic' -or $service.Status -ne 'Running' -or $backupTasks.Count -ne 2) {
    throw 'Cần bản cài CI đang chạy với đủ lịch sao lưu và chưa có dấu bảo trì.'
}
$work = Join-Path $env:RUNNER_TEMP ('tu-go-bao-tri-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$worker = $null
try {
    foreach ($phase in 'chua_doi_du_lieu','da_doi_du_lieu') {
        $blocked = $phase -eq 'da_doi_du_lieu'
        $ready = Join-Path $work $phase
        # Dùng tiến trình diễn tập hiện có để khóa, dừng dịch vụ thật rồi bị ngắt.
        $drill = Join-Path $PSScriptRoot 'Test-S2f2dMaintenanceRecovery.ps1'
        $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $drill + '"'), '-InterruptAfter', ('"' + $ready + '"'))
        if ($blocked) { $arguments += '-AfterDataChange' }
        $worker = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -PassThru
        if (-not $worker.WaitForExit(300000)) { throw 'Tiến trình diễn tập chưa thoát.' }
        if ($worker.ExitCode -eq 0 -or -not (Test-Path -LiteralPath $ready -PathType Leaf)) {
            if (Test-Path -LiteralPath ($ready + '.error.txt')) { Get-Content -LiteralPath ($ready + '.error.txt') -Encoding UTF8 | Out-Host }
            throw "Chưa mô phỏng gián đoạn ở $phase."
        }
        $marker = Read-MinhDucServiceStartModeMarker $serviceName $paths
        $service = Get-Service -Name $serviceName
        if ($marker.Phase -ne $phase -or $marker.Status -ne 'dang_bao_tri' -or
            $service.StartType -ne 'Disabled' -or $service.Status -ne 'Stopped' -or
            -not (Get-MinhDucScheduledTask -Name $taskName).Settings.Enabled) {
            throw "Trạng thái bảo trì trước khi chạy tác vụ không đúng ở $phase."
        }
        $hash = (Get-FileHash -LiteralPath $pending).Hash
        $disabledTasks = @(Get-MinhDucBackupTaskSnapshot)
        Assert-MinhDucBackupTaskSnapshot -Snapshot $disabledTasks -Disabled -RequireBoth
        Assert-MinhDucMaintenanceFirewall -Paths $paths

        $logCount = if (Test-Path -LiteralPath $logPath) { @(Get-Content -LiteralPath $logPath -Encoding UTF8).Count } else { 0 }
        $previous = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
        Start-ScheduledTask -TaskName $taskName -TaskPath '\'
        $deadline = (Get-Date).AddSeconds(150)
        do {
            Start-Sleep -Milliseconds 300
            $run = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
            $state = (Get-MinhDucScheduledTask -Name $taskName).State
            $lines = if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Encoding UTF8 }
            $completed = @($lines).Count -gt $logCount -and $run.LastRunTime -ne $previous.LastRunTime -and
                $state -eq 'Ready' -and $run.LastTaskResult -ne 267009
        } until ($completed -or (Get-Date) -ge $deadline)
        if (-not $completed) { throw "Task Scheduler chưa hoàn tất diễn tập ở $phase (mã $($run.LastTaskResult), trạng thái $state)." }
        $lastLine = @($lines)[-1]
        $service = Get-Service -Name $serviceName
        if ($blocked) {
            if ($run.LastTaskResult -ne 1 -or $lastLine -notmatch 'Phase=da_doi_du_lieu Status=dang_bao_tri.*Cập nhật bị ngắt sau khi đã thay dữ liệu' -or
                (Get-FileHash -LiteralPath $pending).Hash -ne $hash -or $service.StartType -ne 'Disabled' -or $service.Status -ne 'Stopped') {
                throw 'Tác vụ đã đổi trạng thái khóa hoặc báo sai kết quả sau khi đổi dữ liệu.'
            }
            Assert-MinhDucBackupTaskSnapshot -Snapshot $disabledTasks -Disabled -RequireBoth
            Assert-MinhDucMaintenanceFirewall -Paths $paths
        } else {
            if ($run.LastTaskResult -ne 0 -or $lastLine -notmatch 'Phase=chua_doi_du_lieu Status=dang_bao_tri.*HTTPS nội bộ đạt' -or
                (Test-Path -LiteralPath $pending) -or $service.StartType -ne 'Automatic' -or $service.Status -ne 'Running' -or
                (Get-MinhDucDelayedAutoStart $serviceName) -ne $delayed -or
                (Get-MinhDucMaintenanceFirewall $names.FirewallMaintenance ActiveStore) -or
                (Get-MinhDucMaintenanceFirewall $names.FirewallMaintenance PersistentStore) -or
                -not (Wait-Https -Origin $origin -Seconds 15 -LocalOnly)) {
                throw 'Tác vụ chưa trả đủ cấu hình hoặc HTTPS chưa đạt trước mốc đổi dữ liệu.'
            }
            Assert-MinhDucBackupTaskSnapshot -Snapshot $backupTasks -RequireBoth
        }
        Write-Output "PASS: Start-ScheduledTask ở $phase. $lastLine"
    }
} finally {
    try {
        if ($worker -and -not $worker.HasExited) { $worker.Kill(); $worker.WaitForExit() }
        if ((Get-MinhDucScheduledTask -Name $taskName).State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName -TaskPath '\' }
        $lock = Open-MinhDucServiceStartModeLock $paths.MaintenanceLockBase
        try {
            $left = Read-MinhDucServiceStartModeMarker $serviceName $paths
            if ($left -and $left.Phase -eq 'da_doi_du_lieu') {
                # Diễn tập chỉ ghi mốc, không thay mã hay dữ liệu trên VM.
                $left.Phase = 'chua_doi_du_lieu'
                Write-MinhDucServiceStartModeMarker $pending $left -Replace
            }
        } finally { $lock.Dispose() }
        Resume-MinhDucServiceStartMode -Paths $paths -ScriptName 'Test-StartupRecoveryTask.ps1' | Out-Null
        Start-Service -Name $serviceName
        if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { throw 'HTTPS chưa chạy lại sau diễn tập.' }
    } finally { Remove-Item -LiteralPath $work -Recurse -Force }
}
$global:LASTEXITCODE = 0
