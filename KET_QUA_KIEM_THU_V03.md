# Kết quả kiểm thử — Phòng khám đa khoa Minh Đức, v0.3.0

**Ngày:** 08/11/2026
**Phạm vi:** Môi trường cục bộ, dữ liệu bệnh nhân hoàn toàn giả lập.
**Kết luận kỹ thuật:** Bản thử nghiệm **khởi động và chạy được**, các luồng chủ yếu hoạt động trong môi trường kiểm thử. **Không có kết luận nghiệm thu phần mềm khám chữa bệnh thật.**

## 1. Tự động hóa API và cơ sở dữ liệu

Lệnh: `python -m pytest -q` từ thư mục dự án.

**Kết quả kiểm tra lần cuối: 36 passed**.

Đã thử đăng nhập/đăng xuất, quyền xem hồ sơ bác sĩ, tách nhiệm vụ lễ tân–bác sĩ–kỹ thuật viên–dược–thu ngân–quản lý, lạc quan khóa phiên bản hồ sơ, tiếp đón/lịch hẹn, kết quả cận lâm sàng và duyệt, đính kèm, đơn nháp, tạo và xuất 9 loại biểu mẫu PDF/Word, công nợ/thanh toán/idempotency, giảm giá/hoàn trả thừa có phê duyệt, tồn kho FEFO/không âm kho, thuốc kiểm soát bị chặn, backup SQLite và kiểm chứng bản sao. CSDL thử nghiệm được tạo mới trong mỗi lần chạy để tránh trùng mã giao dịch.

## 2. Giao diện Chromium (Playwright)

Lệnh: `python tests/browser_smoke.py`.

**Kết quả:**

- Luồng lễ tân → khám → chỉ định → kỹ thuật viên nhập kết quả → bác sĩ duyệt → đơn nháp → thu tiền → quản lý: **đạt**.
- Các tệp PDF từ giao diện: phiếu tiếp đón, phiếu khám, kết quả xét nghiệm, đơn nháp: **tải và mở được**.
- Desktop 1440 px, mobile 390 px: **giao diện hiển thị đạt trong bài thử**.
- Lỗi JavaScript không bắt được: **0**.
- Sử dụng Chromium qua cầu kết nối API trong tiến trình do chính môi trường sandbox hạn chế điều hướng localhost của trình duyệt; HTTP máy chủ được kiểm độc lập ở mục 3.

Tệp bằng chứng: `test_evidence/le_tan_desktop.png`, `quan_ly_desktop.png`, `quan_ly_mobile.png`, `phieu_tiep_don_chromium.pdf`, `phieu_kham_chromium.pdf`, `ket_qua_chromium.pdf`, `don_nhap_chromium.pdf`. Tất cả nội dung người bệnh là giả lập.

## 3. Kiểm máy chủ HTTP cục bộ thực tế

Khởi động `uvicorn app.main:app --host 127.0.0.1 --port 18777` trong tiến trình độc lập, dùng SQLite mới, gọi qua HTTP:

| Bài kiểm tra | Phản hồi |
|---|---|
| GET `/api/health` | 200, phiên bản và tên phòng khám chính xác |
| GET `/` | 200, trả giao diện HTML |
| GET `/assets/app.js` | 200, trả JavaScript |
| POST `/api/login` đúng thông tin demo | 200, trả tài khoản lễ tân |

Đã chấm dứt tiến trình sau khi kiểm tra. Không triển khai máy chủ thường trực.

## 4. Kiểm định tạo biểu mẫu và sao lưu

- File Word: mở được qua python-docx; nội dung tên, dữ liệu lượt khám, chỉ định, đơn nháp được điền tự động từ CSDL.
- PDF: kiểm chữ tiếng Việt bằng thư viện PyMuPDF, kiểm tra trang A4/A5 và cảnh báo bản thử nghiệm; trang PDF xuất từ Chromium đã được mở bằng trình phân tích PDF.
- Backup: `python scripts/backup_demo.py create` tạo tệp ZIP có bản sao SQLite, tệp đính kèm và manifest SHA-256. Lệnh `verify` kiểm CRC, SHA-256 và `PRAGMA integrity_check`; kiểm cả khả năng mở lại bản sao trong môi trường kiểm thử.

## 5. Những phần chưa thử trực tiếp

- Chạy trên Windows của phòng khám, máy in Canon/Epson, chất lượng in thực tế, chữ ký số, liên thông dữ liệu y tế/thuế, thiết bị cận lâm sàng, truy cập bảo mật từ xa, nhiều người dùng thật, bảo mật triển khai thực tế, quy trình thuốc cần kiểm soát đặc biệt.
- Chưa kiểm nghiệm lâm sàng và pháp lý của tất cả loại biểu mẫu theo phạm vi giấy phép và quy định tại ngày đưa vào sử dụng.

**Tóm lại:** phần mềm **chạy được dưới dạng demo nội bộ đã kiểm thử**, không có đủ bằng chứng để tuyên bố là hệ thống quản lý phòng khám đủ điều kiện dùng với người bệnh thật.
