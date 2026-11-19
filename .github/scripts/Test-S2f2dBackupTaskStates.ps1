[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Capture','Rollback','Success')][string]$Mode,
    [switch]$DisableCatchup,
    [switch]$ResetCatchup
)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:OS -ne 'Windows_NT' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ kiểm tra lịch trên bản cài Windows CI giả lập.'
}
Import-Module C:\MinhDuc\deploy\windows\MinhDuc.Install.psm1 -Force -DisableNameChecking
$daily = (Get-MinhDucNames).BackupTask
$catchup = $daily + ' - Chay bu'
$record = Join-Path $env:RUNNER_TEMP 's2f2d-enabled-before.json'
if ($Mode -eq 'Capture') {
    if ($DisableCatchup) { Disable-ScheduledTask -TaskName $catchup -TaskPath '\' -ErrorAction Stop | Out-Null }
    $before = @(Get-MinhDucBackupTaskSnapshot)
    if ($DisableCatchup) {
        if ($before.Count -ne 2 -or @($before | Where-Object { $_.Enabled }).Count -ne 1) {
            throw 'Cần một lịch đang bật và một lịch đang tắt trước cập nhật.'
        }
    } elseif ($before.Count -ne 1 -or $before[0].Name -ne $daily) {
        throw 'Cần đúng một lịch hằng ngày kiểu cũ trước cập nhật.'
    }
    ConvertTo-Json -InputObject $before | Set-Content -LiteralPath $record -Encoding UTF8
    return
}

$before = Get-Content -LiteralPath $record -Raw -Encoding UTF8 | ConvertFrom-Json
$expected = @{}
foreach ($task in $before) { $expected[$task.Name] = $task.Enabled }
if ($Mode -eq 'Rollback') {
    Assert-MinhDucBackupTaskSnapshot -Snapshot $before -RequireBoth
} elseif (-not $expected.ContainsKey($catchup)) {
    # Lịch chạy bù mới có trạng thái mặc định bật. Lịch hằng ngày giữ trạng thái gốc.
    $expected[$catchup] = $true
}
$after = @(Get-MinhDucBackupTaskSnapshot)
if ($after.Count -ne $expected.Count) { throw 'Số lịch sao lưu sau cập nhật không khớp.' }
foreach ($task in $after) {
    if (-not $expected.ContainsKey($task.Name) -or $task.Enabled -ne $expected[$task.Name]) {
        throw "Trạng thái Enabled không khớp sau cập nhật cho $($task.Name)."
    }
}
if ($ResetCatchup) { Enable-ScheduledTask -TaskName $catchup -TaskPath '\' -ErrorAction Stop | Out-Null }
Write-Output "PASS: $Mode trả đúng trạng thái Enabled của từng lịch."
