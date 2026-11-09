# Báo cáo kiểm tra máy chủ bằng tiếng Việt, lưu tệp .txt trên Desktop để gửi người hỗ trợ.
# Không chứa mật khẩu, chuỗi kết nối hay dữ liệu bệnh nhân.
[CmdletBinding()]
param([switch]$KhongHoi, [string]$ThuMucMa = 'C:\MinhDuc', [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc', [string]$TepKetQua = '')
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script (App Control / Smart App Control).' -ForegroundColor Red
    exit 20
}
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
if (-not (Test-Path -LiteralPath $P.VenvPython) -or -not (Test-Path -LiteralPath $P.ClinicEnv)) {
    Write-Host 'Máy này chưa cài máy chủ Minh Đức (chưa thấy C:\MinhDuc\.venv hoặc clinic.env). Chạy CAI_DAT.bat trước.' -ForegroundColor Red
    exit 2
}
if (-not $TepKetQua) {
    $TepKetQua = Join-Path ([Environment]::GetFolderPath('Desktop')) ('MinhDuc-KiemTra-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.txt')
}
Write-Host 'Đang kiểm tra máy chủ, vui lòng chờ khoảng 30 giây...' -ForegroundColor Cyan
$ok = Invoke-HealthReport -Paths $P -Output $TepKetQua -Title 'BÁO CÁO KIỂM TRA (gửi người hỗ trợ)'
Write-Host ''
Write-Host ('Đã lưu báo cáo: ' + $TepKetQua) -ForegroundColor Cyan
if ($ok) { exit 0 } else { exit 1 }
