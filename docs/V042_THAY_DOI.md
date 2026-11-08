# Minh Đức v0.4.2 – Hoàn thiện bốn quy trình A–D (bản thử nghiệm)

Ngày tạo: 09/11/2026. Nguồn: bản `phong-kham-minh-duc-v0.4.1.zip` người dùng cung cấp. Đây là bản thay đổi độc lập, **chưa được nghiệm thu sử dụng với bệnh nhân thật**.

## Chức năng mới

**A – Chỉ định cận lâm sàng và khoản phải thu**

- Quản lý tạo dịch vụ trong danh mục với loại `lab/ultrasound/xray/ecg` và giá bán dương.
- Bác sĩ chỉ định theo ID dịch vụ; máy chủ kiểm tra loại, giá, quyền bác sĩ, lượt khám chưa kết thúc; ghi chỉ định + khoản thu + liên kết nguồn trong **một transaction**.
- Trong chế độ LAN, bắt buộc `service_id` và `request_key` (ít nhất 8 ký tự); gửi lại cùng `request_key` và cùng payload chỉ trả kết quả đã lưu, không thu trùng. Gửi lại cùng mã với payload khác trả 409. Demo SQLite vẫn cho phép chỉ định văn bản không giá để giữ các bài kiểm thử cũ, không sử dụng đường này cho LAN.
- Bác sĩ đề nghị hủy bằng lý do; quản lý phê duyệt. Không xóa khoản thu gốc, ghi riêng `charge_voids` và `order_cancel_requests`, bảng kê hiển thị trạng thái bị hủy. Nếu đã thu tiền, khoản thu thừa được đối soát và hoàn theo quy trình phê duyệt riêng, **không tự chuyển tiền**.

**B – Đơn thuốc, lô kho và thu ngân**

- Đơn thuốc LAN bắt buộc các dòng `{medicine_id,quantity,directions}` liên kết danh mục thuốc; bác sĩ phải lưu chẩn đoán trước. Mỗi lượt chỉ có một đơn nháp theo cấu trúc hiện có.
- Quản lý hoặc quản trị gán giá cho từng đơn vị cơ sở của thuốc; không cho nhân viên nhà thuốc tự đặt giá. Không hỗ trợ thuốc phải kiểm soát đặc biệt.
- Nhà thuốc xác nhận cấp phát **một lần**, kiểm tồn, cách ly và hạn dùng, xuất theo FEFO, ghi chi tiết lô, xuất kho và phí thuốc vào cùng transaction. Nếu một dòng thiếu giá hoặc thiếu thuốc, tất cả rollback. Thu ngân tiếp tục thu tiền qua quỹ chung; xuất thuốc **không đồng nghĩa đã nhận tiền**.
- Quy đổi hộp/vỉ, hoàn trả thuốc, hóa đơn điện tử, thuế và đơn thuốc ký số chưa được xây dựng đầy đủ. Cần nghiệm thu bổ sung trước khi dùng thật.

**C – Điều dưỡng được phân công**

- Bác sĩ điều trị (hoặc quản trị) phân công điều dưỡng cho một lượt khám; tài khoản điều dưỡng chỉ thấy các lượt đã được giao.
- Điều dưỡng được cập nhật **chỉ sinh hiệu** theo phiên bản hồ sơ, không xem/sửa chẩn đoán hoặc kê đơn. Mọi thay đổi có nhật ký. Quyền nhập sinh hiệu bị khóa sau khi hoàn tất khám.

**D – Hoàn tất khám và khóa hồ sơ**

- Bác sĩ kết thúc lượt nếu đã có chẩn đoán và không có chỉ định đang chờ kết quả. Kết thúc tạo `visit_closures`, lưu phiên bản và sự kiện audit; không cho ghi thêm dữ liệu chuyên môn/đơn thuốc/chỉ định.
- Sau khi khóa, bác sĩ lập phụ lục có lý do và nội dung, quản lý duyệt. Bản gốc không bị sửa hoặc xóa; chưa có tính năng chèn phụ lục vào mẫu Word/PDF chính thức và ký số chuyên môn.

## Cơ sở dữ liệu và triển khai

Các bảng cũ giữ nguyên để bảo toàn dữ liệu. Bảng mới: `service_categories`, `charge_sources`, `order_requests`, `charge_voids`, `order_cancel_requests`, `medicine_prices`, `prescription_items`, `dispensations`, `dispensation_items`, `visit_nurses`, `visit_closures`, `visit_addenda`.

SQLite demo: `schema.sql` tạo thêm bảng bằng `CREATE TABLE IF NOT EXISTS`. PostgreSQL LAN: **bắt buộc** sao lưu + xác minh trước, dừng web, chạy `python -m scripts.with_env <owner.env> scripts.manage migrate` bằng role owner, áp dụng lại `deploy/postgresql-roles.sql` để cấp quyền runtime vào các bảng mới. Kiểm tra quyền không được UPDATE/DELETE audit; giữ HTTPS, firewall, backup và ACL. Phiên bản migration tăng 2.

## Kiểm thử và giới hạn

- Có kiểm thử SQLite chuyên biệt A–D và thử lại các workflow cũ; kết quả thực tế nằm trong nhật ký bàn giao.
- Có ca kiểm thử PostgreSQL LAN mới trong `lan_tests/test_v042_business.py`, các kiểm thử LAN cũ được cập nhật để dùng chỉ định có giá và đơn thuốc cấu trúc; **phải chạy CI với PostgreSQL 17 + Chromium** trước khi hợp nhất.
- Thiết bị Windows 11 tại phòng khám, mất điện, máy in, an toàn thuốc và tính pháp lý chưa nghiệm thu. Chỉ dữ liệu giả lập.
- Các quy tắc nghiệp vụ được chọn theo hướng an toàn, có thể cần thay đổi sau khi người phụ trách chuyên môn và kế toán phòng khám chốt quy trình thực tế.
