# S2a — Dị ứng nhà thuốc, lượt hôm nay, thông tin phòng khám và ảnh chữ ký

- Nhà thuốc nhận `patient_allergies` qua danh sách đơn thuốc hiện có. Dải đỏ nằm ngay dưới tên người bệnh, trước danh sách thuốc; hàng chờ có nhãn Dị ứng, hộp xác nhận cấp thuốc nhắc lại nội dung. Giá trị chưa khai thác hoặc “Không dị ứng” không hiện cảnh báo đỏ. Không mở hồ sơ người bệnh cho dược; phản hồi đơn thuốc của bác sĩ không thêm trường.
- Quản lý xem Lượt hôm nay từ `total` của `/api/manager/visits`, lọc cả hai ngày theo Asia/Ho_Chi_Minh. Không dùng số dòng của trang; Doanh thu hôm nay giữ dấu —.
- Quản trị vào **Cài đặt → Thông tin phòng khám** để nhập tên, cơ quan chủ quản, địa chỉ, điện thoại và email. Chín mẫu Word/PDF trong `forms.py` dùng thông tin đã nhập; khi hoàn toàn chưa khai báo, giữ phần đầu mẫu cũ. Nếu chỉ nhập một phần thì in những trường đã nhập.
- **Cài đặt → Ảnh chữ ký**: chọn tài khoản, tải ảnh PNG/JPG tối đa 300 × 1024 byte. Máy chủ kiểm tra nội dung ảnh, không tin tên tệp hay MIME do trình duyệt gửi; tối đa 4 triệu điểm ảnh. Có nút xem ảnh tài khoản đã chọn.
- Ảnh nằm trong `user_signatures.image` (SQLite BLOB / PostgreSQL BYTEA), cùng CSDL được sao lưu. Không lưu ảnh trong thư mục mã nguồn, không có đường dẫn ảnh tĩnh hay API liệt kê chữ ký. Chỉ quản trị tải lên; chỉ chính chủ và quản trị đọc từng ảnh. Mỗi lần tải lên ghi người tải, thời điểm và audit SHA-256 trước/sau trong cùng giao dịch. Phản hồi ảnh có `Cache-Control: no-store` và `nosniff`.
- **Chờ S2b**: chưa chèn ảnh chữ ký vào phiếu in, chưa thay đổi luồng ký.

## Migration 15 và quay lui

Sao lưu và kiểm bản sao trước nâng cấp. Không cần đổi cấu hình hoặc `deploy/`.

- PostgreSQL: chạy lệnh nâng cấp hiện có `python -m scripts.manage migrate` bằng tài khoản chủ CSDL. Tiến trình web yêu cầu migration 15; không tự chạy DDL khi khởi động LAN.
- SQLite demo: tự nâng cấp khi khởi tạo; cũng có thể chạy `python -m app.s2a_migration --sqlite DUONG_DAN_CSDL` khi ứng dụng đã dừng.
- Quay lui PostgreSQL khi chưa nhập dữ liệu S2a: dừng ứng dụng, chạy `python -m scripts.manage rollback-s2a`, rồi dùng mã trước S2a.
- Quay lui SQLite khi chưa nhập dữ liệu S2a: dừng ứng dụng, chạy `python -m app.s2a_migration --sqlite DUONG_DAN_CSDL --down`, rồi dùng mã trước S2a.
- Migration lên/xuống nằm trong một giao dịch và chạy lại được. Lệnh xuống từ chối nếu thông tin phòng khám có trường khác rỗng hoặc đã có ảnh chữ ký. Khi đó muốn quay về cả mã và dữ liệu cũ phải khôi phục bản sao trước nâng cấp; không xóa thông tin/chữ ký để ép lệnh xuống chạy.

Kiểm thử mới dùng tên giả lập, email `.invalid`, ảnh tạo trong bộ nhớ hoặc thư mục tạm. Không đưa thông tin phòng khám thật hoặc ảnh chữ ký vào Git.
