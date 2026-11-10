# Hồ sơ hành chính và người hành nghề (L1–L2)

Gói này bổ sung trường hồ sơ theo yêu cầu nghiệp vụ dựa trên Thông tư 26/2025/TT-BYT (nội dung đơn thuốc) và Thông tư 25/2026/TT-BYT (mẫu giấy khám sức khỏe). Chưa triển khai ký số. Chỉ dùng dữ liệu giả lập trong mã nguồn, tài liệu, kiểm thử và ảnh minh họa của kho công khai.

## Nâng cấp và quay lại

Sao lưu và xác minh bản sao lưu bằng quy trình hiện hành trước khi nâng cấp. Dừng dịch vụ, cập nhật mã rồi chạy `python -m scripts.manage migrate` bằng tài khoản chủ CSDL như quy trình cài đặt hiện hành; sau đó khởi động lại. Không khởi động bản mới trên CSDL chưa có migration 6. Demo SQLite tự nâng cấp trong giao dịch khi khởi động.

Migration 6 thêm trường vào patients, visits, users và bảng patient_catalog cho danh mục quản trị nạp từ file. Trường mới để trống; phạm vi chuyên môn mặc định là danh sách rỗng. Không suy đoán loại giấy tờ, không sửa số hoặc địa chỉ cũ. Chỉ mục số căn cước cũ chuyển từ duy nhất sang thường để cho phép lưu trùng kèm cảnh báo. Chạy lại migration không đổi dữ liệu.

C5 áp dụng migration 5 và 6 sau lượt đo mã cũ trên cùng bộ dữ liệu; đối chiếu số dòng, tiền và tồn kho trước/sau. Kiểm thử migration riêng còn đối chiếu mọi cột cũ và xuất Word/PDF hồ sơ C5 sau nâng cấp.

Muốn quay lại: dừng dịch vụ và dùng quy trình khôi phục bản sao lưu đã xác minh cùng mã tương ứng trước nâng cấp. Không xóa trường/bảng mới hoặc ép số giấy tờ trùng thành duy nhất; cách đó có thể làm mất dữ liệu mới. Danh mục nằm trong CSDL nên đi cùng bản sao lưu. Công tắc chặn phạm vi nằm trong tệp cài đặt hiện hành và đi cùng bản sao lưu LAN.

## Lễ tân

Ở Tiếp đón, mở hồ sơ đã chọn để bổ sung loại/số giấy tờ, dân tộc, nghề nghiệp, nơi làm việc/học tập và ba phần nơi cư trú. Địa chỉ cũ vẫn hiển thị riêng. Không có giấy tờ thì chọn **Không có**, để trống số. Chọn CCCD/số định danh thì phải nhập đúng 12 chữ số ASCII; hộ chiếu nhập số gồm chữ hoặc số. Trùng số với hồ sơ khác hiện cảnh báo nhưng vẫn lưu.

Ô tìm nhận đủ số giấy tờ và chỉ so số giấy tờ theo toàn bộ chuỗi; các cách tìm tên, mã, điện thoại vẫn giữ nguyên. Danh sách chỉ trả/hiện bốn ký tự cuối. Lễ tân và bác sĩ có quyền xem hồ sơ mới được nhận đủ số trong chi tiết; mỗi lần nhận đủ số có sự kiện `patient_document_viewed`, không ghi số vào nhật ký. Quản trị đơn thuần chỉ nhận số đã che. Điều dưỡng giữ giới hạn hồ sơ như trước. Biểu mẫu xuất che số giấy tờ để không tạo đường lấy đủ số ngoài chi tiết hồ sơ. Launcher demo và LAN đều tắt nhật ký truy cập HTTP để không ghi số được gõ vào ô tìm.

## Quản trị nạp danh mục

Vào **Quản trị → Danh mục → Danh mục hành chính từ tệp**. Nạp CSV UTF-8 hoặc Excel `.xlsx` có đúng một trang tính. File mẫu giả lập: `templates/nhap_lieu/DANH_MUC_HANH_CHINH_GIA_LAP.csv`.

Bốn cột theo thứ tự: `kind,code,name,parent_code`. Mã nên để kiểu văn bản trong Excel để giữ số 0 đầu.

| kind | Ý nghĩa | parent_code |
| --- | --- | --- |
| province | Tỉnh/thành | Để trống |
| commune | Xã/phường/đặc khu | Mã tỉnh/thành có trong cùng file |
| ethnicity | Dân tộc | Để trống |

Mỗi lần nạp thay toàn bộ ba danh mục. File tối đa 2 MB, 20.000 dòng dữ liệu; Excel tối đa 20 MB sau giải nén. Không nhận công thức, ô lỗi, mã trùng trong cùng loại, tên xã trùng trong cùng tỉnh, tên tỉnh/dân tộc trùng trong cùng loại hoặc xã thiếu tỉnh cha. Lỗi báo số dòng và giữ nguyên toàn bộ danh mục trước đó. Tên xã ở hai tỉnh khác nhau được phép trùng. Việc nạp không sửa trường đã lưu trong hồ sơ người bệnh.

Chưa nạp một loại danh mục thì ô tương ứng cho gõ tự do. Đã nạp thì chọn trong danh mục; xã được lọc theo tỉnh đã chọn. Nếu hồ sơ cũ dùng tên ngoài danh mục mới, tên cũ vẫn hiển thị; khi lưu lại cần chọn giá trị hiện hành hoặc để trống.

## Bác sĩ

Hàng chờ và đầu hồ sơ tự hiện tuổi bằng tháng với trẻ dưới 72 tháng, tính theo ngày sinh và ngày hiện tại ở Việt Nam. Trong phần Khám có cân nặng khi khám và họ tên, quan hệ, điện thoại người đưa trẻ. Bấm **Lưu cân nặng và người đưa trẻ** trước khi kê đơn. API chặn lập đơn với trẻ dưới 72 tháng nếu thiếu một trong các trường này; trẻ đủ 72 tháng không bị điều kiện này chặn. Hồ sơ đã khóa không sửa các trường này qua API.

Ngày lọc hàng chờ chỉ nhận 01/01/2000–31/12/2100; ngoài khoảng trả 422. Tab Thanh toán hiện thêm **Cần hoàn: … đồng** khi có tiền phải hoàn; quyền thao tác tiền giữ nguyên.

## Người hành nghề

Vào **Quản trị → Tài khoản**, chọn nhân viên rồi sửa phần **Hồ sơ người hành nghề**: họ tên in, chức danh, số giấy phép, chọn nhiều phạm vi chuyên môn, nhà cung cấp/sê-ri/hạn dùng chứng thư số. Chỉ quản trị được sửa qua API. Mỗi lần lưu ghi đầy đủ giá trị cũ/mới vào nhật ký. Quản trị thấy cảnh báo chứng thư còn dưới 30 ngày hoặc đã hết hạn.

Các đường xuất Word/PDF dùng tên in kèm chức danh từ hồ sơ này; chưa khai thì dùng họ tên tài khoản. Khi duyệt kết quả xét nghiệm mà chưa có phạm vi Xét nghiệm, hoặc siêu âm/X-quang mà chưa có phạm vi Chẩn đoán hình ảnh, API vẫn duyệt, trả cảnh báo và ghi sự kiện `practitioner_scope_warning`; giao diện hiện cảnh báo tại chỉ định. Hàm `has_scope` dùng chung chỉ kiểm phạm vi, không cấp thêm quyền.

Công tắc **Chặn duyệt ngoài phạm vi chuyên môn** trong Cài đặt mặc định tắt. Nếu quản trị bật, API từ chối duyệt thiếu phạm vi bằng 422; kết quả vẫn chờ duyệt. Thông tin chứng thư ở gói này chỉ để mô tả và nhắc hạn.
