# Siêu âm và X-quang S2d

S2d sử dụng chỉ định siêu âm/X-quang hiện có. Nội dung gốc của 28 mẫu nằm trong
`data/danh_muc_goc/mau_ket_qua_28.json`; migration 19 nạp một lần, giữ trạng thái
bật/tắt khi chạy lại. Số 18 không dùng vì đã dành cho bản thử S2c cũ.

## Cài đặt

Sao lưu đã kiểm trước khi nâng cấp. Dừng dịch vụ ghi, chạy bằng tài khoản chủ CSDL:

```
python -m scripts.manage migrate
```

Áp lại quyền từ `deploy/postgresql-roles.sql` theo quy trình cài đặt hiện có, rồi
khởi động dịch vụ. Trình cài/cập nhật Windows chép riêng nguồn JSON đã kiểm SHA-256;
không chép thêm thư mục dữ liệu người bệnh. Khi quay về, dùng bản sao lưu trước
nâng cấp theo quy trình phục hồi hiện có; không tự xóa bảng phiếu hoặc lịch sử ký.
Ảnh nằm trong thư mục tệp đính kèm được cấu hình bằng `CLINIC_UPLOAD_DIR`, thuộc
phạm vi sao lưu hiện có, không lưu trong Git.

## Sử dụng

- Quản trị mở **Danh mục mẫu siêu âm / X-quang** để xem nguồn và bật/tắt từng mẫu.
  Giai đoạn này không cho sửa nguồn mẫu.
- Bác sĩ mở **Phiếu hình ảnh** tại chỉ định; kỹ thuật viên chọn chỉ định rồi mở
  **Nhập kết quả hình ảnh**. Phiếu đã ký có thể mở lại để lập đính chính.
- Chọn mẫu theo chỉ định. Mẫu nam/nữ được gợi ý theo giới, vẫn có thể đổi trước
  khi lập phiếu. Các mục mô tả luôn trống lúc lập; chèn câu bình thường hoặc
  **Không khảo sát rõ** theo hình ảnh thực tế. Mục không có câu gợi ý phải tự nhập.
- Điền yêu cầu kiểm tra nếu còn chỗ trống như bên trái/phải, các mục mô tả và
  kết luận. Còn dấu `……`, mục trống hoặc kết luận trống sẽ chặn in và ký;
  vẫn lưu nháp được. Lời dặn X-quang được nạp nếu nguồn có, cho sửa trên phiếu.
- Mỗi phiếu nhận tối đa hai ảnh JPG/PNG bằng tải tệp, kéo thả hoặc Ctrl+V trong
  cửa sổ phiếu. Ảnh dán được chuyển thành JPG. Máy chủ xác minh nội dung ảnh và
  giới hạn dung lượng theo `CLINIC_UPLOAD_MAX_MB` (mặc định 5 MB), tối đa 20 triệu
  điểm ảnh để giới hạn bộ nhớ. Tải/xóa/xem ảnh có nhật ký.
- Giữ quyền ký hiện có: bác sĩ phụ trách nhập lại mật khẩu để áp chữ ký tài khoản.
  Kỹ thuật viên nhập và xem kết quả. PDF được kiểm vừa một trang A4 trước khi ký;
  nếu quá dài, phải rút gọn mô tả, không cắt mất nội dung.
- Phiếu đã ký bị khóa. Lập **Phiếu đính chính**, ghi lý do, kiểm nội dung và ký
  riêng. Phiếu gốc vẫn có chữ ký gốc; khi bản đính chính được ký, phiếu gốc hiện
  số phiếu đính chính. Các ảnh dùng chung giữa hai phiên bản không bị xóa theo
  thao tác xóa ảnh trên bản nháp đính chính.

Hash chữ ký bao gồm nội dung chuyên môn, thông tin người bệnh/người ký và hash
ảnh; không bao gồm watermark, logo hoặc tệp mẫu. Tham chiếu đính chính là ghi chú
lịch sử, không làm mất chữ ký gốc. Dòng thử nghiệm tuân theo `IN_DONG_THU_NGHIEM`.
Không có DICOM, lấy ảnh tự động từ máy siêu âm hoặc sửa nội dung mẫu gốc.
