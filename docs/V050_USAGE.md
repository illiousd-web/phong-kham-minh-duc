# Sử dụng Minh Đức LAN v0.5.0 với dữ liệu giả lập

Giữ màn hình xanh ngọc–trắng và các menu cũ. Menu **Quy trình v0.5** bổ sung đối soát theo lượt khám. Dùng tài khoản riêng, không dùng mật khẩu demo trong LAN. Chưa dùng cho bệnh nhân, đơn thuốc hoặc tiền thật trước nghiệm thu độc lập.

## A. Chỉ định và thu tiền

Quản lý tạo dịch vụ tại Danh mục; mã tự sinh nếu để trống. Tại Quy trình v0.5 có thể đổi mã, tên, nhóm, giá và trạng thái hiệu lực. Ngừng dùng chỉ chặn chỉ định mới, chứng từ cũ giữ nguyên.

Bác sĩ chọn dịch vụ có giá trong Chỉ định/kết quả: xác nhận ngay hoặc lưu nháp chưa ghi tiền. Nút **Duyệt chỉ định/ghi phí** ghi đúng một khoản phải thu, kể cả gửi lặp/đồng thời. Kỹ thuật viên chỉ nhập kết quả sau duyệt chỉ định. Bác sĩ phụ trách duyệt kết quả.

Thu ngân thu nhiều lần tại menu Thu ngân; nhận ứng trước tại Quy trình v0.5. Bảng kê chung gồm khám, cận lâm sàng và thuốc. Còn phải thu và tiền ứng dư/cần hoàn được tính riêng. Quản lý điều chỉnh giá có lý do và nhật ký; không ghi đè khoản gốc. Hủy chỉ định phải do bác sĩ đề nghị và quản lý duyệt. Thu ngân đề nghị hoàn tiền hoặc giảm phí tại menu cũ, quản lý độc lập duyệt; không xóa phiếu thu. Phải hoàn tác giảm phí có lý do nếu việc hủy/trả làm giảm phí vượt số tiền còn lại.

## B. Đơn thuốc và kho

Quản lý/dược tạo thuốc thường và lô, hạn dùng; quản lý đặt giá bán mỗi đơn vị cơ sở. Tại Quy trình v0.5, quản lý khai báo đơn vị quy đổi (ví dụ vỉ = 10 viên). Hệ số và tên đơn vị được chụp tại lúc kê, không đổi lịch sử.

Bác sĩ lưu chẩn đoán trước rồi lập đơn cấu trúc, chọn thuốc, đơn vị, số lượng, cách dùng. Dược cấp theo đơn; hệ thống kiểm toàn đơn, xuất FEFO ở lô còn hạn, không cách ly; xuất kho và ghi tiền trong cùng giao dịch. Thiếu một thuốc thì cả đơn không xuất. Gửi cấp lặp bị từ chối và không xuất thêm. Đơn văn bản cũ được giữ để xem/in, không tự chuyển thành lệnh xuất kho.

Đơn nháp chưa cấp có thể hủy có lý do. Phiên bản này giữ một đơn trên mỗi lượt khám; đơn đã hủy được lưu và không tái sử dụng. Khi cần đổi thuốc sau hủy phải xử lý theo quy trình nghiệm thu của phòng khám, không sửa trực tiếp cơ sở dữ liệu.

Thuốc đã cấp: dược mở Quy trình v0.5, chọn dòng/lượng trả và lý do. Quản lý độc lập duyệt. Thuốc trả vào **lô cách ly**, không tự đưa lại tồn bán. Tiền thuốc được giảm theo lượng trả, giữ phiếu cấp và các giá lịch sử; tiền đã thu dư chỉ hoàn qua đề nghị thu ngân/duyệt quản lý. Phiếu trả chờ duyệt giữ số lượng để ngăn nhiều người trả vượt số đã cấp.

Thuốc kiểm soát dùng quyền phụ riêng: `controlled_prescriber` cho bác sĩ kê; `controlled_pharmacy` cho dược nhập/cấp/trả; `controlled_reviewer` cho quản lý danh mục/giá/nhập/trả hoặc bác sĩ duyệt đơn độc lập. Quản trị cấp kèm vai trò gốc, không thay vai trò gốc. Nhập phải có người đề nghị và người duyệt khác nhau. Đơn kiểm soát phải có bác sĩ thứ hai có quyền duyệt, lý do và số sổ tham chiếu. Có hàng đợi duyệt riêng và sổ nhập–cấp–trả. Tài khoản chỉ có quyền thường không thực hiện được nghiệp vụ kiểm soát. Quy trình phần mềm mô phỏng này chưa phải chứng nhận tuân thủ quy định dược, chữ ký hay sổ pháp lý.

## C. Điều dưỡng

Bác sĩ phụ trách phân công điều dưỡng tại Khám bệnh, giao y lệnh tại Quy trình v0.5. Điều dưỡng chỉ thấy lượt được phân công, nhập bảy sinh hiệu, ghi chăm sóc và ghi thực hiện y lệnh. Lưu người thực hiện, nội dung và giờ; không thay chẩn đoán, duyệt kết quả hoặc hoàn tất thay bác sĩ. Nhật ký chăm sóc là các bản ghi bổ sung, không sửa âm thầm. Y lệnh chưa thực hiện phải hoàn thành hoặc bác sĩ hủy có lý do trước khi khóa lượt.

## D. Hoàn tất chuyên môn

Trạng thái gồm chờ khám, đang khám, chờ kết quả, hoàn tất và hủy. Bác sĩ phụ trách hoàn tất khi có chẩn đoán, không còn chỉ định/y lệnh chờ và đơn kiểm soát đã được duyệt. Hệ thống kiểm phiên bản, từ chối thao tác từ màn hình cũ.

Hoàn tất **chuyên môn** không đồng nghĩa đã thanh toán hay đã cấp thuốc. Sau khóa vẫn thu/hoàn tiền và cấp/trả theo chứng từ đã duyệt. Nội dung khám bị khóa tại API và PostgreSQL. Bổ sung/đính chính phải lập phụ lục có lý do; quản lý khác người tạo duyệt, kiểm phiên bản. Hồ sơ gốc giữ nguyên; phiếu khám PDF/Word đính kèm phụ lục được duyệt và thông tin người tạo/duyệt. Đề nghị phụ lục cũ bị từ chối khi phiên bản đã đổi; lập lại sau đối chiếu.

Quản lý hủy lượt có lý do khi các chỉ định đã hủy, y lệnh đã xử lý và thuốc đã đối soát. Khoản thu cũ vẫn còn, tiền cần hoàn hiển thị riêng. Không nhập thêm thu mới vào lượt hủy.
