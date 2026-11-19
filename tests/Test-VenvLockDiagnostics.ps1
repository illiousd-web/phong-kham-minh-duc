# Kiểm các nhánh lấy ảnh chụp tiến trình bằng dữ liệu giả lập.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$module = Join-Path $PSScriptRoot '../deploy/windows/MinhDuc.Install.psm1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($module, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Get-MinhDucPythonScriptLabel', 'Get-MinhDucProcessParents', 'Write-MinhDucVenvLockDiagnostics', 'Wait-MinhDucVenvPythonExit', 'Restore-MinhDucOldVenv')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    Invoke-Expression $definition.Extent.Text
}

$venv = 'C:\Minh Duc\.venv'
$python = "$venv\Scripts\python.exe"
$rust = "$venv-quay-ve-tag\Lib\site-packages\cryptography\hazmat\bindings\_rust.pyd"
$late = [pscustomobject]@{
    ProcessId = 606; ParentProcessId = 605; Name = 'python.exe'; ExecutablePath = 'C:\Python\python.exe'
    CommandLine = 'python.exe -m scripts.with_env C:\ProgramData\MinhDuc\clinic.env scripts.run_lan'; CreationDate = 1; CanStop = $true; TreeDepth = 1
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($ClassName -ne 'Win32_Process') { throw 'CIM phải truy vấn Win32_Process.' }
    if ($Filter) { return }
    [pscustomobject]@{ProcessId=601; ParentProcessId=500; CreationDate=3; Name='python.exe'; ExecutablePath=$python; CommandLine=('"'+$python+'" -m scripts.install_db fingerprint --token "secret token value" postgresql://user:secret@localhost/db')}
    [pscustomobject]@{ProcessId=500; ParentProcessId=100; CreationDate=2; Name='MinhDuc.exe'; ExecutablePath='C:\ProgramData\MinhDuc\service\MinhDuc.exe'; CommandLine='MinhDuc.exe --token parent-secret'}
    [pscustomobject]@{ProcessId=100; ParentProcessId=0; CreationDate=1; Name='services.exe'; ExecutablePath='C:\Windows\System32\services.exe'; CommandLine='services.exe'}
    [pscustomobject]@{ProcessId=602; ParentProcessId=100; CreationDate=2; Name='system-tool.exe'; ExecutablePath='C:\Tools\system-tool.exe'; CommandLine='system-tool.exe --scan'}
    [pscustomobject]@{ProcessId=603; ParentProcessId=100; CreationDate=2; Name='tool.exe'; ExecutablePath='C:\Tools\tool.exe'; CommandLine='tool.exe "C:/Minh Duc/.venv-quay-ve-tag/Lib"'}
    [pscustomobject]@{ProcessId=604; ParentProcessId=100; CreationDate=2; Name='tool.exe'; ExecutablePath='C:\Tools\tool.exe'; CommandLine='tool.exe "C:\Minh Duc\.venv-other\Lib"'}
}
function Get-Process {
    param($Id, $ErrorAction)
    if ($Id) { return }
    if ($script:removalFailed) {
        $script:scannedBeforeUndo = (Test-Path -LiteralPath $script:tempVenv) -and -not (Test-Path -LiteralPath $script:previousVenv)
    }
    $moduleEntry = [pscustomobject]@{ModuleName='_rust.pyd'; FileName=$rust}
    [pscustomobject]@{Id=602; Modules=@($moduleEntry); ProcessName='system-tool'; Path='C:\Tools\system-tool.exe'}
    [pscustomobject]@{Id=605; Modules=@($moduleEntry); ProcessName='module-only'; Path='C:\Tools\module-only.exe'}
    [pscustomobject]@{Id=604; Modules=$null; ProcessName='tool'; Path='C:\Tools\tool.exe'}
}
function Stop-Process { throw 'Chẩn đoán chỉ được đọc thông tin tiến trình.' }
function Start-Sleep { param($Seconds, $Milliseconds) }
function Write-Luu { param($Text) }
function Get-DiagnosticRecords($Lines) {
    $Lines | ForEach-Object {
        if ([string]$_ -match '^\[S2F2-VENV\] (\{.*\})$') { ConvertFrom-Json $Matches[1] }
    }
}

$script:removalFailed = $false
$env:GITHUB_ACTIONS = 'true'
$env:RUNNER_TEMP = [IO.Path]::GetTempPath()
$lines = @(Write-MinhDucVenvLockDiagnostics -Venv $venv -Context 'Lỗi giả lập' 6>&1)
$records = @(Get-DiagnosticRecords $lines)
if (($records.PID -join ',') -ne '601,602,603,605') { throw 'Bỏ sót tiến trình ứng viên hoặc ghi nhầm thư mục cùng cấp.' }
$venvPython, $systemTool, $pathOnly, $moduleOnly = $records
if ($venvPython.ExecutablePath -ne $python -or $venvPython.CommandLine -notmatch 'scripts.install_db fingerprint') { throw 'Thiếu đường dẫn hoặc lệnh chạy từ .venv.' }
if (($venvPython.Ancestors.PID -join ',') -ne '500,100' -or $venvPython.Ancestors[0].Name -ne 'MinhDuc.exe' -or ($lines -join ' ') -match 'parent-secret') { throw 'Thiếu chuỗi tổ tiên WinSW hoặc lộ đối số.' }
if (($lines -join ' ') -match 'secret token value|user:secret') { throw 'Lộ tham số bí mật trong nhật ký.' }
if ($systemTool.ParentPID -ne 100 -or $systemTool.Name -ne 'system-tool.exe' -or $systemTool.LoadedRust[0] -ne $rust -or $systemTool.MatchesVenvPath) { throw 'Không nhận diện đúng tiến trình ngoài phần mềm có nạp _rust.pyd.' }
if (-not $pathOnly.MatchesVenvPath -or $pathOnly.LoadedRust.Count) { throw 'Không nhận diện đúng đường dẫn .venv-quay-ve trong CommandLine.' }
if ($moduleOnly.LoadedRust[0] -ne $rust -or $moduleOnly.CommandLine -notmatch 'không đọc được') { throw 'Mất thông tin module của PID thiếu trong CIM.' }

$env:GITHUB_ACTIONS = 'false'
$records = @(Get-DiagnosticRecords @(Write-MinhDucVenvLockDiagnostics -Venv $venv -Context 'Máy phòng khám' 6>&1))
if ($records[0].CommandLine -ne 'module=scripts.install_db') { throw 'Nhật ký máy phòng khám lộ đối số của tiến trình.' }

$script:scans = 0
function Get-MinhDucVenvProcessTree {
    param($Venv, $Known)
    $script:scans++
    if ($script:scans -in @(2,4)) { $late }
}
$lateFailure = ''
$lateLines = @(& {
    try { Wait-MinhDucVenvPythonExit -Venv $venv -Seconds 0 -LogLockDiagnostics }
    catch { $script:lateFailure = $_.Exception.Message }
} 6>&1)
$lateRecord = @(Get-DiagnosticRecords $lateLines | Where-Object { $_.PID -eq $late.ProcessId })
if ($lateFailure -notmatch 'xuất hiện lại' -or $lateRecord.Count -ne 1 -or -not $lateRecord[0].ObservedInWait -or $lateRecord[0].ParentPID -ne 605) {
    throw 'Không giữ được thông tin tiến trình xuất hiện lại rồi biến mất trước lần truy vấn CIM kế tiếp.'
}

function Remove-Item {
    param($LiteralPath, [switch]$Recurse, [switch]$Force, $ErrorAction)
    if (-not $script:removalFailed -and (Split-Path $LiteralPath -Leaf) -like '.venv-quay-ve-*') {
        $script:removalFailed = $true
        $script:tempVenv = $LiteralPath
        throw [UnauthorizedAccessException]::new("Access to the path '_rust.pyd' is denied")
    }
    Microsoft.PowerShell.Management\Remove-Item @PSBoundParameters
}
$root = Join-Path ([IO.Path]::GetTempPath()) ('venv-lock-diagnostics-' + [guid]::NewGuid())
$current = Join-Path $root '.venv'
$script:previousVenv = Join-Path $root '.venv-cu'
$script:scannedBeforeUndo = $false
try {
    New-Item -ItemType Directory -Path $current, $script:previousVenv -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $script:previousVenv 'old.txt') -Value 'old'
    $lines = @(Restore-MinhDucOldVenv -Venv $current -OldVenv $script:previousVenv -LogLockDiagnostics 6>&1)
    if (-not $script:scannedBeforeUndo -or ($lines -join ' ') -notmatch "_rust\.pyd' is denied") { throw 'Không ghi nhận lỗi xóa trước khi trả thư mục.' }
    if (-not (Test-Path (Join-Path $current 'old.txt'))) { throw 'Chẩn đoán làm sai kết quả phục hồi.' }
} finally {
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Output 'PASS: nhật ký nhận diện tiến trình tại nhánh lỗi khóa môi trường Python.'
