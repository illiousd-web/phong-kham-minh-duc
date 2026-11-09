> **v0.5.0:** xem [nâng cấp từ v0.4.x](V050_UPGRADE.md) và [hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md). Migration hiện tại là schema 3; chạy bằng owner rồi cấp lại quyền runtime.

> **Profile máy 8 GB (Issue #3):** mặc định mới 1 worker/pool4, backup7bản và ngưỡng dung lượng. Xem [hướng dẫn Windows ngắn](WINDOWS_8GB_QUICKSTART.md) và [cấu hình tài nguyên](RESOURCE_LIGHT.md); các con số 2worker/pool16/backup30 trong phần v0.4 cũ bên dưới là thông tin lịch sử.

# Vận hành, sao lưu và xử lý sự cố LAN

## Phiên và quyền

Mật khẩu từng người dùng PBKDF2-HMAC-SHA256 600.000 vòng, salt ngẫu nhiên riêng. Sau 5 lần sai một tên tài khoản, đăng nhập tên đó tạm khóa 15 phút; không phân biệt tài khoản tồn tại trong thông báo. Khóa theo tên có thể bị lợi dụng gây gián đoạn; quản trị phải theo dõi sự kiện thất bại. Chưa có MFA/SSO.

LAN dùng cookie `__Host-clinic` Secure, HttpOnly, SameSite=Strict, không lưu bearer token trong Web Storage. Token ngẫu nhiên 48 byte trước encode; database chỉ lưu SHA-256. Mỗi yêu cầu kiểm tra tài khoản còn hoạt động và quyền hiện tại. Origin khớp cấu hình, header yêu cầu và double-submit CSRF bảo vệ các thao tác ghi; không bật CORS. Đổi mật khẩu/đổi quyền/khóa nhân viên thu hồi phiên. Web API không cung cấp xóa nhật ký. Quyền database hạn chế trong `deploy/postgresql-roles.sql` ngăn runtime sửa/xóa nhật ký; DBA vẫn có khả năng sửa nên cần lưu bản sao và quy trình quản trị.

Các thay đổi nghiệp vụ và bản ghi audit cùng transaction: nếu thất bại thì rollback cả hai. Đọc hồ sơ, export, login/logout và HTTP access có nhật ký; log HTTP chỉ lưu method/path/status, không lưu query tìm kiếm, body khám, mật khẩu hoặc token. HTTP access log bổ sung có thể thiếu khi CSDL lỗi; log nghiệp vụ vẫn nằm cùng transaction bắt buộc. Không coi nhật ký là hệ thống chứng cứ chống sửa tuyệt đối.

## Giao dịch đồng thời

PostgreSQL dùng connection pool tối đa 16/worker và 2 worker. Tất cả ghi đi qua một transaction-scoped advisory lock chung. Đây là lựa chọn bảo thủ cho quy mô phòng khám: các ghi được tuần tự hóa trên mọi worker, đọc dùng MVCC. Không dùng nhiều writer ngoài `app.database.db(True)`; tiến trình nhập liệu/tích hợp sau này cũng phải tuân theo khóa. Khóa này không ngăn DBA hoặc SQL ngoài ứng dụng sửa trực tiếp.

Bệnh án kiểm tra `version` để phát hiện ghi đè và trả 409. Thu tiền kiểm tra tổng còn phải thu trong cùng khóa với INSERT, unique idempotency key; gửi lại cùng khóa/nội dung trả khoản đã ghi. Khác nội dung nhận 409. UI chặn submit trùng khi đang chờ và giữ khóa giao dịch cho cùng payload khi lỗi mạng trong cùng trang. Nếu reload/đóng trình duyệt sau mất mạng, mở lịch sử thu và đối soát trước khi tạo giao dịch mới; không hứa exactly-once cho thao tác thủ công qua trang mới. Kho FEFO không xuất lô hết hạn/cách ly/thuốc kiểm soát; cập nhật tồn có điều kiện và kiểm rowcount. Kết quả đã duyệt bị khóa sửa trực tiếp. Mỗi lịch hẹn chỉ tạo một lượt.

Các ghi có statement timeout 30 giây, lock timeout 15 giây. Backup giữ khóa ghi nên người dùng có thể nhận 503 trong lúc backup dài; chạy ngoài giờ. Phải đo lại tải thực tế trước khi tăng số người dùng; đã kiểm thử đồng thời chức năng, chưa có benchmark tải lớn hoặc HA.

## Sao lưu tự động

Dùng client PostgreSQL 17 phù hợp phiên bản server (`pg_dump`, `pg_restore`). Backup gồm dump custom-format, attachments và manifest SHA-256, mã hóa AES-256-GCM bằng khóa ngẫu nhiên 32 byte. Tính nhất quán: giữ khóa ghi của ứng dụng trong lúc pg_dump và chép attachments; không ghi tệp mới ngoài transaction khóa này. Mọi nội dung plaintext tạm nằm trong thư mục backup được bảo vệ rồi xóa sau lệnh, vì vậy volume chứa backup/tạm cũng phải mã hóa. Xóa file không bảo đảm xóa vật lý trên SSD.

Ví dụ Linux, chạy bằng tài khoản dịch vụ từ `/opt/minhduc` (Windows dùng `.venv\Scripts\python.exe` và đường dẫn tương ứng):

```sh
.venv/bin/python -m scripts.with_env /etc/minhduc/clinic.env scripts.backup_lan keygen --key /etc/minhduc/backup.key
.venv/bin/python -m scripts.with_env /etc/minhduc/clinic.env scripts.backup_lan backup --key /etc/minhduc/backup.key --directory /var/lib/minhduc/backups
.venv/bin/python -m scripts.with_env /etc/minhduc/clinic.env scripts.backup_lan verify --key /etc/minhduc/backup.key --file /var/lib/minhduc/backups/TEN_BAN_SAO.mdbackup
```

Tạo key bằng tài khoản có quyền ghi `/etc/minhduc`, sau đó cấp read tối thiểu cho dịch vụ. Không ghi đè key đã tồn tại. Khóa phải có bản sao offline riêng, mã hóa thiết bị chứa khóa; mất khóa thì không giải mã được bản sao. Không để khóa và backup cùng một thiết bị sao chép ngoài máy chủ. Giữ mặc định 30 bản thành công gần nhất; `CLINIC_BACKUP_KEEP` tối thiểu 2. Không pruning trước khi tạo bản mới thành công. Chép backup mã hóa sang thiết bị thứ hai/offline theo lịch, kiểm tra đủ dung lượng và cảnh báo thất bại; cơ chế chép thiết bị ngoài tùy hạ tầng chưa được cài tự động.

Linux enable `minhduc-backup.timer` sau khi chạy backup/verify thủ công đạt; kiểm `systemctl list-timers` và `journalctl -u minhduc-backup`. Timer chạy 20:00 theo múi giờ hệ điều hành, có chạy bù sau lúc tắt máy. Windows dùng Task Scheduler như hướng dẫn cài đặt. Mỗi sáng kiểm Last Run Result/timestamp, không chỉ kiểm file tồn tại. Hằng tháng phục hồi thử sang máy dự phòng, ghi lại kết quả.

RPO mục tiêu với lịch ngày: tối đa khoảng 24 giờ nếu mọi bản ngày thành công; chưa bảo đảm khi lịch thất bại. RTO phải đo trên dung lượng/thiết bị thật, chưa có số nghiệm thu. Chưa có WAL archiving/PITR hay failover tự động.

## Khôi phục

Không restore đè database đang chạy. Tạo database đích rỗng riêng do owner phục hồi sở hữu, thư mục attachments đích rỗng và đủ chỗ cho cả file tạm. Cung cấp URL đích trong file env bảo vệ qua biến `CLINIC_RESTORE_DATABASE_URL`, không qua argument chứa mật khẩu:

```sh
.venv/bin/python -m scripts.with_env /etc/minhduc/restore.env scripts.backup_lan restore --key /etc/minhduc/backup.key --file /duong-dan/ban-sao.mdbackup --target-uploads /var/lib/minhduc-restored/attachments
```

Bản sao lưu chứa cả `ui_settings.json` (bật/tắt chức năng phụ). Khi khôi phục, tệp được ghi cạnh thư mục `--target-uploads` (ví dụ `/var/lib/minhduc-restored/ui_settings.json`), đúng chỗ ứng dụng đọc sau khi đổi `CLINIC_UPLOAD_DIR` sang đích đó; đặt nơi khác bằng `--target-settings` rồi khai `CLINIC_UI_SETTINGS`. Lệnh từ chối ghi đè tệp cài đặt đã có. Bản sao lưu cũ chưa có tệp này: lệnh in cảnh báo, ứng dụng dùng mặc định; vào Cài đặt kiểm tra lại.

`restore.env` chứa cấu hình LAN đầy đủ, URL nguồn hợp lệ và URL đích owner. Lệnh kiểm tag GCM, manifest, hash, thành viên archive; từ chối đường dẫn vượt thư mục, symlink, database/thư mục đích không rỗng. pg_restore chạy single transaction và exit-on-error. Sau restore thu hồi toàn bộ phiên và ghi sự kiện khôi phục. Nếu máy hết đĩa/lỗi filesystem sau bước DB đã commit, đích có thể chỉ hoàn tất một phần: không chuyển ứng dụng sang đích đó; tạo đích rỗng khác và chạy lại sau khi sửa nguyên nhân.

Kiểm đếm hồ sơ, tài khoản/quyền, kho, số dư, file đính kèm và xuất 9 biểu mẫu trên dữ liệu giả lập. Dừng dịch vụ hiện tại trong cửa sổ bảo trì, sao lưu hiện trạng, cấp lại runtime grant ở database đích, đổi `CLINIC_DATABASE_URL` và `CLINIC_UPLOAD_DIR` sang đích đã xác minh rồi khởi động lại. Lưu cấu hình cũ để quay lại khi cần. Không chạy đồng thời hai hệ thống nhận ghi cho cùng nghiệp vụ. Đăng nhập mới sau restore.

## Xử lý sự cố

| Hiện tượng | Kiểm tra và hành động |
|---|---|
| Không vào được từ máy trạm | IP/DNS, cùng VLAN, CIDR, cổng 8443, đúng profile firewall, dịch vụ đang chạy. Không mở `0.0.0.0`, public IP hoặc router forwarding để chữa lỗi. |
| Lỗi chứng thư | Giờ hệ thống, SAN khớp origin, hạn chứng thư và CA tin cậy. Đối chiếu fingerprint; không bỏ qua xác minh TLS. |
| 401 | Phiên hết hạn/khóa nhân viên/đổi quyền; đăng nhập lại. Không phục hồi cookie cũ. |
| 403 | Kiểm vai trò, bác sĩ phân công, origin/CSRF/CIDR. Không cấp admin để lách lỗi nghiệp vụ. |
| 409 bệnh án | Tải bản mới, so nội dung và nhập lại phần cần giữ; không ghi đè version. |
| 409 thanh toán/kho | Xem công nợ/phiếu thu/tồn hiện tại. Không gửi một idempotency key với nội dung khác. |
| 503 hoặc mất kết nối khi thu | Kiểm tra PostgreSQL/khóa backup/dung lượng/dịch vụ. Đối soát khoản đã ghi trước khi gửi lại; trong cùng trang retry dùng lại khóa. |
| Backup lỗi | Kiểm PostgreSQL client, quyền đọc tệp, key32byte, dung lượng, log và lịch; bản chưa hoàn tất không được xuất bản như backup hợp lệ. Giữ bản tốt cũ. |
| Server mất điện | UPS, PostgreSQL tự phục hồi WAL khi khởi động. Kiểm status/log/dữ liệu và backup; không xóa WAL hay file DB để chữa lỗi. |
| Nghi mất/lộ dữ liệu | Ngắt quyền truy cập thiết bị/tài khoản liên quan, bảo toàn log và bản sao, báo đầu mối quản trị; đổi thông tin bí mật có liên quan và đánh giá phạm vi trước khi mở lại. |

## Nâng cấp và quay lui

Sao lưu và verify trước thay đổi schema/phụ thuộc. Dừng web, giữ bản mã/cấu hình trước, chạy migration bằng owner rồi cấp runtime grant. Chạy kiểm thử giả lập và smoke trước mở máy trạm. Version 1 là schema LAN đầu tiên, không có down migration; khi thay schema về sau phải thiết kế rollback. Quay lui sau migration bằng database restore riêng và bản mã phù hợp, không chỉ checkout code cũ trên database đã đổi. Không dùng cơ sở dữ liệu giả lập demo để thay database phòng khám.
