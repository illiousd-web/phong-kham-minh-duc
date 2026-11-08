param(
    [string]$Root = 'C:\MinhDuc',
    [string]$Config = 'C:\ProgramData\MinhDuc\clinic.env',
    [ValidateSet('server','backup')][string]$Action = 'server'
)
$ErrorActionPreference = 'Stop'
# Load literal KEY=VALUE entries, never evaluate file content as PowerShell.
Get-Content -LiteralPath $Config | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        if ($line -notmatch '^([A-Z][A-Z0-9_]*)=(.*)$') { throw 'Invalid config line' }
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
Set-Location -LiteralPath $Root
$python = Join-Path $Root '.venv\Scripts\python.exe'
if ($Action -eq 'server') { & $python -m scripts.run_lan }
else { & $python -m scripts.backup_lan backup --key 'C:\ProgramData\MinhDuc\backup.key' --directory 'C:\ProgramData\MinhDuc\backups' }
exit $LASTEXITCODE
