# Cập nhật phần mềm Minh Đức từ tệp .zip tải về.
# Trình tự: sao lưu -> kiểm bản sao lưu -> dừng dịch vụ -> thay mã -> cài thư viện
# -> migration -> bật dịch vụ -> kiểm tra sức khỏe. Lỗi ở bất kỳ bước nào sau khi dừng
# dịch vụ: tự đưa mã, thư viện và (nếu CSDL đã đổi) cơ sở dữ liệu về bản cũ.
[CmdletBinding()]
param(
    [string]$TepZip = '',
    [switch]$KhongHoi,
    [string]$ThuMucMa = 'C:\MinhDuc',
    [string]$ThuMucDuLieu = 'C:\ProgramData\MinhDuc'
)
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    Write-Host 'DỪNG LẠI: Windows đang chặn script (App Control / Smart App Control).' -ForegroundColor Red
    exit 20
}
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$Names = Get-MinhDucNames
$ThuMucMa = [IO.Path]::GetFullPath($ThuMucMa)
$P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OldCode = Join-Path $P.Updates ('ma-cu-' + $Stamp)
$NewDir = Join-Path $P.Updates ('moi-' + $Stamp)
$OldVenv = Join-Path $P.Code '.venv-cu'
$ResultFile = Join-Path $P.Updates 'ket-qua-cap-nhat.json'
$State = @{ stopped = $false; code_replaced = $false; venv_moved = $false; migrated = $false; backup = $null; fingerprint = $null }

function Get-AppVersion([string]$Root) {
    $main = Join-Path $Root 'app\main.py'
    if (Test-Path -LiteralPath $main) {
        $m = Select-String -LiteralPath $main -Pattern "'version':'([0-9.]+)'" | Select-Object -First 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    return '?'
}

function Get-Fingerprint {
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv, 'fingerprint')
    if ($r.Ok) { return (ConvertFrom-PythonJson $r).sha256 }
    return $null
}

function Write-Result([string]$Status, [string]$Detail) {
    New-Item -ItemType Directory -Force -Path $P.Updates | Out-Null
    @{ status = $Status; detail = $Detail; time = (Get-Date).ToString('o'); backup = $State.backup } | ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding UTF8
}

function Invoke-QuayVe {
    Write-Buoc 'TỰ QUAY VỀ BẢN CŨ'
    Stop-Service -Name $Names.Service -Force -ErrorAction SilentlyContinue
    if ($State.code_replaced -and (Test-Path -LiteralPath $OldCode)) {
        $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($OldCode, $P.Code, '/MIR', '/XD', '.venv', '.venv-cu', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
        if ($r.Ok) { Write-Dat 'Đã trả mã nguồn về bản cũ.' } else { Write-Loi 'Không trả được mã nguồn; báo người hỗ trợ ngay.' }
    }
    if ($State.venv_moved -and (Test-Path -LiteralPath $OldVenv)) {
        if (Test-Path -LiteralPath $P.Venv) { Remove-Item -LiteralPath $P.Venv -Recurse -Force }
        Rename-Item -LiteralPath $OldVenv -NewName '.venv'
        Write-Dat 'Đã trả thư viện Python về bản cũ.'
    }
    $changed = $true
    if ($State.fingerprint) { $now = Get-Fingerprint; $changed = ($null -eq $now -or $now -ne $State.fingerprint) }
    if ($State.migrated -and $changed) {
        Write-Thongtin 'Cấu trúc dữ liệu đã thay đổi: khôi phục cơ sở dữ liệu từ bản sao lưu vừa tạo (giữ lại bản lỗi để kiểm tra)...'
        $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv,
            '--super-env', $P.SuperEnv, 'rollback', '--file', $State.backup, '--key', $P.BackupKey)
        if ($r.Ok) {
            Set-SecureAcl -Path $P.Attachments -Directory -Writers @($Names.ServiceAcct)
            Write-Dat 'Đã khôi phục cơ sở dữ liệu và tệp đính kèm về thời điểm trước cập nhật.'
        }
        else { Write-Loi 'Khôi phục cơ sở dữ liệu thất bại; KHÔNG dùng phần mềm, báo người hỗ trợ ngay.'; $r.Output | Select-Object -Last 3 | ForEach-Object { Write-Thongtin $_ } }
    } elseif ($State.migrated) { Write-Dat 'Cơ sở dữ liệu không bị thay đổi, giữ nguyên.' }
    if ($State.stopped) {
        Start-Service -Name $Names.Service -ErrorAction SilentlyContinue
        $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
        if (Wait-Https -Origin $origin -Seconds 120) { Write-Dat 'Phần mềm bản cũ đã chạy lại bình thường.' }
        else { Write-Loi 'Bản cũ chưa chạy lại được. Bấm KIEM_TRA.bat và gửi kết quả cho người hỗ trợ.' }
    }
}

$exitCode = 0
$transcript = $false
try {
    $admin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { Stop-CaiDat 'Cần quyền Administrator.' @('Bấm đúp CAP_NHAT.bat và chọn "Có".') 30 }
    if (-not (Test-Path -LiteralPath $P.ClinicEnv) -or -not (Get-Service -Name $Names.Service -ErrorAction SilentlyContinue)) {
        Stop-CaiDat 'Máy này chưa cài đặt bằng CAI_DAT.bat.' @('Chạy CAI_DAT.bat trước.') 2
    }
    New-Item -ItemType Directory -Force -Path $P.Updates | Out-Null
    Set-SecureAcl -Path $P.Updates -Directory
    Start-Transcript -Path (Join-Path $P.Journal ('cap-nhat-' + $Stamp + '.log')) | Out-Null
    $transcript = $true
    Write-Host 'CẬP NHẬT PHẦN MỀM PHÒNG KHÁM ĐA KHOA MINH ĐỨC' -ForegroundColor Cyan

    Write-Buoc 'Bước 1/8: Chọn tệp cập nhật (.zip)'
    if (-not $TepZip) {
        $downloads = Join-Path $env:USERPROFILE 'Downloads'
        $latest = Get-ChildItem -LiteralPath $downloads -Filter '*.zip' -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'minh|phong-kham' } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest -and (Read-CoKhong ('Dùng tệp ' + $latest.FullName + ' (' + $latest.LastWriteTime.ToString('dd/MM/yyyy HH:mm') + ')?') -KhongHoi:$KhongHoi -MacDinh $false)) { $TepZip = $latest.FullName }
        elseif (-not $KhongHoi) { $TepZip = (Read-Host '  Kéo thả tệp .zip vào cửa sổ này (hoặc gõ đường dẫn) rồi bấm Enter').Trim('"', ' ') }
    }
    if (-not $TepZip -or -not (Test-Path -LiteralPath $TepZip)) { Stop-CaiDat 'Không thấy tệp cập nhật .zip.' @('Tải tệp cập nhật vào thư mục Downloads rồi chạy lại.') 3 }
    $zipHash = (Get-FileHash -LiteralPath $TepZip -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Thongtin ('Tệp: ' + $TepZip)
    Write-Thongtin ('SHA256: ' + $zipHash + '  (đối chiếu với người gửi bản cập nhật)')
    $expected = $TepZip + '.sha256'
    if (Test-Path -LiteralPath $expected) {
        if ((Get-Content -LiteralPath $expected -Raw) -notmatch $zipHash) { Stop-CaiDat 'Mã SHA256 của tệp cập nhật không khớp tệp .sha256 kèm theo.' @('Tải lại tệp cập nhật.') 4 }
        Write-Dat 'Mã SHA256 khớp tệp .sha256 kèm theo.'
    }

    Write-Buoc 'Bước 2/8: Giải nén và kiểm tra tệp cập nhật'
    Unblock-File -LiteralPath $TepZip -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $TepZip -DestinationPath $NewDir -Force
    $root = @(Get-ChildItem -LiteralPath $NewDir -Recurse -Depth 2 -Filter 'main.py' -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq 'app' -and (Test-Path -LiteralPath (Join-Path $_.Directory.Parent.FullName 'requirements.lock')) -and
                       (Test-Path -LiteralPath (Join-Path $_.Directory.Parent.FullName 'deploy\windows\CaiDat.ps1')) } | Select-Object -First 1)
    if ($root.Count -eq 0) { Stop-CaiDat 'Tệp .zip không phải bản phần mềm Minh Đức hợp lệ.' @('Kiểm tra lại tệp tải về.') 5 }
    $newRoot = $root[0].Directory.Parent.FullName
    Get-ChildItem -LiteralPath $newRoot -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
    Write-Dat ('Phiên bản hiện tại: ' + (Get-AppVersion $P.Code) + '  →  bản mới: ' + (Get-AppVersion $newRoot))

    Write-Buoc 'Bước 3/8: Sao lưu và kiểm tra bản sao lưu'
    $alert = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) $Names.AlertFile
    $r = Invoke-Python -Paths $P -Quiet -OkCodes @(0, 3) -Arguments @('-m', 'scripts.with_env', $P.ClinicEnv, 'scripts.backup_job', '--key', $P.BackupKey,
        '--directory', $P.Backups, '--state', $P.BackupState, '--external-config', $P.ExternalCfg, '--alert-file', $alert)
    if (-not $r.Ok) { Stop-CaiDat 'Sao lưu trước cập nhật thất bại; chưa thay đổi gì.' ($r.Output | Select-Object -Last 4) 6 }
    $last = (Get-Content -LiteralPath $P.BackupState -Raw | ConvertFrom-Json).last_file
    $State.backup = Join-Path $P.Backups $last
    Write-Dat ('Bản sao lưu đã kiểm tra: ' + $last)
    $State.fingerprint = Get-Fingerprint

    Write-Buoc 'Bước 4/8: Dừng dịch vụ web'
    Stop-Service -Name $Names.Service -Force
    $State.stopped = $true
    Write-Dat 'Đã dừng dịch vụ (máy trạm tạm thời không vào được).'

    Write-Buoc 'Bước 5/8: Thay mã nguồn'
    $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($P.Code, $OldCode, '/MIR', '/XD', '.venv', '.venv-cu', '__pycache__', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $r.Ok) { throw 'Không sao chép được mã cũ để dự phòng.' }
    if (Test-Path -LiteralPath $OldVenv) { Remove-Item -LiteralPath $OldVenv -Recurse -Force }
    Rename-Item -LiteralPath $P.Venv -NewName '.venv-cu'
    $State.venv_moved = $true
    $State.code_replaced = $true
    $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($newRoot, $P.Code, '/MIR', '/XD', '.venv', '.venv-cu', '.git', '__pycache__', 'test_evidence', 'data', 'backups', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $r.Ok) { throw 'Không chép được mã mới.' }
    Write-Dat 'Đã thay mã nguồn (bản cũ được giữ để quay về).'

    Write-Buoc 'Bước 6/8: Cài thư viện (kiểm mã băm)'
    $r = Invoke-Native -FilePath $P.BasePython -Arguments @('-m', 'venv', $P.Venv) -Quiet
    if (-not $r.Ok) { throw 'Không tạo được môi trường Python mới.' }
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'pip', 'install', '--no-input', '--require-hashes', '--no-deps', '--only-binary=:all:', '-r', (Join-Path $P.Code 'requirements.lock'))
    if (-not $r.Ok) { $r.Output | Select-Object -Last 5 | ForEach-Object { Write-Thongtin $_ }; throw 'Cài thư viện thất bại.' }
    Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'compileall', '-q', (Join-Path $P.Code 'app'), (Join-Path $P.Code 'scripts')) | Out-Null
    Write-Dat 'Đã cài thư viện.'

    Write-Buoc 'Bước 7/8: Migration và cấp quyền'
    $State.migrated = $true
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.with_env', $P.OwnerEnv, 'scripts.manage', 'migrate')
    if (-not $r.Ok) { $r.Output | Select-Object -Last 5 | ForEach-Object { Write-Thongtin $_ }; throw 'Migration thất bại.' }
    $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv, 'grant')
    if (-not $r.Ok) { throw 'Cấp quyền thất bại.' }
    Write-Dat 'Cấu trúc dữ liệu đã cập nhật.'

    Write-Buoc 'Bước 8/8: Bật dịch vụ và kiểm tra sức khỏe'
    Set-SecureAcl -Path $P.Code -Directory -Readers @('*S-1-5-32-545', $Names.ServiceAcct)
    Start-Service -Name $Names.Service
    $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
    if (-not (Wait-Https -Origin $origin -Seconds 120)) { throw 'Dịch vụ web bản mới không trả lời sau 2 phút.' }
    $report = Join-Path $P.Journal ('kiem-tra-sau-cap-nhat-' + $Stamp + '.txt')
    Invoke-HealthReport -Paths $P -Output $report -Title 'KẾT QUẢ KIỂM TRA SAU CẬP NHẬT' | Out-Null
    if (Test-Path -LiteralPath $OldVenv) { Remove-Item -LiteralPath $OldVenv -Recurse -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $NewDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Result 'thanh_cong' ('Phiên bản ' + (Get-AppVersion $P.Code))
    Write-Host ''
    Write-Host ('CẬP NHẬT THÀNH CÔNG. Bản mã cũ được giữ tại ' + $OldCode) -ForegroundColor Green
} catch {
    $code = $_.Exception.Data['MinhDucExit']
    if ($null -ne $code -and -not $State.stopped) {
        $exitCode = [int]$code
        Write-Result 'dung_truoc_khi_thay_doi' $_.Exception.Message
    } else {
        Write-Loi ('Cập nhật lỗi: ' + $_.Exception.Message)
        try { Invoke-QuayVe } catch { Write-Loi ('Quay về bản cũ gặp lỗi: ' + $_.Exception.Message) }
        Write-Result 'da_quay_ve' $_.Exception.Message
        Write-Host ''
        Write-Host 'CẬP NHẬT KHÔNG THÀNH CÔNG — ĐÃ QUAY VỀ BẢN CŨ. Gửi tệp nhật ký trong C:\ProgramData\MinhDuc\nhatky cho người hỗ trợ.' -ForegroundColor Yellow
        $exitCode = 50
    }
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
}
exit $exitCode
