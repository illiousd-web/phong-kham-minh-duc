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
    Write-Host '  - Không tự tắt Smart App Control hay App Control. Dừng và gọi người hỗ trợ (chụp màn hình này gửi kèm).' -ForegroundColor Yellow
    exit 20
}
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Import-Module (Join-Path $PSScriptRoot 'MinhDuc.Install.psm1') -Force -DisableNameChecking
. (Join-Path $PSScriptRoot 'DanhMucGoc.ps1')
$Names = Get-MinhDucNames
$ThuMucMa = [IO.Path]::GetFullPath($ThuMucMa)
$P = Get-MinhDucPaths -Code $ThuMucMa -Data $ThuMucDuLieu
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OldCode = Join-Path $P.Updates ('ma-cu-' + $Stamp)
$NewDir = Join-Path $P.Updates ('moi-' + $Stamp)
$OldVenv = Join-Path $P.Code '.venv-cu'
$ResultFile = Join-Path $P.Updates 'ket-qua-cap-nhat.json'
$State = @{ rollback_errors = @(); backup_tasks_changed = $false; backup_task_snapshot = @(); stopped = $false; code_replaced = $false; venv_moved = $false; migrated = $false; backup = $null; fingerprint = $null }

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
    @{ status = $Status; detail = $Detail; time = (Get-Date).ToString('o'); backup = $State.backup; rollback_errors = $State.rollback_errors } | ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding UTF8
}

function Invoke-QuayVe {
    Write-Buoc 'TỰ QUAY VỀ BẢN CŨ'
    $failures = New-Object System.Collections.Generic.List[string]
    $recovery = @{ Code = $false; Venv = $false; Database = $false; Tasks = $false; Stopped = $true }
    function Invoke-RecoveryStep([string]$Label, [scriptblock]$Action) {
        try {
            & $Action | Out-Null
            Write-Dat ($Label + ': ĐẠT')
            return $true
        } catch {
            $message = $Label + ': ' + $_.Exception.Message
            $failures.Add($message)
            Write-Loi $message
            return $false
        }
    }
    $needsRecovery = $State.stopped -or $State.code_replaced -or $State.venv_moved -or $State.migrated -or $State.backup_tasks_changed
    if ($needsRecovery) {
        $recovery.Stopped = Invoke-RecoveryStep 'Dừng dịch vụ trước phục hồi' {
            $service = Get-Service -Name $Names.Service -ErrorAction Stop
            if ($service.Status -ne 'Stopped') { Stop-Service -Name $Names.Service -Force -ErrorAction Stop }
            $service.WaitForStatus('Stopped', (New-TimeSpan -Seconds 30))
            $service.Refresh()
            if ($service.Status -ne 'Stopped') { throw 'Dịch vụ chưa dừng; không thay mã hoặc dữ liệu đang chạy.' }
            if (-not $State.backup_tasks_changed) {
                $State.backup_task_snapshot = @(Get-MinhDucBackupTaskSnapshot)
                $State.backup_tasks_changed = $true
            }
            Suspend-MinhDucBackupTasks
            Wait-MinhDucVenvPythonExit -Venv $P.Venv
        }
    }
    $recovery.Code = Invoke-RecoveryStep 'Trả mã nguồn cũ' {
        if (-not $recovery.Stopped) { throw 'Không dừng được dịch vụ, chưa thể trả mã.' }
        if ($State.code_replaced) {
            if (-not (Test-Path -LiteralPath $OldCode -PathType Container)) { throw 'Thiếu thư mục mã nguồn cũ.' }
            $r = Invoke-MinhDucAccessRetry -Action {
                Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($OldCode, $P.Code, '/MIR', '/R:0', '/W:0', '/XD', '.venv', '.venv-cu', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
            } -RetryResult { param($result) $result.Code -ge 8 }
            if (-not $r.Ok) { throw ('Chép trả mã nguồn thất bại, mã ' + $r.Code) }
            foreach ($file in Get-ChildItem -LiteralPath $OldCode -Recurse -File -Force -ErrorAction Stop) {
                $relative = $file.FullName.Substring($OldCode.Length).TrimStart('\')
                if ($relative -match '(^|\\)(\.venv(-cu)?|__pycache__)(\\|$)') { continue }
                $destination = Join-Path $P.Code $relative
                if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw ('Thiếu tệp mã đã phục hồi: ' + $relative) }
                if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256 -ErrorAction Stop).Hash -ne (Get-FileHash -LiteralPath $destination -Algorithm SHA256 -ErrorAction Stop).Hash) {
                    throw ('Tệp mã phục hồi không khớp: ' + $relative)
                }
            }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $P.Code 'app\main.py') -PathType Leaf)) { throw 'Thiếu app/main.py của bản cũ.' }
    }
    $recovery.Venv = Invoke-RecoveryStep 'Trả môi trường Python cũ' {
        if (-not $recovery.Stopped) { throw 'Không dừng được dịch vụ, chưa thể trả môi trường Python.' }
        if ($State.venv_moved) {
            if (-not (Test-Path -LiteralPath $OldVenv -PathType Container)) { throw 'Thiếu môi trường Python cũ.' }
            Invoke-MinhDucAccessRetry {
                if (Test-Path -LiteralPath $P.Venv) { Remove-Item -LiteralPath $P.Venv -Recurse -Force -ErrorAction Stop }
                Rename-Item -LiteralPath $OldVenv -NewName '.venv' -ErrorAction Stop
            }
            if (Test-Path -LiteralPath $OldVenv) { throw 'Chưa chuyển xong môi trường Python cũ.' }
        }
        if (-not (Test-Path -LiteralPath $P.VenvPython -PathType Leaf)) { throw 'Không có trình Python của bản cũ.' }
        $r = Invoke-Python -Paths $P -Quiet -Arguments @('-c', 'import sys; print(sys.prefix)')
        if (-not $r.Ok) { throw ('Python bản cũ không chạy được, mã ' + $r.Code) }
    }
    $recovery.Database = Invoke-RecoveryStep 'Khôi phục CSDL và tệp đính kèm' {
        if (-not $recovery.Code -or -not $recovery.Venv) { throw 'Mã hoặc Python chưa phục hồi đúng; chưa thể phục hồi CSDL.' }
        if ($State.migrated) {
            if (-not $State.fingerprint) { throw 'Thiếu dấu vân tay CSDL trước cập nhật.' }
            $now = Get-Fingerprint
            if (-not $now -or $now -ne $State.fingerprint) {
                $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv,
                    '--super-env', $P.SuperEnv, 'rollback', '--file', $State.backup, '--key', $P.BackupKey)
                if (-not $r.Ok) { throw ('Lệnh khôi phục CSDL trả mã ' + $r.Code + '; KHÔNG dùng phần mềm.') }
                Set-SecureAcl -Path $P.Attachments -Directory -Writers @($Names.ServiceAcct)
                if (Test-Path -LiteralPath $P.Settings) { Set-SecureAcl -Path $P.Settings -Directory -Writers @($Names.ServiceAcct) }
            }
            $verified = Get-Fingerprint
            if (-not $verified -or $verified -ne $State.fingerprint) { throw 'Dấu vân tay CSDL chưa khớp bản trước cập nhật.' }
        }
    }
    $recovery.Tasks = Invoke-RecoveryStep 'Khôi phục lịch sao lưu cũ' {
        if ($State.backup_tasks_changed) { Restore-MinhDucBackupTasks -Snapshot $State.backup_task_snapshot }
    }
    [void](Invoke-RecoveryStep 'Khởi động và kiểm HTTPS bản cũ' {
        if (-not $recovery.Code -or -not $recovery.Venv -or -not $recovery.Database) { throw 'Mã/Python/CSDL chưa đạt; giữ dịch vụ dừng để tránh dùng sai phiên bản.' }
        if ($needsRecovery) { Start-Service -Name $Names.Service -ErrorAction Stop }
        $service = Get-Service -Name $Names.Service -ErrorAction Stop
        $service.WaitForStatus('Running', (New-TimeSpan -Seconds 30))
        $service.Refresh()
        if ($service.Status -ne 'Running') { throw 'Dịch vụ cũ chưa chạy.' }
        $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
        if (-not (Wait-Https -Origin $origin -Seconds 120)) { throw 'HTTPS bản cũ không lên sau khi khởi động.' }
    })
    $State.rollback_errors = @($failures.ToArray())
    if ($failures.Count -gt 0) { throw ('Quay về chưa đạt: ' + ($failures -join '; ')) }
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
    Test-D0PublicCatalogs -SourceRoot $newRoot
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
    if (-not $State.fingerprint) { Stop-CaiDat 'Không đọc được dấu vân tay CSDL trước cập nhật; chưa thay đổi mã/dữ liệu.' @('Kiểm tra PostgreSQL rồi chạy lại.') 6 }

    Write-Buoc 'Bước 4/8: Dừng dịch vụ web'
    Stop-Service -Name $Names.Service -Force
    $State.stopped = $true
    Write-Dat 'Đã dừng dịch vụ (máy trạm tạm thời không vào được).'

    Write-Buoc 'Bước 5/8: Thay mã nguồn'
    $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($P.Code, $OldCode, '/MIR', '/R:2', '/W:2', '/XD', '.venv', '.venv-cu', '__pycache__', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $r.Ok) { throw 'Không sao chép được mã cũ để dự phòng.' }
    if (Test-Path -LiteralPath $OldVenv) { Remove-Item -LiteralPath $OldVenv -Recurse -Force }
    Rename-Item -LiteralPath $P.Venv -NewName '.venv-cu'
    $State.venv_moved = $true
    $State.code_replaced = $true
    $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($newRoot, $P.Code, '/MIR', '/R:2', '/W:2', '/XD', '.venv', '.venv-cu', '.git', '__pycache__', 'test_evidence', 'data', 'backups', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $r.Ok) { throw 'Không chép được mã mới.' }
    Copy-D0PublicCatalogs -SourceRoot $newRoot -DestinationRoot $P.Code
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
    # Bước grant (mã mới) cũng cập nhật chính sách sao lưu (14 bản), giữ nguyên mật khẩu; đặt lại quyền tệp.
    Set-SecureAcl -Path $P.ClinicEnv -Readers @($Names.ServiceAcct)
    Set-SecureAcl -Path $P.OwnerEnv
    # Thư mục cài đặt giao diện (ui_settings.json): dịch vụ được ghi khi quản trị đổi Cài đặt.
    New-Item -ItemType Directory -Force -Path $P.Settings | Out-Null
    Set-SecureAcl -Path $P.Settings -Directory -Writers @($Names.ServiceAcct)
    if (@((ConvertFrom-PythonJson $r).managed_changed).Count -gt 0) { Write-Dat 'Đã chuyển chính sách sao lưu: giữ 14 bản trên máy chủ (xóa bớt bản cũ chỉ sau lần sao lưu mới đầu tiên đã kiểm).' }
    Write-Dat 'Cấu trúc dữ liệu đã cập nhật.'
    # Load the shared task installer from the NEW code, even on an old installation.
    Import-Module (Join-Path $P.Code 'deploy\windows\MinhDuc.Install.psm1') -Force -DisableNameChecking
    $State.backup_task_snapshot = @(Get-MinhDucBackupTaskSnapshot)
    $State.backup_tasks_changed = $true
    Set-MinhDucBackupTasks -Paths $P
    Write-Dat 'Đã chuyển và kiểm lịch sao lưu: 20:00 và chạy bù riêng.'


    Write-Buoc 'Bước 8/8: Bật dịch vụ và kiểm tra sức khỏe'
    Set-SecureAcl -Path $P.Code -Directory -Readers @('*S-1-5-32-545', $Names.ServiceAcct)
    Start-Service -Name $Names.Service
    $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
    if (-not (Wait-Https -Origin $origin -Seconds 120)) { Show-ServiceDiagnostics -Paths $P; throw 'Dịch vụ web bản mới không trả lời sau 2 phút.' }
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
        $updateError = $_.Exception.Message
        $rollbackError = ''
        Write-Loi ('Cập nhật lỗi: ' + $updateError)
        $rollbackOk = $true
        try { Invoke-QuayVe } catch { $rollbackOk = $false; $rollbackError = $_.Exception.Message; Write-Loi ('Quay về bản cũ gặp lỗi: ' + $rollbackError) }
        if ($rollbackOk) {
            Write-Result 'da_quay_ve' $updateError
            Write-Host 'CẬP NHẬT KHÔNG THÀNH CÔNG — ĐÃ QUAY VỀ BẢN CŨ. Gửi nhật ký cho người hỗ trợ.' -ForegroundColor Yellow
        } else {
            Write-Result 'quay_ve_that_bai' ($updateError + ' | ' + $rollbackError)
            Write-Host 'CẬP NHẬT THẤT BẠI, CHƯA KHÔI PHỤC ĐỦ. Không dùng phần mềm; báo người hỗ trợ ngay.' -ForegroundColor Red
        }
        $exitCode = 50
    }
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
}
exit $exitCode
