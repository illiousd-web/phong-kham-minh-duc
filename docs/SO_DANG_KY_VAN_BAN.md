# Sổ đăng ký văn bản

Đây là sổ theo yêu cầu chủ dự án, không phải xác nhận hiệu lực pháp lý. Chưa có bản gốc để đối chiếu ngày, hiệu lực, phụ lục và văn bản sửa đổi thì giữ **[CẦN ĐỐI CHIẾU]**. Không dùng các mục chưa đối chiếu để tự sinh mã danh mục hay bổ sung quy tắc nghiệp vụ. Thông tin mỗi tệp thực tế được nạp lưu riêng trong `catalog_imports`.

| Số hiệu | Ngày ban hành | Hiệu lực | Nội dung cần đối chiếu | Module | Trạng thái |
|---|---|---|---|---|---|
| TT 26/2025/TT-BYT | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | Nội dung/mẫu đơn thuốc | M6/L3 | [CẦN ĐỐI CHIẾU] bản gốc/phụ lục |
| TT 06/2026/TT-BYT + QĐ 1849/QĐ-BYT 2026 | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | ICD-10, các hạn chế cột 24–29, quan hệ hai văn bản | D0/chẩn đoán | Đã kiểm CSV 15.844 dòng/6 cờ; [CẦN ĐỐI CHIẾU] văn bản và ngày |
| TT 23/2024/TT-BYT, VBHN 13/2026 | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | Danh mục kỹ thuật | D0/dịch vụ | Đã kiểm CSV công khai; [CẦN ĐỐI CHIẾU] văn bản/ngày |
| QĐ 1227/QĐ-BYT 2025 | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | Mã dùng chung CLS, LOINC | D0/M5 | Đã kiểm CSV công khai; [CẦN ĐỐI CHIẾU] văn bản/ngày |
| QĐ 2427/QĐ-BYT | [CẦN ĐỐI CHIẾU] năm/ngày | [CẦN ĐỐI CHIẾU] | Thuật ngữ lâm sàng | D0 | [CẦN ĐỐI CHIẾU] |
| CV 1027/CTK-CSCL (Cục Thống kê) | 25/06/2025 | [CẦN ĐỐI CHIẾU] | Mã xã chính thức, giữ mã thuế TMS song song; tệp không có mã tỉnh | D0/L1 | Đã kiểm CSV 3.321 dòng; [CẦN ĐỐI CHIẾU] hiệu lực |
| TT 13/2025 | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | Bệnh án điện tử | D0 | [CẦN ĐỐI CHIẾU] |
| TT 32/2023 + TT 25/2026 | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | Biểu mẫu khám sức khỏe, nội dung sửa đổi | Biểu mẫu | [CẦN ĐỐI CHIẾU] |
| QĐ 1551 + QĐ 2062 | [CẦN ĐỐI CHIẾU] năm/cơ quan | [CẦN ĐỐI CHIẾU] | Cổng dữ liệu khám sức khỏe | D0/liên thông | [CẦN ĐỐI CHIẾU] |
| TT 54/2015 [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | [CẦN ĐỐI CHIẾU] | Báo cáo bệnh truyền nhiễm | D0 | [CẦN ĐỐI CHIẾU] |
| QĐ 1867/2026 + CV 934/2026 | [CẦN ĐỐI CHIẾU] cơ quan/ngày | [CẦN ĐỐI CHIẾU] | Dữ liệu dược | D0/liên thông | [CẦN ĐỐI CHIẾU] |
| Luật BVDLCN 2025 + NĐ 356/2025 | [CẦN ĐỐI CHIẾU] số hiệu/ngày | [CẦN ĐỐI CHIẾU] | Bảo vệ dữ liệu cá nhân | Toàn phần mềm | [CẦN ĐỐI CHIẾU] |

## Năm tệp công khai do chủ dự án cung cấp

Số dòng không tính tiêu đề. Giữ nguyên byte UTF-8 BOM; SHA-256 kiểm cả lúc migrate và CI. Đã đối chiếu cấu trúc/số dòng/SHA với tệp cung cấp; chưa xác nhận các ngày ban hành còn thiếu trong CSV. Metadata ngày để NULL và giao diện ghi “Chưa đối chiếu ngày”, không tự điền ngày. CV 1027 có ngày do chủ dự án cung cấp. PL01 áp dụng đến 30/06/2026, PL02 từ 01/07/2026 theo lệnh nghiệp vụ; không suy ra ngày ban hành từ tên tệp.

| Tệp | Số dòng | SHA-256 |
|---|---:|---|
| `ICD10_TT06_2026.csv` | 15,844 | `05f4db19f5935c5c106185937c4bb956618c7d00408f29c64c0614640d3c73d4` |
| `QD1227_MA_DUNG_CHUNG_CLS_DOT1.csv` | 2,964 | `c3db0f38ff1e9a7cf857a87d3636e6c39d0a047b98de27a353db94110d0fdbed` |
| `TT23_PL01_DANH_MUC_KY_THUAT.csv` | 19,438 | `d4854c88304456c615d28d6bd7f3a0b5ab4a56dc0f00533604c57aaaf9984b1f` |
| `TT23_PL02_DANH_MUC_KY_THUAT_TU_01072026.csv` | 9,128 | `38eab59894dbec1c904b1d7b54cad5e9f43afe75e854de7ea1497409e0fd666f` |
| `DVHC_XA_CV1027_2025.csv` | 3,321 | `3a657a35fd6427d98774c8d74209cf3ec335e4225c4c8b35677358a1b1d8d06a` |

PL02 không có cột mã kỹ thuật riêng: STT chỉ định danh dòng trong từng lần nạp, có ID nội bộ riêng; không là mã kỹ thuật mới. Chuỗi ma_lien_ket_pl01 giữ nguyên; 8.252 mảnh sau tách có 7.343 khớp PL01 và 909 cần rà soát tay. Không nối/sửa các mảnh vỡ. Hai tên CLS và 58 tên PL02 rỗng được giữ nguyên theo nguồn, không tự điền. File ĐVHC chỉ có mã xã, không tự tạo mã tỉnh hay cắt đầu mã xã để suy ra mã tỉnh.
