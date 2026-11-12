# Chỉ các tệp công khai do chủ dự án cho phép; không chép dữ liệu khác.
function Get-D0PublicCatalogs {
    return @{
        'ICD10_TT06_2026.csv' = '05f4db19f5935c5c106185937c4bb956618c7d00408f29c64c0614640d3c73d4'
        'QD1227_MA_DUNG_CHUNG_CLS_DOT1.csv' = 'c3db0f38ff1e9a7cf857a87d3636e6c39d0a047b98de27a353db94110d0fdbed'
        'TT23_PL01_DANH_MUC_KY_THUAT.csv' = 'd4854c88304456c615d28d6bd7f3a0b5ab4a56dc0f00533604c57aaaf9984b1f'
        'TT23_PL02_DANH_MUC_KY_THUAT_TU_01072026.csv' = '38eab59894dbec1c904b1d7b54cad5e9f43afe75e854de7ea1497409e0fd666f'
        'DVHC_XA_CV1027_2025.csv' = '3a657a35fd6427d98774c8d74209cf3ec335e4225c4c8b35677358a1b1d8d06a'
    }
}
function Test-D0PublicCatalogs {
    param([string]$SourceRoot)
    $files = Get-D0PublicCatalogs
    foreach ($name in $files.Keys) {
        $path = Join-Path $SourceRoot ('data\danh_muc_goc\' + $name)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Thiếu tệp danh mục gốc: ' + $name) }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $files[$name]) { throw ('Sai SHA-256 danh mục gốc: ' + $name) }
    }
}
function Copy-D0PublicCatalogs {
    param([string]$SourceRoot, [string]$DestinationRoot)
    Test-D0PublicCatalogs -SourceRoot $SourceRoot
    $target = Join-Path $DestinationRoot 'data\danh_muc_goc'
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    $files = Get-D0PublicCatalogs
    foreach ($name in $files.Keys) {
        $src = Join-Path $SourceRoot ('data\danh_muc_goc\' + $name)
        $dst = Join-Path $target $name
        if ([IO.Path]::GetFullPath($src) -eq [IO.Path]::GetFullPath($dst)) { continue }
        $tmp = $dst + '.moi-' + [guid]::NewGuid().ToString('N')
        try {
            Copy-Item -LiteralPath $src -Destination $tmp -Force
            if ((Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant() -ne $files[$name]) { throw ('Chép danh mục không khớp SHA-256: ' + $name) }
            Move-Item -LiteralPath $tmp -Destination $dst -Force
        } finally { if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force } }
    }
}
