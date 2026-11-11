# M5 — Xét nghiệm theo chỉ số

M5 thêm danh mục chỉ số, khoảng tham chiếu, liên kết dịch vụ và kết quả có phiên bản. Không sửa giá, khoản phí, cách duyệt chỉ định hay công thức tiền. Kết quả chữ/tệp trước M5 vẫn xem và in bằng đường cũ. Chỉ dùng dữ liệu giả lập trong mã, kiểm thử và ảnh minh chứng.

## Cấu hình và nâng cấp

Sao lưu, xác minh bản sao trước nâng cấp; dừng dịch vụ LAN, cập nhật mã, chạy `python -m scripts.manage migrate` bằng tài khoản chủ CSDL, rồi khởi động. Migration 9 chạy giao dịch trên SQLite/PostgreSQL, chạy lại không tạo trùng. Chỉ thêm năm bảng thuộc phạm vi danh mục/tham chiếu/liên kết/kết quả: `lab_tests`, `lab_reference_ranges`, `lab_service_tests`, `lab_reports`, `lab_results`. Không sửa/xóa dữ liệu hay schema bảng cũ. Quay lại bằng mã và bản sao CSDL tương ứng đã xác minh.

Quản trị mở **Chỉ số xét nghiệm**. Khung có 22 chỉ số huyết học, 18 sinh hóa và 10 thông số nước tiểu, chỉ gồm tên/viết tắt/đơn vị thường dùng/thứ tự. Cần rà lại với máy và phương pháp tại cơ sở. Các thông số nước tiểu ban đầu kiểu Chữ để không tự đoán loại kết quả/danh sách của máy. Có thể đổi sang Số hoặc Định tính chọn danh sách. Không có khoảng tham chiếu y khoa nạp sẵn; màn hình và bản in ghi **Chưa có khoảng tham chiếu** khi không tìm được dòng phù hợp.

Chọn chỉ số để sửa đơn vị, số chữ số thập phân, thứ tự, loại kết quả, lựa chọn định tính, tham chiếu, trạng thái dùng/ngừng. Không có thao tác xóa chỉ số đã dùng. Liên kết từng dịch vụ xét nghiệm đang có với các chỉ số; thao tác này không nhập/sửa giá. Liên kết thay đổi chỉ tác động phiếu lập sau đó, không thay danh sách chỉ số trên phiếu đã mở.

### Excel

Tệp rỗng: [DANH_MUC_CHI_SO_RONG.xlsx](../templates/nhap_lieu/DANH_MUC_CHI_SO_RONG.xlsx). Hai sheet, tiêu đề dòng 1:

- `ChiSo`: Mã chỉ số, Tên chỉ số, Viết tắt, Nhóm, Kiểu kết quả, Đơn vị, Số thập phân, Thứ tự in, Đang dùng, Lựa chọn (mỗi dòng một giá trị).
- `ThamChieu`: Mã chỉ số, Giới, Tuổi từ (tháng), Tuổi đến (tháng), Cận dưới, Cận trên, Giá trị bình thường.

Nhóm: Huyết học/Sinh hóa/Nước tiểu/Khác. Kiểu: Số/Định tính/Chữ. Đang dùng: 1 hoặc 0. Giới: Nam/Nữ/chung. Tuổi/cận có thể để trống; không tạo dòng tham chiếu nếu chưa có dữ liệu được cơ sở kiểm chứng. Mỗi dòng cần ít nhất một cận số hoặc một giá trị bình thường. Không nhập cả hai loại trong một dòng. Cùng chỉ số/giới không được có khoảng tuổi chồng lấn. Mã tham chiếu phải có ở sheet ChiSo.

Xem trước kiểm toàn bộ tệp nhưng chỉ vẽ tối đa 50 dòng đầu. Lỗi có sheet/số dòng; thiếu cột nêu tên cột. Không nhận công thức, ô lỗi hay tệp vượt 2 MB/20 MB giải nén/10.000 dòng mỗi sheet. Chỉ khi toàn bộ hợp lệ mới nạp trong một giao dịch. Cập nhật theo mã, giữ nguyên chỉ số không có trong tệp; muốn ngừng dùng phải đặt 0. Tham chiếu của mã xuất hiện trong tệp được thay bằng toàn bộ dòng tham chiếu của mã đó trong tệp. Xuất Excel có cả danh mục và tham chiếu; không xuất người bệnh hay kết quả. Mọi lần nạp/sửa/liên kết đều có nhật ký.

## Nhập, duyệt và điều chỉnh

Kỹ thuật viên mở **Xét nghiệm theo chỉ số**, chọn chỉ định đã được xác nhận qua luồng cũ, lập phiếu. Dịch vụ chưa liên kết chỉ số báo cần Quản trị cấu hình. Chưa có chỉ định hoặc chỉ định chưa duyệt/đã hủy không được nhập M5. Luồng chữ/tệp cũ vẫn dành cho hồ sơ chưa chuyển sang phiếu M5; không cho sửa phiếu M5 qua API cũ.

Nhập thời điểm lấy mẫu/có kết quả theo giờ Việt Nam `dd/mm/yyyy HH:mm`. Người thực hiện là kỹ thuật viên lưu phiếu. Ô số có bàn phím thập phân, nhận dấu phẩy hoặc chấm, không nhận NaN/vô cực. Nhập giá trị, ghi chú mỗi chỉ số và nhận xét chung; lưu nháp trước khi gửi chờ duyệt. Gửi cần đủ chỉ số và hai thời điểm, kết quả không được sớm hơn lấy mẫu. Kiểm phiên bản tránh ghi đè khi hai người cùng mở.

Tuổi là số tháng tròn tại **ngày lấy mẫu ở Việt Nam**, xét cả ngày sinh. Khoảng tuổi bao gồm hai đầu. Dòng đúng giới ưu tiên hơn dòng chung; không suy đoán giới hay tuổi khi thiếu dữ liệu. Thiếu ngày sinh chỉ áp dụng tham chiếu không giới hạn tuổi. Số nhỏ hơn cận dưới gắn L, lớn hơn cận trên gắn H; bằng cận không gắn cờ. Định tính/chữ so với giá trị bình thường (bỏ khoảng trắng hai đầu, không phân biệt hoa thường). Không có tham chiếu phù hợp thì không gắn cờ. Độ chính xác cờ dùng số đã nhập trước làm tròn hiển thị, số thập phân cấu hình dùng khi trình bày/in.

Bác sĩ phụ trách lượt khám có vai trò bác sĩ hiện có duyệt, không thêm vai trò. Màn hình khám/API xem kết quả thông thường chỉ hiện **Đang làm** cho phiếu chưa duyệt, không trả số liệu. Nút **Duyệt phiếu theo chỉ số** mở màn hình duyệt riêng; chỉ bác sĩ phụ trách được truy cập endpoint `/review`, có audit mở để duyệt. Người duyệt cần xem dữ liệu để đánh giá trước khi bấm **Duyệt và khóa phiếu**. Cảnh báo phạm vi Xét nghiệm L2 được giữ nguyên (chỉ chặn nếu cài đặt chặn hiện có đã bật); không cấp thêm quyền từ phạm vi chuyên môn.

Khi duyệt, snapshot lưu thông tin người bệnh, danh sách chỉ số/đơn vị, giá trị, ghi chú, tham chiếu đã chọn, cờ, người thực hiện/duyệt và thời điểm. Sửa danh mục/tham chiếu/hồ sơ sau đó không đổi snapshot hoặc bản in phiếu cũ. Tài khoản có quyền kỹ thuật viên mới sửa nháp/lập điều chỉnh; lễ tân chỉ xem/in phiếu đã duyệt. Quản trị sửa danh mục nhưng không nhập/duyệt kết quả nếu không có vai trò tương ứng.

Sau duyệt, dùng **Tạo phiếu điều chỉnh**, bắt buộc lý do ít nhất 8 ký tự sau bỏ khoảng trắng. Tạo bản mới cùng chỉ định, sao chép chỉ số/giá trị để sửa; bản cũ không bị sửa/xóa. Mỗi bản chỉ có một bản điều chỉnh kế tiếp, có thể tiếp tục tạo chuỗi từ bản mới đã duyệt. Khi bản mới còn nháp/chờ duyệt, kết quả đã duyệt gần nhất vẫn được giữ; khi duyệt bản mới, màn khám/lịch sử chỉ số mặc định dùng bản mới nhất đã duyệt, vẫn xem/in được bản cũ. Bản mới in **BẢN ĐIỀU CHỈNH, thay thế phiếu XN-…**, có lý do. Không ghi số giấy tờ vào audit; lý do audit được che số giấy tờ.

## Xem, in và hàng chờ

Màn hình khám M0 có bảng kết quả theo chỉ số, cờ bất thường tô nổi bật, nút lịch sử chỉ số theo ngày/giá trị/cờ trong phạm vi các lượt bác sĩ được giao. Không mở rộng quyền xem hồ sơ bác sĩ khác.

Word lấy khung A4/đầu trang/chân trang của `04_Phieu_ket_qua_xet_nghiem_A4.docx`, điền phần người bệnh và bảng năm cột **Tên chỉ số | Kết quả | Cờ | Khoảng tham chiếu | Đơn vị**. Word và PDF dùng cùng mô hình nội dung; chỉ số có ghi chú được in cùng tên. Mỗi nhóm có tệp riêng, chỉ nhóm thực sự có trên phiếu mới được in. Thể hiện mã phiếu/chỉ định, người bệnh/địa chỉ, lấy mẫu, có kết quả, người thực hiện/duyệt và thời điểm duyệt. Nháp in **NHÁP – CHƯA DUYỆT**, chỉ kỹ thuật viên in nháp. Lễ tân chỉ có nút in phiếu đã duyệt.

Hàng chờ dùng SQL cho cả danh sách và COUNT, phân trang 30 dòng. Giai đoạn: chưa có lấy mẫu → Chờ lấy mẫu; có mẫu nhưng chưa gửi → Đang làm; đã gửi → Chờ duyệt; đã khóa → Đã duyệt. Chỉ định chữ/tệp cũ đã gửi/duyệt không bị coi là phiếu M5 chờ lấy mẫu. API lễ tân luôn giới hạn đã duyệt. Nhật ký nhập/sửa/gửi nháp, mở duyệt, duyệt, điều chỉnh/lý do, in, lịch sử và sửa danh mục/tham chiếu/liên kết.

## Chừa kết nối máy

`LabResultSource.receive(order_id=...)` trả `ResultInput` gồm phiên bản, thời điểm và danh sách `test_id/value/note`. `FakeLabResultSource` chỉ cấp bản sao dữ liệu giả lập trong test, không gọi mạng và không tự ghi/duyệt. Khi tích hợp máy sau này cần xác định: hãng/model/protocol và tài liệu ASTM/HL7, cổng/kết nối LAN, mã mẫu ↔ chỉ định, ánh xạ mã chỉ số/đơn vị/độ chính xác, thông điệp chất lượng/lỗi, chống trùng bản tin và thời gian/múi giờ. Adapter thật phải qua cùng kiểm giá trị/phiên bản/quyền, có truy vết nguồn; không tự duyệt.

**Chưa làm:** kết nối máy thật ASTM/HL7, khoảng tham chiếu y khoa thật, ký số, nghiệm thu trên máy in/máy xét nghiệm/máy chủ thực tế. Cơ sở chịu trách nhiệm nhập và rà soát tham chiếu đúng máy/phương pháp trước khi dùng; phần mềm không sinh số liệu y khoa.
