# S1 — an toàn và vận hành

S1a (PR #21) xử lý mục 1 và 4 của kiểm toán; S1b tiếp tục các mục 2, 3, 5. Chưa làm đơn N/H thật hoặc S2.

## Đọc và ghi khi máy chủ bận

Đọc dùng MVCC. Xác thực đọc phiên và kiểm hạn tuyệt đối/20 phút không hoạt động trước khi cập nhật `last_seen` trong giao dịch ngắn riêng; cập nhật bận thì bỏ qua, không kéo dài hạn. Hỏi số đếm định kỳ vẫn không gia hạn phiên.

Giao dịch truy cập chỉ cho phép đọc và ghi ba bảng `sessions`, `login_attempts`, `audit_log`; không lấy khóa ghi chung, không được sửa dữ liệu nghiệp vụ. Các API đọc/in có audit dùng giao dịch này. Đăng nhập khóa riêng theo tên đăng nhập để giữ chính xác bộ đếm khóa đăng nhập. Băm mật khẩu nằm ngoài khóa ghi nghiệp vụ; lúc ghi kiểm lại hash/salt để phát hiện đổi mật khẩu đồng thời.

Ghi nghiệp vụ vẫn kiểm dự phòng dung lượng, trả 507 khi thiếu. Chờ khóa ghi tối đa 250 ms rồi trả 503 với `Retry-After: 1`; thông báo đề nghị thử lại sau một giây. Khóa sao lưu và cách chụp CSDL/tệp không đổi. Phiên và audit không sửa tệp đính kèm nên không phá tính nhất quán của bản sao lưu.

Khởi động dành riêng 8 MiB thật trong `logs/.access-reserve` trên ổ dữ liệu; khi trống dưới 8 MiB thì giải phóng tệp dự phòng để phiên/audit có chỗ ghi. Tệp này không chứa hồ sơ và không phải bản sao lưu. Dự phòng có giới hạn: quản trị vẫn phải giải phóng dung lượng khi có cảnh báo, không thể tiếp tục ghi nhật ký vô hạn trên ổ đầy. Cần đặt dữ liệu PostgreSQL và thư mục dữ liệu trên ổ đã giám sát khi nghiệm thu máy thật.

## Sao lưu bù

Tác vụ Windows thêm `--scheduled`. Trong giờ làm mặc định 07:00–17:30 (giờ Việt Nam), hoãn chạy bù tới lịch 20:00; nếu chưa có bản thành công hoặc quá 48 giờ thì vẫn chạy để bảo vệ dữ liệu. Người hỗ trợ cấu hình `CLINIC_WORK_START`, `CLINIC_WORK_END` theo HH:MM trong môi trường tác vụ. Hỗ trợ ca qua nửa đêm. Lệnh sao lưu thủ công/cài đặt không bị hoãn. Không đổi quy tắc giữ bản tốt, kiểm giải mã, sao lưu tệp hay khôi phục.

## Bất biến PostgreSQL

Chủ CSDL chạy migration 12 trong cùng giao dịch, sau đó áp dụng `deploy/postgresql-roles.sql`. Vai trò web không sở hữu bảng, không superuser/CREATEDB/CREATEROLE/BYPASSRLS và không có CREATE schema. Web từ chối khởi động nếu chưa có migration 12.

Trigger bảo vệ đơn đã khóa/hủy, dòng đơn, snapshot phiếu xét nghiệm đã duyệt, kết quả chỉ số và outbox. Đơn khóa chỉ đổi sang hủy có lý do, thời điểm và phiên bản kế tiếp; snapshot/các thông tin khác giữ nguyên. Gộp thuốc được đổi FK danh mục của dòng đơn nhưng không được đổi nội dung đã in. Phiếu M5 điều chỉnh tạo hàng mới có `replaces_id`; bản cũ giữ `approved` và snapshot nguyên trạng, không đổi CHECK trạng thái chỉ để thêm chữ `superseded`. Đây là cách biểu diễn thay thế hiện có của M5.

Outbox chỉ cho cập nhật cột trạng thái, và trigger chỉ cho hủy sau khi đơn bị hủy; không cho sửa payload/xóa/TRUNCATE. Các bảng nháp vẫn cần CRUD cho quy trình đã có; trigger khóa khi duyệt/khóa. Hàm trigger cố định search_path để bảng tạm không che bảng thật.

Trước nâng cấp phải sao lưu đã xác minh. Nếu nâng cấp lỗi, dùng quy trình khôi phục bản sao lưu sang CSDL riêng và kiểm lại trước chuyển dịch vụ; không tắt trigger để sửa hồ sơ đã duyệt.
