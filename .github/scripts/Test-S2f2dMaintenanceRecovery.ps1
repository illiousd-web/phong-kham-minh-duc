[CmdletBinding()]
param([string]$InterruptAfter = '', [switch]$AfterDataChange)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ chạy diễn tập trên Windows CI giả lập.'
}
$source = Join-Path $PSScriptRoot '../../deploy/windows'
$step = 'Nạp mô-đun và đọc cấu hình'
try {
    Import-Module (Join-Path $source 'MinhDuc.Install.psm1') -Force -DisableNameChecking
    $paths = Get-MinhDucPaths
    $names = Get-MinhDucNames
    $origin = (Read-EnvFile -Path $paths.ClinicEnv)['CLINIC_ORIGIN']
    if ($InterruptAfter) {
        $step = 'Mở cửa sổ bảo trì'
        $window = Enter-MinhDucMaintenanceWindow -Name $names.Service -Paths $paths -ScriptName 'CapNhat.ps1' -GuardHttps
        $step = 'Khóa dịch vụ, lịch sao lưu và tường lửa'
        Suspend-MinhDucMaintenanceWindow -Window $window
        $step = 'Kiểm tường lửa và HTTPS nội bộ'
        Assert-MinhDucMaintenanceFirewall -Paths $paths
        if (-not (Wait-Https -Origin $origin -Seconds 15 -LocalOnly)) { throw 'Quy tắc bảo trì chặn cả HTTPS gọi từ máy chủ.' }
        $step = 'Dừng dịch vụ và chờ Python thoát'
        Stop-MinhDucService -Window $window
        if ($AfterDataChange) {
            $step = 'Ghi giai đoạn da_doi_du_lieu'
            Set-MinhDucUpdatePhase -Window $window -Phase da_doi_du_lieu
        }
        $step = 'Ghi tệp ready'
        [IO.File]::WriteAllText($InterruptAfter, 'ready')
        $step = 'Ngắt tiến trình thử'
        [Diagnostics.Process]::GetCurrentProcess().Kill()
        throw 'Tiến trình thử chưa bị ngắt.'
    }
} catch {
    if ($InterruptAfter) {
        $detail = @("PowerShell $($PSVersionTable.PSVersion), bước $step", $_.Exception.Message, $_.ScriptStackTrace)
        Set-Content -LiteralPath ($InterruptAfter + '.error.txt') -Value $detail -Encoding UTF8 -ErrorAction Continue
    }
    throw
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
    $stderr = Join-Path $dir 'worker-stderr.txt'
    $worker = Start-Process -FilePath $engine -ArgumentList $workerArgs -RedirectStandardError $stderr -PassThru
    if (-not $worker.WaitForExit(300000)) { throw 'Tiến trình thử bảo trì chưa thoát.' }
    if ($worker.ExitCode -eq 0) { throw 'Tiến trình con trả mã 0. Diễn tập phải kết thúc bằng gián đoạn.' }
    if (-not (Test-Path -LiteralPath $ready -PathType Leaf)) { throw "Tiến trình con trả mã $($worker.ExitCode) trước khi có tệp ready." }
    if (Test-Path -LiteralPath ($ready + '.error.txt')) { throw "Tiến trình con báo lỗi với mã $($worker.ExitCode)." }
    $marker = Read-MinhDucServiceStartModeMarker $names.Service $paths
    if (-not $marker) { throw 'Thiếu tệp đánh dấu sau khi tiến trình con bị ngắt.' }
    if ($marker.Status -ne 'dang_bao_tri') { throw "Status trong dấu là '$($marker.Status)', cần dang_bao_tri." }
    if ($marker.FirewallRule -ne $names.FirewallMaintenance) { throw "FirewallRule trong dấu là '$($marker.FirewallRule)', cần '$($names.FirewallMaintenance)'." }
    if ($marker.TaskEnabled.($names.BackupTask) -ne $true) { throw "TaskEnabled của lịch '$($names.BackupTask)' phải lưu True." }
    if ($marker.TaskEnabled.$catchup -ne $false) { throw "TaskEnabled của lịch '$catchup' phải lưu False." }
    $startType = (Get-Service -Name $names.Service).StartType
    if ($startType -ne 'Disabled') { throw "StartType dịch vụ là $startType, cần Disabled." }
    foreach ($name in @($names.BackupTask, $catchup)) {
        $task = Get-MinhDucScheduledTask -Name $name
        if (-not $task -or $task.Settings.Enabled -or $task.State -ne 'Disabled') { throw "Lịch '$name' chưa ở trạng thái Disabled trong cửa sổ bảo trì." }
    }
    Assert-MinhDucMaintenanceFirewall -Paths $paths

    $phase = if ($AfterDataChange) { 'da_doi_du_lieu' } else { 'chua_doi_du_lieu' }
    if ($marker.Phase -ne $phase) { throw "Dấu lưu sai giai đoạn $phase." }
    $report = Join-Path $dir 'report.txt'
    if ($AfterDataChange) {
        $hash = (Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash
        $tasks = @(Get-MinhDucBackupTaskSnapshot)
        & (Join-Path $source 'KiemTra.ps1') -KhongHoi -ThuMucMa $dir -TepKetQua $report
        if ($LASTEXITCODE -ne 1) { throw "KIEM_TRA trả mã $LASTEXITCODE, cần mã 1 sau khi dữ liệu đã đổi." }
        if ((Get-Content -LiteralPath $report -Raw -Encoding UTF8) -notmatch
            '\[KHÔNG ĐẠT\].*Cập nhật bị ngắt sau khi đã thay dữ liệu.*KHÔNG dùng phần mềm.*người hỗ trợ') {
            throw 'KIEM_TRA chưa báo KHÔNG ĐẠT do cập nhật bị ngắt sau khi đã thay dữ liệu.'
        }
        if (-not (Test-Path -LiteralPath $paths.ServiceStartModePending -PathType Leaf)) { throw 'KIEM_TRA đã xóa tệp đánh dấu.' }
        if ((Get-FileHash -LiteralPath $paths.ServiceStartModePending).Hash -ne $hash) { throw 'KIEM_TRA đã sửa tệp đánh dấu.' }
        $after = Read-MinhDucServiceStartModeMarker $names.Service $paths
        if ($after.Phase -ne 'da_doi_du_lieu') { throw 'Phase sau KIEM_TRA phải là da_doi_du_lieu.' }
        $service = Get-Service -Name $names.Service
        if ($service.StartType -ne 'Disabled') { throw "KIEM_TRA đã đổi StartType thành $($service.StartType)." }
        if ($service.Status -ne 'Stopped') { throw "Dịch vụ là $($service.Status) sau KIEM_TRA, cần Stopped." }
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
} catch {
    Write-Host ('Diễn tập: ' + $_.Exception.Message)
    $childError = $ready + '.error.txt'
    if (Test-Path -LiteralPath $childError) {
        Get-Content -LiteralPath $childError -Encoding UTF8 | ForEach-Object { Write-Host "Tiến trình con: $_" }
    } elseif ($stderr -and (Test-Path -LiteralPath $stderr)) {
        Get-Content -LiteralPath $stderr | ForEach-Object { Write-Host "Tiến trình con: $_" }
    }
    throw
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
