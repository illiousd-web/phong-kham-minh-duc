# S2c — Mẫu in và ký bằng ảnh chữ ký

Nguồn mẫu: `docs/ui-mau/BoMau_33_ban_repo.pdf`, trang 29–33. Nhánh `feat/s2c-mau-in`, gốc `9647e1e`.

- Trang 29: hóa sinh máu, MS 22/BV-02, hai cụm Xét nghiệm / Trị số bình thường / Kết quả.
- Trang 30: huyết học, MS 17/BV-02, một cụm ba cột.
- Trang 31: hóa sinh nước tiểu, MS 23/BV-02, một cụm ba cột.
- Trang 32: chỉ định nội khoa, đánh dấu các chỉ định chưa hủy của lượt khám.
- Trang 33: đơn A4; ô mã quốc gia để trống.

Đầu phiếu dùng `clinic_profile`; logo từ tài sản công khai trong `app/static`. PDF/Word thông thường gọn một trang A4; nội dung dài tự sang trang, giữ cỡ chữ và đủ nội dung. Trang tiếp nối lặp họ tên, mã NB, số phiếu/mã đơn nội bộ; mọi trang có `Trang x/y`; bảng xét nghiệm lặp tiêu đề; khối ký chỉ ở cuối. Tuổi lấy theo ngày khám/ngày lập phiếu/ngày lấy mẫu; không lấy theo ngày in. Trẻ dưới 72 tháng tại ngày lập đơn phải có cân nặng trước khi in hoặc ký.

## Chữ ký theo nội dung in

Bác sĩ phụ trách hoặc người duyệt nhập lại mật khẩu khi ký. Mỗi bản ký lưu người ký, thời điểm, mã băm, bản sao ảnh và tên tài khoản; mỗi lần ký có audit.

Mã băm lấy từ các khối dữ liệu thực sự được dựng thành bản in qua `printed_content`: đầu phiếu được dùng theo loại mẫu, trường người bệnh, thuốc/chỉ định/chỉ số, lời dặn, ghi chú, ngày giờ hiển thị và tên người ký. Mã băm còn gồm SHA-256 của logo và tệp mẫu Word tương ứng với loại phiếu; thay một trong hai sẽ cần ký lại cho tới khi tài sản trở về bản cũ. Không băm toàn bộ profile, bản ghi nguồn hoặc trạng thái nội bộ. Ví dụ `governing_body` không in trên đơn thuốc nên không tham gia mã băm đơn. Thông báo kiểm chữ ký và ảnh chữ ký không tham gia mã băm nội dung.

Chỉ hiện ảnh của bản ký mới nhất khi mã băm khớp nội dung in hiện tại, người ký vẫn là người chịu trách nhiệm và phiếu còn hợp lệ (`allowed`). Nếu có bản ký nhưng điều kiện không khớp, ô ký trống và PDF/Word hiện: **Phiếu đã thay đổi sau khi ký, cần ký lại**. Phiếu chưa từng ký để trống ô ký. Dưới ảnh hợp lệ có giờ Việt Nam và tài khoản ký.

Khi nội dung trở về đúng nội dung của bản ký mới nhất, chữ ký đó được hiển thị lại nếu người chịu trách nhiệm và tính hợp lệ vẫn khớp. Người dùng cũng có thể ký lại nội dung mới. Luồng xem/in chỉ đọc, không cập nhật hay xóa `document_signatures`; yêu cầu đọc cũ hoàn tất sau khi ký bản mới không tác động bản ký mới.

Bản ký thử đã tạo trước khi bổ sung checksum tài sản dùng công thức băm cũ, do đó cần ký lại sau khi nâng cấp.

Kết quả của chỉ định khác, tên người không liên quan và bản điều chỉnh xét nghiệm còn nháp không làm mất chữ ký nếu các khối in không đổi. Tên người ký dùng trên bản in hiện tại được đối chiếu cả cho đơn M6 và báo cáo M5.

## Migration 017 và bất biến

017/018 chưa phát hành được gộp thành **một migration 017 sạch**, schema version 17; bỏ migration 018, cột `invalidated` và toàn bộ trigger vô hiệu trên các bảng nguồn. Không tự chuyển đổi lịch sử thử nghiệm của thiết kế 017/018 cũ. Khi phát hiện version 18 hoặc cột `invalidated`, nâng cấp từ chối với thông báo “CSDL đã chạy bản thử S2c cũ, cần khôi phục bản sao lưu trước S2c”.

SQLite bật `PRAGMA recursive_triggers=ON` trên các kết nối ứng dụng và công cụ SQLite. Trigger bảng ký chặn mọi UPDATE và DELETE; trigger BEFORE INSERT từ chối ID đã tồn tại, kể cả `INSERT OR REPLACE`/`REPLACE INTO` từ kết nối SQLite trực tiếp khi recursive_triggers tắt. CSDL đã ở version 17 sạch được bổ sung guard khi khởi động. PostgreSQL chặn UPDATE/DELETE bằng trigger; `clinic_app` bị thu hồi UPDATE, DELETE, TRUNCATE, gồm quyền UPDATE từng cột còn sót. Chỉ thêm bản ký mới.

Quay lui bằng `scripts.manage rollback-s2c` với kết nối chủ sở hữu bị từ chối nếu đã có bản ký. Khi chưa có lịch sử ký, quay lui gỡ riêng bảng/guard S2c. C5 và các kiểm tra phiên bản dùng schema 17.

## Tham chiếu xét nghiệm

`data/danh_muc_goc/chi_so_xet_nghiem_minh_duc.xlsx`: 78 chỉ số, 82 dòng tham chiếu, hai sheet `ChiSo` và `ThamChieu`, đúng cột Excel mẫu M5. Nguồn PDF trang 29–31 được đối chiếu bằng pdftotext; giữ số, chỉ sửa `mmo/L` → `mmol/L`, `109/l` → `10⁹/l`; Nam/Nữ thành dòng riêng. Biểu thức `<` giữ nguyên trong cột giá trị bình thường, không đổi thành cận bao gồm.

Quản trị chọn tệp, xem trước rồi nạp qua M5; không tự nạp khi cài. Script `python -m scripts.build_s2c_assets` dựng lại tài sản công khai, không đụng CSDL.

## Kiểm tại chỗ

Test chữ ký dùng API thật trên SQLite và PostgreSQL: ký, sửa khối in, nhận thông báo, ký lại; dữ liệu không in giữ chữ ký; đổi tên người ký làm chữ ký không khớp. Kiểm cả đọc cũ/ký mới, các lệnh thay thế bản ghi, guard vai trò, tuổi theo ngày sự kiện và Word chuyển PDF bằng LibreOffice. Assertion ngoài chữ ký và phiên bản schema được giữ nguyên. Theo yêu cầu không theo dõi GitHub Actions sau khi đẩy.
