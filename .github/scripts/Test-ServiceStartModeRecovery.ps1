[CmdletBinding()]
param([switch]$Interrupt)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ mô phỏng mất điện trên máy Windows CI giả lập.'
}
Import-Module C:\MinhDuc\deploy\windows\MinhDuc.Install.psm1 -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$name = (Get-MinhDucNames).Service
$pending = $paths.ServiceStartModePending
if ($Interrupt) {
    Invoke-WithMinhDucServiceStartupDisabled -Name $name -Paths $paths -ScriptName 'GiaHanChungChi.ps1' -Action {
        Stop-Service -Name $name -ErrorAction Stop
        (Get-Service -Name $name).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
        [Diagnostics.Process]::GetCurrentProcess().Kill()
    }
    throw 'Tiến trình kiểm thử chưa bị ngắt.'
}

$before = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$name"
if ($before.Start -ne 2 -or $before.DelayedAutoStart -ne 1 -or (Get-Service -Name $name).Status -ne 'Running' -or
    (Test-Path -LiteralPath $pending)) { throw 'Cần dịch vụ đang chạy với chế độ Automatic (Delayed Start) và chưa có dấu.' }

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Interrupt
    $childExit = $LASTEXITCODE
    $disabled = Get-Service -Name $name
    if ($childExit -eq 0 -or $disabled.Status -ne 'Stopped' -or $disabled.StartType -ne 'Disabled' -or
        -not (Test-Path -LiteralPath $pending)) { throw 'Tiến trình chưa bị ngắt giữa lúc khóa dịch vụ.' }

    $report = Join-Path $env:RUNNER_TEMP 'kiem-tra-sau-mat-dien.txt'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\MinhDuc\deploy\windows\KiemTra.ps1 -KhongHoi -TepKetQua $report
    if ($LASTEXITCODE -ne 1) { throw 'KIEM_TRA phải báo dịch vụ còn dừng trong kiểm tra sức khỏe.' }
    $after = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$name"
    if ($after.Start -ne $before.Start -or $after.DelayedAutoStart -ne $before.DelayedAutoStart -or
        (Test-Path -LiteralPath $pending)) { throw 'Chưa trả đúng cấu hình khởi động hoặc còn tệp đánh dấu.' }
    $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8
    $log = Get-Content -LiteralPath (Join-Path $paths.Journal 'service-startmode.log') -Raw -Encoding UTF8
    if ($result -notmatch '\[ĐẠT\] Dịch vụ web không bị vô hiệu hóa' -or $log -notmatch 'KiemTra\.ps1.*GiaHanChungChi\.ps1') {
        throw 'Chưa xác nhận khôi phục trong báo cáo và nhật ký.'
    }
    Write-Output 'PASS: ngắt PowerShell khi MinhDuc đang Disabled, KIEM_TRA trả Automatic (Delayed Start) và xóa dấu.'
} finally {
    if (Test-Path -LiteralPath $pending) { Resume-MinhDucServiceStartMode -Paths $paths -ScriptName $MyInvocation.MyCommand.Name | Out-Null }
    Start-Service -Name $name -ErrorAction Stop
    (Get-Service -Name $name).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
}
$global:LASTEXITCODE = 0
