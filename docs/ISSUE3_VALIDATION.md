# Issue #3 — kết quả tối ưu máy 8 GB

Ngày: 08/11/2026. Nhánh `feat/issue-3-low-resource-windows`, bắt đầu từ main `0058564` sau PR LAN v0.4. Giữ nguyên phần cứng đã chốt: i3-10105/RAM8 GB/SSD256 GB/Windows 11Pro. Chỉ dữ liệu giả lập, không truy cập máy chủ phòng khám hoặc dữ liệu bệnh nhân thật.

## Kết quả chính

Profile mặc định đổi từ 2 worker/pool 16 mỗi worker sang **1 worker/pool 4**, threadpool 8, tối đa1 lượt export/worker. Giữ HTTPS, ACL/CIDR, CSRF, mật khẩu riêng, hết hạn phiên, audit, optimistic version, idempotency và khóa giao dịch. PostgreSQL có file cấu hình128 MiB shared_buffers/max20connections, fsync/commit/full_page_writes vẫn bật.

Đã thêm Preflight Windows chỉ đọc, kiểm dung lượng/SMART khi có, tài nguyên và các phần mềm cần thiết, không thu mật khẩu/serial/MAC/tên người dùng. Có hướng dẫn Windows ngắn và file cấu hình sẵn cho người cài. Công cụ không khẳng định đủ tài nguyên nếu thiếu thông tin, SMART không đọc được, hoặc chưa đo workload thật.

## Đo trước/sau

Hai lần đo nối tiếp, không chạy pytest/cài gói đồng thời. Mã trước là git archive main 0058564; mã sau là profile của Issue #3. Mỗi lượt dùng PostgreSQL container mới, 1000 hồ sơ giả, 16 MiB tệp giả, ba phiên lễ tân/bác sĩ/thu ngân qua **HTTPS xác minh CA**, 210 request nghiệp vụ +3 PDF, kiểm quyền, ngắt socket trước đọc kết quả thanh toán và retry cùng khóa.

Môi trường **Linux x86_64**, cgroup8 GiB RAM/2 CPU; PostgreSQL container yêu cầu2 CPU/1536 MiB. Không phải CPUi3-10105 hay Windows 11 vật lý; không mô phỏng SSD256 GB hoặc Defender/ứng dụng nền thực tế. Docker stats ở executor này tính cả cgroup dùng chung nên đã loại khỏi bằng chứng. RAM PG lấy riêng qua `/proc` của các tiến trình PostgreSQL.

| Chỉ số | v0.4 trước (lần1 / lần2) | Resource-light (lần1 / lần2) | Diễn giải |
|---|---:|---:|---|
| App RSS đỉnh, MiB | 200,90 / 197,08 | 94,64 / 94,80 | Trung bình giảm52,4%; RSS cộng có đếm trùng shared pages |
| App USS đỉnh, MiB | 143,66 / 141,16 | 76,00 / 76,24 | Bộ nhớ private trung bình giảm46,5% |
| App CPU, giây CPU | 3,59 / 3,80 | 2,57 / 2,59 | TổngCPU app gồm startup/workload, giảm30,2%; không phải %CPU máy phòng khám |
| API p95, ms | 67,35 / 67,99 | 43,80 / 40,34 | Cùng workload3 phiên; không bảo đảm cho nhiều nhân viên hơn |
| PG USS sau workload, MiB | 27,14 / 26,67 | 22,87 / 23,07 | Snapshot khi pool còn mở, **không phải RAM PG đỉnh** |
| Backup RSS đỉnh, MiB | 49,07 / 48,82 | 48,91 / 48,86 | Gần như không đổi, không tuyên bố giảm RAM backup đỉnh |
| Backup I/O ghi, MiB | 48,29 / 48,29 | 16,18 / 16,18 | Bộ đếm OS theo nhóm tiến trình, giảm khoảng66,5%; không phải phép đo độ bền SSD |
| Backup scratch quan sát đỉnh, MiB | 38,66 / 45,16 | 16,09 / 16,09 | Sample10ms có thể bỏ lỡ đỉnh ngắn; streaming loại copyattachments và TARplaintext |

JSON gốc đã loại credential/host/containerID: [lần1](benchmarks/issue3-linux-run1.json), [lần2](benchmarks/issue3-linux-run2.json). Có thời gianPDF, DB/WAL, quyền và kết quả disconnect trong từng JSON. Không dùng sốCPU/RAM của load generator làm mức tiêu thụ ứng dụng. Không cộng đơn giản RSSPG+RSSapp để suy ra RAM tối thiểu cho toàn Windows.

Cả4 cấu hình/lượt đều không có lỗi request trong workload, quyền sai bị từ chối, retry sau disconnect chỉ có1payment và SHOW fsync/synchronous_commit/full_page_writes đều on. Backup định dạng cũ vẫn restore được; backup mới GCM/manifest/pg_dump/pg_restore được kiểm ở integration test. Benchmark này không thay thế thử UPS/mất điện hoặc rút dây LAN thật.

## Kiểm thử và sửa lỗi

- **47 pytest hồi quy/giới hạn tài nguyên**, **26 pytest LAN**: đủ 9 biểu mẫuPDF/DOCX, 3 context trình duyệt, quyền/phiên/CSRF, giao dịch đồng thời, khoFEFO, thanh toán/hoàn/giảm, backup/restore; bổ sung hết chỗ507, thayattachment/rollback, giới hạnexport, cấu hình sai, xoaylog3tiến trình, offsite mất kết nối không pruning bản tốt.
- **6 tình huống Preflight giả lập** và PowerShell parser: máy đủ điều kiện, hết chỗ, thiếuRAMtrống, SMART unknown, PostgreSQL nghe public, Firewall tắt. Parser đã chạy PowerShell 7 trên Linux; kiểm thêm PowerShell 5.1 và inventory đọc Windows trong CI, trạng tháiCI phải xem riêng trên PR. HostedWindows không phải Windows 11Pro của phòng khám.
- CVE runtime 26 phụ thuộc: không phát hiện lỗ hổng đã biết tại thời điểm audit; dependenciesruntime không tăng, psutil chỉ ở requirements-test. Không tương đương audit toàn bộWindows/PostgreSQL image hoặc pentest.
- Checksum31 tài sản gốc, CSS/JS/HTML không đổi giao diện; compilePython, syntaxJS/YAML/PowerShell, pipcheck và gitdiffcheck.

Các lỗi thực tế sửa trong quá trình:

1. Backupv0.4 chép toànattachments +tạo TAR +mã hóa, tốnI/O và chỗ tạm; đổi TARstream vàoGCM, giữ dump/manifest/tính nhất quán. Báo cáo benchmark ban đầu gặp kiểuDecimal của SUMWAL, đã chuyển số choJSON và đo lại.
2. Upload thay tệp để lại bản cũ không dùng, rollback có thể để lại tệp mới. Nay dọn mới khi rollback và chỉ bỏ bản cũ không tham chiếu sau commit, trong cùng advisorylock với backup. Không dọn dữ liệu đang dùng. Nếu mất ACK của COMMIT, đối chiếu tham chiếu DB trước khi xóa; DB chưa sẵn sàng thì giữ tệp để tránh mất dữ liệu đã commit.
3. AuditHTTP đồng bộ chạy trên eventloop; nay chuyển sang threadpool có giới hạn, vẫn giữ audit nghiệp vụ atomic. Đọc file upload/fsync cũng chạy trong syncendpoint/threadpool, không chặn eventloop khi chờ khóabackup.
4. Worker/pool/concurrency hardcode làm tăng process/RAM; đưa vào cấu hình có kiểm phạm vi và quan hệ. Tách importFastAPI khỏi module cấu hình tài nguyên để công cụ backup không nạp cả webframework chỉ để đọc giới hạn.
5. Log vận hành chưa có giới hạn rõ, nay rotate5 MiB/7 filebackup, khóa liên tiến trình để rotate an toàn; không purge audit DB. PGlog7 tên theo ngày có cảnh báo dung lượng, không cam kết bytecap cứng.
6. Đã loại sốDockerstats không thể gán riêng choPG trong managed executor; các số đó không được dùng để kết luận tối ưu.

## Đạt/chưa đạt theo Issue #3

| Yêu cầu | Đã làm | Còn phải làm tại phòng khám |
|---|---|---|
| GiảmRAM/process/pool | Có cấu hình validated, đo trước/sau hai lần trên Linux | Preflight và TaskManager/ResourceMonitor Windows 11i3 thực tế; chưa cam kết đủ tài nguyên |
| PostgreSQL tiết kiệm/durability | FilePG17 được chạy trong benchmark; fsync/commit/full_page_writeson | Admin áp trên Windows, kiểmpending_restart/HBA/quyềnDB và dung lượng |
| Dung lượngattachments/PDF/log/backup | Quota/free-space guard, exportslot, cleanuprollback, streamingbackup, offsitecopy/retention cóverify | Kiểm ổ thật, tốc độ tăng, nơi ngoài máy vật lý, lịch chạy, chỗ restore, log PG bất thường |
| Preflightreadonly | Có script/batch/JSON chọnfield và testfixture/parser | SMART có thể UNKNOWN; cần đọc trực tiếp trên máy phòng khám; không đưa report cóIP lên public |
| Ba vai trò/security/disconnect/PDF/restore | Unit/integration/HTTPSbrowser và benchmark giả lập | Chưa ba máy vật lý/rút mạng/mất điện/UPS/khôi phục full-size trên SSD thật |
| Hướng dẫn dễ dùng | CóquickstartWindows5bước và runbook kỹ thuật | Người cài điền IP/credential, cấpACL/CA/Firewall và bàn giao thao tác; chưa tự cài máy thật |
| Nhánh/PR/dữ liệu | Nhánh riêng từmain, chỉfake, PRđểreview | Không tựmerge hoặc dùng dữ liệu thật trước nghiệm thu |

## Giới hạn vận hành cần giữ

Chưa quét malware cho attachments, chuẩn y tế/ký số, hay kiểm thửxâmnhập độc lập. Không có PITR/HA/failover. MaxWAL512 MiB là mục tiêu mềm; PostgreSQL và Windows vẫn cần dung lượng dự phòng. Quota backup có thể làm lệnh dừng thay vì xóa bản tốt; phải giám sát thất bại. Không tự chứng minh đường dẫn ngoài máy là thiết bị khác, hoặc độ bền vật lý của fsync trên thiết bị thực tế. Khóa ghi chung giảm thông lượng nhưng tiếp tục bảo vệ transaction; không bỏ khóa khi tăng tải.

Không thay RAM/SSD/máy. Khi tài nguyên thực tế thiếu, trước hết dừng nhập thử, đóng app không cần, kiểm cấu hình/dung lượng và nhờ người phụ trách đánh giá; không giảm độ bền, tắt bảo mật hoặc xóa dữ liệu để tiếp tục.
