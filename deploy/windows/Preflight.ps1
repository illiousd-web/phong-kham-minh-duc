# Read-only Windows inventory. Never reads passwords, serials, document titles,
# process command lines, host/user names, MACs, environment files or patient files.
[CmdletBinding()]
param([string]$Root='C:\MinhDuc',[string]$OutputPath='')
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'Preflight.Core.psm1') -Force
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'Run on Windows. No system settings were changed.' }
function Get-VersionText([string]$Executable) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable) -or $Executable -match 'WindowsApps') { return 'UNKNOWN' }
    try {
        $text=(& $Executable --version 2>$null | Out-String).Trim()
        if ($text -match '(Python 3\.\d+\.\d+|postgres \(PostgreSQL\) \d+\.\d+)') { return $Matches[0] }
    } catch { }
    return 'UNKNOWN'
}
$os=Get-CimInstance Win32_OperatingSystem -Property Caption,Version,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory
$cpu=Get-CimInstance Win32_Processor -Property Name,NumberOfCores,NumberOfLogicalProcessors,LoadPercentage | Select-Object -First 1
$disk=Get-CimInstance Win32_LogicalDisk -Property Size,FreeSpace -Filter "DeviceID='C:'"
$python=Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $command=Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $python=$command.Source }
}
$disks=@();$storageStatus='UNKNOWN'
try {
    foreach ($physical in Get-PhysicalDisk -ErrorAction Stop) {
        $reliability=$null
        try {
            $counter=$physical | Get-StorageReliabilityCounter -ErrorAction Stop
            $reliability=[pscustomobject]@{temperature_c=$counter.Temperature;wear=$counter.Wear;read_errors=$counter.ReadErrorsTotal;write_errors=$counter.WriteErrorsTotal}
        } catch { }
        $disks += [pscustomobject]@{media=[string]$physical.MediaType;health=[string]$physical.HealthStatus;size_gib=[math]::Round($physical.Size/1GB,1);smart=$reliability}
    }
    if ($disks.Count -gt 0) { $storageStatus='REPORTED' }
} catch { }
$network=@()
try {
    $network=@(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' } | ForEach-Object { [pscustomobject]@{ipv4=$_.IPAddress;prefix=$_.PrefixLength} })
} catch { }
$listeners=@()
try { $listeners=@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -in @(8443,5432) | ForEach-Object { [pscustomobject]@{port=$_.LocalPort;address=$_.LocalAddress} }) } catch { }
$defender=$null
try { $mp=Get-MpComputerStatus -ErrorAction Stop; $defender=[pscustomobject]@{antivirus=[bool]$mp.AntivirusEnabled;realtime=[bool]$mp.RealTimeProtectionEnabled} } catch { }
$firewall=@()
try { $firewall=@(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object { [pscustomobject]@{profile=[string]$_.Name;enabled=[bool]$_.Enabled;default_inbound=[string]$_.DefaultInboundAction} }) } catch { }
# Only aggregate familiar process groups; never expose command lines/window titles.
$processes=@()
try {
    $groups=Get-Process | Group-Object { if ($_.ProcessName -match '^(python|pythonw|postgres|chrome|msedge)$') { $_.ProcessName } else { 'Other' } }
    $processes=@($groups | ForEach-Object { [pscustomobject]@{group=$_.Name;count=$_.Count;working_set_mib=[math]::Round(($_.Group | Measure-Object WorkingSet64 -Sum).Sum/1MB,1)} })
} catch { }
$snapshot=[pscustomobject]@{
    os=[pscustomobject]@{caption=$os.Caption;version=$os.Version;architecture=$os.OSArchitecture}
    cpu=[pscustomobject]@{name=$cpu.Name;cores=$cpu.NumberOfCores;threads=$cpu.NumberOfLogicalProcessors;load_percent=$cpu.LoadPercentage}
    memory=[pscustomobject]@{total_mib=[math]::Round($os.TotalVisibleMemorySize/1024);available_mib=[math]::Round($os.FreePhysicalMemory/1024)}
    disk_c=$(if ($disk) { [pscustomobject]@{total_gib=[math]::Round($disk.Size/1GB,1);free_gib=[math]::Round($disk.FreeSpace/1GB,1)} } else { $null })
    storage_status=$storageStatus;physical_disks=$disks;private_ipv4=$network;listeners=$listeners
    python_version=(Get-VersionText $python)
    postgres_version=(Get-VersionText (Join-Path $env:ProgramFiles 'PostgreSQL\17\bin\postgres.exe'))
    defender=$defender;firewall=$firewall;process_groups=$processes
}
$report=[pscustomobject]@{format=1;time_utc=[DateTime]::UtcNow.ToString('o');source='WINDOWS_READ_ONLY';snapshot=$snapshot;assessment=(Get-ClinicAssessment $snapshot)}
Write-Host ('Minh Duc - Preflight: '+$report.assessment.overall)
foreach ($check in $report.assessment.checks) { Write-Host ('['+$check.level+'] '+$check.message) }
Write-Host 'Khong co cai dat, dich vu, Defender/Firewall hay du lieu nao bi thay doi.'
if ($OutputPath) {
    # Only writes the report explicitly requested by the operator; no overwrite.
    $stream=[System.IO.File]::Open($OutputPath,[System.IO.FileMode]::CreateNew)
    try { $bytes=[System.Text.Encoding]::UTF8.GetBytes(($report | ConvertTo-Json -Depth 8));$stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
    Write-Host 'Da luu bao cao (khong chua mat khau/serial/ten nguoi dung). Khong dang cong khai IP noi bo.'
}

if ($report.assessment.overall -eq 'STOP') { exit 2 }
