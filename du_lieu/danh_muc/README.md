# Danh mục công khai do chủ dự án cung cấp

Hai file Excel được chuyển nguyên bản từ thư mục gốc main vào đây theo lệnh bổ sung L1. Đây là dữ liệu địa giới/dân tộc công khai được chủ dự án cho phép lưu trong repo. Không có hồ sơ người bệnh, nhân viên, giấy phép hoặc chứng từ thật.

- `tinh_xa.csv`: 3.321 dòng xã thuộc 34 tỉnh; mã tỉnh BNV, mã xã theo file **mã thuế TMS**, tên huyện cũ chỉ tham khảo. Mã ĐVHC chính thức để trống.
- `dan_toc.csv`: 54 dòng, mã chuỗi `01`–`54`, giữ tên chính và toàn bộ tên gọi khác. Hai lựa chọn ngoài danh mục được thêm ở lớp ứng dụng bằng mã `FOREIGN`, `UNKNOWN`.

Tạo lại CSV UTF-8 bằng `python -m scripts.build_patient_catalog`. Bộ chuyển đọc đúng tiêu đề Excel (địa giới dòng 3; dân tộc dòng 1), tìm cột theo tên đã bỏ khoảng trắng hai đầu, kiểm số lượng và mã trùng trước khi ghi. Khi thay nguồn chính thức trong repo, cập nhật kiểm thử số lượng có chủ đích nếu nhà nước thay đổi cơ cấu. Không tự gán mã TMS thành mã ĐVHC.

SHA-256 của hai bản gốc và CSV được tạo trong lần bổ sung này:

```
0f4257b479e4a7714fa7d4dce579037b3c23e13853153aa5dc1e806e52877141  Danh-muc-Phuong-xa_moi_34-tinh-thanh-sau-sat-nhap.xlsx
d36a169cdad11d5a4f8dabb6c2ee784d25aa01ad52df23981fbf00de1cc5bee0  Danh_sach_54_dan_toc_Viet_Nam_2026.xlsx
b0a233fcbea0ada5db16fd12b8facb5e8a34d63192727cd433daecc22f77b9f9  tinh_xa.csv
f1a02af4619aa6a33ac67f18b4acc4fe2deb03fcc34b95f2e373de5389311d04  dan_toc.csv
```
