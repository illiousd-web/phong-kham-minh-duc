# Kiểm thử giao dịch phục hồi bằng thư mục và lỗi khóa giả lập.
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'MinhDuc.Install.psm1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Module syntax error' }
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Restore-MinhDucOldVenv'},$true)
Invoke-Expression $definition.Extent.Text
function Write-Luu {param($Message) $script:logs.Add($Message)}
function Start-Sleep {param($Seconds) $script:waits.Add($Seconds)}
function Rename-Item {
    param($LiteralPath,$NewName,$ErrorAction)
    if ((Split-Path $LiteralPath -Leaf) -eq '.venv') {
        $script:copies++
        if ($script:permanent -or $script:copies -le 2) { throw [IO.IOException]::new('Tệp giả lập _rust.pyd bị khóa') }
    }
    Microsoft.PowerShell.Management\Rename-Item -LiteralPath $LiteralPath -NewName $NewName -ErrorAction Stop
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('venv-retry-'+[guid]::NewGuid().ToString('N'))
try {
    foreach ($script:permanent in @($false,$true)) {
        $case=Join-Path $root ([string]$script:permanent)
        $venv=Join-Path $case '.venv'; $old=Join-Path $case '.venv-cu'
        New-Item -ItemType Directory -Force -Path $venv,$old | Out-Null
        Set-Content -LiteralPath (Join-Path $venv 'current.txt') -Value 'current'
        Set-Content -LiteralPath (Join-Path $old 'old.txt') -Value 'old'
        $script:copies=0; $script:waits=New-Object 'System.Collections.Generic.List[int]'; $script:logs=New-Object 'System.Collections.Generic.List[string]'
        $errorText=''
        try { Restore-MinhDucOldVenv -Venv $venv -OldVenv $old } catch { $errorText=$_.Exception.Message }
        if ($script:permanent) {
            if ($script:copies -ne 10 -or $errorText -notmatch '_rust.pyd') { throw 'Khóa vĩnh viễn không được báo chính xác sau 10 lần.' }
            if (-not (Test-Path (Join-Path $venv 'current.txt')) -or -not (Test-Path (Join-Path $old 'old.txt'))) { throw 'Môi trường ban đầu bị hỏng.' }
        } else {
            if ($errorText -or $script:copies -ne 3 -or -not (Test-Path (Join-Path $venv 'old.txt'))) { throw ('Phục hồi sau hai lần khóa thất bại: '+$errorText) }
        }
        if ($script:logs.Count -ne $script:copies) { throw 'Thiếu nhật ký lần thử.' }
        if (($script:waits | Measure-Object -Sum).Sum -gt 60) { throw 'Chờ quá 60 giây.' }
    }
    # Lỗi khi đã xóa một phần thư mục tạm phải phục hồi từ bản nguyên vẹn rồi thử lại.
    $case=Join-Path $root 'partial'; $venv=Join-Path $case '.venv'; $old=Join-Path $case '.venv-cu'
    New-Item -ItemType Directory -Force -Path $venv,$old | Out-Null
    Set-Content -LiteralPath (Join-Path $venv 'current.txt') -Value 'current'
    Set-Content -LiteralPath (Join-Path $old 'old.txt') -Value 'old'
    $script:copies=100; $script:permanent=$false; $script:removedOnce=$false; $script:permanentDelete=$false
    $script:waits=New-Object 'System.Collections.Generic.List[int]'; $script:logs=New-Object 'System.Collections.Generic.List[string]'
    function Remove-Item {
        param($LiteralPath,[switch]$Recurse,[switch]$Force,$ErrorAction)
        if ((Split-Path $LiteralPath -Leaf) -like '.venv-quay-ve-*' -and (-not $script:removedOnce -or $script:permanentDelete)) {
            $script:removedOnce=$true
            if (Test-Path (Join-Path $LiteralPath 'current.txt')) { Microsoft.PowerShell.Management\Remove-Item -LiteralPath (Join-Path $LiteralPath 'current.txt') -Force -ErrorAction Stop }
            throw [IO.IOException]::new('Tệp giả lập _rust.pyd bị khóa khi xóa')
        }
        Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse -Force -ErrorAction Stop
    }
    Restore-MinhDucOldVenv -Venv $venv -OldVenv $old
    if (-not $script:removedOnce -or -not (Test-Path (Join-Path $venv 'old.txt')) -or $script:waits.Count -ne 1) { throw 'Không phục hồi sau lỗi xóa dở.' }
    $case=Join-Path $root 'partial-permanent'; $venv=Join-Path $case '.venv'; $old=Join-Path $case '.venv-cu'
    New-Item -ItemType Directory -Force -Path $venv,$old | Out-Null
    Set-Content -LiteralPath (Join-Path $venv 'current.txt') -Value 'current'
    Set-Content -LiteralPath (Join-Path $old 'old.txt') -Value 'old'
    $script:removedOnce=$false; $script:permanentDelete=$true
    $script:waits=New-Object 'System.Collections.Generic.List[int]'; $script:logs=New-Object 'System.Collections.Generic.List[string]'
    $errorText=''
    try { Restore-MinhDucOldVenv -Venv $venv -OldVenv $old } catch { $errorText=$_.Exception.Message }
    if ($errorText -notmatch '_rust.pyd' -or $script:waits.Count -ne 9 -or -not (Test-Path (Join-Path $venv 'current.txt')) -or -not (Test-Path (Join-Path $old 'old.txt'))) { throw 'Khóa kéo dài sau xóa dở làm sai môi trường ban đầu.' }
    Write-Output 'PASS: hai lần khóa rồi phục hồi; khóa vĩnh viễn giữ môi trường ban đầu; thử lại sau xóa dở'
} finally { Microsoft.PowerShell.Management\Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue }
