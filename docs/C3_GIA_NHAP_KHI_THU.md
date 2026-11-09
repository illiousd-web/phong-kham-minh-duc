# C3 — Nhập bảng giá và giá nhập khi thu

Hướng dẫn điền tệp và thao tác nằm trong [Hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md#nhập-bảng-giá-dịch-vụ-từ-excel).

Tệp tổng hợp được đối chiếu có 288 dịch vụ, đủ mã, không trùng tên: 5 Khám, 239 Xét nghiệm, 17 Siêu âm, 23 X-quang, 1 Điện tim, 3 Thủ thuật. Bốn mã để trống giá là KB005, TT001, TT002, TT003. Không đổi tên hoặc tự đặt giá cho các dòng này. Chỉ đọc trang BANG_GIA; CAN_XEM_LAI và hai cột tham khảo là ghi chú. Tệp mẫu tải từ ứng dụng vẫn có một trang tính và bốn cột.

## Quy tắc tiền và phân quyền

- Giá trống bật cờ `service_catalog.price_at_collection`. Giá 0 không bật cờ. Giá nhập tay lần đầu là số nguyên lớn hơn 0, tối đa 2 tỷ đồng và bắt buộc có nội dung cụ thể.
- Khoản phải thu và chỉ định lưu giá tại thời điểm phát sinh; `NULL` biểu thị chưa có giá, tách biệt với 0. Giá nhập tay lưu riêng, không ghi đè khoản gốc. Đổi bảng giá hoặc đổi cách tính giá của dịch vụ chỉ tác động khoản mới, kể cả khi chỉ định cũ còn nháp.
- Bác sĩ và điều dưỡng được phân công lập chỉ định; điều dưỡng vẫn không đọc bệnh án đầy đủ hoặc công nợ. Chỉ thu ngân/quản lý nhập giá. Quản trị đơn thuần, lễ tân, bác sĩ, kỹ thuật viên không được nhập giá.
- Còn khoản chưa có giá thì trạng thái thanh toán là CHƯA CÓ GIÁ, số còn phải thu cuối là `null`; số tiền đã biết được báo riêng. Thu tạm là giao dịch có `prepayment=true`; không coi đó là thu đủ hay hết nợ. Hàng chờ vẫn tính lượt này.
- API in phiếu thu mặc định từ chối khi còn khoản chưa có giá. Chỉ yêu cầu `provisional=true` mới in **PHIẾU THU TẠM**. Không duyệt hoàn tiền trả thừa khi chưa xác định đủ giá.
- Sửa giá nhập tay phải lập đề nghị. Chỉ quản lý khác người đề nghị được duyệt; không dùng API sửa giá trực tiếp để bỏ qua bước này. Nhật ký và báo cáo ngày giữ cả lần nhập đầu và từng lần sửa đã duyệt. Báo cáo dùng ngày Việt Nam, không cắt ở 100 dòng.

## Nâng cấp và quay lui

Migration phiên bản 4 chạy trong bước migrate hiện có của bộ cập nhật. Không chạy DDL khi máy chủ LAN khởi động. Cần áp dụng lại quyền ứng dụng bằng bước grant hiện có sau migration.

Thay đổi gồm cờ giá nhập khi thu; cho phép NULL ở số tiền khoản phải thu và hai bản chụp giá chỉ định; bổ sung nhóm Thủ thuật; bảng giá nhập tay và đề nghị sửa; cập nhật view tính công nợ. Các giá trị cũ giữ nguyên. PostgreSQL dùng một giao dịch của tài khoản chủ CSDL với khóa advisory. SQLite thử nghiệm dùng một giao dịch dựng lại các bảng cần đổi và kiểm toàn bộ khóa ngoại trước khi commit.

Trước cập nhật phải có bản sao lưu đã kiểm theo quy trình hiện có. Nếu cần quay lui migration bằng tài khoản chủ CSDL trong môi trường LAN đã cấu hình:

```text
python -m scripts.manage rollback-manual-prices
```

Lệnh chỉ quay lui khi **chưa có dữ liệu của chức năng mới**. Có cờ giá nhập khi thu, khoản/chỉ định chưa có giá, nhóm mới hoặc lịch sử giá nhập tay thì lệnh dừng, giữ nguyên dữ liệu; không đổi NULL thành 0 hoặc xóa lịch sử để quay lui. Khi đó dùng bản sao lưu trước nâng cấp theo quy trình khôi phục hiện có và đối soát phần phát sinh sau bản sao lưu trước khi thực hiện. Sau quay lui chỉ chạy mã ứng dụng cũ tương ứng. Chạy lại migrate sẽ nâng lên phiên bản 4.

Các bài kiểm migration SQLite/PostgreSQL kiểm chạy lên, chạy lặp lại, quay lui, lỗi giữa chừng, giữ dữ liệu cũ và từ chối quay lui có thể mất dữ liệu. Các bài API/trình duyệt C3 kiểm chỉ định, chưa có giá, thu tạm, nhập giá, thu đủ, đề nghị sửa, duyệt, quyền, báo cáo ngày và bố cục 390px. Job Chromium 109 chạy cùng luồng trình duyệt này.
