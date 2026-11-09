# Gia hạn chứng chỉ HTTPS của máy chủ bằng CA hiện có (ca.key trên máy).
# CA giữ nguyên nên máy trạm KHÔNG phải chạy lại CAI_MAY_TRAM.
# Trình tự an toàn:
#   1. Tạo mốc $stamp TRƯỚC mọi thay đổi (để khôi phục được ở bất kỳ giai đoạn nào).
#   2. Ghi cặp chứng chỉ/khóa mới bằng tên tạm cạnh tệp cũ (server.*.moi-<stamp>).
#   3. Đặt quyền cho tài khoản dịch vụ, KIỂM TRA tài khoản dịch vụ đọc được, kiểm cặp khớp nhau.
#   4. Mới thay tệp (tệp cũ thành server.*.cu-<stamp>), khởi động lại dịch vụ, kiểm HTTPS dùng đúng chứng chỉ mới.
#   5. Lỗi ở bất kỳ bước nào: khôi phục; chỉ báo "đã trả chứng chỉ cũ" khi HTTPS sau khôi phục thực sự đạt.
# Biến MINHDUC_TEST_LOI chỉ dùng cho kiểm thử tự động (CI) để gây lỗi có chủ đích; không đặt khi dùng thật.
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
$Fault = [string]$env:MINHDUC_TEST_LOI

function Write-Result([string]$Status, [string]$Detail) {
    @{ status = $Status; detail = $Detail; time = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding UTF8
}
function Invoke-Cert([string[]]$CertArgs) {
    return Invoke-Python -Paths $P -Quiet -Arguments (@('-m', 'scripts.install_cert') + $CertArgs)
}
function Get-ServedSerial([string]$Origin, [string]$Ca) {
    $r = Invoke-Cert @('served', '--origin', $Origin, '--ca', $Ca)
    if ($r.Ok) { return (ConvertFrom-PythonJson $r).serial }
    return $null
}

$exitCode = 0
$stamp = $null
$changed = $false   # đã có tệp tạm hoặc đã thay tệp: cần khôi phục khi lỗi
try {
    $admin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { Stop-CaiDat 'Cần quyền Administrator.' @('Bấm đúp GIA_HAN_CHUNG_CHI.bat và chọn "Yes".') 30 }
    $cert = Join-Path $P.Tls 'server.crt'
    $ca = Join-Path $P.Tls 'ca.crt'
    if (-not (Test-Path -LiteralPath $P.ClinicEnv) -or -not (Test-Path -LiteralPath $cert)) { Stop-CaiDat 'Máy này chưa cài đặt bằng CAI_DAT.bat (thiếu cấu hình hoặc chứng chỉ).' @('Chạy CAI_DAT.bat.') 2 }
    if (-not (Test-Path -LiteralPath $P.CaKey)) {
        Stop-CaiDat 'Không thấy khóa CA (quantri\ca.key) trên máy.' @('Nếu đã chuyển ca.key ra USB riêng: chép lại vào C:\ProgramData\MinhDuc\quantri\ rồi chạy lại.',
            'Nếu mất ca.key: chạy CAI_DAT.bat để tạo CA mới, sau đó cài lại MỌI máy trạm.') 3
    }
    $cfg = Read-EnvFile -Path $P.ClinicEnv
    $origin = $cfg['CLINIC_ORIGIN']
    Write-Host 'GIA HẠN CHỨNG CHỈ HTTPS — PHÒNG KHÁM ĐA KHOA MINH ĐỨC' -ForegroundColor Cyan
    $r = Invoke-Python -Paths $P -Quiet -OkCodes @(0, 1) -Arguments @('-m', 'scripts.install_cert', 'check', '--cert', $cert, '--ip', $cfg['CLINIC_BIND_IP'], '--days', '60')
    $state = ConvertFrom-PythonJson $r
    if ($null -eq $state) { Stop-CaiDat 'Không đọc được chứng chỉ hiện tại.' @('Chạy KIEM_TRA.bat và gửi báo cáo cho người hỗ trợ.') 4 }
    if ($state.code -eq 'ip') {
        Stop-CaiDat ('Không gia hạn được: ' + $state.reason + '.') @('Đặt lại IP cũ cho máy chủ, hoặc liên hệ người hỗ trợ (đổi IP cần CA mới và cài lại máy trạm).') 4
    }
    Write-Thongtin ('Hiện tại: ' + $state.reason + '.')
    if ($state.ok -and -not (Read-CoKhong 'Chứng chỉ còn trên 60 ngày. Vẫn gia hạn ngay?' -KhongHoi:$KhongHoi -MacDinh $true)) {
        Write-Result 'bo_qua' $state.reason
        exit 0
    }
    $oldSerial = Get-ServedSerial $origin $ca
    # Mốc khôi phục có TRƯỚC mọi thay đổi.
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')

    Write-Buoc 'Bước 1/4: Tạo chứng chỉ mới bằng CA hiện có (tên tạm, cạnh tệp cũ)'
    $changed = $true
    $r = Invoke-Cert @('prepare', '--tls-dir', $P.Tls, '--ca-key', $P.CaKey, '--stamp', $stamp)
    if (-not $r.Ok) { throw ('Không tạo được chứng chỉ mới: ' + (($r.Output | Select-Object -Last 1) -join '')) }
    $renewed = ConvertFrom-PythonJson $r
    Write-Dat ('Đã tạo chứng chỉ mới (hạn tới ' + $renewed.not_after.Substring(0, 10) + '); CA giữ nguyên, vân tay ' + $renewed.ca_fingerprint.Substring(0, 8) + '.')

    Write-Buoc 'Bước 2/4: Đặt quyền và kiểm tra tài khoản dịch vụ đọc được'
    Set-SecureAcl -Path $P.Tls -Directory -Readers @($Names.ServiceAcct)
    foreach ($f in $renewed.files) { Invoke-Native -FilePath 'icacls.exe' -Arguments @($f, '/reset') -Quiet | Out-Null }
    if ($Fault -eq 'tu-choi-doc-khoa') {
        Invoke-Native -FilePath 'icacls.exe' -Arguments @(($renewed.files | Where-Object { $_ -like '*server.key.moi-*' }), '/deny', ($Names.ServiceAcct + ':(R)')) -Quiet | Out-Null
    }
    foreach ($f in $renewed.files) {
        if (-not (Test-AccountCanRead -Path $f -Account $Names.ServiceAcct)) { throw ('Tài khoản dịch vụ không đọc được ' + (Split-Path $f -Leaf) + '; chưa thay tệp nào.') }
    }
    $r = Invoke-Cert @('verify', '--tls-dir', $P.Tls, '--stamp', $stamp)
    if (-not $r.Ok) { throw 'Cặp chứng chỉ/khóa mới không hợp lệ; chưa thay tệp nào.' }
    Write-Dat 'Tài khoản dịch vụ đọc được; chứng chỉ và khóa mới khớp nhau.'

    Write-Buoc 'Bước 3/4: Thay tệp và khởi động lại dịch vụ web'
    $r = Invoke-Cert @('commit', '--tls-dir', $P.Tls, '--stamp', $stamp)
    if (-not $r.Ok) { throw ('Lỗi khi thay tệp: ' + (($r.Output | Select-Object -Last 1) -join '')) }
    if ($Fault -eq 'khoi-phuc-loi') { throw 'Lỗi giả lập sau khi thay tệp (kiểm thử khôi phục thất bại).' }
    Restart-Service -Name $Names.Service -Force

    Write-Buoc 'Bước 4/4: Kiểm tra HTTPS dùng đúng chứng chỉ mới'
    if (-not (Wait-Https -Origin $origin -Seconds 120)) { Show-ServiceDiagnostics -Paths $P; throw 'Dịch vụ web không trả lời sau 2 phút.' }
    $served = Get-ServedSerial $origin $ca
    if ($served -ne $renewed.serial) { throw 'Máy chủ chưa dùng chứng chỉ mới.' }
    Write-Dat ('HTTPS đang dùng chứng chỉ mới (số sê-ri ' + $served + '), máy trạm vẫn tin cậy.')
    Write-Result 'thanh_cong' ('Hạn mới: ' + $renewed.not_after)
    Write-Host ''
    Write-Host 'GIA HẠN THÀNH CÔNG.' -ForegroundColor Green
} catch {
    $code = $_.Exception.Data['MinhDucExit']
    if ($null -ne $code -and -not $changed) {
        $exitCode = [int]$code
        Write-Result 'dung' $_.Exception.Message
    } else {
        $reason = $_.Exception.Message
        Write-Loi ('Gia hạn lỗi: ' + $reason)
        Write-Buoc 'KHÔI PHỤC CHỨNG CHỈ CŨ'
        $r = Invoke-Cert @('rollback', '--tls-dir', $P.Tls, '--stamp', $stamp)
        $rollbackOk = $r.Ok
        if ($rollbackOk) { Write-Thongtin 'Đã đặt lại tệp chứng chỉ cũ; đang kiểm tra...' } else { Write-Loi ('Không đặt lại được tệp chứng chỉ cũ: ' + (($r.Output | Select-Object -Last 1) -join '')) }
        Set-SecureAcl -Path $P.Tls -Directory -Readers @($Names.ServiceAcct)
        foreach ($f in @('server.crt', 'server.key')) { Invoke-Native -FilePath 'icacls.exe' -Arguments @((Join-Path $P.Tls $f), '/reset') -Quiet | Out-Null }
        Restart-Service -Name $Names.Service -Force -ErrorAction SilentlyContinue
        $httpsOk = Wait-Https -Origin $origin -Seconds 120
        $servedNow = if ($httpsOk) { Get-ServedSerial $origin $ca } else { $null }
        # Chỉ coi là đã trả chứng chỉ cũ khi: khôi phục tệp đạt, HTTPS đạt, và đúng chứng chỉ cũ đang chạy.
        $restoreOk = $rollbackOk -and $httpsOk -and ($null -ne $servedNow) -and (($null -eq $oldSerial) -or ($servedNow -eq $oldSerial))
        Write-Host ''
        if ($restoreOk) {
            Write-Dat ('Kiểm tra sau khôi phục ĐẠT: HTTPS dùng chứng chỉ cũ (số sê-ri ' + $servedNow + ').')
            Write-Result 'da_tra_chung_chi_cu' $reason
            Write-Host 'GIA HẠN KHÔNG THÀNH CÔNG — ĐÃ TRẢ CHỨNG CHỈ CŨ, phần mềm vẫn dùng bình thường.' -ForegroundColor Yellow
            $exitCode = 50
        } else {
            Write-Loi ('Kiểm tra sau khôi phục KHÔNG ĐẠT (khôi phục tệp: ' + $(if ($rollbackOk) { 'đạt' } else { 'lỗi' }) + ', HTTPS: ' + $(if ($httpsOk) { 'đạt' } else { 'lỗi' }) + ').')
            Write-Result 'khoi_phuc_that_bai' $reason
            Write-Host 'KHÔI PHỤC CHỨNG CHỈ CŨ THẤT BẠI. Việc cần làm ngay:' -ForegroundColor Red
            Write-Host '  1. Bấm đúp KIEM_TRA.bat, gửi tệp báo cáo trên Desktop và thư mục C:\ProgramData\MinhDuc\nhatky cho người hỗ trợ.' -ForegroundColor Yellow
            Write-Host ('  2. Chạy lại GIA_HAN_CHUNG_CHI.bat một lần (các tệp cũ được giữ với đuôi .cu-' + $stamp + ').') -ForegroundColor Yellow
            Write-Host '  3. Nếu máy trạm báo lỗi chứng chỉ: KHÔNG bấm bỏ qua cảnh báo; chờ người hỗ trợ.' -ForegroundColor Yellow
            $exitCode = 51
        }
    }
}
exit $exitCode
