# Cập nhật phần mềm Minh Đức từ tệp .zip tải về.
# Trình tự: dừng dịch vụ -> sao lưu -> kiểm bản sao lưu -> thay mã -> cài thư viện
# -> migration -> bật dịch vụ -> kiểm tra sức khỏe. Nếu đã gọi migration, quay về
# phải khôi phục cả CSDL, tệp đính kèm và cài đặt giao diện từ bản sao lưu.
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
$State = @{ warnings = @(); rollback_errors = @(); backup_tasks_captured = $false; backup_tasks_changed = $false; backup_task_snapshot = @(); stopped = $false; code_replaced = $false; venv_moved = $false; migrated = $false; backup = $null; fingerprint = $null }

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
    New-Item -ItemType Directory -Force -Path $P.Updates -ErrorAction Stop | Out-Null
    $temp = $ResultFile + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        @{
            status = $Status; detail = $Detail; time = (Get-Date).ToString('o')
            backup = $State.backup; rollback_errors = $State.rollback_errors; warnings = $State.warnings
        } | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding UTF8 -ErrorAction Stop
        if ([IO.File]::Exists($ResultFile)) { [IO.File]::Replace($temp, $ResultFile, [NullString]::Value) }
        else { [IO.File]::Move($temp, $ResultFile) }
    } finally {
        try {
            if ([IO.File]::Exists($temp)) { Remove-Item -LiteralPath $temp -Force -ErrorAction Stop }
        } catch { Add-UpdateWarning ('Chưa dọn được tệp kết quả tạm: ' + $_.Exception.Message) }
    }
}

function Add-UpdateWarning([string]$Message) {
    $State.warnings += $Message
    Write-Warning $Message -WarningAction Continue
}

function Save-InitialBackupTaskSnapshot {
    if ($State.backup_tasks_captured) { return }
    $snapshot = @(Get-MinhDucBackupTaskSnapshot)
    if ($snapshot.Count -notin @(1,2) -or @($snapshot | Where-Object { $_.Name -eq $Names.BackupTask }).Count -ne 1) {
        throw 'Lịch sao lưu ban đầu không hợp lệ: cần lịch hằng ngày cũ hoặc đủ hai lịch mới.'
    }
    $State.backup_task_snapshot = $snapshot
    $State.backup_tasks_captured = $true
}

function Invoke-QuayVe {
    param($Window)
    Write-Buoc 'TỰ QUAY VỀ BẢN CŨ'
    $failures = New-Object System.Collections.Generic.List[string]
    $recovery = @{ Code = $false; Venv = $false; Database = $false; Tasks = $false; Stopped = $true }
    $venvScan = @{ Venv = $P.Venv; ClinicEnv = $P.ClinicEnv; Known = @{} }
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
    $restoreFiles = {
        param($config)
        if ($needsRecovery) {
            $recovery.Stopped = Invoke-RecoveryStep 'Dừng dịch vụ trước phục hồi' {
                if ($config) {
                    $observed = @(Get-MinhDucVenvProcessTree @venvScan)
                    Write-MinhDucVenvLockDiagnostics -Venv $P.Venv -Context ('Đã khóa khởi động dịch vụ trong lúc quay về; PID trình bọc=' + $config.ProcessId) -ObservedProcesses $observed
                }
                $service = Get-Service -Name $Names.Service -ErrorAction Stop
                if ($service.Status -ne 'Stopped') { Stop-Service -Name $Names.Service -Force -ErrorAction Stop }
                $service.WaitForStatus('Stopped', (New-TimeSpan -Seconds 30))
                $service.Refresh()
                if ($service.Status -ne 'Stopped') { throw 'Dịch vụ chưa dừng; không thay mã hoặc dữ liệu đang chạy.' }
                if (-not $State.backup_task_snapshot.Count) { throw 'Thiếu snapshot lịch ban đầu; không chụp lại trong quay về.' }
                $State.backup_tasks_changed = $true
                if (-not $Window) { Suspend-MinhDucBackupTasks }
                Wait-MinhDucVenvPythonExit @venvScan -LogLockDiagnostics
                $service.Refresh()
                if ($service.Status -ne 'Stopped') { throw 'Dịch vụ đã chạy lại trong lúc chờ Python thoát.' }
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
                Wait-MinhDucVenvPythonExit @venvScan -LogLockDiagnostics
                Restore-MinhDucOldVenv -Venv $P.Venv -OldVenv $OldVenv -LogLockDiagnostics
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
                # Dấu vân tay chỉ kiểm cấu trúc và quyền, nên migration sửa dữ liệu vẫn phải phục hồi.
                $r = Invoke-Python -Paths $P -Quiet -Arguments @('-m', 'scripts.install_db', '--clinic-env', $P.ClinicEnv, '--owner-env', $P.OwnerEnv,
                    '--super-env', $P.SuperEnv, 'rollback', '--file', $State.backup, '--key', $P.BackupKey)
                if (-not $r.Ok) { throw ('Lệnh khôi phục CSDL trả mã ' + $r.Code + '; KHÔNG dùng phần mềm.') }
                Set-SecureAcl -Path $P.Attachments -Directory -Writers @($Names.ServiceAcct)
                if (Test-Path -LiteralPath $P.Settings) { Set-SecureAcl -Path $P.Settings -Directory -Writers @($Names.ServiceAcct) }
                $verified = Get-Fingerprint
                if (-not $verified -or $verified -ne $State.fingerprint) { throw 'Dấu vân tay CSDL chưa khớp bản trước cập nhật.' }
            }
        }
        $recovery.Tasks = Invoke-RecoveryStep 'Khôi phục lịch sao lưu cũ' {
            if ($State.backup_tasks_changed) { Restore-MinhDucBackupTasks -Snapshot $State.backup_task_snapshot -Disabled:([bool]$Window) }
        }
    }
    $startupRestored = $true
    if ($needsRecovery -and $Window) {
        $startupRestored = Invoke-RecoveryStep 'Khóa cài đặt bảo trì trước phục hồi' {
            Suspend-MinhDucMaintenanceWindow -Window $Window -AllowAlreadyDisabled
            Set-MinhDucRollbackPending -Window $Window
        }
    }
    if ($startupRestored) {
        $config = if ($Window) { $Window.ServiceConfig }
        & $restoreFiles $config
    }
    [void](Invoke-RecoveryStep 'Khởi động và kiểm HTTPS bản cũ' {
        if (-not $recovery.Code -or -not $recovery.Venv -or -not $recovery.Database) { throw 'Mã/Python/CSDL chưa đạt; giữ dịch vụ dừng để tránh dùng sai phiên bản.' }
        if (-not $startupRestored -or -not $recovery.Tasks) { throw 'Chưa chuẩn bị được chế độ bảo trì hoặc lịch sao lưu của bản cũ.' }
        if ($needsRecovery) {
            Start-MinhDucMaintenanceService -Window $Window
        }
        $service = Get-Service -Name $Names.Service -ErrorAction Stop
        $service.WaitForStatus('Running', (New-TimeSpan -Seconds 30))
        $service.Refresh()
        if ($service.Status -ne 'Running') { throw 'Dịch vụ cũ chưa chạy.' }
        $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
        if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { throw 'HTTPS bản cũ không lên sau khi khởi động.' }
    })
    if ($failures.Count -eq 0) {
        [void](Invoke-RecoveryStep 'Kiểm lịch sao lưu trước xác nhận quay về' {
            Resume-MinhDucMaintenanceWindow -Window $Window -VerifiedRollback -BackupTaskSnapshot $State.backup_task_snapshot
        })
    }
    if ($failures.Count -gt 0) {
        [void](Invoke-RecoveryStep 'Giữ dịch vụ, lịch sao lưu và tường lửa ở chế độ bảo trì' {
            Hold-MinhDucFailedMaintenanceWindow -Window $Window
        })
    }
    $State.rollback_errors = @($failures.ToArray())
    if ($failures.Count -gt 0) { throw ('Quay về chưa đạt: ' + ($failures -join '; ')) }
}

$exitCode = 0
$transcript = $false
$window = $null
$committed = $false
try {
    $admin = (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { Stop-CaiDat 'Cần quyền Administrator.' @('Bấm đúp CAP_NHAT.bat và chọn "Có".') 30 }
    Resume-MinhDucServiceStartMode -Paths $P -ScriptName 'CapNhat.ps1' | Out-Null
    if (-not (Test-Path -LiteralPath $P.ClinicEnv) -or -not (Get-Service -Name $Names.Service -ErrorAction SilentlyContinue)) {
        Stop-CaiDat 'Máy này chưa cài đặt bằng CAI_DAT.bat.' @('Chạy CAI_DAT.bat trước.') 2
    }
    $window = Enter-MinhDucMaintenanceWindow -Name $Names.Service -Paths $P -ScriptName 'CapNhat.ps1' -GuardHttps
    New-Item -ItemType Directory -Force -Path $P.Updates -ErrorAction Stop | Out-Null
    Set-SecureAcl -Path $P.Updates -Directory
    Start-Transcript -Path (Join-Path $P.Journal ('cap-nhat-' + $Stamp + '.log')) -ErrorAction Stop | Out-Null
    $transcript = $true
    Save-InitialBackupTaskSnapshot
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
    Unblock-File -LiteralPath $TepZip -ErrorAction Stop
    Expand-Archive -LiteralPath $TepZip -DestinationPath $NewDir -Force -ErrorAction Stop
    $root = @(Get-ChildItem -LiteralPath $NewDir -Recurse -Depth 2 -Filter 'main.py' -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq 'app' -and (Test-Path -LiteralPath (Join-Path $_.Directory.Parent.FullName 'requirements.lock')) -and
                       (Test-Path -LiteralPath (Join-Path $_.Directory.Parent.FullName 'deploy\windows\CaiDat.ps1')) } | Select-Object -First 1)
    if ($root.Count -eq 0) { Stop-CaiDat 'Tệp .zip không phải bản phần mềm Minh Đức hợp lệ.' @('Kiểm tra lại tệp tải về.') 5 }
    $newRoot = $root[0].Directory.Parent.FullName
    Test-D0PublicCatalogs -SourceRoot $newRoot
    Test-S2dPublicTemplate -SourceRoot $newRoot
    Get-ChildItem -LiteralPath $newRoot -Recurse -File -ErrorAction Stop | Unblock-File -ErrorAction Stop
    Write-Dat ('Phiên bản hiện tại: ' + (Get-AppVersion $P.Code) + '  →  bản mới: ' + (Get-AppVersion $newRoot))

    Write-Buoc 'Bước 3/8: Dừng dịch vụ web'
    Write-Luu 'Máy trạm tạm thời không vào được phần mềm từ lúc dừng dịch vụ, kể cả trong lúc sao lưu và kiểm tra bản sao lưu.'
    try {
        Stop-MinhDucService -Window $window
        $State.stopped = $true
    } catch {
        # WinSW có thể đã dừng trước khi bước chờ Python thoát báo lỗi.
        $service = Get-Service -Name $Names.Service -ErrorAction SilentlyContinue
        $State.stopped = $service.Status -in @('Stopped', 'StopPending')
        throw
    }
    Write-Dat 'Đã dừng dịch vụ web.'

    Write-Buoc 'Bước 4/8: Sao lưu và kiểm tra bản sao lưu'
    $failure = 'Sao lưu trước cập nhật thất bại'
    $guidance = @()
    try {
        $alert = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) $Names.AlertFile
        # Dùng CLI trong gói mới vì bản đang cài có thể chưa có cờ --no-prune.
        $r = Invoke-Python -Paths $P -WorkingDirectory $newRoot -Quiet -OkCodes @(0, 3) -Arguments @('-m', 'scripts.with_env', $P.ClinicEnv, 'scripts.backup_job', '--key', $P.BackupKey,
            '--directory', $P.Backups, '--state', $P.BackupState, '--external-config', $P.ExternalCfg, '--alert-file', $alert, '--no-prune')
        if (-not $r.Ok) {
            $guidance = @($r.Output | Select-Object -Last 4)
            throw ('Lệnh sao lưu trả mã ' + $r.Code)
        }
        # Dùng kết quả của chính lệnh này vì lịch sao lưu cũng ghi vào backup-status.json.
        $verified = $r.Output | Select-String -Pattern '^Sao luu va kiem tra ban sao luu: DAT (minhduc-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.mdbackup)$'
        if (-not $verified) { throw 'Lệnh sao lưu chưa xác nhận bản mới đã kiểm tra.' }
        $last = $verified.Matches[0].Groups[1].Value
        $backup = Join-Path $P.Backups $last
        if (-not (Test-Path -LiteralPath $backup -PathType Leaf) -or -not (Test-Path -LiteralPath ($backup + '.verified') -PathType Leaf)) {
            throw 'Thiếu bản sao lưu mới hoặc tệp đánh dấu đã kiểm tra.'
        }
        $State.backup = $backup
        Write-Dat ('Bản sao lưu đã kiểm tra: ' + $last)

        $failure = 'Không đọc được dấu vân tay CSDL trước cập nhật'
        $guidance = @('Kiểm tra PostgreSQL rồi chạy lại.')
        $State.fingerprint = Get-Fingerprint
        if (-not $State.fingerprint) { throw $failure }
    } catch {
        Write-Loi $_.Exception.Message
        Start-MinhDucMaintenanceService -Window $window
        $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
        if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { throw 'HTTPS bản cũ không lên sau khi khởi động.' }
        Resume-MinhDucMaintenanceWindow -Window $window
        $State.stopped = $false
        Write-Dat 'Dịch vụ web đã chạy lại và HTTPS đã kiểm tra.'
        Stop-CaiDat ($failure + '; chưa thay đổi gì.') $guidance 6
    }

    Write-Buoc 'Bước 5/8: Thay mã nguồn'
    $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($P.Code, $OldCode, '/MIR', '/R:2', '/W:2', '/XD', '.venv', '.venv-cu', '__pycache__', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $r.Ok) { throw 'Không sao chép được mã cũ để dự phòng.' }
    if (Test-Path -LiteralPath $OldVenv) { Remove-Item -LiteralPath $OldVenv -Recurse -Force -ErrorAction Stop }
    Rename-Item -LiteralPath $P.Venv -NewName '.venv-cu' -ErrorAction Stop
    $State.venv_moved = $true
    $State.code_replaced = $true
    $r = Invoke-Native -FilePath 'robocopy.exe' -Quiet -OkCodes @(0, 1, 2, 3, 4, 5, 6, 7) -Arguments @($newRoot, $P.Code, '/MIR', '/R:2', '/W:2', '/XD', '.venv', '.venv-cu', '.git', '__pycache__', 'test_evidence', 'data', 'backups', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if (-not $r.Ok) { throw 'Không chép được mã mới.' }
    Copy-D0PublicCatalogs -SourceRoot $newRoot -DestinationRoot $P.Code
    Copy-S2dPublicTemplate -SourceRoot $newRoot -DestinationRoot $P.Code
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
    New-Item -ItemType Directory -Force -Path $P.Settings -ErrorAction Stop | Out-Null
    Set-SecureAcl -Path $P.Settings -Directory -Writers @($Names.ServiceAcct)
    if (@((ConvertFrom-PythonJson $r).managed_changed).Count -gt 0) { Write-Dat 'Đã chuyển chính sách sao lưu: giữ 14 bản trên máy chủ (xóa bớt bản cũ chỉ sau lần sao lưu mới đầu tiên đã kiểm).' }
    Write-Dat 'Cấu trúc dữ liệu đã cập nhật.'
    # Load the shared task installer from the NEW code, even on an old installation.
    # Keep the single pre-update snapshot; never replace it after task changes.
    $State.backup_tasks_changed = $true
    & {
        Import-Module (Join-Path $P.Code 'deploy\windows\MinhDuc.Install.psm1') -Force -DisableNameChecking
        Set-MinhDucBackupTasks -Paths $P -Disabled
    }
    Write-Dat 'Đã chuyển và kiểm lịch sao lưu: 20:00 và chạy bù riêng.'


    Write-Buoc 'Bước 8/8: Bật dịch vụ và kiểm tra sức khỏe'
    Set-SecureAcl -Path $P.Code -Directory -Readers @('*S-1-5-32-545', $Names.ServiceAcct)
    $versionDetail = 'Phiên bản ' + (Get-AppVersion $P.Code)
    $origin = (Read-EnvFile -Path $P.ClinicEnv)['CLINIC_ORIGIN']
    Write-Result 'dang_cap_nhat' $versionDetail
    Start-MinhDucMaintenanceService -Window $window
    if (-not (Wait-Https -Origin $origin -Seconds 120 -LocalOnly)) { Show-ServiceDiagnostics -Paths $P; throw 'Dịch vụ web bản mới không trả lời sau 2 phút.' }
    # Chốt trước khi mở lại máy trạm. Sau mốc này giữ dữ liệu của bản mới.
    $committed = $true
    try { Resume-MinhDucMaintenanceWindow -Window $window }
    catch { Add-UpdateWarning ('Chưa kết thúc được cửa sổ bảo trì. Chạy KIEM_TRA.bat và báo người hỗ trợ: ' + $_.Exception.Message) }
    $resultWritten = $false
    try {
        Write-Result 'thanh_cong' $versionDetail
        $resultWritten = $true
    } catch { Add-UpdateWarning ('Chưa ghi được kết quả cập nhật: ' + $_.Exception.Message) }
    try {
        $report = Join-Path $P.Journal ('kiem-tra-sau-cap-nhat-' + $Stamp + '.txt')
        if (-not (Invoke-HealthReport -Paths $P -Output $report -Title 'KẾT QUẢ KIỂM TRA SAU CẬP NHẬT')) {
            Add-UpdateWarning ('Báo cáo sức khỏe có mục chưa đạt hoặc chưa tạo được. Kiểm tra tại ' + $report)
        }
    } catch { Add-UpdateWarning ('Lỗi báo cáo sức khỏe: ' + $_.Exception.Message) }
    try {
        if ($resultWritten -and (Test-Path -LiteralPath $OldVenv)) { Remove-Item -LiteralPath $OldVenv -Recurse -Force -ErrorAction Stop }
    } catch { Add-UpdateWarning ('Chưa dọn được môi trường Python cũ: ' + $_.Exception.Message) }
    try { Remove-Item -LiteralPath $NewDir -Recurse -Force -ErrorAction Stop }
    catch { Add-UpdateWarning ('Chưa dọn được thư mục giải nén: ' + $_.Exception.Message) }
    if ($State.warnings.Count) {
        try {
            Write-Result 'thanh_cong' $versionDetail
            $resultWritten = $true
        } catch { Add-UpdateWarning ('Chưa lưu được cảnh báo vào kết quả cập nhật: ' + $_.Exception.Message) }
    }
    Write-Host ''
    if ($resultWritten) {
        Write-Host ('CẬP NHẬT THÀNH CÔNG. Bản mã cũ được giữ tại ' + $OldCode) -ForegroundColor Green
    } else {
        $exitCode = 7
        Write-Luu 'CẬP NHẬT ĐÃ CHỐT VÀ HTTPS ĐÃ ĐẠT, NHƯNG CHƯA GHI ĐƯỢC TỆP KẾT QUẢ (mã 7). Báo người hỗ trợ.'
    }
} catch {
    $code = $_.Exception.Data['MinhDucExit']
    if ($committed) {
        Add-UpdateWarning $_.Exception.Message
    } elseif (-not $window) {
        Write-Loi $_.Exception.Message
        $exitCode = if ($null -ne $code) { [int]$code } else { 1 }
    } elseif (-not $window.FirewallReady) {
        Write-Loi $_.Exception.Message
        $exitCode = if ($null -ne $code) { [int]$code } else { 1 }
        try { Resume-MinhDucMaintenanceWindow -Window $window }
        catch { Write-Loi ('Chưa trả được cấu hình bảo trì. Báo người hỗ trợ: ' + $_.Exception.Message) }
        if ($null -ne $code) {
            try { Write-Result 'dung_truoc_khi_thay_doi' $_.Exception.Message }
            catch { Add-UpdateWarning ('Chưa lưu được kết quả cập nhật: ' + $_.Exception.Message) }
        }
    } elseif ($null -ne $code -and -not $State.stopped) {
        $exitCode = [int]$code
        try { Write-Result 'dung_truoc_khi_thay_doi' $_.Exception.Message }
        catch { Add-UpdateWarning ('Chưa lưu được kết quả cập nhật: ' + $_.Exception.Message) }
    } else {
        $updateError = $_.Exception.Message
        $rollbackError = ''
        $exitCode = 50
        Write-Loi ('Cập nhật lỗi: ' + $updateError)
        $rollbackOk = $true
        try { Invoke-QuayVe -Window $window } catch { $rollbackOk = $false; $rollbackError = $_.Exception.Message; Write-Loi ('Quay về bản cũ gặp lỗi: ' + $rollbackError) }
        if ($rollbackOk) {
            try { Write-Result 'da_quay_ve' $updateError }
            catch { Add-UpdateWarning ('Chưa lưu được kết quả quay về: ' + $_.Exception.Message) }
            Write-Host 'CẬP NHẬT KHÔNG THÀNH CÔNG — ĐÃ QUAY VỀ BẢN CŨ. Gửi nhật ký cho người hỗ trợ.' -ForegroundColor Yellow
        } else {
            try { Write-Result 'quay_ve_that_bai' ($updateError + ' | ' + $rollbackError) }
            catch { Add-UpdateWarning ('Chưa lưu được kết quả quay về: ' + $_.Exception.Message) }
            Write-Host 'CẬP NHẬT THẤT BẠI, CHƯA KHÔI PHỤC ĐỦ. Không dùng phần mềm; báo người hỗ trợ ngay.' -ForegroundColor Red
        }
    }
} finally {
    try {
        if ($transcript) { Stop-Transcript | Out-Null }
    } catch {
        if ($committed) { Add-UpdateWarning $_.Exception.Message }
        else { Write-Loi $_.Exception.Message; if (-not $exitCode) { $exitCode = 1 } }
    } finally {
        if ($window) {
            try { Exit-MinhDucMaintenanceWindow -Window $window -KeepPending }
            catch {
                if ($committed) { Add-UpdateWarning $_.Exception.Message }
                else { Write-Loi $_.Exception.Message; if (-not $exitCode) { $exitCode = 1 } }
            }
        }
    }
}
exit $exitCode
