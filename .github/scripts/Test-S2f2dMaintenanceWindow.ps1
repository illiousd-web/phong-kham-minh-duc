# Diễn tập chỉ chạy trên máy Windows CI chứa dữ liệu giả lập.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ chạy diễn tập bảo trì trên Windows CI giả lập.'
}
$source = Join-Path $PSScriptRoot '../../deploy/windows'
Import-Module (Join-Path $source 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
$zip = Join-Path $env:RUNNER_TEMP 'minhduc-ok.zip'
$resultFile = Join-Path $paths.Updates 'ket-qua-cap-nhat.json'
$fixture = Join-Path $env:RUNNER_TEMP ('minhduc-maintenance-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $fixture | Out-Null
function Write-Fixture([string]$File, [string]$Needle, [string]$Insertion) {
    $text = [IO.File]::ReadAllText((Join-Path $fixture $File))
    if (-not $text.Contains($Needle)) { throw ('Thiếu điểm chèn kiểm thử trong ' + $File) }
    [IO.File]::WriteAllText((Join-Path $fixture $File), $text.Replace($Needle, ($Needle + [Environment]::NewLine + $Insertion)), [Text.UTF8Encoding]::new($true))
}
function Assert-ServiceAndTasksRestored {
    $service = Get-Service -Name $names.Service
    if ($service.Status -ne 'Running' -or $service.StartType -ne 'Automatic' -or
        (Test-Path -LiteralPath $paths.ServiceStartModePending)) {
        throw 'Dịch vụ hoặc dấu khôi phục chưa về trạng thái ban đầu.'
    }
    $tasks = @(Get-MinhDucBackupTaskSnapshot)
    if ($tasks.Count -ne 2) { throw 'Thiếu lịch sao lưu sau bảo trì.' }
    Assert-MinhDucBackupTaskSnapshot -Snapshot $tasks -RequireBoth
}

$worker = $null
try {
    foreach ($file in @('CapNhat.ps1', 'GiaHanChungChi.ps1', 'MinhDuc.Install.psm1', 'DanhMucGoc.ps1')) {
        Copy-Item -LiteralPath (Join-Path $source $file) -Destination $fixture
    }
    Write-Fixture 'GiaHanChungChi.ps1' '    $window = Enter-MinhDucMaintenanceWindow -Name $Names.Service -Paths $P -ScriptName ''GiaHanChungChi.ps1''' @'
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'ready'), 'locked')
    $deadline = (Get-Date).AddSeconds(40)
    while (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'release'))) {
        if ((Get-Date) -gt $deadline) { throw 'Ca tranh khóa quá thời gian.' }
        Start-Sleep -Milliseconds 100
    }
    exit 0
'@
    Assert-ServiceAndTasksRestored
    $beforeResult = (Get-FileHash -LiteralPath $resultFile).Hash
    $beforeEnv = (Get-FileHash -LiteralPath $paths.ClinicEnv).Hash
    $beforeCert = (Get-FileHash -LiteralPath (Join-Path $paths.Tls 'server.crt')).Hash
    $beforeUpdates = @(Get-ChildItem -LiteralPath $paths.Updates -Force | Select-Object -ExpandProperty Name)
    $certScript = Join-Path $fixture 'GiaHanChungChi.ps1'
    $updateScript = Join-Path $fixture 'CapNhat.ps1'
    $worker = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $certScript + '"'), '-KhongHoi') -PassThru
    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Path -LiteralPath (Join-Path $fixture 'ready'))) {
        if ($worker.HasExited -or (Get-Date) -gt $deadline) { throw 'GiaHanChungChi chưa lấy được khóa thử.' }
        Start-Sleep -Milliseconds 100
    }
    & $updateScript -KhongHoi -TepZip $zip
    if ($LASTEXITCODE -ne 52 -or $worker.HasExited -or
        (Get-FileHash -LiteralPath $resultFile).Hash -ne $beforeResult -or
        (Get-FileHash -LiteralPath $paths.ClinicEnv).Hash -ne $beforeEnv -or
        (Get-FileHash -LiteralPath (Join-Path $paths.Tls 'server.crt')).Hash -ne $beforeCert -or
        (Compare-Object -ReferenceObject $beforeUpdates -DifferenceObject @(Get-ChildItem -LiteralPath $paths.Updates -Force | Select-Object -ExpandProperty Name))) {
        throw 'CapNhat không từ chối sạch khi GiaHanChungChi giữ khóa.'
    }
    Assert-ServiceAndTasksRestored
    [IO.File]::WriteAllText((Join-Path $fixture 'release'), 'release')
    if (-not $worker.WaitForExit(10000) -or $worker.ExitCode -ne 0) { throw 'Tiến trình gia hạn thử chưa nhả khóa.' }
    Write-Output 'PASS: GiaHanChungChi giữ khóa, CapNhat trả mã 52 và giữ nguyên kết quả trước đó.'

    # Dùng lệnh sao lưu và dịch vụ thật. Chỉ chèn kiểm trạng thái và lỗi báo cáo.
    Write-Fixture 'MinhDuc.Install.psm1' "    `$env:PYTHONDONTWRITEBYTECODE = '1'" @'
    if ($Arguments -contains 'scripts.backup_job') {
        $service = Get-Service -Name $script:Names.Service
        $tasks = @(Get-MinhDucBackupTaskSnapshot)
        if ($service.StartType -ne 'Disabled' -or $service.Status -ne 'Stopped' -or
            $tasks.Count -ne 2 -or $Arguments -notcontains '--no-prune') { throw 'Bảo trì chưa kín ở lệnh sao lưu.' }
        foreach ($item in $tasks) {
            $task = Get-MinhDucScheduledTask -Name $item.Name
            if ($task.State -ne 'Disabled' -or $task.Settings.Enabled) { throw 'Lịch sao lưu còn hoạt động.' }
        }
        if (-not (Test-Path -LiteralPath $Paths.ServiceStartModePending)) { throw 'Thiếu dấu phục hồi startup.' }
        [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'backup-checked'), 'checked')
    }
'@
    Write-Fixture 'CapNhat.ps1' '    Write-Result ''dang_cap_nhat'' $versionDetail' @'
    if ((Get-Service -Name $Names.Service).StartType -ne 'Disabled') { throw 'Web was startable before the local HTTPS probe.' }
    Assert-MinhDucMaintenanceFirewall -Paths $P
'@
    Write-Fixture 'CapNhat.ps1' '    $committed = $true' @'
    Assert-MinhDucMaintenanceFirewall -Paths $P
'@
    Write-Fixture 'CapNhat.ps1' "        `$report = Join-Path `$P.Journal ('kiem-tra-sau-cap-nhat-' + `$Stamp + '.txt')" @'
        function Invoke-HealthReport {
            param($Paths, $Output, $Title)
            if (Get-MinhDucMaintenanceFirewall $Names.FirewallMaintenance ActiveStore) { throw 'Firewall still blocked after commit.' }
            $result = Get-Content -LiteralPath $ResultFile -Raw | ConvertFrom-Json
            if ($result.status -ne 'thanh_cong' -or -not (Test-Path -LiteralPath $OldVenv)) {
                throw 'Không ghi thành công trước báo cáo hoặc đã xóa venv cũ.'
            }
            throw 'S2f-2D CI: loi bao cao sau HTTPS'
        }
'@
    & $updateScript -KhongHoi -TepZip $zip
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $fixture 'backup-checked'))) {
        throw 'Cập nhật thật gặp lỗi hoặc chưa kiểm được cửa sổ sao lưu.'
    }
    $result = Get-Content -LiteralPath $resultFile -Raw | ConvertFrom-Json
    if ($result.status -ne 'thanh_cong' -or @($result.rollback_errors).Count -ne 0 -or
        ($result.warnings -join ' ') -notmatch 'S2f-2D CI: loi bao cao sau HTTPS' -or
        -not (Test-Path -LiteralPath ($result.backup + '.verified'))) {
        throw 'Lỗi lập báo cáo sau HTTPS làm mất kết quả cập nhật hoặc bản sao lưu.'
    }
    Assert-ServiceAndTasksRestored
    & $paths.VenvPython (Join-Path $PSScriptRoot 'windows_e2e.py') login
    if ($LASTEXITCODE) { throw 'Không đăng nhập được sau lỗi báo cáo.' }
    Write-Output 'PASS: sao lưu khi dịch vụ và lịch đều Disabled, lỗi báo cáo sau HTTPS giữ kết quả thành công.'
} finally {
    if ($worker -and -not $worker.HasExited) {
        [IO.File]::WriteAllText((Join-Path $fixture 'release'), 'release')
        if (-not $worker.WaitForExit(10000)) { throw 'Tiến trình kiểm thử chưa thoát.' }
    }
    Remove-Item -LiteralPath $fixture -Recurse -Force
}
