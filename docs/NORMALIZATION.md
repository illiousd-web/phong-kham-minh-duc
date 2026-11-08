# Chuẩn hóa mã nguồn v0.3.1

Nguồn: Phan_mem_Phong_kham_Minh_Duc_v0.3.1_Sua_khoi_dong_Windows.zip.
SHA-256: a4c50f4d4da3d1facfbc3ac8b3a3a265816927b42a8e7a023d2ea79c2defe74e.

Bỏ lớp thư mục MinhDuc_Clinic_v0.3 để phát triển tại gốc repository. Giữ app, tests, scripts, schema, tài liệu, logo và toàn bộ các bản biểu mẫu. Không nhập ảnh/PDF bằng chứng thử nghiệm từ ZIP. Các tệp nhị phân được đối chiếu nguyên vẹn trong assets-v031.sha256.

ZIP gốc được gỡ khỏi đầu nhánh vì chứa mật khẩu demo cố định và kết quả thử nghiệm; bản lịch sử vẫn tồn tại trong commit nguồn. Đây không phải thao tác xóa lịch sử hay thu hồi mật khẩu đã công khai. Không tái sử dụng mật khẩu cũ. Bản đối chiếu cục bộ nằm ngoài checkout.

Thay mật khẩu cố định bằng DEMO_PASSWORD; trình khởi động hỏi kín nếu chưa đặt biến. Không lưu mật khẩu. Các kiểm thử tạo mật khẩu ngẫu nhiên riêng cho phiên chạy. Mật khẩu của tài khoản đã tạo không tự đổi khi đổi biến môi trường.

Kiểm thử API: 36 đạt trên Python 3.12. Chromium: luồng tiếp đón, khám, chỉ định, duyệt kết quả, đơn nháp, thu tiền, quản lý; tải PDF; desktop/mobile; không có lỗi JavaScript. Kiểm thử thu tiền kiểm tra trạng thái số tiền trên giao diện thay vì chờ thông báo thoáng qua. Cảnh báo còn lại: Starlette cảnh báo cơ chế TestClient/httpx sẽ thay đổi.

Chưa kiểm tra trực tiếp Windows; các tệp .bat cần xác minh trên Windows. Chưa triển khai LAN, chưa dùng dữ liệu bệnh nhân thật. Không thay đổi nghiệp vụ trong lần chuẩn hóa này.
