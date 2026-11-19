# Chạy phần bảo trì thật của CapNhat.ps1 bằng dịch vụ và lệnh Python giả lập.
$ErrorActionPreference = 'Stop'
$windowsDir = Join-Path $PSScriptRoot '../deploy/windows'
Import-Module (Join-Path $windowsDir 'MinhDuc.Install.psm1') -Force -DisableNameChecking
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $windowsDir 'CapNhat.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Get-Fingerprint', 'Write-Result', 'Invoke-QuayVe')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $false)
    Invoke-Expression $definition.Extent.Text
}
$main = $ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.TryStatementAst] } | Select-Object -Last 1
# Bỏ phần kiểm quyền quản trị và mở ZIP. Giữ các bước bảo trì và nhánh catch chính.
$statements = $main.Body.Statements
$start = $statements | Where-Object { $_.Extent.Text -like 'Write-Dat *Phiên bản hiện tại*' }
if (-not $start) { throw 'Không tìm thấy phần bảo trì của CapNhat.ps1.' }
$body = $statements | Select-Object -Skip ($statements.IndexOf($start) + 1) | ForEach-Object { $_.Extent.Text }
$maintenance = [scriptblock]::Create((@('try {') + @($body) + @('}', $main.CatchClauses[0].Extent.Text)) -join [Environment]::NewLine)

function Join-Path {
    param($Path, $ChildPath)
    # CommonDesktopDirectory có thể rỗng khi chạy ngoài Windows.
    if (-not $Path) { $Path = $root }
    Microsoft.PowerShell.Management\Join-Path -Path $Path -ChildPath $ChildPath
}
function Stop-MinhDucService {
    param($Name, $Paths, $ScriptName)
    if ($ScriptName -ne 'CapNhat.ps1') { throw 'Sai tên script trong dấu phục hồi chế độ khởi động.' }
    $scenario.Service = 'Stopped'
    $scenario.Calls.Add('stop')
    if ($case -eq 'StopError') { throw 'Lỗi chờ Python thoát sau khi dịch vụ đã dừng.' }
}
function Start-Service {
    param($Name, $ErrorAction)
    $scenario.Service = 'Running'
    $scenario.Calls.Add('start')
}
function Get-Service {
    param($Name, $ErrorAction)
    $service = [pscustomobject]@{ Status = $scenario.Service }
    $service | Add-Member ScriptMethod WaitForStatus { param($status, $timeout) }
    $service | Add-Member ScriptMethod Refresh { }
    return $service
}
function Read-EnvFile { param($Path) return @{ CLINIC_ORIGIN = 'https://127.0.0.1:8443' } }
function Wait-Https {
    param($Origin, $Seconds)
    $scenario.Calls.Add('https')
    return ($scenario.Service -eq 'Running')
}
function Invoke-WithMinhDucServiceStartupDisabled {
    param($Name, $Paths, $ScriptName, $Action, [switch]$AllowAlreadyDisabled)
    & $Action
}
function Wait-MinhDucVenvPythonExit { param($Venv, $ClinicEnv, [switch]$LogLockDiagnostics) }
function Set-SecureAcl { param($Path, [switch]$Directory, $Writers) }
function Suspend-MinhDucBackupTasks { }
function Restore-MinhDucBackupTasks { param($Snapshot) }
function Assert-MinhDucBackupTaskSnapshot { param($Snapshot, [switch]$RequireBoth) }
function Copy-D0PublicCatalogs { param($SourceRoot, $DestinationRoot) }
function Copy-S2dPublicTemplate { param($SourceRoot, $DestinationRoot) }
function Restore-MinhDucOldVenv {
    param($Venv, $OldVenv, [switch]$LogLockDiagnostics)
    Rename-Item -LiteralPath $OldVenv -NewName '.venv'
}
function Invoke-Native {
    param($FilePath, $Arguments, [switch]$Quiet, $OkCodes)
    if ($Arguments[0] -eq $P.Code) {
        $scenario.Calls.Add('save-code')
        New-Item -ItemType Directory -Path (Join-Path $OldCode 'app') | Out-Null
        Copy-Item -LiteralPath (Join-Path $P.Code 'app/main.py') -Destination (Join-Path $OldCode 'app/main.py')
    } elseif ($Arguments[0] -eq $newRoot) {
        $scenario.Calls.Add('replace-code')
        Copy-Item -LiteralPath (Join-Path $newRoot 'app/main.py') -Destination (Join-Path $P.Code 'app/main.py')
        if ($case -eq 'BeforeMigration') { return @{ Ok = $false; Code = 16 } }
    } elseif ($Arguments[0] -eq $OldCode) {
        Copy-Item -LiteralPath (Join-Path $OldCode 'app/main.py') -Destination (Join-Path $P.Code 'app/main.py')
    } elseif ($FilePath -ne $P.BasePython) {
        throw "Lệnh ngoài chưa giả lập: $FilePath"
    }
    return @{ Ok = $true }
}
function Invoke-Python {
    param($Paths, $Arguments, [switch]$Quiet, $OkCodes)
    $code = 0
    $output = @()
    if ($Arguments -contains 'scripts.backup_job') {
        $scenario.Calls.Add('backup')
        if ($scenario.Service -ne 'Stopped' -or -not $State.stopped) { throw 'Web còn chạy khi sao lưu.' }
        if ($case -eq 'BackupError') { $code = 1 }
        else {
            $scenario | Select-Object -Property Row, Attachment | ConvertTo-Json | Set-Content -LiteralPath $backupPath -Encoding UTF8
            if ($case -ne 'MissingVerification') { New-Item -ItemType File -Path ($backupPath + '.verified') | Out-Null }
            $output = @("Sao luu va kiem tra ban sao luu: DAT $backupName")
            $code = 3
        }
    } elseif ($Arguments -contains 'fingerprint') {
        $scenario.Calls.Add('fingerprint')
        if ($case -eq 'FingerprintError') { $code = 1 }
        else { $output = @('{"sha256":"' + $scenario.Fingerprint + '"}') }
    } elseif ($Arguments -contains 'migrate') {
        $scenario.Calls.Add('migrate')
        $scenario.Row = 'đã sửa'
        $scenario.Attachment = 'đã sửa'
        $code = 1
    } elseif ($Arguments -contains 'rollback') {
        $scenario.Calls.Add('restore')
        $file = $Arguments[[array]::IndexOf($Arguments, '--file') + 1]
        if ($file -ne $backupPath) { throw 'Không dùng đúng bản sao lưu vừa tạo.' }
        $saved = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        $scenario.Row = $saved.Row
        $scenario.Attachment = $saved.Attachment
        if ($case -eq 'BadRestoredFingerprint') { $scenario.Fingerprint = 'khác baseline' }
    }
    return @{ Ok = ($code -eq 0 -or $code -in $OkCodes); Code = $code; Output = $output }
}

$root = Microsoft.PowerShell.Management\Join-Path ([IO.Path]::GetTempPath()) ('minhduc-update-' + [guid]::NewGuid().ToString('N'))
try {
    foreach ($case in @('StopError', 'BackupError', 'MissingVerification', 'FingerprintError', 'BeforeMigration', 'DataOnlyMigration', 'BadRestoredFingerprint')) {
        $homeForCase = Join-Path $root $case
        $scenario = @{ Service = 'Running'; Row = 'ban đầu'; Attachment = 'ban đầu'; Fingerprint = 'baseline'; Calls = [Collections.Generic.List[string]]::new() }
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
        $OldCode = Join-Path $homeForCase 'old'
        $newRoot = Join-Path $homeForCase 'new'
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
        $calls = $scenario.Calls -join ','
        $expected = switch ($case) {
            'StopError'              { @(50, 'da_quay_ve', 'stop,start,https') }
            'BackupError'            { @(6, 'dung_truoc_khi_thay_doi', 'stop,backup,start,https') }
            'MissingVerification'   { @(6, 'dung_truoc_khi_thay_doi', 'stop,backup,start,https') }
            'FingerprintError'      { @(6, 'dung_truoc_khi_thay_doi', 'stop,backup,fingerprint,start,https') }
            'BeforeMigration'       { @(50, 'da_quay_ve', 'stop,backup,fingerprint,save-code,replace-code,start,https') }
            'DataOnlyMigration'     { @(50, 'da_quay_ve', 'stop,backup,fingerprint,save-code,replace-code,migrate,restore,fingerprint,start,https') }
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
