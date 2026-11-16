# S2b — Kết quả và phạm vi thay đổi

Migration **016**: SQLite + PostgreSQL; lên/xuống, giữ tồn cũ và giá chưa biết là NULL;
chặn rollback khi đã có dữ liệu mới. Hướng dẫn: [Kho thuốc](S2B_KHO_THUOC.md).

Kết quả cục bộ (dữ liệu giả lập):

- **38 bài SQLite đạt**: kho/cấp thuốc, hàng chờ, S2b và migration.
- **48 bài PostgreSQL/HTTPS liên quan đạt** qua lượt ghép và lượt kiểm lại sau sửa fixture:
  các bài được yêu cầu, v050_abcd, v050_migration, S2b và bảng 390px.
- **7 bài S2a/migration C5 đạt**; giữ đủ 20.000 người bệnh / 22.000 lượt giả lập.
- Ruff `app scripts tests lan_tests`, eslint `app/static`, `git diff --check`: đạt.
- CI được báo trực tiếp ở PR; số liệu trên là kiểm tra cục bộ.

14 bài mới của lượt S2b đầu (tính cả tham số hóa/hai CSDL): giá vốn đúng 2 lô; cân từng thuốc/kỳ/ngày
Việt Nam; số PN đồng thời; loại trường tiền qua JSON/Excel/PDF; bảng 390px, sticky,
kéo/nhớ cột và bộ nhớ bị khóa; giữ tồn cũ/“chưa có giá”; audit và bất biến chứng từ;
rollback/idempotence/lỗi migration nguyên tử. Không nới assertion R5 để qua test.

Sửa tiếp PR #39 thêm 2 bài kiểm toàn schema/S1 và phục hồi ACL/sequence/tồn; báo cáo nguyên nhân và cách sửa tại [S2B_SUA_TIEP_39.md](S2B_SUA_TIEP_39.md).

## Số dòng từng tệp

Số dòng là tổng hiện tại; cột +/− so với `main df9aa8a`.

| Tệp | Dòng | + | − |
|---|---:|---:|---:|
| `AGENTS.md` | 64 | 6 | 0 |
| `app/accounts.py` | 132 | 3 | 3 |
| `app/catalog.py` | 73 | 3 | 1 |
| `app/database.py` | 181 | 3 | 0 |
| `app/domain.py` | 105 | 2 | 2 |
| `app/main.py` | 1090 | 5 | 74 |
| `app/s2b_migration.py` | 83 | 83 | 0 |
| `app/static/app.js` | 1271 | 192 | 15 |
| `app/static/styles.css` | 683 | 37 | 0 |
| `app/stock.py` | 360 | 360 | 0 |
| `app/stock_exports.py` | 208 | 208 | 0 |
| `docs/S2B_KET_QUA.md` | 57 | 57 | 0 |
| `docs/S2B_KHO_THUOC.md` | 67 | 67 | 0 |
| `docs/S2B_SUA_TIEP_39.md` | 35 | 35 | 0 |
| `lan_tests/s2b_browser_cases.py` | 168 | 168 | 0 |
| `lan_tests/test_browser_https.py` | 656 | 2 | 1 |
| `lan_tests/test_pending_queues.py` | 340 | 10 | 3 |
| `lan_tests/test_s2a.py` | 132 | 2 | 2 |
| `lan_tests/test_s2b_migration.py` | 197 | 197 | 0 |
| `lan_tests/test_s2b_stock.py` | 17 | 17 | 0 |
| `lan_tests/test_v050_migration.py` | 148 | 2 | 2 |
| `migrations/016_s2b_stock.sql` | 36 | 36 | 0 |
| `scripts/backup_lan.py` | 303 | 4 | 0 |
| `scripts/do_hieu_nang.py` | 483 | 4 | 1 |
| `scripts/manage.py` | 69 | 7 | 0 |
| `tests/s2b_cases.py` | 228 | 228 | 0 |
| `tests/test_s2b_migration.py` | 101 | 101 | 0 |
| `tests/test_s2b_stock.py` | 28 | 28 | 0 |

Chờ S2c.
