# Mẫu giao diện chính thức – Phòng khám đa khoa Minh Đức (bản 2, 14/11/2026)

Phong cách: Liquid Glass + Android 17 Expressive (A + C). Font Be Vietnam Pro. Logo: MinhDuc_logo_mau.svg (nền sáng), MinhDuc_logo_trang.svg (trên khối xanh).

## Cách dùng cho người lập trình
- File .png = hình phải đạt. File .html = giá trị CSS gốc (thuộc tính style, hoặc khối <style> trong <helmet> ở các file U_*).
- KHÔNG chép support.js, <x-dc>, <helmet>, <sc-for>, <sc-if>, {{...}} vào phần mềm; chỉ lấy CSS.
- Số liệu, tên người trong mẫu là giả lập. Chức năng phần mềm chưa có thì không làm nút giả.

## Quy chuẩn bắt buộc (đã kiểm tự động trên cả 26 mẫu)
- Màu: xanh chính #008249, xanh dương #0069C7, đen chữ #0B1F17, chữ phụ #1F3A31, đỏ #B42318. Không dùng #17803D (màu cũ).
- Khối tiêu đề lớn (hero): nền xanh rgba(0,118,66,0.9) / xanh dương rgba(0,95,180,0.9) / đen rgba(11,31,23,0.86), chữ trắng, không làm mờ chữ.
- Tương phản chữ ≥ 4,5:1 (chữ thường), ≥ 3:1 (chữ ≥ 24px hoặc ≥ 18,7px đậm).
- Cỡ chữ nhỏ nhất 13px. Nút, tab, mục điều hướng cao ≥ 44px.
- Viền ô nhập #6F8F7E (3,56:1 trên nền trắng).
- Dải "Bản thử nghiệm" luôn hiện, kể cả màn đăng nhập; điện thoại cho xuống 2 dòng.
- Điện thoại (≤ 900px): điều hướng là thanh nổi ở đáy; thông báo (toast) nằm trên thanh đáy.

## Danh mục màn
| File | Màn | Vai trò → menu trong phần mềm |
|---|---|---|
| U_DangNhap, U_DangNhapDT | Đăng nhập (1366 / 390) | tất cả |
| U_DoiMatKhau | Đổi mật khẩu | tất cả |
| KetHop | Tiếp đón | Lễ tân → reception (gồm Lịch hẹn) |
| U_BangGia | Bảng giá | Lễ tân → prices |
| KH_Kham, KetHopDT | Bác sĩ khám (1366 / 390) | Bác sĩ → doctor |
| KH_KeDon | Kê đơn | Bác sĩ → doctor (tab Đơn thuốc) |
| U_DonThuocKhoa | Đơn thuốc đã khóa | Lễ tân, Bác sĩ, Dược → m6-list |
| KH_XetNghiem | Nhập kết quả cận lâm sàng | KTV → lab |
| U_PhieuXN | Phiếu xét nghiệm theo chỉ số | Lễ tân, KTV → m5-queue |
| KH_ThuNgan | Thu ngân | Thu ngân → cashier |
| U_NhaThuoc, U_NhaThuocDT | Nhà thuốc – cấp thuốc | Dược → pharmacy |
| U_KhoThuoc | Kho, nhập lô, xuất nội bộ | Dược → pharmacy |
| U_DieuDuong | Điều dưỡng | Điều dưỡng → nurse |
| U_QuanLy | Quản lý – Cần duyệt | Quản lý → manager (approve) |
| U_QuanLyBaoCao | Quản lý – Báo cáo (Lượt khám, Danh mục cùng bố cục bảng) | manager |
| U_QuanTri | Quản trị – Tài khoản | Quản trị → admin |
| U_NhatKy | Quản trị – Nhật ký (Danh mục cùng bố cục bảng) | admin |
| U_NhapBangGia | Nhập bảng giá | price-management, manager (import) |
| U_CaiDat | Cài đặt | settings |
| U_ThuocRaSoat | Thuốc chưa rà soát | m6-admin |
| U_ChiSoXN | Chỉ số xét nghiệm | m5-admin |
| TrangThai | Trạng thái đặc biệt (trống, tải, sao lưu, mất mạng, ổ đầy, tên dài) | dùng chung |
| QuyChuan | Quy chuẩn gốc đợt 1 (màu nút cũ, chỉ tham khảo bố cục) | — |
