# Hồ sơ hành chính và người hành nghề (L1–L2)

Gói này bổ sung trường hồ sơ theo yêu cầu nghiệp vụ dựa trên Thông tư 26/2025/TT-BYT (nội dung đơn thuốc) và Thông tư 25/2026/TT-BYT (mẫu giấy khám sức khỏe). Chưa triển khai ký số. Người bệnh, nhân viên, giấy phép, tiền và chứng từ trong kiểm thử đều giả lập. Hai file danh mục địa giới/dân tộc công khai do chủ dự án cung cấp được phép nằm trong repo; không dùng dữ liệu người bệnh thật.

## Nâng cấp và quay lại

Sao lưu và xác minh bản sao lưu bằng quy trình hiện hành trước khi nâng cấp. Dừng dịch vụ, cập nhật mã rồi chạy `python -m scripts.manage migrate` bằng tài khoản chủ CSDL như quy trình cài đặt hiện hành; sau đó khởi động lại. Không khởi động bản mới trên CSDL chưa có migration 7. Demo SQLite tự nâng cấp trong giao dịch khi khởi động.

Migration 6 thêm trường vào patients, visits, users và bảng patient_catalog. Migration 7 thêm mã tham chiếu trong hồ sơ người bệnh và thông tin danh mục (tên gọi khác, huyện cũ, nguồn mã, mã ĐVHC chính thức, trạng thái dùng); tự nạp danh mục có sẵn. Trường mới để trống; phạm vi chuyên môn mặc định là danh sách rỗng. Không suy đoán loại giấy tờ, không sửa số hoặc địa chỉ cũ. Chỉ mục số căn cước cũ chuyển từ duy nhất sang thường để cho phép lưu trùng kèm cảnh báo. Chạy lại migration không đổi dữ liệu.

C5 áp dụng migration 5, 6 và 7 sau lượt đo mã cũ trên cùng bộ dữ liệu; đối chiếu số dòng, tiền và tồn kho trước/sau; tính riêng 3.411 mục danh mục cùng một dòng nhật ký khởi tạo được thêm đúng dự kiến. Kiểm thử migration riêng còn đối chiếu mọi cột cũ và xuất Word/PDF hồ sơ C5 sau nâng cấp.

Muốn quay lại: dừng dịch vụ và dùng quy trình khôi phục bản sao lưu đã xác minh cùng mã tương ứng trước nâng cấp. Không xóa trường/bảng mới hoặc ép số giấy tờ trùng thành duy nhất; cách đó có thể làm mất dữ liệu mới. Danh mục nằm trong CSDL nên đi cùng bản sao lưu. Công tắc chặn phạm vi nằm trong tệp cài đặt hiện hành và đi cùng bản sao lưu LAN.

## Lễ tân

Ở Tiếp đón, mở hồ sơ đã chọn để bổ sung loại/số giấy tờ, dân tộc, nghề nghiệp, nơi làm việc/học tập và ba phần nơi cư trú. Địa chỉ cũ vẫn hiển thị riêng. Không có giấy tờ thì chọn **Không có**, để trống số. Chọn CCCD/số định danh thì phải nhập đúng 12 chữ số ASCII; hộ chiếu nhập 6–40 ký tự gồm chữ hoặc số. Trùng số với hồ sơ khác hiện cảnh báo nhưng vẫn lưu.

Ô tìm nhận đủ số giấy tờ và chỉ so số giấy tờ theo toàn bộ chuỗi; các cách tìm tên, mã, điện thoại vẫn giữ nguyên. Số giấy tờ dài hơn bốn ký tự chỉ hiện bốn ký tự cuối; số cũ có tối đa bốn ký tự được che toàn bộ bằng `••••`. Lễ tân và bác sĩ có quyền xem hồ sơ mới được nhận đủ số trong chi tiết; mỗi lần nhận đủ số có sự kiện `patient_document_viewed`, không ghi số vào nhật ký. Quản trị đơn thuần chỉ nhận số đã che. Điều dưỡng giữ giới hạn hồ sơ như trước. Biểu mẫu xuất che số giấy tờ để không tạo đường lấy đủ số ngoài chi tiết hồ sơ. Launcher demo và LAN đều tắt nhật ký truy cập HTTP để không ghi số được gõ vào ô tìm.

Biểu mẫu dùng địa chỉ cấu trúc theo thứ tự chi tiết, xã/phường, tỉnh/thành; thiếu toàn bộ địa chỉ cấu trúc mới dùng địa chỉ cũ. Thông tin hành chính nằm trong phần người bệnh, không nối cuối Word.

API cập nhật dùng `PATCH /api/patients/{id}/administrative`: chỉ gửi trường cần sửa; trường không gửi giữ nguyên, gửi `null` để xóa rõ ràng. Gửi rỗng trả 422. PUT cũ chỉ nhận khi gửi đủ mọi trường hành chính, gồm cả `citizen_id` và các mã danh mục; thiếu trường trả 422. Nhật ký `patient_administrative_updated` ghi tên trường thực sự đổi; chỉ nghề nghiệp, dân tộc, tỉnh, xã có giá trị cũ/mới. Không ghi giá trị số giấy tờ. Lượt sửa tiếp này không thêm migration hoặc đổi schema.

## Danh mục có sẵn và nạp lại

Phần mềm tự nạp **34 tỉnh, 3.321 xã và 54 dân tộc** khi migrate/cài đặt. Nguồn Excel và CSV UTF-8 ở `du_lieu/danh_muc/`; không cần nạp tay dân tộc khi cài mới. Kiểm thử đối chiếu trực tiếp CSV với cả hai file Excel, số lượng và mã không trùng.

Lễ tân chọn tỉnh rồi gõ tên xã không dấu để tìm; ví dụ `cat thanh` ra **Xã Cát Thành**, `phuong nam dinh` ra **Phường Nam Định** khi chọn **Tỉnh Ninh Bình**. Mỗi lần chỉ tải tối đa 30 xã trong tỉnh đã chọn. Đổi tỉnh sẽ xóa lựa chọn xã cũ. Quản trị đặt **Tỉnh/thành mặc định của phòng khám** ở Cài đặt; chỉ áp dụng cho hồ sơ mới, không điền lại hồ sơ cũ.

Ô dân tộc tìm theo tên chính và tên gọi khác: `viet` có **Kinh** (Việt), `tho` có **Tày** (Thổ…). Tên gọi khác hiện mờ bên cạnh. Mặc định để trống, không mặc định Kinh. Có thêm **Người nước ngoài** (`FOREIGN`) và **Không rõ** (`UNKNOWN`), tách khỏi mã `01`–`54`. Mã luôn là chuỗi có số 0 đầu.

Mã xã từ file được lưu đúng dưới nguồn **mã thuế TMS**. Đây không phải mã ĐVHC chính thức. Cột mã ĐVHC chính thức ban đầu để trống; không suy đoán hoặc chuyển mã TMS thành mã chính thức. Huyện cũ chỉ để tham khảo, không phải một cấp cư trú hiện tại.

Khi có nguồn cập nhật, vào **Quản trị → Danh mục → Nạp lại danh mục**. Chọn Tỉnh/xã hoặc Dân tộc và tệp công khai mới. Bỏ trống tệp để nạp lại bản đi kèm; chọn **Cả hai bản đi kèm** để khôi phục danh mục chuẩn sau khi chọn nhầm nguồn. Chỉ quản trị được gọi API nạp lại. Mọi lần nạp lại có nhật ký số thêm, cập nhật và ngừng dùng.

Excel tỉnh/xã có tiêu đề dòng 3, dữ liệu từ dòng 4; CSV có tiêu đề dòng 1. Tìm cột theo tên, bỏ khoảng trắng hai đầu: **Mã tỉnh (BNV)**, **Tên tỉnh/TP mới**, **Mã phường/xã mới**, **Tên Phường/Xã mới**, **Tên Quận huyện TMS (cũ)**. Cột tùy chọn **Mã ĐVHC chính thức** dùng cho nguồn chính thức được nạp sau. Excel/CSV dân tộc có tiêu đề dòng 1: **Mã dân tộc**, **Tên dân tộc**, **Tên gọi khác**.

File tối đa 2 MB, 20.000 dòng; Excel tối đa 20 MB sau giải nén và đúng một trang tính. Thiếu cột báo rõ tên cột; trùng mã hoặc dữ liệu lỗi báo số dòng, không nạp dở. Tên xã có thể trùng giữa các tỉnh, không trùng trong cùng tỉnh. Danh mục đi kèm được kiểm cứng đúng số lượng hiện tại; file cập nhật do quản trị nạp có thể thay đổi số lượng khi địa giới thay đổi.

Nạp lại cập nhật theo mã; mục bị bỏ được đánh dấu **ngừng dùng**, không xóa. Tên và mã đã lưu trong hồ sơ cũ giữ nguyên, kể cả mục đã ngừng dùng. Không tự gán mã dân tộc hoặc sửa nơi cư trú cho hồ sơ cũ; chọn lại danh mục chỉ khi có thông tin và thao tác rõ ràng của người dùng. Mục ngừng dùng không xuất hiện khi tìm để lập hồ sơ mới. Danh mục và mã tham chiếu nằm trong CSDL, đi cùng sao lưu/khôi phục; tỉnh mặc định nằm trong tệp cài đặt đã có cơ chế sao lưu.

## Bác sĩ

Hàng chờ và đầu hồ sơ tự hiện tuổi bằng tháng với trẻ dưới 72 tháng, tính theo ngày sinh và ngày hiện tại ở Việt Nam. Trong phần Khám có cân nặng khi khám và họ tên, quan hệ, điện thoại người đưa trẻ. Bấm **Lưu cân nặng và người đưa trẻ** trước khi kê đơn. API chặn lập đơn với trẻ dưới 72 tháng nếu thiếu một trong các trường này; trẻ đủ 72 tháng không bị điều kiện này chặn. Hồ sơ đã khóa không sửa các trường này qua API.

Ngày lọc hàng chờ chỉ nhận 01/01/2000–31/12/2100; ngoài khoảng trả 422. Tab Thanh toán hiện thêm **Cần hoàn: … đồng** khi có tiền phải hoàn; quyền thao tác tiền giữ nguyên.

## Người hành nghề

Vào **Quản trị → Tài khoản**, chọn nhân viên rồi sửa phần **Hồ sơ người hành nghề**: họ tên in, chức danh, số giấy phép, chọn nhiều phạm vi chuyên môn, nhà cung cấp/sê-ri/hạn dùng chứng thư số. Chỉ quản trị được sửa qua API. Mỗi lần lưu ghi đầy đủ giá trị cũ/mới vào nhật ký. Quản trị thấy cảnh báo chứng thư còn dưới 30 ngày hoặc đã hết hạn.

Các đường xuất Word/PDF dùng tên in kèm chức danh từ hồ sơ này; chưa khai thì dùng họ tên tài khoản. Khi duyệt kết quả xét nghiệm mà chưa có phạm vi Xét nghiệm, hoặc siêu âm/X-quang mà chưa có phạm vi Chẩn đoán hình ảnh, API vẫn duyệt, trả cảnh báo và ghi sự kiện `practitioner_scope_warning`; giao diện hiện cảnh báo tại chỉ định. Hàm `has_scope` dùng chung chỉ kiểm phạm vi, không cấp thêm quyền.

Công tắc **Chặn duyệt ngoài phạm vi chuyên môn** trong Cài đặt mặc định tắt. Nếu quản trị bật, API từ chối duyệt thiếu phạm vi bằng 422; kết quả vẫn chờ duyệt. Thông tin chứng thư ở gói này chỉ để mô tả và nhắc hạn.
