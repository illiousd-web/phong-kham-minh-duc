# Tác vụ lúc bật máy: chỉ trả bảo trì theo dấu do bộ cài ghi.
[CmdletBinding()]
param([string]$ThuMucMa = 'C:\MinhDuc', [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc')
$ErrorActionPreference = 'Stop'
$logPath = Join-Path $ThuMucDuLieu 'nhatky\tu-go-bao-tri.log'
$recovery = @{ Marker = $null }
$clock = [Diagnostics.Stopwatch]::StartNew()
$budgetSeconds = 720

function Write-TuGoBaoTriLog([int]$Code, [string]$Message) {
    $marker = $recovery.Marker
    $phase = if ($marker) { $marker.Phase } else { '-' }
    $status = if ($marker -and $marker.PSObject.Properties['Status']) { $marker.Status } else { '-' }
    $now = [datetime]::UtcNow.AddHours(7).ToString("dd/MM/yyyy HH:mm:ss 'UTC+7'", [Globalization.CultureInfo]::InvariantCulture)
    $messageLine = $Message -replace '[\r\n]+', ' '
    try {
        Add-Content -LiteralPath $logPath -Value "[$now] Phase=$phase Status=$status Mã=$Code $messageLine" -Encoding UTF8 -ErrorAction Stop
    } catch {
        Write-Warning ('Chưa ghi được nhật ký tự gỡ bảo trì: ' + $_.Exception.Message)
    }
}

$startRecoveredService = {
    # Resume chỉ gọi đoạn này sau khi đã trả cấu hình, trong khi vẫn giữ khóa.
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            # Chừa thời gian cho SCM. Dừng chờ StartPending khi PowerShell đưa ra cảnh báo.
            if ($clock.Elapsed.TotalSeconds + 30 -ge $budgetSeconds) { throw 'Đã hết thời gian khởi động trong giới hạn 12 phút.' }
            Start-Service -Name (Get-MinhDucNames).Service -WarningAction Stop -ErrorAction Stop
            $origin = (Read-EnvFile -Path $paths.ClinicEnv)['CLINIC_ORIGIN']
            # Wait-Https có thể còn một yêu cầu HTTP và một lần ngủ khi hết thời gian thăm dò.
            $probeSeconds = [math]::Min(120, [math]::Floor($budgetSeconds - $clock.Elapsed.TotalSeconds) - 23)
            if ($probeSeconds -le 0) { throw 'HTTPS nội bộ chưa đạt trong giới hạn 12 phút.' }
            if (-not (Wait-Https -Origin $origin -Seconds $probeSeconds -LocalOnly)) {
                throw "HTTPS nội bộ chưa đạt sau $probeSeconds giây."
            }
            Write-TuGoBaoTriLog 0 "Lần khởi động $attempt/4. Đã trả cấu hình bảo trì, dịch vụ đã khởi động và HTTPS nội bộ đạt."
            return
        } catch {
            $message = "Lần khởi động $attempt/4. Đã trả cấu hình bảo trì. Khởi động hoặc kiểm HTTPS chưa đạt: $($_.Exception.Message)"
            if ($attempt -eq 4 -or $clock.Elapsed.TotalSeconds + 120 + 30 -ge $budgetSeconds) { throw $message }
            Write-TuGoBaoTriLog 1 $message
            Start-Sleep -Seconds 120
        }
    }
}

$exitCode = 0
try {
    Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
    $paths = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
    for ($retry = 0; ; $retry++) {
        try {
            $restored = Resume-MinhDucServiceStartMode -Paths $paths -ScriptName 'TuGoBaoTri.ps1' -AtStartup -RecoveryInfo $recovery -AfterRestore $startRecoveredService
            if (-not $restored) { Write-TuGoBaoTriLog 0 'Không có tệp đánh dấu.' }
            break
        } catch {
            if ($_.Exception.Data['MinhDucExit'] -ne 52) { throw }
            Write-TuGoBaoTriLog 52 "Lần lấy khóa $($retry + 1)/6. $($_.Exception.Message)"
            if ($retry -eq 5 -or $clock.Elapsed.TotalSeconds + 60 -ge $budgetSeconds) {
                $exitCode = 52
                break
            }
            Start-Sleep -Seconds 60
        }
    }
} catch {
    $exitCode = 1
    Write-TuGoBaoTriLog $exitCode $_.Exception.Message
}
exit $exitCode
