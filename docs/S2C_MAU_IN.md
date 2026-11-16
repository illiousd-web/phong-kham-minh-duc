# S2c — Mẫu in và ký bằng ảnh chữ ký

Nguồn: `docs/ui-mau/BoMau_33_ban_repo.pdf`, trang 29–33. Nhánh `feat/s2c-mau-in`, gốc `9647e1e`.

- Trang 29: hóa sinh máu, MS 22/BV-02, hai cụm Xét nghiệm / Trị số bình thường / Kết quả.
- Trang 30: huyết học, MS 17/BV-02, một cụm ba cột.
- Trang 31: hóa sinh nước tiểu, MS 23/BV-02, một cụm ba cột.
- Trang 32: phiếu chỉ định nội khoa, đánh dấu theo các chỉ định còn hiệu lực của lượt khám.
- Trang 33: đơn thuốc A4, ô mã quốc gia để trống; không in mã nội bộ vào ô này.

Đầu phiếu dùng `clinic_profile`. Để trống cài đặt thì đầu phiếu cũng trống. Logo in được dựng từ SVG công khai có sẵn trong `app/static`. Không có danh tính cơ sở, bệnh nhân hoặc ảnh chữ ký thật trong các tệp mới.

Các mẫu chung, M5 và M6 dùng chung mô hình nội dung và bộ dựng Word/PDF. Giữ đủ thuốc, kết quả, ghi chú và nội dung điều chỉnh. Nội dung thông thường gọn một trang A4. Nội dung dài tự sang trang tiếp theo, giữ nguyên cỡ chữ và toàn bộ nội dung; không từ chối in vì độ dài. Trang tiếp theo lặp họ tên, mã NB, số phiếu/mã đơn nội bộ; mọi trang có `Trang x/y`. Bảng chỉ số lặp tiêu đề cột. Khối ký và ảnh ký chỉ ở trang cuối, cùng dòng cuối nội dung. PDF dùng khung trang tiếp nối và bộ đếm tổng trang; Word dùng đầu trang đầu/tiếp nối, trường PAGE/NUMPAGES và hàng tiêu đề bảng lặp. Ô mã đơn quốc gia ở trang đầu vẫn để trống. Trẻ dưới 72 tháng thiếu cân nặng không được in hoặc ký đơn; giữ nguyên các điều kiện lưu/khóa đơn hiện có.

## Ký phiếu

Bác sĩ kê đơn/chỉ định hoặc chính bác sĩ đã duyệt phiếu xét nghiệm bấm **Ký**, nhập lại mật khẩu. API chọn người ký và ảnh từ tài khoản đang xác thực; không nhận `signed_by` hay ảnh do trình duyệt gửi.

Mỗi lần ký lưu người ký, thời điểm, SHA-256 của mô hình nội dung, tên tài khoản và bản sao ảnh chữ ký tại thời điểm ký. Mỗi lần ký có audit riêng. Thay ảnh chữ ký hiện hành không thay ảnh trên bản đã ký.

Khi in, chữ ký chỉ hiện nếu đúng người chịu trách nhiệm, phiếu còn hiệu lực và mã băm khớp chính nội dung đưa vào bản in. Dưới ảnh ghi giờ Việt Nam: `Ký lúc HH:MM dd/mm/yyyy bởi tài khoản …`.

Sửa các trường nội dung in của hồ sơ nguồn làm bản ký mất hiệu lực vĩnh viễn, kể cả sửa lại giá trị cũ. Chỉ tăng phiên bản, hoàn tất lượt hoặc chuyển trạng thái cấp thuốc không làm mất chữ ký khi nội dung in giữ nguyên. Cần ký lại. Phiếu M5 điều chỉnh vẫn đi qua duyệt như trước; bản mới không kế thừa chữ ký bản cũ.

## Migration 017–018

Migration 017 bổ sung `document_signatures`. Migration 018 nâng cấp từ 017: thay đổi chỉ định vô hiệu mọi phiếu chỉ định đã ký của cùng lượt vì mỗi phiếu in gộp các chỉ định chưa hủy; phiếu xét nghiệm và đơn vẫn được giới hạn theo loại và mã tài liệu. Thay đổi thông tin in của người hành nghề chỉ vô hiệu bản ký có liên quan đến người đó: người ký, bác sĩ in trên phiếu, người thực hiện hoặc người duyệt xét nghiệm; hồ sơ lượt khám, người bệnh và cơ sở vẫn áp dụng rộng. Bản ký chỉ được cập nhật `invalidated` một chiều 0 → 1; không được sửa cột khác hoặc xóa. Vai trò `clinic_app` chỉ được cập nhật cột `invalidated`. Cả SQLite và PostgreSQL đều có trigger bảo vệ. Quay lui riêng 018 bằng `scripts.manage rollback-s2c-018` với kết nối chủ sở hữu khôi phục trigger 017, nhưng bị từ chối nếu đã có bản ký. Luồng xem/in chỉ kiểm mã băm và trả về không có chữ ký khi không khớp, không ghi trạng thái bản ký. Việc vô hiệu chỉ xảy ra ở trigger của thao tác sửa nguồn; vì vậy yêu cầu đọc cũ hoàn tất sau khi ký bản mới không thể làm mất bản ký mới. Nâng cấp lặp lại không thêm bản ký hoặc nạp tham chiếu. Quay lui 017 chỉ được thực hiện khi chưa có lịch sử ký; nếu đã có, migration từ chối để giữ bằng chứng.

Bộ chuẩn bị C5 được cập nhật migration 018 và bảng ký rỗng; không thay phép đo, dữ liệu đo hoặc ngưỡng đạt. Quyền bảng ký và cài LibreOffice trong CI được cập nhật theo yêu cầu; không đổi logic kê đơn, duyệt xét nghiệm hoặc thuốc kiểm soát.

## Tệp tham chiếu tùy chọn

`data/danh_muc_goc/chi_so_xet_nghiem_minh_duc.xlsx`: 78 chỉ số, 82 dòng tham chiếu, hai sheet `ChiSo` và `ThamChieu`, đúng cột của nút **Tải Excel mẫu rỗng** M5.

Nguồn được đối chiếu bằng `pdftotext -f 29 -l 31 -layout`. Giữ nguyên con số và đơn vị; chỉ sửa lỗi gõ `mmo/L` thành `mmol/L` và quy ước `109/l` thành `10⁹/l`. Không sửa các giá trị đáng ngờ như C.peptide `0.37 – 1.47 mmol/L`, CRP `< 10 mg/dl`, pH `5.0`, tỷ trọng `1.010`. Nam/Nữ tách thành các dòng tham chiếu riêng.

Mẫu M5 hiện chỉ có cận số bao gồm hai đầu. Để giữ đúng dấu `<` của PDF, dùng cột **Giá trị bình thường** với biểu thức nguyên văn, ví dụ `< 6.5`; bộ đánh giá số hỗ trợ riêng biểu thức này. Không đổi `<` thành `≤` hoặc tự trừ một lượng nhỏ khỏi cận. Các tham chiếu dạng chữ/ghi chú giữ nguyên nguồn; không suy diễn thêm khoảng y khoa.

Quản trị mở **Danh mục chỉ số xét nghiệm**, chọn tệp, bấm **Xem trước**, kiểm tra rồi tích **Nạp sau khi đã xem trước đúng tệp** và nạp. Không tự nạp khi cài hoặc khởi động. Chỉ số dùng mã theo nhóm để phân biệt glucose máu với glucose nước tiểu; cần liên kết các chỉ số được chọn vào dịch vụ theo luồng M5 sẵn có.

Có thể dựng lại tài sản bằng `python -m scripts.build_s2c_assets` trong môi trường kiểm thử có PyMuPDF. Script chỉ ghi các template, logo dẫn xuất và Excel công khai, không đụng CSDL.

## Căn cứ cập nhật assertion cũ

- `tests/m5_cases.py`: trang 29–31 có `Xét nghiệm / Trị số bình thường / Kết quả`, không còn năm cột cũ. Đơn vị nằm cùng tham chiếu; ↑/↓ nằm cùng kết quả.
- `tests/m6_cases.py`: đọc cả đầu trang đầu của Word khi bật đầu trang tiếp nối; giữ nguyên mọi assertion nội dung. Trang 33 đặt thông tin cơ sở ở đầu và ô mã quốc gia để trống; tiêu đề `ĐƠN THUỐC`, khối ký `BÁC SĨ KHÁM BỆNH`. Kiểm mã nội bộ trong JSON vẫn giữ nguyên.
- `lan_tests/test_mot_ngay_kham.py`: tiêu đề trang 33 là `ĐƠN THUỐC`; vẫn kiểm đúng người bệnh và các phép đối chiếu nghiệp vụ cũ.

- `tests/test_s2a.py`: đầu đơn ở trang 33 không có cơ quan chủ quản; vẫn kiểm tên, địa chỉ, điện thoại, email từ cài đặt và không còn tên cơ sở ghi cứng.
- `tests/administrative_revision_cases.py`: trang 33 đặt địa chỉ trong bảng người bệnh, trước chẩn đoán/thuốc; vẫn kiểm nguyên địa chỉ và vị trí, không còn yêu cầu dòng nghề nghiệp vốn không nằm trong mẫu đơn mới.
- `tests/test_s1_prescription.py`: đọc cả đoạn và bảng theo trang 33; giữ nguyên assertion liều `0,75 viên`.
- `tests/test_v041_fixes.py`: trang 29–31 chỉ có khối ký Trưởng khoa xét nghiệm; tên người thực hiện/duyệt vẫn được kiểm, và phiếu đã duyệt không có dấu nháp.
- `lan_tests/test_lan.py`: theo yêu cầu sửa bắt buộc PR #40, bỏ nhánh chấp nhận 422 và kiểm một trang cho nội dung dài. Phiếu khám, xét nghiệm và đơn dài phải giữ đủ TAIL_MARKER ở PDF/Word, nhiều trang, ký ở cuối, mọi trang có `Trang x/y`. Word còn được chuyển sang PDF để kiểm bố cục khi có LibreOffice.
- `tests/test_s2c_pagination.py`: ba nhóm 60 chỉ số, đơn 25 thuốc, lời dặn/ô cách dùng dài và chỉ định dài; kiểm mọi dòng, định danh lặp, tiêu đề bảng, ảnh ký chỉ trang cuối và cùng dòng nội dung cuối. `test_all_three_complete_lab_groups_and_five_medicines_fit_one_a4` vẫn kiểm một trang A4 cho nội dung thông thường, cả PDF trực tiếp và Word chuyển sang PDF.
- `lan_tests/test_s2a.py`, `lan_tests/test_v050_migration.py`: nâng kiểm phiên bản chính xác từ 16 lên 18 theo migration S2c; giữ toàn bộ kiểm dữ liệu cũ/khôi phục và kiểm thêm bảng ký, tham chiếu đều rỗng sau nâng cấp.
