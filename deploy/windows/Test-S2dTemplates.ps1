# Kiểm nguồn công khai riêng S2d, không chép dữ liệu người bệnh.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'DanhMucGoc.ps1')
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$temp=Join-Path ([IO.Path]::GetTempPath()) ('s2d-public-'+[guid]::NewGuid().ToString('N'))
try {
    Copy-S2dPublicTemplate -SourceRoot $root -DestinationRoot $temp
    Test-S2dPublicTemplate -SourceRoot $temp
    Copy-S2dPublicTemplate -SourceRoot $temp -DestinationRoot $temp
    $file=Join-Path $temp 'data\danh_muc_goc\mau_ket_qua_28.json'
    $templates=Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    if($templates.Count -ne 28){throw 'Sai số mẫu công khai.'}
    Add-Content -LiteralPath $file -Value 'sai gia lap'
    $blocked=$false
    try {Test-S2dPublicTemplate -SourceRoot $temp} catch {$blocked=$true}
    if(-not $blocked){throw 'Không chặn nguồn bị thay đổi.'}
    Write-Output 'PASS: nguồn 28 mẫu S2d, chép lặp không đổi, sai hash bị chặn'
} finally {if(Test-Path $temp){Remove-Item -LiteralPath $temp -Recurse -Force}}
