# Báo cáo S2c

Nhánh `feat/s2c-mau-in`, gốc `9647e1e`, PR #40. Mẫu trang 29–33; đầu phiếu từ `clinic_profile`; không có dữ liệu hoặc ảnh ký thật trong repo.

- Sửa bắt buộc PR #40: bỏ từ chối in do vượt A4. PDF/Word dài tự sang trang, giữ nguyên cỡ chữ và đủ nội dung; trang tiếp nối lặp họ tên, mã NB, số phiếu/mã đơn nội bộ; mọi trang có `Trang x/y`. Tiêu đề bảng xét nghiệm lặp; khối ký/ảnh ký chỉ ở trang cuối, cùng dòng nội dung cuối.
- Giữ kiểm nội dung thông thường một trang A4, ký đúng người, mật khẩu/audit, sửa mất hiệu lực, trẻ dưới 72 tháng thiếu cân nặng, ↑/↓ đậm và xem trước → nạp Excel **78 chỉ số / 82 tham chiếu**.
- Thêm **7 ca phân trang**: ba nhóm 60 chỉ số, đơn 25 thuốc, lời dặn dài, cách dùng dài, chỉ định dài. Kiểm đủ từng dòng, đuôi, số lần lặp, cỡ chữ, đầu/chân trang và chữ ký cuối; kiểm cả Word chuyển PDF bằng LibreOffice cục bộ. Khôi phục kiểm đủ TAIL_MARKER ở cả ba phiếu trong bài LAN.
- Migration **018** nâng cấp từ 017, giới hạn vô hiệu theo tài liệu và bảo vệ lịch sử ký; quay lui 018 khôi phục trigger 017. Vai trò ứng dụng chỉ được cập nhật cột vô hiệu; logic kê đơn, duyệt xét nghiệm và thuốc kiểm soát giữ nguyên.
- Kiểm thử cục bộ: 58 bài Python và 27 bài LAN liên quan đạt; kiểm S2c bổ sung 26 bài SQLite, 8 bài PostgreSQL, cùng các bài nâng cấp/quay lui, thiếu LibreOffice và tuổi 71/73 tháng. Hai ca lời dặn dài đều đạt. Ruff, ESLint và diff-check đạt. CI cài LibreOffice Writer; theo yêu cầu không theo dõi GitHub Actions. Chưa kiểm máy in thật/Word tại phòng khám.

Chi tiết và căn cứ cập nhật assertion: [S2C_MAU_IN.md](S2C_MAU_IN.md). Lần chạy cục bộ dùng dữ liệu giả lập, PostgreSQL 17 và Chromium cục bộ; không thay timeout hoặc bỏ bài kiểm.

Số dòng sau sửa; `+ / −` so với `9647e1e`; tệp nhị phân không tính dòng.

| Tệp | Số dòng | + / − |
|---|---:|---:|
| `.github/workflows/clinic-tests.yml` | 596 | 2 / 2 |
| `.gitignore` | 270 | 2 / 0 |
| `app/database.py` | 183 | 2 / 0 |
| `app/document_signatures.py` | 148 | 148 / 0 |
| `app/form_pagination.py` | 205 | 205 / 0 |
| `app/forms.py` | 497 | 62 / 20 |
| `app/forms_api.py` | 147 | 19 / 0 |
| `app/m5.py` | 481 | 19 / 6 |
| `app/m5_forms.py` | 6 | 4 / 70 |
| `app/m6.py` | 601 | 4 / 4 |
| `app/m6_forms.py` | 6 | 3 / 81 |
| `app/main.py` | 1101 | 11 / 0 |
| `app/s2c_forms.py` | 535 | 535 / 0 |
| `app/s2c_migration.py` | 81 | 81 / 0 |
| `app/s2c_migration_018.py` | 71 | 71 / 0 |
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
| `data/danh_muc_goc/chi_so_xet_nghiem_minh_duc.xlsx` | ChiSo: 78; ThamChieu: 82 | - / - |
| `deploy/postgresql-roles.sql` | 60 | 10 / 0 |
| `docs/S2C_BAO_CAO.md` | 72 | 72 / 0 |
| `docs/S2C_MAU_IN.md` | 55 | 55 / 0 |
| `docs/assets-v031.sha256` | 35 | 13 / 9 |
| `lan_tests/test_lan.py` | 304 | 38 / 3 |
| `lan_tests/test_mot_ngay_kham.py` | 755 | 2 / 2 |
| `lan_tests/test_s2a.py` | 134 | 4 / 2 |
| `lan_tests/test_s2c.py` | 70 | 70 / 0 |
| `lan_tests/test_s2c_browser.py` | 71 | 71 / 0 |
| `lan_tests/test_v050_migration.py` | 150 | 4 / 2 |
| `migrations/017_s2c_signatures.sql` | 14 | 14 / 0 |
| `scripts/build_s2c_assets.py` | 198 | 198 / 0 |
| `scripts/do_hieu_nang.py` | 486 | 4 / 1 |
| `scripts/manage.py` | 76 | 7 / 0 |
| `tests/administrative_revision_cases.py` | 123 | 11 / 8 |
| `tests/m5_cases.py` | 131 | 2 / 1 |
| `tests/m6_cases.py` | 157 | 10 / 5 |
| `tests/print_pagination_cases.py` | 79 | 79 / 0 |
| `tests/s2c_cases.py` | 221 | 221 / 0 |
| `tests/test_s1_prescription.py` | 62 | 2 / 1 |
| `tests/test_s2a.py` | 116 | 4 / 2 |
| `tests/test_s2c.py` | 313 | 313 / 0 |
| `tests/test_s2c_pagination.py` | 94 | 94 / 0 |
| `tests/test_v041_fixes.py` | 106 | 3 / 1 |

Chờ S2d.
