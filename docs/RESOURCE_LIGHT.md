# Profile tiết kiệm tài nguyên — Issue #3

Base `main`: `0058564` (LAN v0.4 đã merge). Mục tiêu cố định: i3-10105 4 nhân/8 luồng, RAM 8 GB, SSD 256 GB, Windows 11 Pro. Không đề xuất nâng cấp phần cứng. Chưa khẳng định đủ tài nguyên vì chưa có số đo dung lượng trống, SMART, ứng dụng nền và tải thực tế từ máy này.

## Tiến trình và bộ nhớ

| Tham số | v0.4 trước | Profile hiện tại |
|---|---:|---:|
| Worker Uvicorn | 2 | 1 |
| Pool mỗi worker | min1/max16 | min1/max4 |
| Tổng kết nối app tối đa | 32 | 4 |
| Luồng xử lý đồng bộ mỗi worker | mặc định AnyIO40 | 8 |
| Concurrent request giới hạn | 80/worker | 24/worker |
| Xuất biểu mẫu song song | Không có giới hạn riêng | 1/worker, trả 503/Retry-After khi bận |

Các biến trong `deploy/windows/clinic-8gb.env.example` được kiểm số nguyên/phạm vi và quan hệ: worker1–2, poolmax1–8, min<=max<=thread limit, tổng pool<=12. Mặc định dùng 1/4; chỉ người quản trị đổi sau đo lại. Pool trả bớt kết nối nhàn rỗi sau 60 giây và chỉ dùng một thread quản lý nền. Lifespan đóng pool khi tắt. Việc ghi nhật ký HTTP bổ sung chuyển khỏi event loop sang threadpool, không bỏ audit hoặc cơ chế transaction.

Với Windows 11/Defender và app khác, không dùng toàn bộ 8 GB cho PostgreSQL. Mục tiêu trước chạy có khoảng 2 GiB RAM khả dụng; đây là ngưỡng vận hành để kiểm tra, không phải bảo đảm mọi workload nằm trong 2 GiB. RSS cộng các worker đếm trùng trang shared; dùng thêm USS để đánh giá bộ nhớ private. Chưa đo Windows i3 thật.

## PostgreSQL 17

File `deploy/postgresql/minhduc-8gb.conf` cần admin áp dụng trong cửa sổ bảo trì, backup cấu hình và restart. Không có lệnh tự chỉnh máy phòng khám. Dùng quyền runtime hạn chế và HBA/SCRAM như v0.4.

- max_connections20, shared_buffers128 MiB, effective_cache_size2 GiB (chỉ là gợi ý planner, không cấp phát sẵn 2 GiB).
- work_mem4 MiB, hash_mem_multiplier1, maintenance_work_mem64 MiB; autovacuum2 worker, tối đa32 MiB/worker. work_mem cấp cho từng operation, không phải giới hạn toàn bộ query/process; không nhân đơn giản work_mem với connections để cam kết mức RAM tuyệt đối.
- Giảm song song query/maintenance; temp_file_limit256 MiB/backend. Query quá lớn có thể thất bại có kiểm soát, không tăng work_mem không giới hạn.
- min_wal_size80 MiB/max_wal_size512 MiB, wal_buffers8 MiB, checkpoint10 phút, completion_target0.9. `max_wal_size` là mục tiêu mềm, **không phải hard cap**; WAL vẫn có thể vượt khi checkpoint/replication/transaction dài. Không xóa WAL. max_slot_wal_keep_size512 MiB áp dụng cho slot nếu sau này có dùng; hệ thống này chưa triển khai replica/PITR.
- Giữ **fsync=on, synchronous_commit=on, full_page_writes=on, autovacuum=on**. Không giảm độ bền ghi để đổi lấy kết quả benchmark.
- Collector giữ 7 tên log theo thứ, ghi đè khi xoay thời gian sau một tuần. Mỗi file vẫn có thể tăng khi lỗi dồn dập; không gọi đó là giới hạn byte cứng. Báo động khi thư mục log PG vượt1 GiB; sửa nguyên nhân lỗi và xử lý log theo quy trình, không xóa audit DB. Không log SQL/parameters chứa nội dung khám hoặc mật khẩu. App operational log quay vòng khoảng40 MiB, khóa liên tiến trình khi rotate để không ghi nhầm file cũ nếu admin chọn2 worker. Không dùng log HTTP có query chứa thông tin tìm kiếm.

Admin xác minh sau restart qua psql/pgAdmin (không chép mật khẩu vào command line):

```sql
SHOW max_connections; SHOW shared_buffers; SHOW work_mem;
SHOW fsync; SHOW synchronous_commit; SHOW full_page_writes;
SHOW listen_addresses; SHOW logging_collector;
SELECT name,setting,unit,pending_restart FROM pg_settings
WHERE name IN ('max_connections','shared_buffers','work_mem','maintenance_work_mem','autovacuum_work_mem');
```

Runtime vẫn kiểm optimistic version, idempotency và advisory lock trước read-check-write; các thay đổi nghiệp vụ và audit cùng transaction. Phiên/CSRF/HTTPS/CIDR/phân quyền giữ nguyên. Không purge bệnh nhân hoặc audit để “tối ưu”.

## Dung lượng và backup

SSD256 GB danh nghĩa thường hiện khoảng238 GiB trước phân vùng/Windows. Không biết còn trống bao nhiêu cho tới Preflight. Dự trù tối thiểu: Windows/apps/update + DB/index/WAL/temp + attachments + 7 bản backup + chỗ tạo bản mới + chỗ restore riêng +10 GiB dự phòng. Ngưỡng40 GiB trống trước cài là mức kiểm tra ban đầu, không thay phép tính theo dữ liệu tăng thực tế.

- LAN từ chối giao dịch ghi khi volume dữ liệu dưới ngưỡng10 GiB. Đọc health và công cụ OS vẫn dùng để chẩn đoán. Ngưỡng test256 MiB chỉ dùng ở workspace giả lập nhỏ, không sao chép sang config phòng khám.
- Uploadmax5 MiB, tổngattachments2 GiB, body6 MiB; cho phép hạ giới hạn tệp, không tăng quá5 MiB. Không lưu DICOM/phim/ảnh gốc lớn. Khi thay attachment, chỉ bỏ tệp cũ không còn tham chiếu sau commit thành công, trong khóa đồng bộ với backup. Rollback giữ nguyên tệp cũ; chỉ dọn tệp mới sau khi xác minh DB không tham chiếu. Mất ACK COMMIT hoặc DB chưa sẵn sàng thì giữ tệp chờ đối chiếu, không xóa nhầm tệp đã commit. Không có dọn hàng loạt tệp bệnh nhân.
- Export giữ đủ nội dung, giới hạn1tác vụ/worker và10 MiB đầu ra; lượt có hơn200 chỉ định trả lỗi thay vì tải toàn bộ vào RAM hoặc cắt im lặng. Tài liệu xuất không lưu cache server; Downloads phía máy trạm vẫn cần chính sách riêng.
- Backup mới stream TAR vào AES-GCM, chỉ giữ dump DB tạm và output mã hóa. Tránh bản sao toàn bộattachments và TAR plaintext trên SSD; format/GCM/manifest cũ vẫn đọc được. Khóa ứng dụng được giữ trong lúc đọc snapshot/tệp, nên chạy ngoài giờ; không bỏ khóa để tăng tốc.
- Trước dump, kiểm dung lượng: dự phòng10 GiB + khoảng2*(pg_database_size+attachments)+64 MiB để có dư cho tạo bản mới. Tổng local backups có ngân sách20 GiB, giữ7 bản thành công gần nhất. DBsize là ước lượng bảo thủ (bao gồm index), không dự đoán chính xác mức nén; kiểm lại output trước xuất bản. Nếu vượt ngân sách/thiếu chỗ thì lệnh thất bại và giữ bản tốt cũ, không tự xóa trước để lấy chỗ.
- Bản ngoài máy được copy mã hóa sang thư mục đã có, fsync và kiểm SHA-256 rồi atomic rename, không copy key. Giữ30 bản mặc định (2–90); chỉ pruning sau copy mới đã xác minh. Cần tối thiểu đủ chỗ bản mới +256 MiB ở nơi ngoài máy. Copy lỗi giữ cả bản mới local và bản tốt cũ; vận hành phải nhận cảnh báo và khắc phục để tránh local tiếp tục tăng. Không thể tự chứng minh USB/NAS là ngoài máy chỉ từ đường dẫn; admin phải nghiệm thu vị trí và quyền truy cập.
- Restore vào đích DB/tệp rỗng như v0.4; cần đủ chỗ plaintext TAR/tệp/dump và đích riêng. Không restore đè hay gọi hai tài nguyên DB/filesystem là transaction nguyên tử. Diễn tập trên dữ liệu giả lập, không khẳng định RTO khi chưa đo ở máy thật.

`scripts.storage_status` chỉ báo tổng dung lượng, số kết nối và cảnh báo; không trả tên bệnh nhân, tên tệp hoặc mật khẩu. Có thể cấu hình CLINIC_PG_LOG_DIR để đọc tổng log PG nếu tài khoản đủ quyền. Không nâng quyền DB runtime chỉ để đọc log.

## Preflight Windows

`Preflight.ps1` chỉ gọi các API đọc Windows và `--version`; report chỉ gồm field được chọn: OS/CPU/RAM, C: size/free, trạng thái vật lý/SMART nếu có, IPv4 private, listener8443/5432, Python/PostgreSQL version, Defender/Firewall và nhómprocess theo tên ứng dụng phổ biến/Other. Không ghi host/user name, serial, MAC, ID phần cứng, command line, cửa sổ tài liệu, env credential hoặc tệp bệnh nhân.

Không tự đổi cấu hình/dịch vụ, không gọi tắt bảo vệ; chỉ ghi JSON khi operator yêu cầu `-OutputPath`, dùng CreateNew không ghi đè. Thiếu quyền/API/SMART phải hiện UNKNOWN/WARN. Script không kết nối PostgreSQL hay đọc mật khẩu. Test fixture không thay bằng chứng SMART hoặc Windows 11 thật. Không public report IP LAN.

## Đo và nghiệm thu

Có harness `scripts.benchmark_lan` tạo/xóa container PostgreSQL của riêng nó, không nhận URL database phòng khám. So mã v0.4 từ git archive main 0058564 với mã mới trên cùng workload1000 hồ sơ giả, ba phiênHTTPS, 210 request/round, PDF, quyền sai, ngắt socket trước đọc kết quả rồi retry cùng idempotency key. Giữ fsync/commit/full_page_writes on; đo appRSS/USS/CPU, snapshot RAM riêng các tiến trìnhPG, dung lượngDB/WAL và IO/đĩa tạm backup. Load generator không tính vào app memory. SốIO0 có thể do page cache, không phải khẳng định không ghi SSD.

Chạy hai lần riêng, không chạy pytest hoặc tải cài gói cùng lúc:

```sh
# Chỉ môi trường phát triển Linux có Docker local, PostgreSQL client17, dependencies-test.
python -m scripts.benchmark_lan --baseline-ref 0058564 --iterations 30 --output test_evidence/benchmark.json
```

Bằng chứng và giới hạn đo nằm trong [báo cáo Issue #3](ISSUE3_VALIDATION.md). Không dùng số Linux để suy ra máy Windows i3 đã đạt. Nghiệm thu ở phòng khám cần Preflight thực tế, ba máy hiện có, ca mô phỏng giờ cao điểm, Task Manager/Resource Monitor theo dõi commit/RAM/CPU/disk, thử mất mạng và restore riêng. Không tắt bảo mật khi đo.
