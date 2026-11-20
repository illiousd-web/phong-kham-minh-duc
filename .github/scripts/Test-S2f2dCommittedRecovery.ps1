# Diễn tập lỗi gỡ tường lửa trên bản cài Windows CI dùng dữ liệu giả lập.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Chỉ chạy diễn tập bảo trì trên Windows CI giả lập.'
}
$source = Join-Path $PSScriptRoot '../../deploy/windows'
Import-Module (Join-Path $source 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$paths = Get-MinhDucPaths
$names = Get-MinhDucNames
$zip = Join-Path $env:RUNNER_TEMP 'minhduc-ok.zip'
$fixture = Join-Path $env:RUNNER_TEMP ('minhduc-committed-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $fixture | Out-Null
try {
    foreach ($name in 'CapNhat.ps1', 'MinhDuc.Install.psm1', 'DanhMucGoc.ps1') {
        Copy-Item -LiteralPath (Join-Path $source $name) -Destination $fixture
    }
    $modulePath = Join-Path $fixture 'MinhDuc.Install.psm1'
    $text = [IO.File]::ReadAllText($modulePath)
    $needle = 'function Remove-MinhDucMaintenanceFirewall([string]$Name) {'
    $lines = [regex]::Matches($text, ('(?m)^' + [regex]::Escape($needle) + '(?=\r?$)'))
    if ($lines.Count -ne 1) { throw 'Cần đúng một dòng chèn lỗi gỡ tường lửa.' }
    $failure = 'S2f-2D CI: không gỡ được tường lửa'
    $line = $lines[0]
    $text = $text.Insert($line.Index + $line.Length, [Environment]::NewLine + "    throw '$failure'")
    [IO.File]::WriteAllText($modulePath, $text, [Text.UTF8Encoding]::new($true))

    $beforeCount = & $paths.VenvPython (Join-Path $PSScriptRoot 'windows_e2e.py') count | Select-Object -Last 1
    if ($LASTEXITCODE) { throw 'Không đọc được dữ liệu trước diễn tập.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture 'CapNhat.ps1') -KhongHoi -TepZip $zip
    $updateExit = $LASTEXITCODE
    $result = Get-Content -LiteralPath (Join-Path $paths.Updates 'ket-qua-cap-nhat.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $marker = Read-MinhDucServiceStartModeMarker $names.Service $paths
    $service = Get-Service -Name $names.Service
    if ($updateExit -ne 8 -or $result.status -ne 'thanh_cong_can_kiem_tra' -or $result.detail -notlike "*$failure*" -or
        @($result.rollback_errors).Count -ne 0 -or $marker.Phase -ne 'da_chot' -or $marker.Status -ne 'dang_bao_tri' -or
        $service.StartType -ne 'Disabled' -or $service.Status -ne 'Running') {
        throw 'Lỗi gỡ tường lửa sau chốt phải trả mã 8, giữ bản mới chạy và giữ dấu da_chot.'
    }
    Assert-MinhDucMaintenanceFirewall -Paths $paths

    # Để trống thư mục mã khi kiểm nhằm tách kết quả trả cấu hình khỏi báo cáo Python.
    $report = Join-Path $fixture 'kiem-tra.txt'
    & (Join-Path $source 'KiemTra.ps1') -KhongHoi -ThuMucMa $fixture -TepKetQua $report
    if ($LASTEXITCODE -ne 2 -or (Get-Content -LiteralPath $report -Raw -Encoding UTF8) -notmatch '\[ĐẠT\] Dịch vụ web.*Đã trả' -or
        (Test-Path -LiteralPath $paths.ServiceStartModePending) -or (Get-Service -Name $names.Service).StartType -ne 'Automatic' -or
        (Get-MinhDucMaintenanceFirewall $names.FirewallMaintenance ActiveStore) -or
        (Get-MinhDucMaintenanceFirewall $names.FirewallMaintenance PersistentStore) -or -not (Test-MinhDucBackupTasks -Paths $paths)) {
        throw 'KIEM_TRA chưa trả đủ cấu hình sau lỗi gỡ tường lửa.'
    }
    & $paths.VenvPython (Join-Path $PSScriptRoot 'windows_e2e.py') login
    if ($LASTEXITCODE) { throw 'Không đăng nhập được sau khi kết thúc cửa sổ bảo trì.' }
    $afterCount = & $paths.VenvPython (Join-Path $PSScriptRoot 'windows_e2e.py') count | Select-Object -Last 1
    if ($LASTEXITCODE -or $afterCount -ne $beforeCount) { throw 'Dữ liệu đổi sau khi trả cấu hình bảo trì.' }
    Write-Output 'PASS: mã 8, không quay về, KIEM_TRA trả nốt cấu hình và đăng nhập được.'
} finally { Remove-Item -LiteralPath $fixture -Recurse -Force }
