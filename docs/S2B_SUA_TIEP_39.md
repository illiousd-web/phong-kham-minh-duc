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

## Sửa báo cáo tiền từ head 89b4f9b

Nguyên nhân: `app/stock.py::stock_report` cộng giá vốn mọi loại xuất rồi trừ khỏi doanh thu,
đồng thời chưa đọc khoản giảm thu và giá vốn của trả thuốc đã duyệt. Màn hình và bản xuất
đều lấy công thức này nên thẻ tháng, Excel và PDF cùng sai.

- Tách `cogs_sold`, `cost_internal`, `cost_supplier_return`, `cost_expired`; ba loại xuất
  ngoài bán có cột riêng, không làm giảm lãi gộp. `cost_of_goods` giữ tên tương thích cho `cogs_sold`.
- Doanh thu thuần = tiền cấp theo đơn − `charge_credits` của trả đã duyệt, theo ngày duyệt Việt Nam.
  Giá vốn trả lấy snapshot của lần xuất gốc; ghép dòng cấp và biến động theo thứ tự trong từng lô
  (hai dòng được tạo cùng giao dịch sau khóa/trừ lô). Không lấy giá hiện tại của lô;
  thiếu snapshot hoặc số lượng đối chiếu không khớp thì giữ “chưa có giá”.
- Lãi gộp = doanh thu thuần − `cogs_sold`; thẻ tháng/JSON/Excel/PDF cùng dùng kết quả này.
  Các trường chi phí mới qua cùng bộ lọc tiền admin/stock_owner; doanh thu và khoản giảm doanh thu
  theo quyền đọc doanh thu cũ. Không đổi migration 016, FEFO, workflow, deploy/ hay phân quyền.
- Sửa ghi chú mẫu HTML dòng 122 đúng “chỉ hiện với Quản trị và Chủ kho thuốc”.
- Thêm 14 ca tham số hóa trên SQLite/PostgreSQL trong `tests/s2b_cases.py` và hai wrapper:
  nội bộ 20.000 không giảm lãi; trả NCC/hủy 20.000 đúng cột; bán 50.000/vốn 20.000 rồi trả
  toàn bộ ra 0/0/0, trả nửa ra 25.000/10.000/15.000. Trả lấy từ hai lô 1.000 và 2.250;
  kiểm pending, ngày duyệt cùng/ngày kế tiếp, tồn cách ly/cân tồn, Excel/PDF và tổng thẻ tháng.
  Assertion giá vốn chưa biết của xuất nội bộ được chuyển sang `cost_internal IS NULL` và
  lãi bằng 0 theo chính yêu cầu sửa công thức mới; giữ kiểm bất biến snapshot.
- Bổ sung kiểm cột báo cáo ở 390px và quyền UI. Khi test lưu quyền bộc lộ đọc dữ liệu trước
  HTTP lưu xong, dùng helper `send` sẵn có chờ đúng phản hồi; không nới assertion hoặc timeout.

Kết quả kiểm lần này được ghi tại [S2B_KET_QUA.md](S2B_KET_QUA.md); CI báo trực tiếp trên PR.

Chờ S2c.
