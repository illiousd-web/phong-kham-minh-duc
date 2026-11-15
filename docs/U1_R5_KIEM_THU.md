# R5 — nhà thuốc, kho thuốc, điều dưỡng và ba việc tồn R4

Nhánh `feat/u1-r5-nha-thuoc`, tạo từ `main` tại `7539cd3`.
Đã đọc AGENTS.md và mở PNG/HTML của U_NhaThuoc, U_NhaThuocDT, U_KhoThuoc, U_DieuDuong.

## Thay đổi theo tệp

| Tệp | Dòng thêm / xóa |
|---|---|
| `app/static/app.js` | +64 / −16 |
| `app/static/styles.css` | +64 / −0 |
| `lan_tests/test_administrative_browser.py` | +58 / −0 |
| `lan_tests/test_browser_https.py` | +63 / −0 |
| `lan_tests/test_pending_queues.py` | +104 / −0 |
| `docs/U1_R5_KIEM_THU.md` | +43 / −0 |

- Nhà thuốc: hero, thống kê, tìm trên trang, hàng chờ và chi tiết đơn; tái dùng r2-hero, r2-stat, r4-person, r4-tabs, renderState.
- Kho: bảng tồn bên trái, nhập lô bên phải; giữ nhập, xuất nội bộ, thêm thuốc và biểu mẫu thuốc kiểm soát hiện có. Thanh tab cuộn có tính stickyOffset.
- Điều dưỡng: hàng chờ bên trái, sinh hiệu bên phải; giữ y lệnh, chăm sóc, chỉ định và các thao tác lưu cũ.
- Ba việc tồn: Khách đưa/Trả lại/Thiếu chỉ tính tại giao diện; tiêu đề xét nghiệm r4-blue; phân biệt mất kết nối với lỗi HTTP và nút Tải lại gọi render().
- CSS r5-* đặt trước khối @media print đầu tiên, bỏ hiệu ứng kính khi in. Không sửa backend, API, workflow, phép tính tiền, cấp phát hoặc điều kiện thuốc kiểm soát.

## Kiểm thử

- `test_mot_ngay_kham.py` + `test_v042_business.py` + `test_pending_queues.py` + `test_administrative_browser.py`: **24 đạt**.
- `test_browser_https.py -k "u1r1 or u1r2"`: **10 đạt**, 9 không chọn.
- Kiểm lại riêng bố cục R5 sau sửa CSS cuối: **1 đạt**, 2 không chọn.
- Ruff 0.17.5 (`ruff check .`), ESLint 9.39.5 (`eslint app/static/*.js`) và `git diff --check`: đạt.
- Môi trường: PostgreSQL 17.12 dùng một lần, Chromium hệ thống 156; ảnh tại `test_evidence/r5/` (không đưa vào Git).
- Không sửa/xóa/nới assertion cũ. Ba tệp test chỉ thêm kiểm tra; không cần viện dẫn mẫu để thay assertion cũ.
- Administrative: kiểm Khách đưa không có name, chỉ hiện khi thu tiền mặt, trả lại/thiếu cập nhật theo amount; payment chỉ một button; POST giữ đúng sáu trường cũ, amount và bản ghi tiền vẫn 1.000 đồng.
- HTTPS: page.route chặn mạng, thử tải lại khi còn mất mạng và sau khôi phục; lỗi HTTP giữ thông báo máy chủ; kiểm hero xét nghiệm ở 1366/390px.
- Pending queues: ảnh nhà thuốc/kho/điều dưỡng ở 1366/390px, tìm đơn, lô sắp hết hạn, trường form kho, kích thước nút, không tràn ngang, ô tìm nằm trong hero, cuộn không bị tab che, quyền điều dưỡng và bản in.
- Lần chạy đầu test mới thiếu bước lưu chẩn đoán bắt buộc trước lập đơn; đã bổ sung dữ liệu chuẩn bị, không đổi quy tắc ứng dụng hay tăng timeout.

## Điểm khác mẫu và Chờ S2

- Cấp thuốc tiếp tục dùng đơn kho hiện có; API chưa cung cấp lô sẽ xuất trước khi cấp. Không dựng lô FEFO hoặc số đã cấp dự đoán; giữ Hủy đơn, Cấp thuốc, tải PDF/Word và trả thuốc hiện có.
- Tìm và số đơn chờ cấp giới hạn trang hiện tại; giữ phân trang 100 đơn. Không tạo tìm kiếm hoặc API mới.
- Kho chưa có trường giá nhập trên API, nên không thêm ô Giá mỗi đơn vị cơ sở của mẫu. Các biểu mẫu xuất nội bộ/thêm thuốc được giữ dưới khối nhập lô.
- API điều dưỡng chưa trả dị ứng, tên bác sĩ/y lệnh trong hàng chờ hoặc tổng đã xong hôm nay: không suy đoán; thống kê đã xong hiện “—”. Giữ Lưu sinh hiệu; không tạo nút Lưu nháp/Hoàn tất báo bác sĩ khi chưa có nghiệp vụ. BMI dùng cảnh báo hiện có.
- Chưa xác nhận Chromium 109 và năm job CI xanh; để CI kiểm bộ đầy đủ. Không hợp nhất.
- **Chờ S2**: tín hiệu sao lưu, bảo toàn dữ liệu đang nhập khi mất mạng, lịch thử lại từ máy chủ và trạng thái ổ gần đầy/khóa ghi thực tế.
