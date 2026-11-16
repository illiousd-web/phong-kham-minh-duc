# Báo cáo S2c

Nhánh `feat/s2c-mau-in`, tạo từ `9647e1e`. Mẫu PDF trang 29–33; đầu phiếu từ `clinic_profile`; ảnh ký chỉ ở CSDL, không có ảnh ký thật trong repo.

- Migration **017**: bảng bản ký, trigger mất hiệu lực khi sửa; quay lui từ chối nếu có lịch sử ký.
- Excel **78 chỉ số / 82 dòng tham chiếu**; xem trước → nạp đã đạt, không tự nạp khi cài.
- **54 bài Python đạt**: `test_s2c`, `test_form_exports`, `test_forms_v02`, `test_s2a`, `test_m5`, `test_m6`, `test_c5_measurement`.
- **27 bài LAN đạt**: `test_s2c`, `test_s2c_browser`, `test_m5_browser`, `test_m6_browser`, `test_mot_ngay_kham`, `test_v050_browser`. Có Chromium thật ở 1366/390px. Hồi quy màn bác sĩ `test_m0_browser` và các bài `u1b/u1c` cũng đã đạt trong lượt kiểm liên quan.
- **22 bài mới**: 15 Python + 5 PostgreSQL + 2 Chromium; kiểm một trang A4, đúng ảnh/người ký, mật khẩu, audit, sửa mất hiệu lực, trẻ thiếu cân nặng, ↑/↓ đậm và Excel.
- Sau chỉnh độ rộng nhãn và đầu đơn trang 33: 4 bài bố cục và 20 bài S2a/S2c đạt. PDF trực tiếp và Word chuyển sang PDF với ảnh ký: các mẫu đã kiểm đều một trang A4.
- Ruff, ESLint, `git diff --check`, checksum tài sản: đạt. Năm job CI còn chờ kết quả trên PR; chưa kiểm máy in thật/Word trên Windows.

Chi tiết vận hành và căn cứ cập nhật assertion: [S2C_MAU_IN.md](S2C_MAU_IN.md).

Số dòng sau sửa; tệp đã xóa ghi 0. `+/-` là số dòng thay đổi so với `9647e1e`; tệp nhị phân không có số dòng.

| Tệp | Số dòng | + / − |
|---|---:|---:|
| `.gitignore` | 270 | 2 / 0 |
| `app/database.py` | 183 | 2 / 0 |
| `app/document_signatures.py` | 145 | 145 / 0 |
| `app/forms.py` | 459 | 14 / 10 |
| `app/forms_api.py` | 147 | 19 / 0 |
| `app/m5.py` | 481 | 19 / 6 |
| `app/m5_forms.py` | 6 | 4 / 70 |
| `app/m6.py` | 601 | 4 / 4 |
| `app/m6_forms.py` | 6 | 3 / 81 |
| `app/main.py` | 1101 | 11 / 0 |
| `app/s2c_forms.py` | 467 | 467 / 0 |
| `app/s2c_migration.py` | 53 | 53 / 0 |
| `app/static/MinhDuc_logo_in.png` | Nhị phân | - / - |
| `app/static/app.js` | 1321 | 51 / 1 |
| `app/static/m5.js` | 93 | 1 / 1 |
| `app/static/m6.js` | 76 | 1 / 1 |
| `app/static/styles.css` | 689 | 6 / 0 |
| `app/templates/03_Phieu_chi_dinh_CLS_A4.docx` | 0 (xóa) | - / - |
| `app/templates/03_Phieu_chi_dinh_noi_khoa_A4.docx` | Nhị phân | - / - |
| `app/templates/04_Phieu_XN_biochemistry_A4.docx` | Nhị phân | - / - |
| `app/templates/04_Phieu_XN_hematology_A4.docx` | Nhị phân | - / - |
| `app/templates/04_Phieu_XN_other_A4.docx` | Nhị phân | - / - |
| `app/templates/04_Phieu_XN_urine_A4.docx` | Nhị phân | - / - |
| `app/templates/04_Phieu_ket_qua_xet_nghiem_A4.docx` | 0 (xóa) | - / - |
| `app/templates/08_Don_thuoc_A4.docx` | Nhị phân | - / - |
| `app/templates/08_Don_thuoc_ngoai_tru_A5.docx` | 0 (xóa) | - / - |
| `data/danh_muc_goc/chi_so_xet_nghiem_minh_duc.xlsx` | ChiSo: 78; ThamChieu: 82 (không tính đầu cột) | - / - |
| `docs/S2C_MAU_IN.md` | 49 | 49 / 0 |
| `docs/assets-v031.sha256` | 35 | 13 / 9 |
| `lan_tests/test_mot_ngay_kham.py` | 755 | 2 / 2 |
| `lan_tests/test_s2c.py` | 10 | 10 / 0 |
| `lan_tests/test_s2c_browser.py` | 71 | 71 / 0 |
| `migrations/017_s2c_signatures.sql` | 14 | 14 / 0 |
| `scripts/build_s2c_assets.py` | 198 | 198 / 0 |
| `scripts/do_hieu_nang.py` | 486 | 4 / 1 |
| `tests/m5_cases.py` | 131 | 2 / 1 |
| `tests/m6_cases.py` | 157 | 10 / 5 |
| `tests/s2c_cases.py` | 145 | 145 / 0 |
| `tests/test_s2a.py` | 116 | 3 / 1 |
| `tests/test_s2c.py` | 238 | 238 / 0 |
| `docs/S2C_BAO_CAO.md` | 61 | mới |

Chờ S2d.
