# D0 — Danh mục gốc dùng chung

Năm tệp công khai được chủ dự án cho phép đưa vào `data/danh_muc_goc/`, giữ nguyên UTF-8 BOM và SHA-256 (gitattributes tắt đổi xuống dòng). Xem [sổ đăng ký](SO_DANG_KY_VAN_BAN.md) để biết tên, số dòng, hash, nguồn và các ngày còn cần đối chiếu. Không có dữ liệu người bệnh, nhân viên, bảng giá hay thuốc thật trong các tệp này.

## Cài đặt và cập nhật

Sao lưu đã xác minh, nâng cấp bằng quy trình hiện có. LAN chạy `python -m scripts.manage migrate` bằng chủ CSDL trước khi web khởi động. Migration 10 tạo nền danh mục; migration 11 mở rộng đúng cấu trúc nguồn và tự nạp đủ 5 tệp trong một giao dịch. Chạy lại không nạp trùng. Không đổi giá, tiền, vai trò hay quyền. Bộ cài/cập nhật vẫn bỏ qua data nói chung, chỉ chép đúng năm CSV công khai đã kiểm SHA-256. Khi nâng cấp từ main cũ, sao lưu trước rồi mở PowerShell bằng quyền Quản trị và chạy trực tiếp `deploy/windows/CapNhat.ps1` từ bộ mới giải nén, chỉ rõ `-ThuMucMa` là thư mục đã cài và `-TepZip` là ZIP mới. Không bấm batch từ thư mục giải nén vì batch lấy thư mục chứa nó làm đích cập nhật. Sau lần nâng cấp này, dùng CAP_NHAT.bat trong thư mục đã cài như thường lệ. Không tự gắn mã cho dịch vụ/chỉ số hoặc đoán mã bệnh của hồ sơ cũ.

ICD 15.844, CLS 2.964, PL01 19.438, PL02 9.128, xã chính thức 3.321. Ghi số/ngày văn bản, nguồn, phiên bản, số dòng, SHA-256 và audit mỗi lần nạp. CSV không có ngày ban hành đầy đủ: NULL có nghĩa “Chưa đối chiếu ngày”; không dùng ngày hôm nay hoặc suy từ tên tệp. Các mục đã có liên kết mà bị bỏ khỏi phiên bản mới chỉ ngừng dùng, không xóa hồ sơ lịch sử.

Ví dụ đường dẫn giả lập cho bản cài mặc định (thay đường dẫn tệp tải về theo máy):

```powershell
& "C:\BoMoi\deploy\windows\CapNhat.ps1" -ThuMucMa "C:\MinhDuc" -TepZip "C:\BoMoi.zip"
```

## Nạp lại

Quản trị → Danh mục D0. Chọn đúng loại (PL01 và PL02 riêng), nhập metadata, chọn nguyên tệp gốc. CSV nguồn được nhận diện theo cột gốc; không ánh xạ sửa mã/tên. Danh mục nghề nghiệp chưa có file chuẩn, vẫn có mẫu nhập rỗng và ánh xạ cột Excel/CSV.

Bấm **Xem trước**. Tất cả dòng được kiểm, hiển thị tối đa 30 dòng và tổng số. Sau thành công mới hiện xác nhận. Mã vân tay SHA-256 ràng buộc bytes + loại + metadata + ánh xạ/dòng tiêu đề; bước ghi cần bằng chứng đã xem của cùng tài khoản. Đổi tệp/loại/metadata sau xem trước phải xem lại. Lỗi có số dòng/tên cột, không ghi dở.

Tệp danh mục tối đa 12 MB, toàn yêu cầu nhập tối đa 16 MB riêng đường `/api/standards/*/import` để nhận ICD gốc 9,4 MB. Các API khác giữ giới hạn 6 MB. Excel tối đa 20 MB giải nén; chọn sheet bằng `__sheet`, ánh xạ giá trị chỉ cho cờ/giới/cấp hành chính, không tạo mã.

## Khám, kê đơn và mã ICD

Tìm theo mã hiển thị, khóa không dấu chấm/liên thông, tên Việt hoặc Anh (bỏ dấu). Chọn bệnh chính/bệnh kèm, giữ mô tả chữ. Mã †/* được giữ nguyên để hiển thị; `ma_benh_khong_dau` lấy nguyên từ nguồn, không tự sinh. Bảng giữ đủ chương/khối/nhóm và hướng dẫn mã hóa gốc.

API chặn cờ không dùng bệnh chính, tử vong, mã chi tiết hơn, sai giới; cờ không khuyến khích chỉ cảnh báo. Mã con gợi ý phải có thực trong nguồn, không dựng mã từ chuỗi. Hoàn tất lượt/khóa đơn M6 bắt buộc mã chính mặc định BẬT; Quản trị có thể tắt chạy song song, có audit. Hồ sơ chữ cũ ghi chưa mã hóa; không tự mã hóa. In mã – tên kèm mô tả; JSON giữ mã hiển thị và khóa liên thông riêng. Phiên bản hồ sơ/đơn khóa giữ snapshot, không bị nạp danh mục mới sửa lại. Audit sửa chẩn đoán chỉ ghi tên trường/số lượng, chi tiết vẫn trong phạm vi bác sĩ được phân công.

## Chọn mã CLS và kỹ thuật

Màn **Chỉ số chưa gắn mã**: gõ tên, bấm chọn mã dùng chung; LOINC/thuộc tính lấy theo mã đã chọn. Không tự gắn theo tên. Thuộc tính sau thành phần rỗng ở nhóm Chẩn đoán hình ảnh là dữ liệu nguồn hợp lệ. Phiếu M5 duyệt sau khi gắn mã lưu mã/LOINC/phiên bản trong snapshot; phiếu cũ không đổi.

Màn **Dịch vụ chưa gắn mã**: gợi ý tên PL01 và dòng PL02 riêng, người dùng chọn rõ. PL02 dùng STT gốc định danh dòng, không đặt mã kỹ thuật mới. Dịch vụ lẻ một mã PL01, gói nhiều mã khi xác nhận gói; có thể gắn dòng PL02 nếu có. Giá/cách tính tiền không đổi.

`tech_catalog_pl01` giữ mã kể cả BS_x.y; `tech_catalog_pl02` giữ nguyên ma_lien_ket_pl01. Tách đúng `[;,\s]+`, chỉ mảnh khớp chính xác PL01 mới có liên kết, mảnh không khớp ghi cần rà soát tay. Giao diện có bảng rà soát; không tự sửa PDF vỡ mã. Bảng `tech_catalog` giữ cùng dữ liệu PL01 để tương thích liên kết nền D0; không phải một nguồn kỹ thuật mới.

## Địa chỉ và nghề nghiệp

Mã xã 5 số từ CV 1027 là mã chuẩn; TMS giữ song song. Ghép theo tên tỉnh+xã không dấu, riêng Tp Hồ Chí Minh chuẩn hóa Thành phố Hồ Chí Minh. Chỉ ghép duy nhất; danh sách không ghép được để Quản trị xử lý tay. Xã Cát Thành (Ninh Bình) có mã 14056. CSV không có mã tỉnh chính thức: không tự cắt mã xã hay gán mã TMS làm mã tỉnh chính thức. Hồ sơ/JSON dùng mã xã chính thức riêng, thiếu để trống. Không tự gán hàng loạt hồ sơ lịch sử. Mã bị bỏ ngừng dùng, bỏ gợi ý cho hồ sơ mới, giữ mã đã lưu ở hồ sơ cũ.

Nghề nghiệp chưa có file Bộ Y tế [CẦN ĐỐI CHIẾU]. Cho nhập chữ, occupation_code trống là chưa chuẩn hóa; không tự đoán.

## Kiểm và giới hạn

CI nạp thật đủ 5 tệp trên SQLite/PostgreSQL, kiểm hash, số dòng, quy tắc ICD, ký hiệu in/JSON, chọn mã không đổi giá, PL02 giữ mảnh vỡ, ghép địa giới, migration và backup/restore. C5 dùng đủ 22.000 lượt/20.000 người bệnh và 15.844 mã ICD gốc; p95 nearest-rank <300 ms, có chỉ mục tên không dấu/Anh/khóa liên thông. Ghi dung lượng sau nạp vào PR.

D0 gộp vào asset app.js để giữ ngân sách tải LAN, không tăng giới hạn 48 kết nối hay timeout. C5 chuẩn bị đúng schema 11 trước profile mới, không thay thuật toán/ngưỡng đo hoặc quy mô C5. Chrome 109 và 390px được kiểm tự động; máy Windows/máy in thật vẫn cần nghiệm thu. Chưa làm liên thông mạng thật; chưa có danh mục nghề chuẩn và chưa xác nhận ngày ban hành còn thiếu trong nguồn.
