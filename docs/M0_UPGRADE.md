# M0: màn hình bác sĩ, dị ứng thuốc và lượt bỏ dở

Bản này dùng migration 5, thêm duy nhất `patients.allergies TEXT NULL`. Không thêm cột số thứ tự hoặc trạng thái lưu trong CSDL. `results_ready` chỉ là nhãn tính khi đọc hàng chờ.

## Nâng cấp

Dừng dịch vụ, sao lưu và kiểm bản sao lưu theo quy trình hiện có. Chạy `CAP_NHAT.bat` hoặc `python -m scripts.with_env <tệp cấu hình owner> scripts.manage migrate`, cấp lại quyền runtime theo quy trình hiện có rồi khởi động dịch vụ. Không chạy migration bằng tài khoản web. Kiểm `SELECT version FROM schema_migrations ORDER BY version` có phiên bản 5 và đăng nhập lại. SQLite demo tự chạy migration trong giao dịch khi khởi động.

Migration chỉ thêm cột nullable, không sửa hoặc backfill dữ liệu bệnh nhân cũ. Nếu lỗi, giao dịch bị rollback. Khi quay lại mã cũ, giữ nguyên cột và nhật ký; nếu quy trình cập nhật yêu cầu khôi phục thì dùng bản sao lưu đã kiểm và đối soát giao dịch phát sinh. Không tự xóa dị ứng hoặc nhật ký để hạ phiên bản.

## Sử dụng

- Lễ tân chọn người bệnh trong Tiếp đón rồi sửa dị ứng. Bác sĩ bấm **Sửa dị ứng** trên dải thông tin. Có ba lựa chọn: **Chưa khai thác**, **Không dị ứng**, hoặc tên thuốc/phản ứng đã biết. Mỗi thay đổi ghi nhật ký đầy đủ giá trị cũ/mới. Cảnh báo hiện bằng chữ đỏ trên hồ sơ và phần Đơn thuốc, chưa chặn kê đơn.
- Mặc định bác sĩ thấy mọi lượt chưa hoàn tất, kể cả ngày trước; để trống ngày để trở lại danh sách này. Bác sĩ lọc danh sách theo ngày tiếp đón (giờ Việt Nam), tìm tên có dấu hoặc không dấu. Số thứ tự tính từ giờ tiếp đón của toàn phòng khám trong ngày, cùng giờ thì theo mã lượt; lọc không đánh lại số. Lượt đã hủy không hiện. Hoàn tất vẫn xem được khi lọc ngày đó, không tính vào số lượt chưa hoàn tất.
- **F4** tìm người bệnh; **F2** lưu phiếu khám; **F8** hoàn tất theo điều kiện hiện có và vẫn có hộp xác nhận. Phím chỉ tác dụng trong màn hình bác sĩ, không tác dụng khi đang mở hộp thoại hay khi đang tải. **Esc** đóng hộp thoại dị ứng/đóng lượt.
- Lịch sử khám hiển thị ngày, chẩn đoán, đơn thuốc, kết quả/kết luận CLS của các lượt trước mà bác sĩ được phân công. Không mở quyền sang bệnh án bác sĩ khác. Phần Thanh toán chỉ có chữ trạng thái, không có nút thu tiền.
- Lễ tân và bác sĩ phụ trách có nút **Đóng lượt bỏ dở**. Chọn **Người bệnh bỏ về**, **Tạo nhầm** hoặc **Khác** (bắt buộc ghi chú). Chỉ đóng lượt đang mở, không có bất kỳ phiếu thu, khoản phí hoặc lần cấp thuốc nào, kể cả khoản phí 0/chưa có giá/đã hủy hoặc thuốc đã trả. Chỉ định, đơn thuốc, y lệnh còn mở phải xử lý qua quy trình hiện có. Ghi lý do, phiên bản hồ sơ và nhật ký trong cùng giao dịch; dùng trạng thái `cancelled`.
- Tạo lượt hiện tự ghi phí khám. Vì vậy lượt vừa tạo qua Tiếp đón thường phải qua quy trình hủy/hoàn của Quản lý, không dùng đóng bỏ dở để bỏ qua khoản phí đó.

## Kiểm chứng

`tests/test_m0.py`, `lan_tests/test_m0.py` kiểm quyền, nhật ký cũ/mới dài hơn 500 ký tự, các dấu vết tiền/phí/cấp thuốc, ngày Việt Nam và số đếm. `lan_tests/test_m0_browser.py` kiểm chọn lượt, sáu phần hồ sơ, F2/F8, Esc, dị ứng và tràn ngang ở 1366/1280/900/390px; ảnh ở `test_evidence/m0/doctor-1366.png` và `doctor-390.png` được CI tải lên artifact.

Bộ C4 giữ nguyên. Bộ đo `scripts/do_hieu_nang.py` áp dụng migration 5 sau profile mã cũ, trên cùng dữ liệu C5 22.000 lượt; kiểm số dòng, tiền và tồn kho trước/sau migration rồi đo profile mới. Ngưỡng đo C5 giữ nguyên. Số đo Linux không thay cho nghiệm thu Windows 11/i3 tại phòng khám.
