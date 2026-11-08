# Rà soát và kiểm thử LAN v0.4

Ngày thực hiện: 08/11/2026. Base: `main` tại `793dcb1` (PR chuẩn hóa #1 đã merge). Nhánh phát triển: `feat/lan-server-postgresql`. Chỉ dữ liệu giả lập, chưa triển khai lên máy chủ phòng khám, chưa dùng bệnh nhân thật. Không merge main.

## Phạm vi mã nguồn

Đối chiếu các module runtime Python, frontend JS/HTML/CSS, schema, launcher, script backup, bộ kiểm thử và hướng dẫn cũ. Tách tầng cấu hình, PostgreSQL/SQLite, xác thực, tài khoản, danh mục; giữ endpoint nghiệp vụ và bộ xuất 9 biểu mẫu. Đọc luồng quyền, truy vấn, giao dịch, upload và export; đây là rà soát phát triển, không phải chứng nhận hết lỗi hay kiểm thử xâm nhập độc lập. Các bản Word/logo kiểm tra bằng manifest byte, không suy luận nội dung nhị phân là mã nguồn.

## Kết quả theo yêu cầu

| Hạng mục | Kết quả đã xác minh | Phần chưa xác minh tại phòng khám |
|---|---|---|
| Rà mã và sửa lỗi | Sửa các lỗi ghi dưới đây; kiểm thử hồi quy và LAN đạt | Không khẳng định toàn bộ mã không còn lỗi |
| Giao diện, logo, 9 mẫu | Giữ nguyên CSS; 31 tệp PNG/DOCX khớp SHA-256 gốc; xem screenshot lễ tân và PDF thực | Chưa đối chiếu mọi trang Word/PDF dài bằng mắt hoặc nghiệm thu biểu mẫu y tế |
| Máy chủ LAN | Launcher chỉ bind IP riêng đã chọn; CIDR/Host/HTTPS bắt buộc; không tin proxy header | Chưa kiểm router, VLAN, máy chủ thật hoặc Wi-Fi khách |
| Tài khoản riêng, quyền, audit | LAN không seed demo; tạo/khóa/reset/đổi mật khẩu, phân vai, thu hồi phiên; audit theo nhân viên và phân trang | Chưa nhập ma trận nhân sự thực, chưa có MFA/SSO |
| PostgreSQL và đồng thời | PostgreSQL 17.11, khóa ghi giữa worker, version bệnh án, idempotency, FEFO và rollback | Chưa benchmark tải lớn, HA hoặc tích hợp SQL ngoài ứng dụng |
| HTTPS, phiên, dữ liệu | HTTPS thật, TLS tối thiểu 1.2/cipher hiện đại; CA riêng; cookie HttpOnly/Secure/Strict; CSRF, idle20m/absolute8h, lockout; script firewall | Chưa áp firewall/trust/BitLocker/LUKS trên thiết bị phòng khám; không có kiểm thử xâm nhập độc lập |
| Backup/restore/sự cố | Dump + attachments + manifest, AES-GCM, khôi phục database riêng, thu hồi phiên, lỗi DB503, rollback, từ chối backup sửa/sai khóa | Timer/systemd/Task Scheduler mới là cấu hình; chưa chạy theo lịch trên máy thật, chưa đo RPO/RTO hay phục hồi sau mất điện thật |
| Ba vai trò đồng thời | API ba tác vụ đồng thời; ba browser context lễ tân/bác sĩ/thu ngân cùng đăng nhập qua HTTPS, web 2 worker | Không phải ba máy vật lý; phải nghiệm thu tại LAN |
| Quy trình nghiệp vụ | Tiếp đón/hẹn/khám/chỉ định/nhập và duyệt 4 loại kết quả/đơn nháp/kho/thu/giảm phí/hoàn tiền/PDF và Word | Chưa thẩm định chuyên môn, ký số, liên thông, hóa đơn, thuốc kiểm soát hoặc máy CLS |
| Hướng dẫn | Có đường cài native Linux/Windows, máy trạm, CA, quyền DB, backup/restore và runbook sự cố | Windows/PowerShell chưa chạy thực tế trong môi trường Linux này |
| PR | Thay đổi trên nhánh riêng, đưa vào PR để chủ repo kiểm tra | Không tự merge; không tự nghiệm thu dùng dữ liệu thật |

## Các lỗi/rủi ro đã xử lý

1. Trước đó web bắt buộc mật khẩu demo chung và tự tạo tài khoản/kho demo. Chế độ LAN mới không dùng `DEMO_PASSWORD`, không tạo demo users/data, quản trị tạo từng tài khoản và danh mục qua UI/CLI riêng.
2. Token trước đó được frontend giữ trong sessionStorage. LAN chuyển cookie HttpOnly và cơ chế chống CSRF, kiểm origin, rotate/logout/revoke; giữ bearer chỉ cho demo loopback để không phá bộ hồi quy cũ.
3. Bản cũ dùng SQLite `BEGIN IMMEDIATE`; nếu chuyển thẳng sang PostgreSQL sẽ mất bảo vệ read-check-write. Tầng PostgreSQL mới giữ advisory lock trước các đọc nghiệp vụ trong giao dịch ghi, chống thu vượt, sửa trạng thái kết quả, nhập/xuất kho và duyệt điều chỉnh cạnh tranh. Có thêm unique lịch hẹn và số định danh.
4. Hàm xuất biểu mẫu cắt bệnh sử/chỉ dẫn/kết quả tại các mốc 400/600/900/6000 ký tự, dù API nhận dài hơn. Đã giữ đủ nội dung chấp nhận; bảng chỉ định Word thêm hàng thay vì chỉ 3 hàng; bảng đơn PDF có thể tách hàng qua trang. Kiểm tail marker xác nhận các phần dài còn đầy đủ.
5. Phiếu tiếp đón Word trước đó đưa `chief_complaint` của bác sĩ vào tài liệu lễ tân. Đã bỏ phần chuyên môn khỏi phiếu tiếp đón, có bài kiểm không lộ triệu chứng/bệnh sử qua export này.
6. Thêm kiểm bác sĩ còn hoạt động khi phân công và kiểm định dạng ngày/giờ lịch hẹn; phản hồi validation bỏ dữ liệu input chứa mật khẩu/hồ sơ. Upload giới hạn body 6MB và tệp 5MB, giữ kiểm loại/chữ ký đầu tệp.
7. Bổ sung request submit guard, giữ idempotency key khi retry trong cùng trang; rowcount kiểm tồn kho. Lỗi DB/pool trả 503 không lộ thông tin kết nối. Log truy cập bổ sung không biến thanh toán đã commit thành lỗi phản hồi nếu log bổ sung gặp sự cố.
8. Backup demo trước đó không mã hóa và chưa có khôi phục an toàn cho máy chủ. LAN có backup nhất quán với attachments, GCM/manifest, restore đích rỗng, single transaction DB và thu hồi session; file thành công xuất bản bằng rename, giữ bản tốt cũ khi lệnh thất bại trước xuất bản.
9. Audit CVE phát hiện cryptography 47.0.0; nâng lên 50.0.2 theo các bản vá được công bố. Khóa phiên bản runtime/test, giữ công cụ audit ra khỏi dependencies runtime.

## Lệnh và bằng chứng kiểm thử

Môi trường: Python 3.12, PostgreSQL 17.11 trong container official chỉ publish loopback, Chromium headless, hai Uvicorn worker. Database test tạo tên ngẫu nhiên rồi xóa. Mật khẩu/key/cert test phát sinh ngẫu nhiên và không commit.

```sh
python -m pip install -r requirements-test.lock
python -m pytest tests -q --junitxml=test_evidence/demo-junit.xml
# CLINIC_TEST_DATABASE_URL trỏ PostgreSQL thử nghiệm local có quyền CREATE DATABASE.
# Không trỏ test vào database có dữ liệu cần giữ.
# Cài pg_dump/pg_restore 17; CHROMIUM_PATH tùy môi trường.
python -m pytest lan_tests -q --junitxml=test_evidence/lan-junit.xml
python -m pip install pip-audit==2.10.1
python -m pip_audit -r requirements.lock --no-deps --disable-pip --format json
sha256sum -c docs/assets-v031.sha256
node --check app/static/app.js
python -m compileall -q app scripts lan_tests
python -m pip check
git diff --check
```

- Bộ hồi quy: **43 passed**. Bộ LAN: **21 passed**. Không có test bỏ qua trong hai lần chạy báo cáo này.
- Browser LAN dùng HTTP/TLS thật, không dùng API bridge. HTTPX xác minh chain/hostname bằng CA test; Chromium pin riêng public key chứng thư test. Kiểm cookie, không token sessionStorage, ba context độc lập và không có JS page error. Có tải PDF kết quả và đơn nháp qua UI.
- Tranh chấp: hai cập nhật cùng version chỉ một thành công; ba khoản thu cạnh tranh không vượt dư nợ; ba POST cùng idempotency key tạo đúng một payment; hai xuất kho cạnh tranh chỉ một thành công và FEFO còn đúng tồn.
- Kiểm đủ 9 loại biểu mẫu ở cả PDF và DOCX qua API trên PostgreSQL, có thêm phiếu thu PDF, từ chối quyền sai/chưa duyệt, kiểm nội dung dài và rò rỉ phiếu tiếp đón.
- Backup/restore dùng pg_dump/pg_restore thật, phục hồi tệp và bản ghi, từ chối đích đã có bảng, bản sửa byte/sai khóa bị GCM từ chối, session sau restore bằng 0.
- Kiểm phân quyền DB với runtime role không sở hữu bảng: INSERT/SELECT audit được; UPDATE/DELETE/TRUNCATE bị từ chối.
- CVE audit runtime: **không phát hiện lỗ hổng đã biết** theo dữ liệu dịch vụ tại thời điểm chạy. Không tương đương quét hệ điều hành, PostgreSQL image, trình duyệt hoặc pentest; lockfile hiện pin phiên bản, chưa pin hash wheel.
- Manifest: **31/31 tệp gốc khớp**, CSS không sửa. `pip check`, parse YAML, compile Python, JS syntax, shell syntax và diff whitespace đạt.
- Một cảnh báo deprecation từ Starlette TestClient khi dùng httpx; không làm test thất bại. Chưa chuyển adapter test sang httpx2 để tránh thêm thay đổi ngoài phạm vi.

Bằng chứng local (không commit dữ liệu test/key): `test_evidence/demo-junit.xml`, `lan-junit.xml`, `dependency-audit.json`, `lan/reception.png`, `doctor.png`, `cashier.png`, `result.pdf`, `rx.pdf`. Workflow `.github/workflows/clinic-tests.yml` tạo lại các kiểm thử và upload artifact dữ liệu giả lập; trạng thái CI trên GitHub phải đọc riêng, không suy từ kết quả local.

## Giới hạn còn lại

Không dùng dữ liệu thật trước nghiệm thu bảo mật và nghiệp vụ y tế. Chưa có mã hóa từng trường CSDL; bảo vệ at-rest phụ thuộc ổ mã hóa, ACL, backup/key và vận hành host. Chưa tích hợp quét malware/CDR cho PDF/ảnh đính kèm, chưa kiểm định chữ ký số/đơn thuốc/chuẩn y tế. Nhân viên có quyền tải tài liệu có thể giữ file ngoài hệ thống; cần quy trình quản lý thiết bị/in ấn.

Khóa toàn bộ ghi là thiết kế bảo thủ, giảm throughput và có thể gây timeout trong backup dài. Restore có hai tài nguyên DB/filesystem, không có distributed transaction: lỗi filesystem sau DB commit có thể để đích phục hồi chưa đầy đủ; runbook yêu cầu xác minh đích mới trước chuyển cấu hình. Không có tự động copy backup offline, PITR, failover, số RTO thực tế hay bảo đảm lịch chạy trên máy chưa được cài.

Một phần dữ liệu phi cấu trúc/ngày vẫn giữ kiểu TEXT để tương thích nghiệp vụ cũ; chưa chuẩn hóa bệnh án điện tử. Chưa chuyển SQLite demo sang hồ sơ production; LAN khởi tạo rỗng để tránh kéo tài khoản/mật khẩu và dữ liệu demo cũ sang hệ thống mới. ZIP/mật khẩu demo từng có trong lịch sử Git vẫn tồn tại trong lịch sử, không được dùng lại làm thông tin đăng nhập thực tế.
