$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'DanhMucGoc.ps1')
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$folder = Join-Path ([IO.Path]::GetTempPath()) ('d0-public-' + [guid]::NewGuid().ToString('N'))
try {
    $source = Join-Path $folder 'source'
    $target = Join-Path $folder 'target'
    Copy-D0PublicCatalogs -SourceRoot $root -DestinationRoot $source
    Set-Content -LiteralPath (Join-Path $source 'data\danh_muc_goc\KHONG_DUOC_CHEP.csv') -Value 'DU LIEU GIA LAP KHONG CONG KHAI'
    Copy-D0PublicCatalogs -SourceRoot $source -DestinationRoot $target
    Test-D0PublicCatalogs -SourceRoot $target
    if ((Get-ChildItem (Join-Path $target 'data\danh_muc_goc') -File).Count -ne 7) { throw 'Must copy exactly seven public sources' }
    Copy-D0PublicCatalogs -SourceRoot $source -DestinationRoot $target
    Copy-D0PublicCatalogs -SourceRoot $target -DestinationRoot $target
    $before = @{}
    foreach ($name in (Get-D0PublicCatalogs).Keys) { $before[$name] = (Get-FileHash (Join-Path (Join-Path $target 'data\danh_muc_goc') $name)).Hash }
    Add-Content -LiteralPath (Join-Path $source 'data\danh_muc_goc\ICD10_TT06_2026.csv') -Value 'SAI GIA LAP'
    $blocked = $false
    try { Copy-D0PublicCatalogs -SourceRoot $source -DestinationRoot $target } catch { $blocked = $true }
    if (-not $blocked) { throw 'Invalid source hash must stop before writing' }
    foreach ($name in $before.Keys) { if ((Get-FileHash (Join-Path (Join-Path $target 'data\danh_muc_goc') $name)).Hash -ne $before[$name]) { throw 'Destination changed after invalid source' } }
    Write-Output 'PASS: seven exact public files, no private files, idempotent copy, invalid hash leaves destination intact'
} finally { if (Test-Path -LiteralPath $folder) { Remove-Item -LiteralPath $folder -Recurse -Force } }
