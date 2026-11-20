# Tác vụ lúc bật máy: chỉ trả bảo trì theo dấu do bộ cài ghi.
[CmdletBinding()]
param([string]$ThuMucMa = 'C:\MinhDuc', [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc')
$ErrorActionPreference = 'Stop'
$logPath = Join-Path $ThuMucDuLieu 'nhatky\tu-go-bao-tri.log'
$recovery = @{ Marker = $null }
$exitCode = 0
try {
    Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
    $paths = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
    $restored = Resume-MinhDucServiceStartMode -Paths $paths -ScriptName 'TuGoBaoTri.ps1' -AtStartup -RecoveryInfo $recovery -AfterRestore {
        try {
            Start-Service -Name (Get-MinhDucNames).Service -ErrorAction Stop
            $origin = (Read-EnvFile -Path $paths.ClinicEnv)['CLINIC_ORIGIN']
            if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { throw 'HTTPS nội bộ chưa đạt sau 2 phút.' }
        } catch {
            throw ('Đã trả cấu hình bảo trì. Khởi động hoặc kiểm HTTPS chưa đạt: ' + $_.Exception.Message)
        }
    }
    $outcome = if ($restored) { 'Đã trả cấu hình bảo trì, dịch vụ đã khởi động và HTTPS nội bộ đạt.' }
        else { 'Không có tệp đánh dấu.' }
} catch {
    $exitCode = if ($_.Exception.Data['MinhDucExit'] -eq 52) { 52 } else { 1 }
    $outcome = $_.Exception.Message -replace '[\r\n]+', ' '
}
$marker = $recovery.Marker
$phase = if ($marker) { $marker.Phase } else { '-' }
$status = if ($marker -and $marker.PSObject.Properties['Status']) { $marker.Status } else { '-' }
$now = [datetime]::UtcNow.AddHours(7).ToString("dd/MM/yyyy HH:mm:ss 'UTC+7'", [Globalization.CultureInfo]::InvariantCulture)
try {
    Add-Content -LiteralPath $logPath -Value "[$now] Phase=$phase Status=$status Mã=$exitCode $outcome" -Encoding UTF8 -ErrorAction Stop
} catch {
    Write-Warning ('Chưa ghi được nhật ký tự gỡ bảo trì: ' + $_.Exception.Message)
}
exit $exitCode
