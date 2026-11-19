# Gia hạn chứng chỉ HTTPS của máy chủ bằng CA hiện có (ca.key trên máy).
# Tự nhận ra chứng chỉ/khóa máy chủ thiếu hoặc hỏng: CHẾ ĐỘ PHỤC HỒI cấp chứng chỉ mới từ
# ca.key mà không đọc chứng chỉ cũ. Mất cả ca.key: báo phải tạo CA mới và cài lại mọi máy trạm.
# Mã thoát: 0 đạt (hoặc không gia hạn theo lựa chọn); 50 lỗi nhưng đã trả chứng chỉ cũ và HTTPS
# kiểm lại đạt; 51 không trả được chứng chỉ cũ / phục hồi không thành công. Mã 8: HTTPS đã dùng chứng chỉ mới,
# còn cấu hình bảo trì cần kiểm tra.
# CA giữ nguyên nên máy trạm KHÔNG phải chạy lại CAI_MAY_TRAM.
# Trình tự an toàn:
#   1. Tạo mốc $stamp TRƯỚC mọi thay đổi (để khôi phục được ở bất kỳ giai đoạn nào).
#   2. Ghi cặp chứng chỉ/khóa mới bằng tên tạm cạnh tệp cũ (server.*.moi-<stamp>).
#   3. Đặt quyền cho tài khoản dịch vụ, KIỂM TRA tài khoản dịch vụ đọc được, kiểm cặp khớp nhau.
#   4. Mới thay tệp (tệp cũ thành server.*.cu-<stamp>), khởi động lại dịch vụ, kiểm HTTPS dùng đúng chứng chỉ mới.
#   5. Khi phục hồi, nếu khởi động lại lỗi sau khi thay tệp, thử thêm một lần với cặp mới.
#      Nếu cần trả tệp cũ, chỉ báo "đã trả chứng chỉ cũ" khi HTTPS sau khôi phục thực sự đạt.
# Biến MINHDUC_TEST_LOI chỉ dùng cho kiểm thử tự động (CI) để gây lỗi có chủ đích; không đặt khi dùng thật.
[CmdletBinding()]
param([switch]$KhongHoi, [string]$ThuMucMa = 'C:\MinhDuc', [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc')
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script (App Control / Smart App Control).' -ForegroundColor Red
    Write-Host '  - Không tự tắt Smart App Control hay App Control. Dừng và gọi người hỗ trợ (chụp màn hình này gửi kèm).' -ForegroundColor Yellow
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
    @{ status = $Status; detail = $Detail; time = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding UTF8 -ErrorAction Stop
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
$resultStatus = $null
$resultDetail = ''
$stamp = $null
$window = $null
$changed = $false   # đã có tệp tạm hoặc đã thay tệp: cần khôi phục khi lỗi
try {
    $admin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { Stop-CaiDat 'Cần quyền Administrator.' @('Bấm đúp GIA_HAN_CHUNG_CHI.bat và chọn "Yes".') 30 }
    Resume-MinhDucServiceStartMode -Paths $P -ScriptName 'GiaHanChungChi.ps1' | Out-Null
    if (-not (Test-Path -LiteralPath $P.ClinicEnv)) { Stop-CaiDat 'Máy này chưa cài đặt bằng CAI_DAT.bat (thiếu tệp cấu hình).' @('Chạy CAI_DAT.bat.') 2 }
    $window = Enter-MinhDucMaintenanceWindow -Name $Names.Service -Paths $P -ScriptName 'GiaHanChungChi.ps1'
    $cert = Join-Path $P.Tls 'server.crt'
    $key = Join-Path $P.Tls 'server.key'
    $ca = Join-Path $P.Tls 'ca.crt'
    $cfg = Read-EnvFile -Path $P.ClinicEnv
    $origin = $cfg['CLINIC_ORIGIN']
    $ip = $cfg['CLINIC_BIND_IP']
    Write-Host 'GIA HẠN CHỨNG CHỈ HTTPS — PHÒNG KHÁM ĐA KHOA MINH ĐỨC' -ForegroundColor Cyan
    $r = Invoke-Python -Paths $P -Quiet -OkCodes @(0, 1) -Arguments @('-m', 'scripts.install_cert', 'check', '--cert', $cert, '--key', $key, '--ip', $ip, '--days', '60')
    $state = ConvertFrom-PythonJson $r
    if ($null -eq $state) { $state = [pscustomobject]@{ ok = $false; code = 'hong'; reason = 'không kiểm tra được chứng chỉ hiện tại' } }
    # Chứng chỉ/khóa máy chủ thiếu hoặc hỏng: CHẾ ĐỘ PHỤC HỒI (không đọc chứng chỉ cũ, cấp mới từ ca.key).
    $recovery = $state.code -in @('missing', 'hong')
    if (-not (Test-Path -LiteralPath $P.CaKey)) {
        if ($recovery) {
            Stop-CaiDat ('Chứng chỉ máy chủ ' + $state.reason + ' VÀ không thấy khóa CA (quantri\ca.key).') @(
                'Nếu ca.key được cất trên USB riêng: chép lại vào C:\ProgramData\MinhDuc\quantri\ rồi chạy lại GIA_HAN_CHUNG_CHI.bat.',
                'Nếu mất hẳn ca.key: KHÔNG phục hồi được bằng CA cũ. Gọi người hỗ trợ tạo CA mới (CAI_DAT.bat), sau đó phải CÀI LẠI CA (CAI_MAY_TRAM.bat) cho MỌI máy trạm.') 5
        }
        Stop-CaiDat 'Không thấy khóa CA (quantri\ca.key) trên máy.' @('Nếu đã chuyển ca.key ra USB riêng: chép lại vào C:\ProgramData\MinhDuc\quantri\ rồi chạy lại.',
            'Nếu mất hẳn ca.key: gọi người hỗ trợ tạo CA mới (CAI_DAT.bat), sau đó phải CÀI LẠI CA (CAI_MAY_TRAM.bat) cho MỌI máy trạm.') 3
    }
    if (-not (Test-Path -LiteralPath $ca)) {
        Stop-CaiDat 'Không thấy chứng chỉ gốc tls\ca.crt trên máy chủ.' @('Gọi người hỗ trợ; không tự tạo CA mới (máy trạm sẽ phải cài lại).') 6
    }
    if ($state.code -eq 'ip') {
        Stop-CaiDat ('Không gia hạn được: ' + $state.reason + '.') @('Đặt lại IP cũ cho máy chủ, hoặc liên hệ người hỗ trợ (đổi IP cần CA mới và cài lại máy trạm).') 4
    }
    if ($recovery) {
        Write-Luu ('CHẾ ĐỘ PHỤC HỒI: ' + $state.reason + '. Sẽ cấp chứng chỉ mới cho IP ' + $ip + ' từ khóa CA hiện có, không đọc chứng chỉ cũ; CA giữ nguyên nên máy trạm không phải cài lại.')
    } else {
        Write-Thongtin ('Hiện tại: ' + $state.reason + '.')
        if ($state.ok -and -not (Read-CoKhong 'Chứng chỉ còn trên 60 ngày. Vẫn gia hạn ngay?' -KhongHoi:$KhongHoi -MacDinh $true)) {
            Write-Result 'bo_qua' $state.reason
            Write-Host 'KHÔNG GIA HẠN (theo lựa chọn của bạn); chứng chỉ hiện tại giữ nguyên.'
            exit 0
        }
    }
    $oldSerial = Get-ServedSerial $origin $ca
    # Mốc khôi phục có TRƯỚC mọi thay đổi.
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')

    Write-Buoc 'Bước 1/4: Tạo chứng chỉ mới bằng CA hiện có (tên tạm, cạnh tệp cũ)'
    $changed = $true
    $prepareArgs = @('prepare', '--tls-dir', $P.Tls, '--ca-key', $P.CaKey, '--stamp', $stamp)
    if ($recovery) { $prepareArgs += @('--ip', $ip) }
    $r = Invoke-Cert $prepareArgs
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
    Suspend-MinhDucMaintenanceWindow -Window $window
    $r = Invoke-Cert @('commit', '--tls-dir', $P.Tls, '--stamp', $stamp)
    if (-not $r.Ok) { throw ('Lỗi khi thay tệp: ' + (($r.Output | Select-Object -Last 1) -join '')) }
    if ($Fault -eq 'khoi-phuc-loi') { throw 'Lỗi giả lập sau khi thay tệp (kiểm thử khôi phục thất bại).' }
    # Restart-Service không chờ cây Python cũ thoát sau khi WinSW báo Stopped.
    try {
        Restart-MinhDucService -Window $window
    } catch {
        if (-not $recovery -or $_.Exception.Data['MinhDucExternalProcess']) { throw }
        Write-Luu ('Khởi động lại lần đầu lỗi: ' + $_.Exception.Message + '. Thử thêm một lần với chứng chỉ mới.')
        Restart-MinhDucService -Window $window
    }

    Write-Buoc 'Bước 4/4: Kiểm tra HTTPS dùng đúng chứng chỉ mới'
    if (-not (Wait-Https -Origin $origin -Seconds 120)) { Show-ServiceDiagnostics -Paths $P; throw 'Dịch vụ web không trả lời sau 2 phút.' }
    $served = Get-ServedSerial $origin $ca
    if ($served -ne $renewed.serial) { throw 'Máy chủ chưa dùng chứng chỉ mới.' }
    Write-Dat ('Đã kiểm: HTTPS đang dùng chứng chỉ mới (số sê-ri ' + $served + '), hợp lệ theo ca.crt của phòng khám (CA không đổi).')
    $resultStatus = 'thanh_cong'
    $resultDetail = $(if ($recovery) { 'Phục hồi; ' } else { '' }) + 'hạn mới: ' + $renewed.not_after
} catch {
    $code = $_.Exception.Data['MinhDucExit']
    if (-not $window) {
        Write-Loi $_.Exception.Message
        $exitCode = if ($null -ne $code) { [int]$code } else { 1 }
    } elseif ($null -ne $code -and -not $changed) {
        $exitCode = [int]$code
        $resultStatus = 'dung'
        $resultDetail = $_.Exception.Message
    } else {
        $reason = $_.Exception.Message
        $resultDetail = $reason
        Write-Loi ('Gia hạn lỗi: ' + $reason)
        $rollbackOk = $false
        $httpsOk = $false
        $servedNow = $null
        if (-not $_.Exception.Data['MinhDucExternalProcess']) {
            try {
                Write-Buoc 'KHÔI PHỤC CHỨNG CHỈ CŨ'
                Suspend-MinhDucMaintenanceWindow -Window $window
                $r = Invoke-Cert @('rollback', '--tls-dir', $P.Tls, '--stamp', $stamp)
                $rollbackOk = $r.Ok
                if ($rollbackOk) { Write-Thongtin 'Đã đặt lại tệp chứng chỉ cũ; đang kiểm tra...' } else { Write-Loi ('Không đặt lại được tệp chứng chỉ cũ: ' + (($r.Output | Select-Object -Last 1) -join '')) }
                Set-SecureAcl -Path $P.Tls -Directory -Readers @($Names.ServiceAcct)
                foreach ($f in @('server.crt', 'server.key')) { Invoke-Native -FilePath 'icacls.exe' -Arguments @((Join-Path $P.Tls $f), '/reset') -Quiet | Out-Null }
                $outsideProcess = $false
                try {
                    Restart-MinhDucService -Window $window
                } catch {
                    Write-Loi ('Khởi động lại khi trả chứng chỉ cũ lỗi: ' + $_.Exception.Message)
                    $outsideProcess = $_.Exception.Data['MinhDucExternalProcess']
                }
                if (-not $outsideProcess) {
                    $httpsOk = Wait-Https -Origin $origin -Seconds 120
                    if ($httpsOk) { $servedNow = Get-ServedSerial $origin $ca }
                }
            } catch {
                Write-Loi ('Lỗi khi chuẩn bị hoặc kiểm tra khôi phục chứng chỉ: ' + $_.Exception.Message)
            }
        }
        # Chỉ coi là đã trả chứng chỉ cũ khi: khôi phục tệp đạt, HTTPS đạt, và đúng chứng chỉ cũ đang chạy.
        $restoreOk = $rollbackOk -and $httpsOk -and ($null -ne $servedNow) -and (($null -eq $oldSerial) -or ($servedNow -eq $oldSerial))
        Write-Host ''
        if ($restoreOk) {
            Write-Dat ('Kiểm tra sau khôi phục ĐẠT: HTTPS dùng chứng chỉ cũ (số sê-ri ' + $servedNow + ').')
            $resultStatus = 'da_tra_chung_chi_cu'
            Write-Host 'GIA HẠN KHÔNG THÀNH CÔNG — ĐÃ TRẢ CHỨNG CHỈ CŨ; HTTPS đã kiểm lại: ĐẠT. Báo người hỗ trợ để gia hạn lại.' -ForegroundColor Yellow
            $exitCode = 50
        } else {
            Write-Loi ('Kiểm tra sau khôi phục KHÔNG ĐẠT (khôi phục tệp: ' + $(if ($rollbackOk) { 'đạt' } else { 'lỗi' }) + ', HTTPS: ' + $(if ($httpsOk) { 'đạt' } else { 'lỗi' }) + ').')
            $resultStatus = 'khoi_phuc_that_bai'
            Write-Host $(if ($recovery) { 'PHỤC HỒI CHỨNG CHỈ KHÔNG THÀNH CÔNG.' } else { 'KHÔI PHỤC CHỨNG CHỈ CŨ THẤT BẠI: KHÔNG trả được chứng chỉ cũ.' }) -ForegroundColor Red
            Write-Host 'Phần mềm CÓ THỂ KHÔNG TRUY CẬP ĐƯỢC từ máy trạm. GỌI NGƯỜI HỖ TRỢ NGAY. Trong lúc chờ:' -ForegroundColor Red
            Write-Host '  1. Bấm đúp KIEM_TRA.bat, gửi tệp báo cáo trên Desktop và thư mục C:\ProgramData\MinhDuc\nhatky cho người hỗ trợ.' -ForegroundColor Yellow
            Write-Host ('  2. Chạy lại GIA_HAN_CHUNG_CHI.bat một lần (các tệp cũ được giữ với đuôi .cu-' + $stamp + ').') -ForegroundColor Yellow
            Write-Host '  3. Nếu máy trạm báo lỗi chứng chỉ: KHÔNG bấm bỏ qua cảnh báo; chờ người hỗ trợ.' -ForegroundColor Yellow
            $exitCode = 51
        }
    }
} finally {
    if ($window) {
        try { Exit-MinhDucMaintenanceWindow -Window $window }
        catch {
            $maintenanceError = 'Chưa trả được cấu hình bảo trì: ' + $_.Exception.Message
            Write-Loi $maintenanceError
            if ($resultStatus -eq 'thanh_cong') {
                $resultStatus = 'thanh_cong_can_kiem_tra'
                $exitCode = 8
            } elseif (-not $exitCode) {
                $resultStatus = 'khoi_phuc_that_bai'
                $exitCode = 51
            }
            $resultDetail = (@($resultDetail, $maintenanceError) | Where-Object { $_ }) -join ' | '
        }
        if ($resultStatus) {
            try { Write-Result $resultStatus $resultDetail }
            catch {
                Write-Loi ('Chưa ghi được tệp kết quả gia hạn: ' + $_.Exception.Message)
                if (-not $exitCode) { $exitCode = 1 }
            }
        }
    }
}
if ($exitCode -eq 8) {
    Write-Luu 'HTTPS ĐÃ DÙNG CHỨNG CHỈ MỚI, NHƯNG CHƯA KẾT THÚC BẢO TRÌ (mã 8). Chạy KIEM_TRA.bat để trả cấu hình còn thiếu.'
} elseif ($exitCode -eq 0 -and $resultStatus -eq 'thanh_cong') {
    Write-Host ''
    Write-Host $(if ($recovery) { 'PHỤC HỒI CHỨNG CHỈ THÀNH CÔNG (HTTPS đã kiểm lại: ĐẠT).' } else { 'GIA HẠN THÀNH CÔNG (HTTPS đã kiểm lại: ĐẠT).' }) -ForegroundColor Green
}
exit $exitCode
