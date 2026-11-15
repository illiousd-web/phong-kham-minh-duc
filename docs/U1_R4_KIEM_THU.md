# R4 — giao diện xét nghiệm và thu ngân

Nhánh `feat/u1-r4-xn-thu-ngan`, gốc `main` tại `e02afba`.
Đã mở cả PNG và HTML của KH_XetNghiem, U_PhieuXN, KH_ThuNgan, TrangThai.

## Thay đổi theo tệp

| Tệp | Dòng thêm / xóa |
|---|---|
| `app/static/app.js` | +46 / −14 |
| `app/static/m5.js` | +42 / −3 |
| `app/static/m6.js` | +1 / −1 |
| `app/static/styles.css` | +58 / −0 |
| `docs/ui-mau/README.md` | +1 / −0 |
| `eslint.config.js` | +1 / −1 |
| `lan_tests/test_c5_queue_pages.py` | +14 / −0 |
| `lan_tests/test_m5_browser.py` | +20 / −1 |
| `lan_tests/test_m6_browser.py` | +26 / −0 |
| `docs/U1_R4_KIEM_THU.md` | +46 / −0 |

- Dựng bố cục r4-*; dùng lại hero, stat; giữ form, API, cách tính tiền và quyền cũ.
- Trạng thái trống/đang tải/lỗi tải dùng renderState; tên dài có ellipsis và title.
- Enter tìm thuốc bỏ qua isComposing; hàng chờ có đệm đáy lớn hơn chiều cao dock.
- Khi in, ẩn khối Xuất chứng từ; các khối R4 bỏ hiệu ứng kính.
- eslint.config.js chỉ khai báo các hàm dùng chung được gọi thêm từ m5.js.

## Kiểm thử

- Không sửa hoặc nới assertion cũ; chỉ thêm kiểm tra và ảnh chụp trong ba tệp browser.
- test_m6_browser.py: kiểm tra 390px, Enter khi đang gõ không thêm thuốc; Enter sau khi gõ thêm được; khoảng đệm và điểm giữa thẻ đầu không bị dock che; khối Xuất chứng từ không hiện khi in; ảnh màn lab.
- test_m5_browser.py: hero, bốn thống kê, title tên; lỗi tải và Thử lại chỉ gọi lại một lượt; ảnh hàng chờ/nhập kết quả.
- test_c5_queue_pages.py: tiêu đề, tên đầy đủ, chọn hình thức thanh toán vẫn truyền đúng giá trị; ảnh thu ngân 390/1366px; giữ nguyên kiểm tra đủ nợ cũ.
- Nhóm năm tệp m5_browser, m5, c5_queue_pages, administrative_browser, m6_browser: 16 đạt.
- test_browser_https.py -k "u1b or u1c or u1r2": 10 đạt, 7 không được chọn.
- Chạy lại c5_queue_pages + m6_browser sau chỉnh cuối: 6 đạt.
- Kiểm lỗi tải cuối: M5 browser 1366px đạt; bài 390px với lỗi tải–Thử lại đạt sau khi dùng thao tác điều hướng dành cho tình huống lỗi (helper go mặc định yêu cầu tải thành công). Không nới assertion.
- Ruff 0.17.5 và ESLint 9.39.5: đạt. Không sửa workflow hoặc mã backend.
- PostgreSQL 17 tạm và Chromium hệ thống; lần đầu test sao lưu thiếu pg_dump, đã cấp bộ công cụ 17 và chạy lại đạt. Không tăng timeout.

## Điểm chưa giống mẫu / Chờ S2

- Màn lab cũ giữ kết quả dạng văn bản, lịch sử phiên bản và đính kèm; không dựng chỉ số/đơn vị/tham chiếu từ văn bản tự do. Bảng nhập từng chỉ số thuộc M5; vẫn giữ ngày lấy mẫu, ngày kết quả, ghi chú và các nút in hiện có.
- Phiếu M5 dùng “Đã duyệt”, chưa đổi thành “Đã trả”: API chưa theo dõi trả phiếu. Hàng chờ chỉ hiện thông tin người bệnh/chỉ định thực có; không suy đoán tuổi, giới, thời điểm lấy mẫu, người thực hiện.
- Thu ngân giữ các phần giá chưa xác định, thu tạm, ứng trước, đề nghị điều chỉnh và lịch sử; không tạo nút in trước khi có chứng từ. Không thêm phép tính Khách đưa/Trả lại hoặc đổi cách tính công nợ.
- Chờ S2: tín hiệu sao lưu đang diễn ra, quy tắc bảo toàn dữ liệu nhập và lịch thử lại có xác nhận từ máy chủ; phân biệt mất mạng với lỗi máy chủ; tín hiệu ổ gần đầy và trạng thái khóa ghi thực tế. Không hiển thị các lời khẳng định này từ lỗi tải chung.
- Chưa xác nhận 5 job CI xanh; không hợp nhất.

## Sửa tiếp PR #35 — radio hình thức thu tiền

- Thay hai nút phụ và select ẩn bằng radio native `name="method"`, giá trị `cash`/`transfer`; form payment chỉ có một button thu. Bỏ handler data-r4-method. Nhãn dạng nút chọn, vùng radio cao 48px, có focus bàn phím.
- Thêm test Chromium 390px trong test_administrative_browser.py: chọn bằng ArrowRight, kiểm focus/chiều cao, thu 1.000 đồng, xác nhận payload và bản ghi CSDL đều là transfer.
- test_manual_prices.py + test_mot_ngay_kham.py + test_administrative_browser.py: 20 đạt.
- test_browser_https.py -k "u1r1 and cashier": 1 đạt (1366px), 1 lỗi (390px), 15 không chọn. Lỗi còn lại tại dòng 484: test đòi gradient `15% 10%`, CSS body cashier dùng `15% 15%` như KH_ThuNgan.html:19. Không liên quan locator payment button; giữ nguyên test và nền theo yêu cầu báo nguyên nhân.
- Không sửa các test đang đỏ. Chỉ cập nhật phần kiểm tra chọn hình thức do R4 đã thêm trong test_c5_queue_pages.py từ nút sang radio; không chạy C5 ngoài danh sách cho phép. Không chạy các tệp test khác; không đổi API/cách tính tiền/workflow. Chưa xác nhận đủ 5 job CI xanh.
