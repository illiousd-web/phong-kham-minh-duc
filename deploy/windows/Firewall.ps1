param(
    [Parameter(Mandatory=$true)][string]$ServerIP,
    [Parameter(Mandatory=$true)][string]$ClinicCIDR,
    [int]$Port=8443,
    [string]$Python='C:\MinhDuc\.venv\Scripts\python.exe'
)
$ErrorActionPreference='Stop'
# Review and run elevated on the clinic server, never on client workstations.
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Use an unprivileged HTTPS port, e.g. 8443' }
New-NetFirewallRule -DisplayName 'MinhDuc LAN HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $ServerIP -LocalPort $Port -RemoteAddress $ClinicCIDR -Profile Private -Program $Python
New-NetFirewallRule -DisplayName 'MinhDuc block PostgreSQL LAN' -Direction Inbound -Action Block -Protocol TCP -LocalPort 5432 -Profile Any
Get-NetFirewallRule -DisplayName 'MinhDuc*'
Write-Output 'Review and remove existing broad inbound Python/8443 rules. Keep default inbound Block and use only the clinic Private network.'
