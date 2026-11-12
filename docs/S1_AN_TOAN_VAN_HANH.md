# S1 — an toàn và vận hành

S1a (PR #21) xử lý mục 1 và 4 của kiểm toán; S1b tiếp tục các mục 2, 3, 5. Chưa làm đơn N/H thật hoặc S2.

## Đọc và ghi khi máy chủ bận

Đọc dùng MVCC. Xác thực đọc phiên và kiểm hạn tuyệt đối/20 phút không hoạt động trước khi cập nhật `last_seen` trong giao dịch ngắn riêng; cập nhật bận thì bỏ qua, không kéo dài hạn. Hỏi số đếm định kỳ vẫn không gia hạn phiên.

Giao dịch truy cập chỉ cho phép đọc và ghi ba bảng `sessions`, `login_attempts`, `audit_log`; không lấy khóa ghi chung, không được sửa dữ liệu nghiệp vụ. Các API đọc/in có audit dùng giao dịch này. Đăng nhập khóa riêng theo tên đăng nhập để giữ chính xác bộ đếm khóa đăng nhập. Chỉ bước lấy khóa tên đặt `lock_timeout` 250 ms, sau đó khôi phục giá trị cũ; tranh khóa trả 503 “Đang xử lý đăng nhập, thử lại”, `Retry-After: 1`, không tăng bộ đếm. Băm mật khẩu nằm ngoài khóa ghi nghiệp vụ; lúc ghi kiểm lại hash/salt để phát hiện đổi mật khẩu đồng thời.

Ghi nghiệp vụ vẫn kiểm dự phòng dung lượng, trả 507 khi thiếu. Khóa ghi nghiệp vụ chờ tối đa 5 giây; quá hạn trả 503 “Hệ thống đang bận, vui lòng thử lại”. Không đặt `lock_timeout` toàn cục cho khóa dòng/bảng. Sao lưu giữ riêng `BACKUP_LOCK_ID` độc quyền; mỗi giao dịch ghi giữ khóa này ở chế độ chia sẻ cho đến sau COMMIT và ghi tệp. Nếu sao lưu đang giữ khóa thì trả ngay 503 “Đang sao lưu, thử lại sau 1 giây” với `Retry-After: 1`. Nạp D0 dùng khóa danh mục riêng, không giữ khóa tuần tự hóa thu tiền/phiếu khám; cập nhật danh mục vẫn nguyên khối bằng MVCC và vẫn chịu khóa sao lưu. `api()` chỉ tự thử lại một lần sau `Retry-After` khi ghi JSON có `idempotency_key`; thao tác khác hiện nguyên thông báo máy chủ. Phiên và audit không sửa tệp đính kèm nên không phá tính nhất quán của bản sao lưu.

Khởi động dành riêng 8 MiB thật trong `logs/.access-reserve` trên ổ dữ liệu; khi trống dưới 8 MiB thì giải phóng tệp dự phòng để phiên/audit có chỗ ghi. Tệp này không chứa hồ sơ và không phải bản sao lưu. Dự phòng có giới hạn: quản trị vẫn phải giải phóng dung lượng khi có cảnh báo, không thể tiếp tục ghi nhật ký vô hạn trên ổ đầy. Cần đặt dữ liệu PostgreSQL và thư mục dữ liệu trên ổ đã giám sát khi nghiệm thu máy thật.

## Sao lưu bù

Windows dùng hai tác vụ: lịch hằng ngày 20:00 truyền `--daily`, luôn chạy kể cả giờ làm kéo tới 21:00; không dùng `StartWhenAvailable` cho tác vụ này. Tác vụ khởi động riêng, trễ hai phút, truyền `--catchup`. Chỉ chạy bù mới xét giờ làm mặc định 07:00–17:30 (giờ Việt Nam): hoãn tới lịch 20:00 nếu còn bản tốt trong 48 giờ; chưa có bản thành công hoặc quá 48 giờ thì chạy ngay. `--scheduled` cũ là bí danh của `--daily`, vì tác vụ cũ chính là lịch 20:00; không áp giờ làm cho cờ này. `CaiDat.ps1` và `CapNhat.ps1` gọi chung `Set-MinhDucBackupTasks`: chụp XML hai tác vụ được quản lý, xóa lịch cũ, đăng ký hai lịch mới, rồi đọc lại và kiểm action/trigger/giờ chạy. Nếu đăng ký hay kiểm tra lỗi thì khôi phục XML cũ và kiểm lại action, trigger, cài đặt và principal. Cập nhật tự thực hiện bước này sau thay mã/migration; không cần chạy lại bộ cài. Nếu phần cập nhật sau đó lỗi, lịch cũ cũng được khôi phục cùng đường quay về mã/CSDL.

Người hỗ trợ cấu hình `CLINIC_WORK_START`, `CLINIC_WORK_END` theo HH:MM trong môi trường tác vụ. Hỗ trợ ca qua nửa đêm. Lệnh sao lưu thủ công/cài đặt không bị hoãn. Không đổi quy tắc giữ bản tốt, kiểm giải mã, sao lưu tệp hay khôi phục.

## Bất biến PostgreSQL

Chủ CSDL chạy migration 12 trong cùng giao dịch, sau đó áp dụng `deploy/postgresql-roles.sql`. Vai trò web không sở hữu bảng, không superuser/CREATEDB/CREATEROLE/BYPASSRLS và không có CREATE schema. Web từ chối khởi động nếu chưa có migration 12.

Trigger bảo vệ đơn đã khóa/hủy, dòng đơn, snapshot phiếu xét nghiệm đã duyệt, kết quả chỉ số và outbox. Đơn khóa chỉ đổi sang hủy có lý do, thời điểm và phiên bản kế tiếp; snapshot/các thông tin khác giữ nguyên. Gộp thuốc qua `public.clinic_merge_drug(from_id, to_id, actor, reason)` SECURITY DEFINER do owner/migration sở hữu, search_path cố định. Hàm kiểm người gộp là quản trị đang hoạt động và điều kiện hai thuốc, tự cập nhật danh mục/liên kết và ghi audit trong cùng giao dịch. Runtime không có UPDATE ở bảng hay bất kỳ cột nào của dòng đơn; chỉ được EXECUTE hàm gộp. Trigger kiểm current_user là table owner và cặp nguồn–đích đúng trong bảng TEMP ngữ cảnh do owner tạo riêng trong lần gọi, ACL không cấp runtime; ngữ cảnh bị xóa khi hàm xong hoặc rollback. Hàm từ chối bảng tạm có sẵn, tránh tin đối tượng do caller tạo. Không dùng biến phiên làm chứng cứ. Nội dung/snapshot đơn cũ bất biến. Xác nhận dị ứng được ghi bằng thay hàng khi còn nháp, giữ nguyên ID, không cấp lại UPDATE cho runtime. Migration chạy lại cũng cập nhật hàm trigger của bản S1a đã cài. Phiếu M5 điều chỉnh tạo hàng mới có `replaces_id`; bản cũ giữ `approved` và snapshot nguyên trạng, không đổi CHECK trạng thái chỉ để thêm chữ `superseded`. Đây là cách biểu diễn thay thế hiện có của M5.

Outbox chỉ cho cập nhật cột trạng thái, và trigger chỉ cho hủy sau khi đơn bị hủy; không cho sửa payload/xóa/TRUNCATE. Các dòng đơn nháp dùng SELECT/INSERT/DELETE, không có UPDATE trực tiếp; trigger khóa khi duyệt/khóa. Hàm trigger cố định search_path để bảng tạm không che bảng thật.

Trước nâng cấp phải sao lưu đã xác minh. Nếu nâng cấp lỗi, dùng quy trình khôi phục bản sao lưu sang CSDL riêng và kiểm lại trước chuyển dịch vụ; không tắt trigger để sửa hồ sơ đã duyệt.

## Đo giữ khóa trên C5 giả lập

Lệnh: `CLINIC_PERF_SOURCE_DATABASE_URL=<PostgreSQL cục bộ /postgres> python -m scripts.do_khoa_ghi_s1 --output test_evidence/s1-write-lock-c5.json`. Công cụ chỉ tạo CSDL C5 mới có tên ngẫu nhiên, từ chối dùng CSDL có sẵn và xóa CSDL đo khi xong. Đo qua API thật, từ lúc lấy được khóa đến sau COMMIT, không tính chờ khóa/parse tệp/mạng. Không cài đo đạc vào mã chạy dịch vụ.

Ngày 12/11/2026, Linux cục bộ, PostgreSQL 17; C5: 20.000 người bệnh, 22.000 lượt, 88.000 chỉ định, 546.543 audit, 2.000 tệp giả lập. Mỗi thao tác 20 mẫu; chưa đại diện Windows/i3 hay tải phòng khám thật.

| Thao tác | p50 (ms) | p95 (ms) |
|---|---:|---:|
| Lưu phiếu khám | 3,095 | 4,623 |
| Thu tiền | 4,628 | 9,345 |
| Khóa đơn M6 | 5,583 | 9,175 |
| Nạp ICD-10 15.844 mã (khóa danh mục riêng) | 4.902,663 | 5.454,280 |

Nạp ICD-10 có thể giữ giao dịch hơn 5 giây nên không dùng khóa ghi nghiệp vụ. Test đồng thời giữ giao dịch nhập đang mở và vẫn lưu phiếu khám thành công.

## Giới hạn nghiệm thu

- Đầy ổ được thử bằng giả lập `monkeypatch` số byte trống; chưa làm đầy dung lượng thật hay WAL PostgreSQL.
- Chưa thử `pg_dump` đồng thời với ghi nghiệp vụ. Test mới kiểm khóa sao lưu thật và tranh chấp giao dịch; không coi là nghiệm thu bản dump trong tải ghi đồng thời.
- Dự phòng 8 MiB ở `logs/.access-reserve` chưa chắc cùng phân vùng với thư mục dữ liệu PostgreSQL; giải phóng tệp này không bảo đảm PostgreSQL có thêm dung lượng nếu nằm khác phân vùng. Phải kiểm và giám sát cả hai phân vùng trên máy thật.
- Số đo giữ khóa là Linux với dữ liệu C5 giả lập, chưa thay thế nghiệm thu Windows i3/8 GB, SSD và máy in thật.
- PR #22 vẫn Draft dựa trên S1a. Chỉ sau khi chủ dự án merge #21 mới rebase #22 lên main mới và chạy lại toàn bộ, đặc biệt khóa đơn M6 với trigger S1a.
