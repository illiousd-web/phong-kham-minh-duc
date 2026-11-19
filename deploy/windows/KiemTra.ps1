# Báo cáo kiểm tra máy chủ bằng tiếng Việt, lưu tệp .txt trên Desktop để gửi người hỗ trợ.
# Không chứa mật khẩu, chuỗi kết nối hay dữ liệu bệnh nhân.
[CmdletBinding()]
param([switch]$KhongHoi, [string]$ThuMucMa = 'C:\MinhDuc', [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc', [string]$TepKetQua = '')
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script (App Control / Smart App Control).' -ForegroundColor Red
    Write-Host '  - Không tự tắt Smart App Control hay App Control. Dừng và gọi người hỗ trợ (chụp màn hình này gửi kèm).' -ForegroundColor Yellow
    exit 20
}
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
if (-not $TepKetQua) {
    $TepKetQua = Join-Path ([Environment]::GetFolderPath('Desktop')) ('MinhDuc-KiemTra-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.txt')
}
$label = 'Dịch vụ web không bị vô hiệu hóa'
$recoveryError = $null
try {
    $restored = Resume-MinhDucServiceStartMode -Paths $P -ScriptName 'KiemTra.ps1'
} catch {
    $recoveryError = $_.Exception.Message
}
$Names = Get-MinhDucNames
$service = Get-Service -Name $Names.Service -ErrorAction SilentlyContinue
if ($recoveryError) {
    $startup = if ($service) { 'Chế độ khởi động hiện tại là ' + $service.StartType + '.' } else { 'Không tìm thấy dịch vụ MinhDuc.' }
    if ($recoveryError -notmatch 'Báo người hỗ trợ') { $recoveryError += ' Báo người hỗ trợ.' }
    $row = "[KHÔNG ĐẠT] ${label} - $recoveryError $startup"
    Set-Content -LiteralPath $TepKetQua -Value $row -Encoding UTF8 -ErrorAction Stop
    Write-Host $row -ForegroundColor Red
    Write-Host ('Đã lưu báo cáo: ' + $TepKetQua) -ForegroundColor Cyan
    exit 1
}
$serviceEnabled = $service -and $service.StartType -in @('Automatic', 'Manual')
if ($serviceEnabled) {
    $row = "[ĐẠT] $label"
    if ($restored) { $row += ' - ' + $restored }
} else {
    $detail = if ($service) { 'Chế độ khởi động hiện tại là ' + $service.StartType + '.' } else { 'Không tìm thấy dịch vụ MinhDuc.' }
    $row = "[KHÔNG ĐẠT] ${label} - $detail Gửi báo cáo cho người hỗ trợ."
}

if (-not (Test-Path -LiteralPath $P.VenvPython) -or -not (Test-Path -LiteralPath $P.ClinicEnv)) {
    $missing = '[KHÔNG ĐẠT] Thiếu môi trường Python (.venv) hoặc clinic.env. Gửi báo cáo cho người hỗ trợ.'
    Set-Content -LiteralPath $TepKetQua -Value @($row, $missing) -Encoding UTF8 -ErrorAction Stop
    Write-Host $row
    Write-Host $missing -ForegroundColor Red
    Write-Host ('Đã lưu báo cáo: ' + $TepKetQua) -ForegroundColor Cyan
    if ($service -and -not $serviceEnabled) { exit 1 }
    exit 2
}

Write-Host 'Đang kiểm tra máy chủ, vui lòng chờ khoảng 30 giây...' -ForegroundColor Cyan
$ok = Invoke-HealthReport -Paths $P -Output $TepKetQua -Title 'BÁO CÁO KIỂM TRA (gửi người hỗ trợ)' -ServiceStartupCheck @{ Ok = $serviceEnabled; Row = $row }
Write-Host ''
Write-Host ('Đã lưu báo cáo: ' + $TepKetQua) -ForegroundColor Cyan
if ($ok) { exit 0 } else { exit 1 }
