# R6 — đợt giao diện cuối

Nhánh `feat/u1-r6-quan-ly`, gốc `main` tại `8da31ff`.
Đã mở PNG và HTML của U_QuanLy, U_QuanLyBaoCao, U_QuanTri, U_NhatKy, U_NhapBangGia, U_CaiDat, U_ThuocRaSoat, U_ChiSoXN.

## Thực hiện

- Lớp trình bày `r6Present()` ở app/static/app.js:472 sắp lại các node đã được màn hình tạo; không tạo lại form, không đổi tên trường, data-action, handler hoặc điều kiện phân quyền. Dọn các lớp R6 khi chuyển màn/đăng xuất.
- Quản lý: hero đen, thống kê, tab và thẻ đề nghị; giữ nguyên nút duyệt/từ chối và lý do. Lượt khám có bộ lọc trái/bảng phải; báo cáo có kỳ báo cáo trái và số liệu/bảng phải.
- Quản trị: bảng nhân viên trái, tạo tài khoản phải; sửa/khóa/đặt lại mật khẩu vẫn dùng form gốc. Nhật ký đưa thời điểm lên đầu, lọc nội dung trên trang đã tải, chỉ đọc.
- Nhập bảng giá: hero và tải tệp hai cột, xem trước/xác nhận bên dưới; giữ nguyên preview → commit, tệp và mã xem trước.
- Cài đặt: hero đen/chức năng phụ hai cột; thông tin trên đơn thuốc bên dưới. Công tắc vẫn là checkbox native với tên/checked cũ.
- Thuốc chờ rà soát vẽ tại **app/static/m6.js:21**, được bổ sung danh mục TT18 tại **app/static/m6.js:73**; R6 trình bày tại app/static/app.js trong nhánh `page==='m6-admin'` của r6Present. Danh sách trái, chọn mục mở form rà soát/gộp gốc bên phải. Giữ các phần nhập Excel và cơ sở bên dưới.
- Chỉ số XN vẽ tại **app/static/m5.js:50** (`M5.admin()`); R6 thêm bảng danh mục từ dữ liệu đã tải và đặt sửa chỉ số dưới hero, bên trái. Giữ nhập/xuất, tham chiếu và liên kết dịch vụ gốc.
- CSS r6-* trước khối in đầu tiên; tái dùng r2-hero, r2-stat, r4-person, r4-tabs, renderState. Khi in bỏ hiệu ứng kính.
- R5: không còn đơn chỉ hiện một trạng thái trống trong danh sách, không dựng khung chi tiết; tab ngay dưới hero, trên điện thoại dùng luồng cuộn thường để không chồng menu đáy.

## Kiểm thử

- Hai ca Chromium 1366/390 trong test_administrative_browser.py đi qua phê duyệt (có đề nghị giả lập), báo cáo, lượt khám, tài khoản, nhật ký, nhập giá, cài đặt, thuốc chờ rà soát (có thuốc giả lập) và chỉ số xét nghiệm: ảnh, không tràn ngang, không chữ dưới 13px, mọi button cao ít nhất 44px.
- Hai ca trong test_pending_queues.py kiểm không có đơn: chỉ một trạng thái trống hiện trong danh sách, không có khung chi tiết; đo tab nằm giữa hero/danh sách và ở trên menu đáy tại 390px.
- Không sửa/xóa/nới assertion cũ; không tăng timeout. Chỉ thêm test vào hai tệp trên.
- Tám tệp được yêu cầu (HTTPS chạy toàn bộ, không `-k`): **51 đạt**. Kiểm lại riêng các ca R6 ở bản trình bày cuối: **4 đạt**. Ruff 0.17.5, ESLint 9.39.5 và `git diff --check`: đạt. PostgreSQL 17.12 dùng một lần, Chromium hệ thống 156; ảnh trong `test_evidence/r6/` không đưa vào Git.

## Điểm khác mẫu / Chờ S2

- Không lấy số doanh thu/lượt hôm nay từ số tích lũy: hero phê duyệt hiện “—” cho hai tổng chưa có. Tổng số thuốc đã rà soát cũng chưa có, hiển thị “—”; thuốc chưa rà soát đếm trên trang hiện tại, TT18 đếm từ danh mục đã tải.
- Báo cáo giữ ngày báo cáo giá nhập tay và tổng quan hiện có; chưa có báo cáo từ–đến/ngày–tuần–tháng, phân tích doanh thu theo dịch vụ hoặc xuất Excel như mẫu. **Chờ S2** cho các tổng hợp và API tương ứng.
- Nhật ký chỉ lọc trên trang 100 dòng hiện có; bộ lọc ngày/nhân viên/sự kiện toàn bộ lịch sử và xuất CSV trong mẫu: **Chờ S2**. Không có nút sửa/xóa.
- Rà soát thuốc giữ đủ trường và thao tác cũ, không dựng số lần gõ/tên bác sĩ/cảnh báo trùng thuốc khi chưa có dữ liệu tương ứng. Không tự quyết định gộp/đổi cờ.
- Giữ các phần an toàn hiện có vượt mẫu: xác nhận quyền quản trị, cảnh báo chứng thư/cài đặt, liên kết chỉ số, TT18 và các biểu mẫu phụ.
- Chưa xác nhận đủ năm job CI và Chromium 109 ở head mới; không hợp nhất. Không sửa backend, API, workflow hoặc deploy/.

## Số dòng so với 8da31ff

| Tệp | Thêm / xóa |
|---|---:|
| app/static/app.js | +125 / −4 |
| app/static/styles.css | +43 / −1 |
| lan_tests/test_administrative_browser.py | +52 / −0 |
| lan_tests/test_pending_queues.py | +40 / −0 |
| docs/U1_R6_KIEM_THU.md | +42 / −0 |
