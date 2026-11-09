# Gia hạn chứng chỉ HTTPS của máy chủ bằng CA hiện có (ca.key trên máy).
# CA giữ nguyên nên máy trạm KHÔNG phải chạy lại CAI_MAY_TRAM.
# Trình tự: sao lưu chứng chỉ cũ -> cấp chứng chỉ mới -> khởi động lại dịch vụ -> kiểm HTTPS
# (đúng chứng chỉ mới) -> lỗi thì trả chứng chỉ cũ và khởi động lại.
[CmdletBinding()]
param([switch]$KhongHoi, [string]$ThuMucMa = 'C:\MinhDuc', [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc')
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script (App Control / Smart App Control).' -ForegroundColor Red
    exit 20
}
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$Names = Get-MinhDucNames
$P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
$ResultFile = Join-Path $P.Journal 'ket-qua-gia-han.json'

function Write-Result([string]$Status, [string]$Detail) {
    @{ status = $Status; detail = $Detail; time = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding UTF8
}

$exitCode = 0
$stamp = $null
try {
    $admin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { Stop-CaiDat 'Cần quyền Administrator.' @('Bấm đúp GIA_HAN_CHUNG_CHI.bat và chọn "Yes".') 30 }
    $cert = Join-Path $P.Tls 'server.crt'
    $ca = Join-Path $P.Tls 'ca.crt'
    if (-not (Test-Path -LiteralPath $P.ClinicEnv) -or -not (Test-Path -LiteralPath $cert)) { Stop-CaiDat 'Máy này chưa cài đặt bằng CAI_DAT.bat.' @() 2 }
    if (-not (Test-Path -LiteralPath $P.CaKey)) {
        Stop-CaiDat 'Không thấy khóa CA (quantri\ca.key) trên máy.' @('Nếu đã chuyển ca.key ra USB riêng: chép lại vào C:\ProgramData\MinhDuc\quantri\ rồi chạy lại.',
            'Nếu mất ca.key: chạy CAI_DAT.bat để tạo CA mới, sau đó cài lại MỌI máy trạm.') 3
    }
    $cfg = Read-EnvFile -Path $P.ClinicEnv
    $origin = $cfg['CLINIC_ORIGIN']
    Write-Host 'GIA HẠN CHỨNG CHỈ HTTPS — PHÒNG KHÁM ĐA KHOA MINH ĐỨC' -ForegroundColor Cyan
    $r = Invoke-Python -Paths $P -Quiet -OkCodes @(0, 1) -Arguments @('-m', 'scripts.install_cert', 'check', '--cert', $cert, '--ip', $cfg['CLINIC_BIND_IP'], '--days', '60')
    $state = ConvertFrom-PythonJson $r
    if ($state.code -eq 'ip') {
        Stop-CaiDat ('Không gia hạn được: ' + $state.reason + '.') @('Đặt lại IP cũ cho máy chủ, hoặc liên hệ người hỗ trợ (đổi IP cần CA mới và cài lại máy trạm).') 4
    }
    Write-Thongtin ('Hiện tại: ' + $state.reason + '.')
    if ($state.ok -and -not (Read-CoKhong 'Chứng chỉ còn trên 60 ngày. Vẫn gia hạn ngay?' -KhongHoi:$KhongHoi -MacDinh $true)) {
        Write-Result 'bo_qua' $state.reason
        exit 0
    }

    Write-Buoc 'Bước 1/3: Sao lưu chứng chỉ cũ và cấp chứng chỉ mới bằng CA hiện có'
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_cert', 'renew', '--tls-dir', $P.Tls, '--ca-key', $P.CaKey)
    if (-not $r.Ok) { Stop-CaiDat 'Không cấp được chứng chỉ mới; chứng chỉ cũ giữ nguyên.' $r.Output 5 }
    $renewed = ConvertFrom-PythonJson $r
    $stamp = $renewed.stamp
    Set-SecureAcl -Path $P.Tls -Directory -Readers @($Names.ServiceAcct)
    # Tệp mới nhận quyền đọc của thư mục tls (tài khoản dịch vụ phải đọc được server.key).
    foreach ($f in @('server.crt', 'server.key')) { Invoke-Native -FilePath 'icacls.exe' -Arguments @((Join-Path $P.Tls $f), '/reset') -Quiet | Out-Null }
    Write-Dat ('Đã cấp chứng chỉ mới, hạn tới ' + $renewed.not_after.Substring(0, 10) + '; chứng chỉ cũ lưu với đuôi .cu-' + $stamp)
    Write-Dat ('CA giữ nguyên (vân tay ' + $renewed.ca_fingerprint.Substring(0, 8) + '): máy trạm không phải cài lại.')

    Write-Buoc 'Bước 2/3: Khởi động lại dịch vụ web'
    Restart-Service -Name $Names.Service -Force
    Write-Buoc 'Bước 3/3: Kiểm tra HTTPS dùng đúng chứng chỉ mới'
    if (-not (Wait-Https -Origin $origin -Seconds 120)) { Show-ServiceDiagnostics -Paths $P; throw 'Dịch vụ web không trả lời sau 2 phút.' }
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_cert', 'served', '--origin', $origin, '--ca', $ca)
    $served = ConvertFrom-PythonJson $r
    if (-not $r.Ok -or $served.serial -ne $renewed.serial) { throw 'Máy chủ chưa dùng chứng chỉ mới.' }
    Write-Dat ('HTTPS đang dùng chứng chỉ mới (số sê-ri ' + $served.serial + '), máy trạm vẫn tin cậy.')
    Write-Result 'thanh_cong' ('Hạn mới: ' + $renewed.not_after)
    Write-Host ''
    Write-Host 'GIA HẠN THÀNH CÔNG.' -ForegroundColor Green
} catch {
    $code = $_.Exception.Data['MinhDucExit']
    if ($null -ne $code -and -not $stamp) {
        $exitCode = [int]$code
        Write-Result 'dung' $_.Exception.Message
    } else {
        Write-Loi ('Gia hạn lỗi: ' + $_.Exception.Message)
        Write-Buoc 'TRẢ CHỨNG CHỈ CŨ'
        $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_cert', 'rollback', '--tls-dir', $P.Tls, '--stamp', $stamp)
        if ($r.Ok) { Write-Dat 'Đã trả chứng chỉ cũ.' } else { Write-Loi 'Không trả được chứng chỉ cũ; báo người hỗ trợ ngay.' }
        Set-SecureAcl -Path $P.Tls -Directory -Readers @($Names.ServiceAcct)
        foreach ($f in @('server.crt', 'server.key')) { Invoke-Native -FilePath 'icacls.exe' -Arguments @((Join-Path $P.Tls $f), '/reset') -Quiet | Out-Null }
        Restart-Service -Name $Names.Service -Force -ErrorAction SilentlyContinue
        if (Wait-Https -Origin $origin -Seconds 120) { Write-Dat 'Phần mềm chạy lại bằng chứng chỉ cũ.' } else { Write-Loi 'Dịch vụ chưa chạy lại. Bấm KIEM_TRA.bat và gửi kết quả cho người hỗ trợ.' }
        Write-Result 'da_tra_chung_chi_cu' $_.Exception.Message
        Write-Host 'GIA HẠN KHÔNG THÀNH CÔNG — ĐÃ TRẢ CHỨNG CHỈ CŨ.' -ForegroundColor Yellow
        $exitCode = 50
    }
}
exit $exitCode
