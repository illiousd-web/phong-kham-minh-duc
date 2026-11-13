# S1 — an toàn và vận hành

S1a (PR #21) xử lý mục 1 và 4 của kiểm toán; S1b tiếp tục các mục 2, 3, 5. Chưa làm đơn N/H thật hoặc S2.

## Đọc và ghi khi máy chủ bận

Đọc dùng MVCC. Xác thực đọc phiên và kiểm hạn tuyệt đối/20 phút không hoạt động trước khi cập nhật `last_seen` trong giao dịch ngắn riêng; cập nhật bận thì bỏ qua, không kéo dài hạn. Hỏi số đếm định kỳ vẫn không gia hạn phiên.

Giao dịch truy cập chỉ cho phép đọc và ghi ba bảng `sessions`, `login_attempts`, `audit_log`; không lấy khóa ghi chung, không được sửa dữ liệu nghiệp vụ. Các API đọc/in có audit dùng giao dịch này. Đăng nhập khóa riêng theo tên đăng nhập để giữ chính xác bộ đếm khóa đăng nhập. Chỉ bước lấy khóa tên đặt `lock_timeout` 250 ms, sau đó khôi phục giá trị cũ; tranh khóa trả 503 “Đang xử lý đăng nhập, thử lại”, `Retry-After: 1`, không tăng bộ đếm. Băm mật khẩu nằm ngoài khóa ghi nghiệp vụ; lúc ghi kiểm lại hash/salt để phát hiện đổi mật khẩu đồng thời.

Ghi nghiệp vụ vẫn kiểm dự phòng dung lượng, trả 507 khi thiếu. Khóa ghi nghiệp vụ chờ tối đa 5 giây; quá hạn trả 503 “Hệ thống đang bận, vui lòng thử lại”. Không đặt `lock_timeout` toàn cục cho khóa dòng/bảng. Sao lưu giữ riêng `BACKUP_LOCK_ID` độc quyền; mỗi giao dịch ghi giữ khóa này ở chế độ chia sẻ cho đến sau COMMIT và ghi tệp. Nếu sao lưu đang giữ khóa thì trả ngay 503 “Đang sao lưu, thử lại sau 1 giây” với `Retry-After: 1`. Nạp D0 dùng khóa danh mục riêng, không giữ khóa tuần tự hóa thu tiền/phiếu khám; cập nhật danh mục vẫn nguyên khối bằng MVCC và vẫn chịu khóa sao lưu. `api()` chỉ tự thử lại một lần sau `Retry-After` khi ghi JSON có `idempotency_key`; thao tác khác hiện nguyên thông báo máy chủ. Phiên và audit không sửa tệp đính kèm nên không phá tính nhất quán của bản sao lưu.

Khởi động dành riêng 8 MiB thật trong `logs/.access-reserve` trên ổ dữ liệu; khi trống dưới 8 MiB thì giải phóng tệp dự phòng để phiên/audit có chỗ ghi. Tệp này không chứa hồ sơ và không phải bản sao lưu. Dự phòng có giới hạn: quản trị vẫn phải giải phóng dung lượng khi có cảnh báo, không thể tiếp tục ghi nhật ký vô hạn trên ổ đầy. Cần đặt dữ liệu PostgreSQL và thư mục dữ liệu trên ổ đã giám sát khi nghiệm thu máy thật.

## Sao lưu bù

Windows dùng hai tác vụ: lịch hằng ngày 20:00 truyền `--daily`, luôn chạy kể cả giờ làm kéo tới 21:00; không dùng `StartWhenAvailable` cho tác vụ này. Tác vụ khởi động riêng, trễ hai phút, truyền `--catchup`. Chỉ chạy bù mới xét giờ làm mặc định 07:00–17:30 (giờ Việt Nam): hoãn tới lịch 20:00 nếu còn bản tốt trong 48 giờ; chưa có bản thành công hoặc quá 48 giờ thì chạy ngay. `--scheduled` cũ là bí danh của `--daily`, vì tác vụ cũ chính là lịch 20:00; không áp giờ làm cho cờ này. `CaiDat.ps1` và `CapNhat.ps1` gọi chung `Set-MinhDucBackupTasks`: chụp XML hai tác vụ được quản lý, xóa lịch cũ, đăng ký hai lịch mới, rồi đọc lại và kiểm action/trigger/giờ chạy. Nếu đăng ký hay kiểm tra lỗi thì khôi phục XML cũ và kiểm lại action, trigger, cài đặt và principal. Cập nhật tự thực hiện bước này sau thay mã/migration; không cần chạy lại bộ cài. Nếu phần cập nhật sau đó lỗi, lịch cũ cũng được khôi phục cùng đường quay về mã/CSDL. Dấu vân tay CSDL xét cả định nghĩa hàm, owner, SECURITY DEFINER, quyền hàm/bảng/cột để nhận thay đổi dù không thêm bảng/version; lỗi cập nhật sẽ không bỏ sót việc phục hồi CSDL. Sau restore không ACL, bước grant thu EXECUTE khỏi PUBLIC cho các trigger; không có hàm gộp đặc quyền để cấp lại.

Người hỗ trợ cấu hình `CLINIC_WORK_START`, `CLINIC_WORK_END` theo HH:MM trong môi trường tác vụ. Hỗ trợ ca qua nửa đêm. Lệnh sao lưu thủ công/cài đặt không bị hoãn. Không đổi quy tắc giữ bản tốt, kiểm giải mã, sao lưu tệp hay khôi phục.

## Bất biến PostgreSQL

Chủ CSDL chạy migration 12 trong cùng giao dịch, sau đó áp dụng `deploy/postgresql-roles.sql`. Vai trò web không sở hữu bảng, không superuser/CREATEDB/CREATEROLE/BYPASSRLS và không có CREATE schema. Web từ chối khởi động nếu chưa có migration 12.

Trigger bảo vệ đơn đã khóa/hủy, dòng đơn, snapshot phiếu xét nghiệm đã duyệt, kết quả chỉ số và outbox. Đơn khóa chỉ đổi sang hủy có lý do, thời điểm và phiên bản kế tiếp; snapshot/các thông tin khác giữ nguyên. Gộp thuốc chỉ sửa danh mục `drugs`: nguồn trỏ `merged_into` sang đích, ngừng dùng nguồn và gộp cờ độc/kiểm soát sang đích. Không sửa bất kỳ dòng đơn nào khi gộp. Dòng đã khóa giữ `drug_id` gốc vĩnh viễn; nội dung/snapshot không đổi. `current_drug(c, id)` là hàm dùng chung tra chuỗi gộp, có tập mã đã thăm để chặn vòng lặp/mã mất. Kiểm cờ khi khóa, xếp thuốc độc và lưu lại dòng nháp đều dùng hàm này. Khi bác sĩ lưu lại nháp, dòng có thể liên kết mã cuối chuỗi; gộp không tự thay dòng nháp hay dòng khóa.

Không còn SECURITY DEFINER gộp thuốc, ngữ cảnh bảng tạm hay quyền EXECUTE hàm gộp. Migration xóa hàm cũ và thay guard: mọi UPDATE/DELETE dòng thuộc đơn không còn nháp (hoặc đã có snapshot) đều bị chặn, kể cả owner; không có ngoại lệ. API quản trị thực hiện gộp/audit trong cùng giao dịch với người dùng HTTP đã xác thực. Runtime vẫn không có UPDATE trực tiếp ở bảng/cột dòng đơn. Migration chạy lại cũng cập nhật hàm trigger của bản S1a đã cài. Phiếu M5 điều chỉnh tạo hàng mới có `replaces_id`; bản cũ giữ `approved` và snapshot nguyên trạng, không đổi CHECK trạng thái chỉ để thêm chữ `superseded`. Đây là cách biểu diễn thay thế hiện có của M5.

Outbox chỉ cho cập nhật cột trạng thái, và trigger chỉ cho hủy sau khi đơn bị hủy; không cho sửa payload/xóa/TRUNCATE. Các dòng đơn nháp dùng SELECT/INSERT/DELETE, không có UPDATE trực tiếp; trigger khóa khi duyệt/khóa. Hàm trigger cố định search_path để bảng tạm không che bảng thật.

Trước nâng cấp phải sao lưu đã xác minh. Nếu nâng cấp lỗi, dùng quy trình khôi phục bản sao lưu sang CSDL riêng và kiểm lại trước chuyển dịch vụ; không tắt trigger để sửa hồ sơ đã duyệt.

## S1b — kiểm đơn thuốc và kết quả chữ (PR #22)

Nhánh S1b đã merge main sau khi S1a được chủ dự án merge. Chạy test liên quan xung đột cục bộ; CI kiểm toàn bộ, gồm M6 cùng trigger bất biến.

Khóa M6 yêu cầu số lượng, liều và tần suất dương; số ngày nguyên 1–30; hàm lượng và thời điểm dùng; đơn vị liều. Ô đơn vị liều mới được để trống để dùng đơn vị thuốc đã nhập (tương thích dòng cũ), bản in luôn ghép đơn vị với liều. Dòng nháp vẫn lưu thông tin chưa đủ. Số lượng lệch trên 20% yêu cầu xác nhận và lý do ít nhất 8 ký tự; đơn vị lỏng/ống/chai/lọ/tuýp/gói chỉ cảnh báo. Lưu xác nhận trong nội dung dòng và audit đã che chuỗi giấy tờ.

Migration 13 nạp đúng hai CSV TT18 được chủ dự án cung cấp, kiểm SHA/số dòng trước DDL. Ghi nguồn, ngày, phiên bản và số dòng vào sổ nạp. Dược chất và alias ở hai bảng mới; tách tên gọi cùng ô nguồn theo dấu `;` hoặc `/`, giữ nguyên ô nguồn trong JSON. Khóa so không dấu/hoa thường; chuẩn hóa dấu phân cách trong tên, sinh alias bỏ E/INE→IN. Quản trị thêm alias có nhật ký và tự rà lại cờ thuốc, không tự bỏ cờ đã khai.

Thuốc đơn thành phần trùng danh mục bị chặn N/H; phối hợp cần hàm lượng **từng hoạt chất cùng thứ tự**, ngăn bằng `+`, ví dụ `10 mg + 5 mg` tương ứng hai hoạt chất. Chỉ so ngưỡng mg/đơn vị chia liều khi xác định chắc chắn; giữ cả ngưỡng nồng độ gốc để đối chiếu, chưa tự suy đổi từ mg/ml hay phần trăm sang đơn vị chia liều. Không xác định được hoặc không có ngưỡng thì chặn. Tên gần giống chỉ cảnh báo và cần bác sĩ xác nhận có lý do. Phối hợp dưới ngưỡng có nhãn trong nội dung/in/snapshot. Cờ danh mục được gắn theo dược chất dù một phối hợp đủ điều kiện được kê; không dùng việc thiếu cờ thủ công để bỏ kiểm tra hoạt chất.

Migration 14 thêm `order_result_versions`, bảo toàn kết quả chữ cũ. API gửi kết quả bắt buộc `version`; bản đầu version 0, mỗi lần gửi thành phiên bản mới, sai phiên bản trả 409. Bác sĩ chỉ xem các phiên bản đã duyệt; kỹ thuật viên xem lịch sử đã gửi. Duyệt lưu snapshot của phiên bản hiện tại; nội dung các phiên bản không sửa/xóa được qua API, PostgreSQL có trigger và giới hạn quyền cập nhật cột duyệt. Chỉ định đã có kết quả duyệt bị chặn cả lúc xin hủy và khi quản lý duyệt yêu cầu cũ; thông báo dùng giảm phí nếu cần bỏ phí. Không đổi phép tính tiền hay luồng duyệt giảm phí hiện có.

Các kiểm thử cũ tiếp tục giữ nguyên assertion nghiệp vụ; dữ liệu thử được bổ sung trường version, hàm lượng/thời điểm và xác nhận số lượng nhập tay nay bắt buộc. Không nới quy tắc xác nhận, cảnh báo hoặc quyền để giữ test cũ xanh.

Chưa làm: đơn N/H thật, S2, ký số/liên thông, suy diễn hàm lượng không xác định, nghiệm thu máy Windows thật và máy in.

Kiểm lệch số lượng tính độc lập với giới hạn tự điền của nháp; vượt giới hạn tự điền không được bỏ qua xác nhận. Khi đổi đơn vị hàm lượng TT18, giữ đủ độ chính xác đầu vào, không làm tròn giá trị vượt ngưỡng xuống ngưỡng. Hai biên này có test FAIL trước sửa và PASS sau sửa.

## Đo giữ khóa trên C5 giả lập

Lệnh: `CLINIC_PERF_SOURCE_DATABASE_URL=<PostgreSQL cục bộ /postgres> python -m scripts.do_khoa_ghi_s1 --output test_evidence/s1-write-lock-c5.json`. Công cụ chỉ tạo CSDL C5 mới có tên ngẫu nhiên, từ chối dùng CSDL có sẵn và xóa CSDL đo khi xong. Đo qua API thật, từ lúc lấy được khóa đến sau COMMIT, không tính chờ khóa/parse tệp/mạng. Không cài đo đạc vào mã chạy dịch vụ.

Đo tại head `dc4fd2b` trước lượt sửa definer/lịch cập nhật, ngày 12/11/2026, Linux cục bộ, PostgreSQL 17; C5: 20.000 người bệnh, 22.000 lượt, 88.000 chỉ định, 546.543 audit, 2.000 tệp giả lập. Mỗi thao tác 20 mẫu; chưa đại diện Windows/i3 hay tải phòng khám thật.

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
- PR #21 đã merge; PR #22 nhận main bằng merge. Chỉ chạy kiểm liên quan xung đột cục bộ, để CI kiểm toàn bộ, đặc biệt khóa đơn M6 với trigger S1a.

## Kết luận quay lui cập nhật

`Invoke-QuayVe` kiểm riêng việc dừng dịch vụ, trả mã nguồn (đối chiếu SHA-256 các tệp), trả venv (kiểm trình Python chạy được), phục hồi CSDL/tệp (mã trả về và dấu vân tay), phục hồi lịch và khởi động bản cũ (trạng thái dịch vụ và Wait-Https). Bước độc lập vẫn được thử sau khi bước khác lỗi; danh sách lỗi giữ trong `rollback_errors` và cuối hàm throw nếu còn bất kỳ lỗi nào. Mã/Python/CSDL chưa đạt thì giữ dịch vụ dừng.

Chỉ ghi `da_quay_ve` khi tất cả bước đạt và HTTPS bản cũ lên. Nếu không, ghi `quay_ve_that_bai`, trả mã khác 0 và nêu các bước lỗi; không báo đã khôi phục thành công. Phải có dấu vân tay trước cập nhật, nếu không thì dừng trước khi thay mã/dữ liệu. Windows E2E chèn lỗi CLI rollback trả 23 và lỗi bản cũ không khởi động, trên VM giả lập riêng.
