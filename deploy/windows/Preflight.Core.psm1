function Get-ClinicAssessment {
    param([Parameter(Mandatory=$true)]$Snapshot)
    $checks = [System.Collections.Generic.List[object]]::new()
    function Add-Check($Id,$Level,$Message) { $checks.Add([pscustomobject]@{id=$Id;level=$Level;message=$Message}) }
    if ($Snapshot.os.architecture -notmatch '64') { Add-Check 'os' 'STOP' 'Can Windows 64-bit.' }
    elseif ($Snapshot.os.caption -notmatch 'Windows 11 Pro') { Add-Check 'os' 'WARN' 'Chua xac nhan dung Windows 11 Pro cua phong kham.' }
    else { Add-Check 'os' 'OK' 'Windows 11 Pro 64-bit.' }
    if ($Snapshot.cpu.name -notmatch 'i3-10105') { Add-Check 'cpu' 'WARN' 'CPU khac i3-10105; ket qua nay khong dai dien may phong kham.' }
    else { Add-Check 'cpu' 'OK' 'Intel Core i3-10105.' }
    if ($Snapshot.memory.total_mib -lt 7168) { Add-Check 'memory' 'STOP' 'Khong du bo nho theo cau hinh 8 GB da chot. Kiem tra lai may.' }
    elseif ($Snapshot.memory.available_mib -lt 2048) { Add-Check 'memory' 'WARN' 'RAM trong duoi 2 GB: dong ung dung khong can thiet, giu Defender/Firewall.' }
    else { Add-Check 'memory' 'OK' 'Con it nhat 2 GB RAM trong tai thoi diem kiem tra.' }
    if ($null -eq $Snapshot.disk_c) { Add-Check 'disk' 'STOP' 'Khong doc duoc dung luong C:.' }
    elseif ($Snapshot.disk_c.free_gib -lt 20) { Add-Check 'disk' 'STOP' 'C: con duoi 20 GiB. Chua bat dau cai/nhap du lieu; khong xoa ho so, WAL hay backup tot.' }
    elseif ($Snapshot.disk_c.free_gib -lt 40) { Add-Check 'disk' 'WARN' 'C: con 20-40 GiB. Can tinh them cho backup, phuc hoi va Windows Update.' }
    else { Add-Check 'disk' 'OK' 'C: con it nhat 40 GiB; van can theo doi tang truong.' }
    if ($Snapshot.storage_status -eq 'UNKNOWN') { Add-Check 'smart' 'WARN' 'Khong doc duoc SMART/SSD. Trang thai chua biet, khong duoc coi la SSD tot.' }
    elseif (@($Snapshot.physical_disks | Where-Object { $_.health -ne 'Healthy' }).Count -gt 0) { Add-Check 'smart' 'STOP' 'Co o dia bao trang thai khong Healthy. Dung thu nghiem ghi, bao quan tri va kiem tra ban sao.' }
    else { Add-Check 'smart' 'OK' 'Windows bao Healthy; day khong thay the kiem tra SSD chuyen sau.' }
    if (@($Snapshot.physical_disks | Where-Object { $_.media -eq 'SSD' }).Count -eq 0) { Add-Check 'ssd' 'WARN' 'Chua xac nhan SSD qua Windows; kiem tra lai MediaType va SMART.' }
    if (@($Snapshot.physical_disks | Where-Object { $null -eq $_.smart }).Count -gt 0) { Add-Check 'smart_details' 'WARN' 'Mot so o khong tra chi tiet SMART; khong suy ra SSD khong co loi.' }
    if (@($Snapshot.listeners | Where-Object { $_.port -eq 5432 -and $_.address -notin @('127.0.0.1','::1') }).Count -gt 0) { Add-Check 'postgres_network' 'STOP' 'Cong 5432 dang nghe ngoai loopback; can quan tri sua cau hinh truoc khi thu.' }
    if (@($Snapshot.listeners | Where-Object { $_.port -eq 8443 -and $_.address -in @('0.0.0.0','::') }).Count -gt 0) { Add-Check 'https_network' 'STOP' 'Cong 8443 dang nghe tat ca dia chi; can bind dung IP LAN.' }
    if ($Snapshot.python_version -notmatch '^Python 3\.12\.') { Add-Check 'python' 'WARN' 'Chua thay Python 3.12 trong venv/PATH. Cai theo huong dan.' }
    else { Add-Check 'python' 'OK' 'Python 3.12.' }
    if ($Snapshot.postgres_version -notmatch 'PostgreSQL\) 17\.') { Add-Check 'postgres' 'WARN' 'Chua thay PostgreSQL 17. Kiem tra duong dan cai dat.' }
    else { Add-Check 'postgres' 'OK' 'PostgreSQL 17.' }
    if ($null -eq $Snapshot.defender -or -not $Snapshot.defender.realtime) { Add-Check 'defender' 'WARN' 'Khong xac nhan Defender bao ve thoi gian thuc. Khong tat bao ve de tang toc.' }
    if (@($Snapshot.firewall).Count -ne 3 -or @($Snapshot.firewall | Where-Object { -not $_.enabled }).Count -gt 0) { Add-Check 'firewall' 'WARN' 'Chua xac nhan ca 3 profile Firewall dang bat. Can quan tri kiem tra.' }
    $overall='OK'
    if (@($checks | Where-Object level -eq 'WARN').Count -gt 0) { $overall='WARN' }
    if (@($checks | Where-Object level -eq 'STOP').Count -gt 0) { $overall='STOP' }
    return [pscustomobject]@{overall=$overall;checks=@($checks.ToArray());note='Chi doc tai nguyen, khong thay doi he thong. Khong cam ket du tai nguyen neu chua benchmark tai phong kham.'}
}
Export-ModuleMember -Function Get-ClinicAssessment
