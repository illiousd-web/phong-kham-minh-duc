# Chạy phần bảo trì thật của CapNhat.ps1 bằng dịch vụ và lệnh Python giả lập.
$ErrorActionPreference = 'Stop'
$windowsDir = Join-Path $PSScriptRoot '../deploy/windows'
$module = Import-Module (Join-Path $windowsDir 'MinhDuc.Install.psm1') -Force -DisableNameChecking -PassThru
& $module {
    function Get-NetIPAddress {
        param($AddressFamily, $IPAddress, $ErrorAction)
        if ($AddressFamily -ne 'IPv4' -or $IPAddress -ne '192.168.50.5') { throw 'Đọc nhầm địa chỉ máy chủ.' }
        @{ IPAddress = $IPAddress }
    }
    $envFile = New-TemporaryFile -ErrorAction Stop
    try {
        $paths = @{ ClinicEnv = $envFile.FullName }
        Set-Content -LiteralPath $paths.ClinicEnv -Value @('CLINIC_ORIGIN=https://192.168.50.5:8443', 'CLINIC_BIND_IP=192.168.50.5')
        $scope = Get-MinhDucMaintenanceFirewallScope $paths
        if ($scope.IP -ne '192.168.50.5' -or ($scope.Remote -join ',') -ne '0.0.0.0-192.168.50.4,192.168.50.6-255.255.255.255') {
            throw 'Hai khoảng chặn phải phủ các địa chỉ từ xa, trừ IP nguồn của máy chủ.'
        }
        Set-Content -LiteralPath $paths.ClinicEnv -Value @('CLINIC_ORIGIN=https://192.168.50.5:5432', 'CLINIC_BIND_IP=192.168.50.5')
        $wrongPortRejected = $false
        try { $null = Get-MinhDucMaintenanceFirewallScope $paths }
        catch { $wrongPortRejected = $true }
        if (-not $wrongPortRejected) { throw 'Cho phép dựng quy tắc ngoài cổng HTTPS của phần mềm.' }
    } finally { Remove-Item -LiteralPath $envFile.FullName -Force }
}
Write-Output 'PASS: Firewall IPv4 scope'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $windowsDir 'CapNhat.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Get-AppVersion', 'Get-Fingerprint', 'Write-Result', 'Add-UpdateWarning', 'Invoke-QuayVe')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $false)
    Invoke-Expression $definition.Extent.Text
}
$main = $ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.TryStatementAst] } | Select-Object -Last 1
# Bỏ phần kiểm quyền quản trị và mở ZIP. Giữ các bước bảo trì và nhánh catch chính.
$statements = $main.Body.Statements
$start = $statements | Where-Object { $_.Extent.Text -like 'Write-Dat *Phiên bản hiện tại*' }
if (-not $start) { throw 'Không tìm thấy phần bảo trì của CapNhat.ps1.' }
$body = $statements | Select-Object -Skip ($statements.IndexOf($start) + 1) | ForEach-Object { $_.Extent.Text }
$body = $body -replace '(?m)^        Import-Module .*$', ''
$maintenance = [scriptblock]::Create((@('try {') + @($body) + @('}', $main.CatchClauses[0].Extent.Text, ('finally ' + $main.Finally.Extent.Text))) -join [Environment]::NewLine)

function Join-Path {
    param($Path, $ChildPath)
    # CommonDesktopDirectory có thể rỗng khi chạy ngoài Windows.
    if (-not $Path) { $Path = $root }
    Microsoft.PowerShell.Management\Join-Path -Path $Path -ChildPath $ChildPath
}
function Stop-MinhDucService {
    param($Window)
    if ($Window.ScriptName -ne 'CapNhat.ps1') { throw 'Sai tên script trong dấu phục hồi chế độ khởi động.' }
    Suspend-MinhDucMaintenanceWindow -Window $Window
    $scenario.Service = 'Stopped'
    $scenario.Calls.Add('stop')
    if ($case -eq 'StopError') { throw 'Lỗi chờ Python thoát sau khi dịch vụ đã dừng.' }
}
function Start-MinhDucMaintenanceService {
    param($Window)
    if (-not $scenario.Firewall -or $scenario.Startup -ne 'Disabled' -or $scenario.Tasks -contains 'Enabled') {
        throw 'Bật web trước khi chặn máy trạm hoặc ngoài cửa sổ bảo trì.'
    }
    $scenario.Service = 'Running'
    $scenario.Calls.Add('start')
}
function Stop-Service { param($Name, [switch]$Force, $ErrorAction) $scenario.Service = 'Stopped' }
function Show-ServiceDiagnostics { param($Paths) }
function Set-MinhDucRollbackPending { param($Window) $scenario.Marker = 'quay_ve_that_bai' }
function Hold-MinhDucFailedMaintenanceWindow {
    param($Window)
    $scenario.Service = 'Stopped'
    Suspend-MinhDucMaintenanceWindow -Window $Window
    Set-MinhDucRollbackPending -Window $Window
}
function Get-Service {
    param($Name, $ErrorAction)
    $service = [pscustomobject]@{ Status = $scenario.Service }
    $service | Add-Member ScriptMethod WaitForStatus { param($status, $timeout) }
    $service | Add-Member ScriptMethod Refresh { $this.Status = $scenario.Service }
    return $service
}
function Read-EnvFile { param($Path) return @{ CLINIC_ORIGIN = 'https://127.0.0.1:8443' } }
function Wait-Https {
    param($Origin, $Seconds, [switch]$LocalOnly)
    $scenario.Calls.Add('https')
    if (-not $LocalOnly -or -not $scenario.Firewall -or $committed) { throw 'Thử HTTPS trước khi chốt phải qua đường nội bộ và có quy tắc chặn máy trạm.' }
    if ($case -eq 'HttpsError' -and -not $scenario.Calls.Contains('restore')) {
        $scenario.NewHttpsFailed = $true
        return $false
    }
    $scenario.HttpsPassed = $true
    return ($scenario.Service -eq 'Running')
}
function Suspend-MinhDucMaintenanceWindow {
    param($Window, [switch]$AllowAlreadyDisabled)
    $scenario.Startup = 'Disabled'
    $scenario.Tasks = @('Disabled', 'Disabled')
    $scenario.Firewall = $true
    $Window.FirewallReady = $true
    if (-not $scenario.Marker) {
        $scenario.Marker = 'dang_bao_tri'
        $scenario.Phase = 'chua_doi_du_lieu'
    }
}
function Set-MinhDucUpdatePhase {
    param($Window, $Phase)
    if ($Phase -eq 'da_doi_du_lieu') {
        if ($scenario.Phase -ne 'chua_doi_du_lieu' -or $scenario.Startup -ne 'Disabled' -or
            -not (Test-Path -LiteralPath $P.Venv) -or (Test-Path -LiteralPath $OldVenv)) { throw 'Đánh dấu thay dữ liệu quá muộn.' }
    } elseif ($Phase -ne 'da_chot' -or $scenario.Phase -ne 'da_doi_du_lieu' -or
        -not $scenario.HttpsPassed -or -not $scenario.Firewall -or $committed) { throw 'Đánh dấu chốt ngoài cửa sổ HTTPS.' }
    $scenario.Phase = $Phase
}
function Resume-MinhDucMaintenanceWindow {
    param($Window, [switch]$VerifiedRollback, $BackupTaskSnapshot)
    if (-not $scenario.HttpsPassed -or (-not $committed -and -not $VerifiedRollback -and $case -notin @('BackupError', 'MissingVerification', 'FingerprintError'))) {
        throw 'Gỡ tường lửa trước khi đã chốt bản mới hoặc xác nhận bản cũ.'
    }
    if ($committed -and $scenario.Phase -ne 'da_chot') { throw 'Mở bảo trì khi chưa ghi mốc chốt.' }
    $scenario.Tasks = @('Enabled', 'Enabled')
    if ($case -eq 'FirewallResumeError') { throw 'Gỡ và kiểm lại tường lửa bảo trì chưa đạt: lỗi giả lập' }
    $scenario.Firewall = $false
    $scenario.Startup = 'Auto'
    $scenario.Marker = ''
}
function Exit-MinhDucMaintenanceWindow {
    param($Window, [switch]$KeepPending)
    if (-not $KeepPending) { throw 'finally có thể mở lại một cửa sổ bảo trì bị khóa.' }
}
function Set-MinhDucBackupTasks {
    param($Paths, [switch]$Disabled)
    if (-not $Disabled -or $scenario.Tasks -contains 'Enabled') { throw 'Đăng ký lịch mới trước khi mở lại web phải ở Disabled.' }
}
function Set-MinhDucStartupRecoveryTask { param($Paths) }
function Unregister-ScheduledTask { param($TaskName, $TaskPath, $Confirm, $ErrorAction) }
function Invoke-HealthReport {
    param($Paths, $Output, $Title)
    $result = Get-Content -LiteralPath $ResultFile -Raw | ConvertFrom-Json
    if (-not $committed -or $scenario.Firewall) { throw 'Báo cáo chạy trước khi chốt hoặc trước khi mở lại máy trạm.' }
    if ($result.status -ne 'dang_cap_nhat') { throw 'Đã ghi kết quả cuối trước khi kiểm sức khỏe.' }
    if (-not (Test-Path -LiteralPath $OldVenv)) { throw 'Dọn venv cũ trước khi lập báo cáo.' }
    $scenario.HealthChecked = $true
    # Mô phỏng dữ liệu máy trạm vừa nhập sau khi HTTPS bản mới trả lời.
    $scenario.Row = 'máy trạm vừa ghi'
    if ($case -eq 'HealthError') { throw 'Lỗi báo cáo sức khỏe giả lập' }
    return ($case -ne 'HealthNotPassed')
}
function Set-Content {
    [CmdletBinding()]
    param($LiteralPath, [Parameter(ValueFromPipeline=$true)]$Value, $Encoding = 'UTF8')
    process {
        # ConvertTo-Json khác khoảng trắng giữa 5.1 và 7.
        $status = if ($LiteralPath -like '*/ket-qua-cap-nhat.json.*.tmp' -or $LiteralPath -like '*\ket-qua-cap-nhat.json.*.tmp') {
            ($Value | ConvertFrom-Json).status
        }
        if ($status -eq 'dang_cap_nhat' -and $case -eq 'WriteBeforeStart') {
            if (-not (Test-Path -LiteralPath $OldVenv) -or $scenario.Startup -ne 'Disabled') { throw 'Thiếu venv cũ hoặc web đã mở tại điểm ghi kết quả trước khởi động.' }
            $scenario.WriteFault = $true
            $PSCmdlet.WriteError([Management.Automation.ErrorRecord]::new(
                [IO.IOException]::new('Lỗi ghi kết quả trước khi bật web'),
                'PreStartWrite', [Management.Automation.ErrorCategory]::WriteError, $LiteralPath))
            return
        }
        if ($status -eq 'thanh_cong' -and ($case -eq 'WriteAfterHttpsTwice' -or ($case -eq 'WriteAfterHttps' -and -not $scenario.WriteFault))) {
            $scenario.WriteFault = $true
            throw 'Lỗi ghi kết quả sau khi HTTPS đạt'
        }
        Microsoft.PowerShell.Management\Set-Content -LiteralPath $LiteralPath -Value $Value -Encoding $Encoding
    }
}
function Wait-MinhDucVenvPythonExit { param($Venv, $ClinicEnv, [switch]$LogLockDiagnostics) }
function Set-SecureAcl { param($Path, [switch]$Directory, $Writers) }
function Suspend-MinhDucBackupTasks { }
function Restore-MinhDucBackupTasks { param($Snapshot, [switch]$Disabled) }
function Assert-MinhDucBackupTaskSnapshot { param($Snapshot, [switch]$RequireBoth) }
function Copy-D0PublicCatalogs { param($SourceRoot, $DestinationRoot) }
function Copy-S2dPublicTemplate { param($SourceRoot, $DestinationRoot) }
function Restore-MinhDucOldVenv {
    param($Venv, $OldVenv, [switch]$LogLockDiagnostics)
    if (Test-Path -LiteralPath $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force }
    Rename-Item -LiteralPath $OldVenv -NewName '.venv'
}
function Invoke-Native {
    param($FilePath, $Arguments, [switch]$Quiet, $OkCodes)
    if ($Arguments[0] -eq $P.Code) {
        $scenario.Calls.Add('save-code')
        New-Item -ItemType Directory -Path (Join-Path $OldCode 'app') | Out-Null
        Copy-Item -LiteralPath (Join-Path $P.Code 'app/main.py') -Destination (Join-Path $OldCode 'app/main.py')
    } elseif ($Arguments[0] -eq $newRoot) {
        if ($scenario.Phase -ne 'da_doi_du_lieu') { throw 'Thay mã trước khi ghi giai đoạn.' }
        $scenario.Calls.Add('replace-code')
        Copy-Item -LiteralPath (Join-Path $newRoot 'app/main.py') -Destination (Join-Path $P.Code 'app/main.py')
        if ($case -eq 'BeforeMigration') { return @{ Ok = $false; Code = 16 } }
    } elseif ($Arguments[0] -eq $OldCode) {
        Copy-Item -LiteralPath (Join-Path $OldCode 'app/main.py') -Destination (Join-Path $P.Code 'app/main.py')
    } elseif ($FilePath -eq $P.BasePython) {
        New-Item -ItemType Directory -Path (Join-Path $P.Venv 'Scripts') | Out-Null
        Set-Content -LiteralPath $P.VenvPython -Value 'Python mới' -Encoding UTF8
    } else {
        throw "Lệnh ngoài chưa giả lập: $FilePath"
    }
    return @{ Ok = $true }
}
function Invoke-Python {
    param($Paths, $Arguments, [switch]$Quiet, $OkCodes, $WorkingDirectory)
    $code = 0
    $output = @()
    if ($Arguments -contains 'scripts.backup_job') {
        $scenario.Calls.Add('backup')
        if ($scenario.Service -ne 'Stopped' -or -not $State.stopped) { throw 'Web còn chạy khi sao lưu.' }
        if ($scenario.Startup -ne 'Disabled' -or ($scenario.Tasks -join ',') -ne 'Disabled,Disabled' -or
            $Arguments -notcontains '--no-prune' -or $WorkingDirectory -ne $newRoot) { throw 'Sao lưu bên ngoài cửa sổ bảo trì hoặc có thể dọn bản cũ.' }
        $scenario.BackupGuarded = $true
        if ($case -eq 'BackupError') { $code = 1 }
        else {
            $snapshot = [pscustomobject]@{ Row = $scenario.Row; Attachment = $scenario.Attachment }
            $snapshot | ConvertTo-Json | Set-Content -LiteralPath $backupPath -Encoding UTF8
            if ($case -ne 'MissingVerification') { New-Item -ItemType File -Path ($backupPath + '.verified') | Out-Null }
            $output = @("Sao luu va kiem tra ban sao luu: DAT $backupName")
            $code = 3
        }
    } elseif ($Arguments -contains 'fingerprint') {
        $scenario.Calls.Add('fingerprint')
        if ($case -eq 'FingerprintError') { $code = 1 }
        else { $output = @('{"sha256":"' + $scenario.Fingerprint + '"}') }
    } elseif ($Arguments -contains 'migrate') {
        if ($scenario.Phase -ne 'da_doi_du_lieu') { throw 'Migration trước khi ghi giai đoạn.' }
        $scenario.Calls.Add('migrate')
        $scenario.Row = 'đã sửa'
        $scenario.Attachment = 'đã sửa'
        if ($case -notin @('WriteBeforeStart', 'HealthError', 'HealthNotPassed', 'WriteAfterHttps', 'WriteAfterHttpsTwice', 'HttpsError', 'FirewallResumeError')) { $code = 1 }
    } elseif ($Arguments -contains 'grant') {
        $output = @('{"managed_changed":[]}')
    } elseif ($Arguments -contains 'rollback') {
        $scenario.Calls.Add('restore')
        $file = $Arguments[[array]::IndexOf($Arguments, '--file') + 1]
        if ($file -ne $backupPath) { throw 'Không dùng đúng bản sao lưu vừa tạo.' }
        $saved = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
        $scenario.Row = $saved.Row
        $scenario.Attachment = $saved.Attachment
        if ($case -eq 'BadRestoredFingerprint') { $scenario.Fingerprint = 'khác baseline' }
    }
    return @{ Ok = ($code -eq 0 -or $code -in $OkCodes); Code = $code; Output = $output }
}

$root = Microsoft.PowerShell.Management\Join-Path ([IO.Path]::GetTempPath()) ('minhduc-update-' + [guid]::NewGuid().ToString('N'))
try {
    foreach ($case in @('StopError', 'BackupError', 'MissingVerification', 'FingerprintError', 'BeforeMigration', 'DataOnlyMigration', 'BadRestoredFingerprint', 'WriteBeforeStart', 'HealthError', 'HealthNotPassed', 'WriteAfterHttps', 'WriteAfterHttpsTwice', 'HttpsError', 'FirewallResumeError')) {
        $homeForCase = Join-Path $root $case
        $scenario = @{ Service = 'Running'; Startup = 'Auto'; Tasks = @('Enabled', 'Enabled'); Row = 'ban đầu'; Attachment = 'ban đầu'; Fingerprint = 'baseline'; Calls = [Collections.Generic.List[string]]::new() }
        $enabledBefore = $scenario.Tasks -join ','
        $P = @{
            Code = (Join-Path $homeForCase 'live'); Venv = (Join-Path $homeForCase 'live/.venv')
            VenvPython = (Join-Path $homeForCase 'live/.venv/Scripts/python.exe'); BasePython = 'base-python'
            ClinicEnv = 'clinic.env'; OwnerEnv = 'owner.env'; SuperEnv = 'super.env'; BackupKey = 'backup.key'
            Backups = (Join-Path $homeForCase 'backups'); BackupState = (Join-Path $homeForCase 'backup-status.json')
            Updates = (Join-Path $homeForCase 'updates'); Attachments = (Join-Path $homeForCase 'attachments')
            Settings = (Join-Path $homeForCase 'settings'); ExternalCfg = 'external.json'
        }
        $Names = @{ Service = 'FakeMinhDuc'; AlertFile = 'alert.txt'; ServiceAcct = 'fake' }
        $State = @{ rollback_errors = @(); stopped = $false; code_replaced = $false; venv_moved = $false; migrated = $false; backup_tasks_changed = $false; backup_task_snapshot = @('fake'); backup = $null; fingerprint = $null }
        $window = @{ ScriptName = 'CapNhat.ps1' }
        $transcript = $false
        $committed = $false
        $Stamp = 'ci'
        $P.Journal = $homeForCase
        $State.warnings = @()
        $OldCode = Join-Path $homeForCase 'old'
        $newRoot = Join-Path $homeForCase 'new'
        $NewDir = $newRoot
        $OldVenv = Join-Path $P.Code '.venv-cu'
        $ResultFile = Join-Path $P.Updates 'ket-qua-cap-nhat.json'
        $backupName = 'minhduc-20261119T010000Z-1234abcd.mdbackup'
        $backupPath = Join-Path $P.Backups $backupName
        New-Item -ItemType Directory -Path (Join-Path $P.Code 'app'), (Join-Path $P.Venv 'Scripts'), (Join-Path $newRoot 'app'), $P.Backups | Out-Null
        Set-Content -LiteralPath (Join-Path $P.Code 'app/main.py') -Value 'mã cũ' -Encoding UTF8
        Set-Content -LiteralPath (Join-Path $newRoot 'app/main.py') -Value 'mã mới' -Encoding UTF8
        Set-Content -LiteralPath $P.VenvPython -Value 'Python giả lập' -Encoding UTF8
        Set-Content -LiteralPath $P.BackupState -Value '{"last_file":"ban-sao-luu-cua-lich.mdbackup"}'
        $exitCode = 0
        . $maintenance
        $result = Get-Content -LiteralPath $ResultFile -Raw | ConvertFrom-Json
        if ($case -eq 'FirewallResumeError') {
            if ($exitCode -ne 8 -or $result.status -ne 'thanh_cong_can_kiem_tra' -or $result.detail -notmatch 'tường lửa' -or
                $scenario.Calls.Contains('restore') -or $scenario.Row -ne 'đã sửa' -or
                -not $committed -or $scenario.Phase -ne 'da_chot' -or $scenario.Startup -ne 'Disabled' -or -not $scenario.Firewall -or
                $scenario.Service -ne 'Running' -or (Get-Content -LiteralPath (Join-Path $P.Code 'app/main.py')) -ne 'mã mới') {
                throw 'Lỗi tường lửa sau chốt phải trả mã 8 và giữ bản mới cùng dấu bảo trì.'
            }
            Write-Output "PASS: $case"
            continue
        }
        if ($case -eq 'BadRestoredFingerprint') {
            if ($scenario.Startup -ne 'Disabled' -or $scenario.Tasks -contains 'Enabled' -or $scenario.Service -ne 'Stopped' -or
                -not $scenario.Firewall -or $scenario.Marker -ne 'quay_ve_that_bai') { throw 'Quay về lỗi phải giữ mọi khóa bảo trì.' }
        } else {
            if ($scenario.Startup -ne 'Auto' -or $scenario.Tasks -contains 'Disabled') {
                throw "Cấu hình bảo trì chưa được trả sau ca $case."
            }
            if ($scenario.Firewall -or $scenario.Marker) { throw 'Còn quy tắc hoặc dấu bảo trì sau khi đã xác nhận HTTPS.' }
            if (($scenario.Tasks -join ',') -ne $enabledBefore) { throw "Sai trạng thái từng lịch trước và sau ca $case." }
        }
        if ($case -ne 'StopError' -and -not $scenario.BackupGuarded) { throw 'Chưa kiểm được trạng thái dịch vụ và lịch tại bước sao lưu.' }
        if ($case -eq 'WriteAfterHttpsTwice') {
            if ($exitCode -ne 7 -or $result.status -ne 'dang_cap_nhat' -or -not $scenario.WriteFault -or -not $committed -or
                $scenario.Calls.Contains('restore') -or $scenario.Row -ne 'máy trạm vừa ghi' -or -not (Test-Path -LiteralPath $OldVenv)) {
                throw 'Hai lần ghi kết quả sau khi chốt phải trả mã 7 và giữ dữ liệu mới cùng venv cũ.'
            }
            Write-Output "PASS: $case"
            continue
        }
        if ($case -in @('HealthError', 'HealthNotPassed', 'WriteAfterHttps')) {
            $expectedExit = if ($case -eq 'WriteAfterHttps') { 0 } else { 8 }
            $expectedStatus = if ($case -eq 'WriteAfterHttps') { 'thanh_cong' } else { 'thanh_cong_can_kiem_tra' }
            if ($exitCode -ne $expectedExit -or $result.status -ne $expectedStatus -or -not $scenario.HealthChecked -or
                $scenario.Calls.Contains('restore') -or $scenario.Row -ne 'máy trạm vừa ghi' -or
                $scenario.Service -ne 'Running' -or (Get-Content -LiteralPath (Join-Path $P.Code 'app/main.py')) -ne 'mã mới') {
                throw "Không giữ được bản mới/dữ liệu máy trạm sau lỗi hậu kiểm $case."
            }
            if ($case -eq 'HealthError' -and ($result.warnings -notmatch 'Lỗi báo cáo sức khỏe giả lập')) { throw 'Thiếu cảnh báo lỗi lập báo cáo.' }
            if ($case -eq 'HealthNotPassed' -and ($result.detail -notmatch 'sức khỏe chưa đạt' -or
                -not (Test-Path -LiteralPath $OldVenv))) { throw 'Thiếu kết quả chưa đạt hoặc đã dọn venv cũ.' }
            if ($case -eq 'WriteAfterHttps' -and (-not $scenario.WriteFault -or -not (Test-Path -LiteralPath $OldVenv))) {
                throw 'Đã dọn venv cũ dù lần ghi thành công đầu tiên gặp lỗi.'
            }
            Write-Output "PASS: $case"
            continue
        }
        if ($case -eq 'WriteBeforeStart' -and (-not $scenario.WriteFault -or (Get-Content -LiteralPath $P.VenvPython) -ne 'Python giả lập')) {
            throw 'Lỗi ghi kết quả trước khi bật web chưa quay về được với venv cũ.'
        }
        if ($case -eq 'HttpsError' -and (-not $scenario.NewHttpsFailed -or $committed)) { throw 'Kiểm HTTPS lỗi vẫn chốt bản mới.' }
        $calls = $scenario.Calls -join ','
        $expected = switch ($case) {
            'StopError'              { @(50, 'da_quay_ve', 'stop,start,https') }
            'BackupError'            { @(6, 'dung_truoc_khi_thay_doi', 'stop,backup,start,https') }
            'MissingVerification'   { @(6, 'dung_truoc_khi_thay_doi', 'stop,backup,start,https') }
            'FingerprintError'      { @(6, 'dung_truoc_khi_thay_doi', 'stop,backup,fingerprint,start,https') }
            'BeforeMigration'       { @(50, 'da_quay_ve', 'stop,backup,fingerprint,save-code,replace-code,start,https') }
            'DataOnlyMigration'     { @(50, 'da_quay_ve', 'stop,backup,fingerprint,save-code,replace-code,migrate,restore,fingerprint,start,https') }
            'HttpsError'             { @(50, 'da_quay_ve', 'stop,backup,fingerprint,save-code,replace-code,migrate,start,https,restore,fingerprint,start,https') }
            'WriteBeforeStart'       { @(50, 'da_quay_ve', 'stop,backup,fingerprint,save-code,replace-code,migrate,restore,fingerprint,start,https') }
            'BadRestoredFingerprint' { @(50, 'quay_ve_that_bai', 'stop,backup,fingerprint,save-code,replace-code,migrate,restore,fingerprint') }
        }
        if ($exitCode -ne $expected[0] -or $result.status -ne $expected[1] -or $calls -ne $expected[2]) {
            throw "$($case): mã $exitCode, trạng thái $($result.status), thứ tự $calls"
        }
        if ($exitCode -eq 6 -and $result.detail -notlike '*chưa thay đổi gì*') { throw 'Thiếu thông báo trước khi thay mã.' }
        if ($scenario.Row -ne 'ban đầu' -or $scenario.Attachment -ne 'ban đầu') { throw 'Dữ liệu hoặc tệp đính kèm chưa quay về.' }
        if ($case -eq 'BadRestoredFingerprint' -and ($result.rollback_errors -join ' ') -notlike '*Dấu vân tay CSDL chưa khớp*') {
            throw 'Không ghi nhận lỗi dấu vân tay sau khôi phục.'
        }
        if ((Get-Content -LiteralPath (Join-Path $P.Code 'app/main.py')) -ne 'mã cũ') { throw 'Mã cũ chưa quay về.' }
        Write-Output "PASS: $case"
    }
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force
}
