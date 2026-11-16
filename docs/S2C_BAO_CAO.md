# Báo cáo S2c

Nhánh `feat/s2c-mau-in`, gốc `9647e1e`, PR #40. Mẫu trang 29–33; đầu phiếu từ `clinic_profile`; không có dữ liệu hoặc ảnh ký thật trong repo.

- Sửa bắt buộc PR #40: bỏ từ chối in do vượt A4. PDF/Word dài tự sang trang, giữ nguyên cỡ chữ và đủ nội dung; trang tiếp nối lặp họ tên, mã NB, số phiếu/mã đơn nội bộ; mọi trang có `Trang x/y`. Tiêu đề bảng xét nghiệm lặp; khối ký/ảnh ký chỉ ở trang cuối, cùng dòng nội dung cuối.
- Giữ kiểm nội dung thông thường một trang A4, ký đúng người, mật khẩu/audit, sửa mất hiệu lực, trẻ dưới 72 tháng thiếu cân nặng, ↑/↓ đậm và xem trước → nạp Excel **78 chỉ số / 82 tham chiếu**.
- Thêm **7 ca phân trang**: ba nhóm 60 chỉ số, đơn 25 thuốc, lời dặn dài, cách dùng dài, chỉ định dài. Kiểm đủ từng dòng, đuôi, số lần lặp, cỡ chữ, đầu/chân trang và chữ ký cuối; kiểm cả Word chuyển PDF bằng LibreOffice cục bộ. Khôi phục kiểm đủ TAIL_MARKER ở cả ba phiếu trong bài LAN.
- Thiết kế chữ ký mới: chỉ hiện ảnh khi nội dung in hiện tại khớp mã băm bản ký mới nhất, đúng người chịu trách nhiệm và phiếu còn hợp lệ. Nếu không khớp, không hiện ảnh và có thông báo cần ký lại. Luồng xem/in không ghi bảng ký.
- Một migration **017 sạch**, schema 17; bỏ 018, `invalidated` và mọi trigger vô hiệu nguồn. Bảng ký chặn UPDATE/DELETE; SQLite còn chặn INSERT trùng ID để ngăn REPLACE ngay cả khi recursive_triggers tắt. Vai trò PostgreSQL bị thu hồi UPDATE/DELETE/TRUNCATE; quay lui từ chối khi có bản ký.
- Mã băm gồm các khối thực sự in và checksum logo, mẫu tương ứng; CSDL đã chạy thử version 18 hoặc có cột invalidated bị từ chối nâng cấp và phải khôi phục bản sao lưu trước S2c; tuổi theo ngày khám/lập phiếu/lấy mẫu. Đợt sửa mới kiểm tại chỗ đạt **36 bài S2c SQLite**, **8 bài phân trang** và **20 bài S2c PostgreSQL**; kiểm quyền vai trò PostgreSQL chạy lại sau khi bổ sung SQLSTATE. Các đợt trước đạt 73 bài Python, 38 bài LAN và 11 bài guard/tuổi/tài nguyên. Các ca API bao gồm thay đổi in/không in, thông báo PDF/Word, ký lại, tên người ký, đọc cũ/ký mới, bản điều chỉnh XN nháp và REPLACE. Ruff, ESLint, checksum và diff-check đạt. Không theo dõi GitHub Actions theo yêu cầu; chưa kiểm máy in thật/Microsoft Word tại cơ sở.

Chi tiết và căn cứ cập nhật assertion: [S2C_MAU_IN.md](S2C_MAU_IN.md). Lần chạy cục bộ dùng dữ liệu giả lập, PostgreSQL 17 và Chromium cục bộ; không nới assertion ngoài phạm vi chữ ký và phiên bản schema.

Số dòng sau sửa; `+ / −` so với `9647e1e`; tệp nhị phân không tính dòng.

| Tệp | Số dòng | + / − |
|---|---:|---:|
| `.github/workflows/clinic-tests.yml` | 596 | 2 / 2 |
| `.gitignore` | 270 | 2 / 0 |
| `app/database.py` | 184 | 3 / 0 |
| `app/document_signatures.py` | 163 | 163 / 0 |
| `app/form_pagination.py` | 205 | 205 / 0 |
| `app/forms.py` | 501 | 67 / 21 |
| `app/forms_api.py` | 149 | 21 / 0 |
| `app/m5.py` | 482 | 20 / 6 |
| `app/m5_forms.py` | 6 | 4 / 70 |
| `app/m6.py` | 607 | 11 / 5 |
| `app/m6_forms.py` | 6 | 3 / 81 |
| `app/main.py` | 1102 | 12 / 0 |
| `app/manual_price_migration.py` | 141 | 1 / 0 |
| `app/s2a_migration.py` | 39 | 1 / 0 |
| `app/s2b_migration.py` | 84 | 1 / 0 |
| `app/s2c_forms.py` | 564 | 564 / 0 |
| `app/s2c_migration.py` | 50 | 50 / 0 |
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
| `deploy/postgresql-roles.sql` | 59 | 9 / 0 |
| `docs/S2C_BAO_CAO.md` | 76 | 76 / 0 |
| `docs/S2C_MAU_IN.md` | 43 | 43 / 0 |
| `docs/assets-v031.sha256` | 35 | 13 / 9 |
| `lan_tests/test_lan.py` | 304 | 38 / 3 |
| `lan_tests/test_mot_ngay_kham.py` | 755 | 2 / 2 |
| `lan_tests/test_s2a.py` | 134 | 4 / 2 |
| `lan_tests/test_s2c.py` | 83 | 83 / 0 |
| `lan_tests/test_s2c_browser.py` | 71 | 71 / 0 |
| `lan_tests/test_v050_migration.py` | 150 | 4 / 2 |
| `migrations/017_s2c_signatures.sql` | 13 | 13 / 0 |
| `scripts/backup_demo.py` | 90 | 3 / 0 |
| `scripts/build_s2c_assets.py` | 198 | 198 / 0 |
| `scripts/do_hieu_nang.py` | 486 | 4 / 1 |
| `scripts/manage.py` | 76 | 7 / 0 |
| `tests/administrative_revision_cases.py` | 123 | 11 / 8 |
| `tests/m5_cases.py` | 131 | 2 / 1 |
| `tests/m6_cases.py` | 157 | 10 / 5 |
| `tests/print_pagination_cases.py` | 79 | 79 / 0 |
| `tests/s2c_cases.py` | 334 | 334 / 0 |
| `tests/test_s1_prescription.py` | 62 | 2 / 1 |
| `tests/test_s2a.py` | 116 | 4 / 2 |
| `tests/test_s2c.py` | 417 | 417 / 0 |
| `tests/test_s2c_pagination.py` | 94 | 94 / 0 |
| `tests/test_v041_fixes.py` | 106 | 3 / 1 |

Chờ S2d.
