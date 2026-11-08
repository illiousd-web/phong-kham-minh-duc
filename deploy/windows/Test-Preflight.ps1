$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'Preflight.Core.psm1') -Force
function Assert-True($Condition,$Message) { if (-not $Condition) { throw $Message } }
function Sample {
    return [pscustomobject]@{
        os=[pscustomobject]@{caption='Microsoft Windows 11 Pro';architecture='64-bit'}
        cpu=[pscustomobject]@{name='Intel Core i3-10105'}
        memory=[pscustomobject]@{total_mib=8192;available_mib=3072}
        disk_c=[pscustomobject]@{total_gib=238.5;free_gib=80}
        storage_status='REPORTED';physical_disks=@([pscustomobject]@{health='Healthy';media='SSD';smart=[pscustomobject]@{temperature_c=30;wear=0}})
        listeners=@([pscustomobject]@{port=5432;address='127.0.0.1'})
        python_version='Python 3.12.16';postgres_version='postgres (PostgreSQL) 17.11'
        defender=[pscustomobject]@{realtime=$true}
        firewall=@('Domain','Private','Public' | ForEach-Object { [pscustomobject]@{profile=$_;enabled=$true} })
    }
}
$s=Sample; Assert-True ((Get-ClinicAssessment $s).overall -eq 'OK') 'Healthy fixture must pass'
$s.disk_c.free_gib=12; Assert-True ((Get-ClinicAssessment $s).overall -eq 'STOP') 'Low disk must stop'
$s=Sample;$s.storage_status='UNKNOWN'; Assert-True ((Get-ClinicAssessment $s).overall -eq 'WARN') 'Unknown SMART cannot pass'
$s=Sample;$s.memory.available_mib=1000; Assert-True ((Get-ClinicAssessment $s).overall -eq 'WARN') 'Low free memory must warn'
$s=Sample;$s.listeners=@([pscustomobject]@{port=5432;address='0.0.0.0'}); Assert-True ((Get-ClinicAssessment $s).overall -eq 'STOP') 'Public DB listener must stop'
$s=Sample;$s.firewall[0].enabled=$false; Assert-True ((Get-ClinicAssessment $s).overall -eq 'WARN') 'Disabled firewall must warn'
foreach ($path in Get-ChildItem $PSScriptRoot -Include *.ps1,*.psm1 -Recurse) {
    $tokens=$null;$errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path.FullName,[ref]$tokens,[ref]$errors)
    Assert-True ($errors.Count -eq 0) ('Syntax errors: '+$path.Name)
}
Write-Output 'PASS: six synthetic preflight assessments and PowerShell parser checks'
