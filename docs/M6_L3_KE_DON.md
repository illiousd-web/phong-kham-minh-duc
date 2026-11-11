# M6 + L3 — kê đơn và dữ liệu đơn thuốc điện tử

Bản triển khai đang kiểm thử; chưa nghiệm thu vận hành thật. Nhánh `feat/m6-l3-ke-don` tạo từ main `0a1376f`. Không dùng dữ liệu thuốc, nhân viên hoặc người bệnh thật trong kiểm thử.

## Nguồn và phạm vi

Nguồn gốc: [Thông tư 26/2025/TT-BYT, bản đính kèm trên Cổng Chính phủ](https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/7/26-byt.pdf), Điều 6 trang 3–4 và Phụ lục I trang 12 (số trang tính từ 1). Đã mở và đọc trong phiên ngày 11/11/2026. Bảng dưới đối chiếu yêu cầu dự án với dữ liệu triển khai; không tuyên bố phần mềm đã được nghiệm thu pháp lý.

Không triển khai liên thông thật, ký số, đơn N/H hoặc kê 90 ngày theo Phụ lục VII trong gói này. Outbox và adapter giả không gọi mạng. Không thay đổi thuật toán tiền, tồn kho hay cấp/trả thuốc.

## Đối chiếu Phụ lục I với dữ liệu

Dữ liệu được thêm bằng migration 8; bảng tiền và kho hiện có không thay đổi.

| Mục | Trường / nguồn | Cách thể hiện |
|---|---|---|
| 4.1 Mã đơn | `clinic_facility_code`, `clinical_prescriptions.local_code` | 5 ký tự cơ sở + 7 ký tự đơn + `-C`, tổng 14 ký tự; ràng buộc duy nhất. Nháp được cấp mã khi đã có mã cơ sở, vẫn in dấu NHÁP; mã cố định sau khi khóa. Thiếu mã cơ sở: dòng MÃ NHÁP – CHƯA CÓ MÃ CƠ SỞ; không khóa trong LAN vận hành thật. |
| 4.2 Cơ sở | `clinic_name`, `clinic_address`, `clinic_phone` trong cài đặt | Lấy từ cài đặt quản trị; chụp giá trị tại lúc khóa để việc sửa cài đặt không đổi đơn đã khóa. |
| 4.3 Người bệnh | `patients.full_name`, số giấy tờ tùy chọn, `date_of_birth`, `sex`; `visits.weight_kg` | Word và PDF dùng cùng dữ liệu đã chốt. Số giấy tờ không đi vào audit. Dòng BHYT được giữ và để trống. |
| 4.3 Cư trú | `address_detail`, `commune`, `province`, `address` cũ | Hàm `format_patient_address` ghép chi tiết, xã, tỉnh; nếu thiếu chi tiết nhưng có địa chỉ cũ thì dùng địa chỉ cũ làm phần đầu. Không có gì mới in dấu —. |
| 4.4 Chẩn đoán | `visits.diagnosis` | Chụp nội dung khi khóa, không đọc lại nội dung mới để thay đơn cũ. |
| 4.5 Thuốc điều trị | Dòng đơn: tên, hoạt chất, hàm lượng, đơn vị, số lượng, liều/lần, lần/ngày, đường dùng, thời điểm, số ngày, ghi chú | Lưu nội dung riêng trên dòng đơn; liên kết `drugs` phục vụ gợi ý và quản trị. Gộp danh mục chỉ đổi liên kết, không đổi nội dung đơn đã khóa. Thuốc độc đứng trước, giữ thứ tự nhập trong mỗi nhóm. |
| 4.6 Lời dặn | `lifestyle_advice`, `follow_up_advice`, `purchase_advice` | Ba ô riêng; không in mục trống. |
| 4.7 Ngày và người kê | Thời điểm khóa giờ Việt Nam; họ tên in, chức danh, giấy phép/phạm vi từ hồ sơ người hành nghề | Có chỗ ký; không giả chữ ký số. Chụp thông tin người kê khi khóa. |
| 4.8 Cuối đơn | Số điện thoại liên hệ; tháng tuổi tính từ ngày sinh; `visits.escort_name` | Giữ lời nhắc mang đơn khi khám lại. Trẻ dưới 72 tháng có tháng tuổi, cân nặng và người đưa trẻ. |

JSON nội bộ dùng `schema_version`, các khối `facility`, `patient`, `encounter`, `prescriber`, `items`, `advice`, thời điểm khóa, mã nội bộ và mã đơn quốc gia `null`. Đây không phải schema liên thông quốc gia đã được chứng nhận. Giao diện phải hiện CHƯA LIÊN THÔNG.

## Quyết định về hoạt chất đã được chủ dự án duyệt

Đơn nháp lưu được khi thiếu hoạt chất. Khi khóa, mọi dòng phải có hoạt chất; lỗi trả số dòng và trường `ingredient`, giao diện tô đỏ đúng dòng và báo **Bổ sung hoạt chất để in đúng tên theo TT 26/2025**. Bác sĩ bổ sung ngay trên dòng, không phải chờ quản trị. Mục tương ứng trong `drugs` chưa rà soát được cập nhật hoạt chất nhưng vẫn giữ trạng thái chưa rà soát. Chọn gợi ý tự điền hoạt chất, hàm lượng, đơn vị và đường dùng.

Tách hoạt chất bằng dấu `+`, không có ô chọn một/nhiều. Một hoạt chất in hoạt chất kèm tên thương mại trong ngoặc nếu có; nhiều hoạt chất bắt buộc tên thương mại khi khóa và in tên thương mại. Các ô dùng thuốc nhận chữ tự do; tự tính số lượng khi liều, lần/ngày và số ngày là số dương, nếu cách ghi không thể tính thì bác sĩ nhập số lượng thủ công. Không tự đoán dược chất hoặc cờ độc/N/H từ tên.

## Cài đặt, nâng cấp và sử dụng

Sao lưu và xác minh trước nâng cấp theo quy trình hiện hành. Demo SQLite tự chạy migration 8; LAN chạy `python -m scripts.manage migrate` bằng tài khoản chủ CSDL trước khi khởi động dịch vụ. Migration thêm `drugs`, `clinical_prescriptions`, `clinical_prescription_items`, `prescription_outbox`, `prescription_settings`; không sửa hoặc sao chép dữ liệu tiền/kho/đơn cũ. Không nạp danh mục thuốc thật vào Git. Muốn quay lại: dừng dịch vụ, khôi phục mã cùng CSDL từ bản sao lưu đã xác minh, không xóa riêng bảng mới.

Quản trị nhập mã cơ sở 5 ký tự và thông tin đơn vị ở Cài đặt hoặc Thuốc chưa rà soát. Excel tùy chọn: sheet `DanhMucThuoc`, tiêu đề dòng 1, đủ 10 cột theo [mẫu giả lập](../templates/nhap_lieu/DANH_MUC_THUOC_GIA_LAP.xlsx); dòng tên bắt đầu VÍ DỤ được bỏ qua. Xem trước không ghi CSDL; tệp lỗi chỉ rõ dòng/cột, không nạp dở. Nhập Excel không ghi đè mục đã rà soát hoặc ngừng dùng. Chỉ ngừng dùng, không xóa thuốc đã được tham chiếu. Gộp chỉ cập nhật liên kết dòng và giữ cờ hạn chế, không đổi JSON/bản in đã khóa.

Bác sĩ mở lượt được giao, kê ở phần Đơn thuốc, lưu nháp, kiểm và khóa. Muốn sửa đơn đã khóa thì lập đơn mới thay thế, giữ liên kết và lịch sử. Hủy có lý do và phiên bản. Lễ tân/dược chỉ xem, in đơn M6 đã khóa; bác sĩ xem nháp/hủy của lượt được giao. JSON chỉ xuất đơn đã khóa cho bác sĩ. Mỗi lần in đều ghi nhật ký in/in lại. Số giấy tờ không xuất hiện trong nhật ký; số nằm trong dữ liệu đơn được phân quyền và bản sao lưu mã hóa.

Đơn M6 là đơn lâm sàng, không tự trừ kho/ghi tiền. Mục **Kê / cấp thuốc từ kho (quy trình hiện có)** giữ luồng cấp/trả và sổ tiền cũ; không tự biến thuốc gõ tự do thành mặt hàng có tồn hoặc giá. Đơn lịch sử cũ vẫn mở/in theo luồng cũ. Đây không phải liên thông giữa đơn M6 và cấp thuốc kho.

Snapshot khóa lưu thông tin người bệnh, người kê, cơ sở, thuốc và lời dặn tại thời điểm khóa. Các thay đổi sau đó ở hồ sơ hoặc danh mục không sửa bản in cũ. Outbox được tạo cùng giao dịch khóa, hủy đơn đánh dấu hủy trong outbox; không có tiến trình gửi thật. `PrescriptionGateway` và `FakePrescriptionGateway` chỉ là hợp đồng/adapter giả. Đơn không có mã quốc gia và luôn ghi **CHƯA LIÊN THÔNG**.

## Các điểm cần đối chiếu

- [CẦN ĐỐI CHIẾU] Cách gạch chéo phần trống trong Word/PDF nhiều trang; không tự thêm thao tác này trước khi duyệt mẫu.
- [CẦN ĐỐI CHIẾU] Định dạng mã và việc tiếp nhận mã khi liên thông thật; mã nội bộ không được trình bày thành mã quốc gia đã cấp.
- [CẦN ĐỐI CHIẾU] Hồ sơ có giới tính Khác trong dữ liệu cũ so với hai lựa chọn Nam/Nữ của mẫu; không tự chuyển giới tính.

## Kiểm thử

SQLite và PostgreSQL: nâng cấp dữ liệu cũ, rollback giao dịch khi nhập Excel lỗi, snapshot bất biến khi khóa/gộp/sửa danh mục, tìm không dấu, chống trùng, số lượng tự tính và sửa tay, điều kiện khóa, mã duy nhất 14 ký tự, phân quyền tại API, audit không có số giấy tờ, xuất JSON không gọi mạng, sao lưu/khôi phục chính xác. Word/PDF phải đủ mục 4.1–4.8. Chromium 109 kiểm 1366px/390px; COUNT và danh sách dùng cùng điều kiện SQL. Giữ nguyên tiêu chí C4, C5, M0 và 5 job CI.
