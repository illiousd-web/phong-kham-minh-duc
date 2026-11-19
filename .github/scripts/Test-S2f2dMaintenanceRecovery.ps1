[CmdletBinding()]
param([string]$InterruptAfter = '', [switch]$AfterDataChange)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ chạy diễn tập trên Windows CI giả lập.'
}
$source = Join-Path $PSScriptRoot '../../deploy/windows'
Import-Module (Join-Path $source 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
$origin = (Read-EnvFile -Path $paths.ClinicEnv)['CLINIC_ORIGIN']
if ($InterruptAfter) {
    $window = Enter-MinhDucMaintenanceWindow -Name $names.Service -Paths $paths -ScriptName 'CapNhat.ps1' -GuardHttps
    Suspend-MinhDucMaintenanceWindow -Window $window
    Assert-MinhDucMaintenanceFirewall -Paths $paths
    if (-not (Wait-Https -Origin $origin -Seconds 15 -LocalOnly)) { throw 'Quy tắc bảo trì chặn cả HTTPS gọi từ máy chủ.' }
    Stop-MinhDucService -Window $window
    if ($AfterDataChange) { Set-MinhDucUpdatePhase -Window $window -Phase da_doi_du_lieu }
    [IO.File]::WriteAllText($InterruptAfter, 'ready')
    [Diagnostics.Process]::GetCurrentProcess().Kill()
    throw 'Tiến trình thử chưa bị ngắt.'
}

$catchup = $names.BackupTask + ' - Chay bu'
$delayed = Get-MinhDucDelayedAutoStart $names.Service
$dir = Join-Path $env:RUNNER_TEMP ('minhduc-interrupted-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $dir | Out-Null
$ready = Join-Path $dir 'ready'
$worker = $null
try {
    Disable-ScheduledTask -TaskName $catchup -TaskPath '\' | Out-Null
    $engine = (Get-Process -Id $PID).Path
    $workerArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        ('"' + $PSCommandPath + '"'), '-InterruptAfter', ('"' + $ready + '"'))
    if ($AfterDataChange) { $workerArgs += '-AfterDataChange' }
    $worker = Start-Process -FilePath $engine -ArgumentList $workerArgs -PassThru
    if (-not $worker.WaitForExit(45000)) { throw 'Tiến trình thử bảo trì chưa thoát.' }
    $marker = Read-MinhDucServiceStartModeMarker $names.Service $paths
    if ($worker.ExitCode -eq 0 -or -not (Test-Path -LiteralPath $ready) -or $marker.Status -ne 'dang_bao_tri' -or
        $marker.FirewallRule -ne $names.FirewallMaintenance -or -not $marker.TaskEnabled.($names.BackupTask) -or $marker.TaskEnabled.$catchup -or
        (Get-Service -Name $names.Service).StartType -ne 'Disabled') { throw 'Chưa mô phỏng được gián đoạn giữa bảo trì.' }
    foreach ($name in @($names.BackupTask, $catchup)) {
        if ((Get-MinhDucScheduledTask -Name $name).Settings.Enabled) { throw 'Lịch vẫn bật trong cửa sổ bảo trì.' }
    }
    Assert-MinhDucMaintenanceFirewall -Paths $paths

    $phase = if ($AfterDataChange) { 'da_doi_du_lieu' } else { 'chua_doi_du_lieu' }
    if ($marker.Phase -ne $phase) { throw "Dấu lưu sai giai đoạn $phase." }
    $report = Join-Path $dir 'report.txt'
    if ($AfterDataChange) {
        $hash = (Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash
        $tasks = @(Get-MinhDucBackupTaskSnapshot)
        & (Join-Path $source 'KiemTra.ps1') -KhongHoi -ThuMucMa $dir -TepKetQua $report
        if ($LASTEXITCODE -ne 1 -or (Get-Content -LiteralPath $report -Raw -Encoding UTF8) -notmatch
            '\[KHÔNG ĐẠT\].*Cập nhật bị ngắt sau khi đã thay dữ liệu.*KHÔNG dùng phần mềm.*người hỗ trợ' -or
            (Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash -ne $hash -or
            (Get-Service -Name $names.Service).StartType -ne 'Disabled' -or (Get-Service -Name $names.Service).Status -ne 'Stopped') {
            throw 'KIEM_TRA không được mở bảo trì khi cập nhật bị ngắt sau lúc thay dữ liệu.'
        }
        Assert-MinhDucBackupTaskSnapshot -Snapshot $tasks -Disabled -RequireBoth
        Assert-MinhDucMaintenanceFirewall -Paths $paths
        Write-Output 'PASS: KIEM_TRA giữ nguyên dấu, dịch vụ, lịch và tường lửa sau gián đoạn ở da_doi_du_lieu.'
        $global:LASTEXITCODE = 0
        return
    }
    # Thư mục mã trống: KIEM_TRA phải trả đủ cấu hình mà không cần Python.
    & (Join-Path $source 'KiemTra.ps1') -KhongHoi -ThuMucMa $dir -TepKetQua $report
    if ($LASTEXITCODE -ne 2 -or (Get-Content -LiteralPath $report -Raw -Encoding UTF8) -notmatch '\[ĐẠT\] Dịch vụ web.*Đã trả' -or
        (Get-Service -Name $names.Service).StartType -ne 'Automatic' -or (Get-MinhDucDelayedAutoStart $names.Service) -ne $delayed -or
        -not (Get-MinhDucScheduledTask -Name $names.BackupTask).Settings.Enabled -or (Get-MinhDucScheduledTask -Name $catchup).Settings.Enabled -or
        (Test-Path -LiteralPath $paths.ServiceStartModePending) -or (Get-MinhDucMaintenanceFirewall $names.FirewallMaintenance ActiveStore)) {
        throw 'KIEM_TRA chưa trả đủ dịch vụ, DelayedAutoStart, lịch và tường lửa.'
    }
    Write-Output 'PASS: HTTPS nội bộ qua quy tắc thật, gián đoạn bảo trì và KIEM_TRA trả trạng thái gốc với một lịch vốn tắt.'
} finally {
    try {
        if ($worker -and -not $worker.HasExited) { $worker.Kill(); $worker.WaitForExit() }
        if ($AfterDataChange) {
            # Chỉ diễn tập mốc ghi dấu. Mã, venv và CSDL thật của máy CI chưa bị thay.
            $lock = Open-MinhDucServiceStartModeLock $paths.MaintenanceLockBase
            try {
                $left = Read-MinhDucServiceStartModeMarker $names.Service $paths
                if ($left -and $left.Phase -eq 'da_doi_du_lieu') {
                    $left.Phase = 'chua_doi_du_lieu'
                    Write-MinhDucServiceStartModeMarker $paths.ServiceStartModePending $left -Replace
                }
            } finally { $lock.Dispose() }
        }
        Resume-MinhDucServiceStartMode -Paths $paths -ScriptName 'KiemTra.ps1' | Out-Null
        Enable-ScheduledTask -TaskName $catchup -TaskPath '\' | Out-Null
        Start-Service -Name $names.Service
        if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { throw 'Không khởi động lại được HTTPS sau diễn tập.' }
    } finally { Remove-Item -LiteralPath $dir -Recurse -Force }
}
