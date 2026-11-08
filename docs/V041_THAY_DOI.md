# v0.4.1 — Sửa giao diện, biểu mẫu và chứng chỉ HTTPS

Ngày: 09/11/2026. Người sửa: Claude, trên mã nguồn v0.4.0 do người dùng gửi (`phong-kham-minh-duc-main.zip`).
Không đổi cấu trúc cơ sở dữ liệu: không cần chạy lại `migrate`, dữ liệu cũ đọc được bình thường.

## Kết quả kiểm thử

| Bộ | Trước khi sửa (máy Claude, Python 3.13) | Sau khi sửa |
|---|---|---|
| `tests` (SQLite) | 47/47 đạt | 53/53 đạt (thêm 6 bài) |
| `lan_tests` (PostgreSQL 16, HTTPS, Chromium) | 25/26 — hỏng bài HTTPS trình duyệt | 26/26 đạt |

CI trên GitHub dùng Python 3.12 và PostgreSQL 17 nên không gặp lỗi chứng chỉ ở mục 1; máy thật cài Python 3.13 (README khuyến nghị) sẽ gặp.

## Đã sửa

1. **Chứng chỉ HTTPS nội bộ bị Python 3.13 từ chối.** Python 3.13 bật kiểm tra chứng chỉ chặt (`VERIFY_X509_STRICT`); chứng chỉ do `scripts/create_lan_certificate.py` tạo thiếu Subject/Authority Key Identifier nên mọi kết nối Python tới máy chủ (kiểm tra sức khỏe, sao lưu, kiểm thử) đều thất bại. Đã bổ sung các phần mở rộng này và KeyUsage cho chứng chỉ máy chủ. **Ai đã tạo chứng chỉ bằng bản cũ cần tạo lại.**
2. **Mã tiếng Anh lọt ra màn hình và giấy in** (`waiting`, `approved`, `pending_review`, `cash`, `discount`...). Thêm `app/labels.py`; màn hình, PDF, Word đều dùng nhãn tiếng Việt. CSDL vẫn lưu mã cũ.
3. **Ngày kiểu Mỹ.** Mọi ô ngày (ngày sinh, hẹn tái khám, ngày hẹn, hạn dùng) nhập dạng `dd/mm/yyyy`, tự chèn dấu `/`, kiểm tra ngày có thật (chặn 31/02). Máy chủ nhận cả `dd/mm/yyyy` lẫn ISO và lưu ISO. Giờ hẹn nhập 24 giờ. Thời điểm lưu theo UTC được hiển thị theo giờ Việt Nam (UTC+7), tránh lệch ngày khi thao tác trước 7 giờ sáng.
4. **Sinh hiệu có cấu trúc.** 7 ô: mạch, huyết áp, nhiệt độ, nhịp thở, cân nặng, chiều cao, SpO2; kiểm tra khoảng hợp lý; tự tính BMI; cảnh báo huyết áp cao/thấp, mạch nhanh/chậm, sốt, SpO2 thấp, BMI. Vẫn lưu vào cột `vitals` dạng một dòng chuẩn nên biểu mẫu in cũ đọc được; ghi chú tự do giữ trong "Ghi chú sinh hiệu khác".
5. **Phiếu khám thiếu thông tin người bệnh.** Thêm dải thông tin: họ tên, mã, giới, tuổi, ngày sinh, lượt, trạng thái. Cùng màn hình có danh sách chỉ định của lượt và đơn thuốc, kèm nút chuyển sang lập chỉ định/kê đơn với lượt đã chọn sẵn.
6. **Hồ sơ cho phép thiếu dữ liệu.** Ngày sinh, giới tính (Nam/Nữ/Khác, bỏ "Chưa rõ" cho hồ sơ mới) và số điện thoại bắt buộc ở cả giao diện lẫn máy chủ. Chuẩn hóa khoảng trắng họ tên và chữ số điện thoại. **Đơn thuốc chỉ lập được khi phiếu khám đã có chẩn đoán.**
7. **Phiếu kết quả.** Kỹ thuật viên nhập mỗi chỉ số một dòng `Tên | Kết quả | Đơn vị | Tham chiếu | Đánh dấu`; dòng `Kết luận: ...` vào mục Kết luận. PDF và Word in thành bảng, có mục Kết luận, tách khung ký **Người thực hiện** và **Người duyệt kết quả** kèm tên. Không dòng nào bị bỏ.
8. **Thu ngân.** Chỉ liệt kê lượt còn nợ; số tiền tự điền số còn phải thu và đổi theo lượt được chọn.
9. PDF in đậm được nhãn (trước đây font đậm không được đăng ký nên `<b>` in thường).

## Phát hiện chưa sửa — cần anh quyết định nghiệp vụ

Các mục này không phải lỗi giao diện; sửa đúng cần chốt quy trình và có thể đổi CSDL.

- **A. Chỉ định cận lâm sàng không phát sinh tiền.** `POST /api/orders` không tạo khoản phải thu; tên chỉ định là chữ tự do, không gắn bảng giá. Xét nghiệm, siêu âm, X-quang, điện tim hiện đều miễn phí trên hệ thống.
- **B. Đơn thuốc không nối với kho và thu ngân.** Đơn là văn bản tự do; nhà thuốc xuất kho bằng một màn hình riêng không gắn đơn; tiền thuốc không vào bảng kê.
- **C. Điều dưỡng không làm được gì.** Vai trò `nurse` bị chặn khỏi mọi hồ sơ chuyên môn (chưa có phân công), menu chỉ có "Công việc"; không nhập được sinh hiệu.
- **D. Lượt khám không có bước kết thúc.** Trạng thái chỉ có `waiting` → `in_progress`; hồ sơ sửa được vô thời hạn, không khóa sau khi bác sĩ kết luận.

## Tệp đã đổi

`app/labels.py` (mới), `app/main.py`, `app/forms.py`, `app/print_forms.py`, `app/static/app.js`, `app/static/styles.css`, `app/static/index.html`,
`scripts/create_lan_certificate.py`, `tests/test_v041_fixes.py` (mới), các test cũ chỉ bổ sung trường bắt buộc / bước lưu chẩn đoán trước khi kê đơn.
