# PR #39 — sửa menu và phục hồi sau migration 016

## Nguyên nhân gốc

Ở head `47fcf68`, `app/s2b_migration.py:49` thu hồi quyền PUBLIC của `s2b_stock_immutable()`, nhưng `scripts/backup_lan.py:255` phục hồi bằng `pg_restore --no-acl` nên ACL riêng đó trở thành `NULL`; bước cấp quyền hiện hành chưa tái lập ACL cho hàm mới. `scripts/install_db.py:106` đưa cả định nghĩa, chủ sở hữu và `proacl` vào dấu kiểm SHA256 nên ACL khác làm kiểm tra quay lui thất bại, dù thân hàm, bảng, thứ tự cột, trigger, default và index vẫn giống.

Menu kho được thêm trong mảng gốc trước khi `m6.js:25` và `m5.js:58` nối hai mục quản trị, nên nó nằm thứ tư thay vì cuối.

## Cách sửa

- `app/static/app.js:21`: đăng ký mục `stock` khi DOMContentLoaded, sau khi các script defer M6/M5 đã nối menu và trước boot; chỉ đổi menu admin.
- `lan_tests/test_browser_https.py:67`: giữ phép so sánh nguyên danh sách cho mọi vai trò; chỉ bổ sung `stock` ở cuối danh sách admin và ghi đúng chú thích theo lệnh.
- `app/s2b_migration.py:12`: dùng chung bước tái lập ACL riêng, không cấp quyền EXECUTE cho PUBLIC/runtime. Không có hàm S2b thì không làm gì; không nâng cấp nhầm bản sao trước 016.
- `scripts/backup_lan.py:256`: gọi bước trên ngay sau pg_restore, trước công bố tệp đính kèm/cài đặt. Giữ nguyên DDL, trigger, hàm bảo vệ S1 và cách tính fingerprint; không sửa deploy/ hoặc workflow.

## Đối chiếu schema và dữ liệu

| Nội dung yêu cầu | Phép kiểm thực tế |
|---|---|
| Bảng/cột/thứ tự cột/default/FK/CHECK/PK | Chụp pg_catalog gồm attnum, kiểu, nullable, identity, generated, default và constraintdef; so bằng hoàn toàn trước/sau phục hồi và trước nâng cấp/sau down. SQLite so cả sqlite_master, PRAGMA table_info và FK. |
| Trigger/function của 012 S1 | 016 chỉ ALTER medicines/stock_lots/stock_movements, không ALTER năm bảng được guard bởi 012; so nguyên pg_get_triggerdef, pg_get_functiondef, chủ hàm và ACL trước/trong/sau 016. |
| Index và sequence | So nguyên indexdef và thông số sequence; stock_receipts_id_seq, stock_issues_id_seq xuất hiện trong pg_restore --list; last_value/is_called của mọi stock sequence giữ nguyên. |
| Bảng mới và số phiếu | stock_receipts, stock_issues, stock_document_sequences có trong dump; dữ liệu phiếu, lô, giá/VAT, biến động và bộ đếm PN/PX khôi phục bằng hoàn toàn. |
| Giá trị thời gian/ngẫu nhiên | 016 không thêm DEFAULT now()/random(); tên tệp, nonce sao lưu không thuộc schema fingerprint. Restore chủ động thêm đúng một audit backup_restored, đã kiểm riêng số dòng/sự kiện; đây là dữ liệu dự kiến, không phải nguyên nhân SHA256 lệch. |
| Không nới bảo vệ | Giữ assertion fingerprint cũ; kiểm runtime không EXECUTE được hàm guard và sau restore vẫn chặn UPDATE/DELETE/TRUNCATE phiếu, biến động. Không sửa timeout. |

Hai bài PostgreSQL bổ sung trong `lan_tests/test_s2b_migration.py` kiểm toàn schema/S1 khi lên-xuống và kiểm sao lưu-phục hồi đủ schema/ACL/sequence/tồn. `test_evidence/s2b-review/schema-restore-diff.json` của lần chạy sau sửa là `{}`; tệp bằng chứng sinh khi kiểm thử, không đưa dữ liệu vào Git.

## Kiểm chứng lần chạy lại

Lần chạy lại trên PostgreSQL 17 có SCRAM (không skip vì trust): `lan_tests/test_windows_install_db.py` **19 đạt**; `lan_tests/test_browser_https.py` **19 đạt**; `lan_tests/test_s2b_migration.py` **3 đạt**; `tests/test_s2b_migration.py` **8 đạt**. Ruff toàn bộ và eslint app/static đạt; giữ nguyên `scripts/install_db.py::fingerprint`, không tăng timeout.

CI windows-install-e2e chạy trên head mới; chưa coi kết quả cục bộ là kết quả CI. Các bộ `lan_tests/test_windows_install_db.py`, `lan_tests/test_browser_https.py`, migration 016 PostgreSQL/SQLite chạy riêng để tách biến môi trường mà test CLI của bộ cài chủ động thay đổi; không sửa assertion để bỏ qua lỗi môi trường.

Chờ S2c.
