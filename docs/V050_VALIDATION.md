# Kiểm thử Minh Đức LAN v0.5.0

Phạm vi: mã nguồn A–D trên nhánh `feat/v0.5.0-clinical-workflows`, dữ liệu giả lập, PostgreSQL 17.11 cục bộ và Chromium trên Linux. Đã đối chiếu [nguồn main/ZIP v0.4.1](V050_SOURCE.md). Không triển khai máy phòng khám, không merge main, không sử dụng dữ liệu bệnh nhân thật.

## Kết quả tự chạy

| Bộ kiểm tra | Kết quả |
|---|---|
| Toàn bộ hồi quy `pytest tests` | 61 đạt, 0 thất bại |
| Toàn bộ `pytest lan_tests` | 47 đạt, 0 thất bại |
| Chromium smoke cũ | Đạt tiếp đón → khám → chỉ định → kết quả duyệt → đơn nháp → thu ngân → quản lý; tải PDF, desktop/mobile, 0 lỗi JS |
| HTTPS thực, các tài khoản riêng | Đạt; phiên lễ tân/bác sĩ/thu ngân cùng mở; luồng A–D thêm kỹ thuật viên, dược, điều dưỡng, quản lý; kiểm cả bác sĩ duyệt độc lập chưa được giao lượt |
| Chín biểu mẫu DOCX/PDF và bố cục | Các bài cũ và mới đạt; phụ lục xuất PDF/Word giữ nguyên nội dung gốc |
| Hash tài sản gốc | 31/31 dòng manifest đạt, gồm 9 DOCX và logo |
| Migration dữ liệu cũ | Đạt schema v0.4.1 từ ZIP và v0.4.2 từ nhánh; so từng giá trị cột cũ, chạy lặp, không tự thu phí cũ |
| Rollback lỗi migration | Đạt: cố ý gây lỗi DDL, không để schema/marker nâng cấp nửa chừng |
| Backup/restore | Đạt mã hóa, kiểm toàn vẹn, attachments, đích rỗng, phiên bị thu hồi; gồm dữ liệu đã nâng cấp |
| Quyền PostgreSQL runtime | Đạt SELECT view, từ chối DDL và sửa/xóa/truncate các bảng chứng cứ; trigger chặn đổi nội dung/trạng thái hồ sơ đã khóa |
| PowerShell Preflight | Parser và 6 tình huống giả lập đạt bằng PowerShell 7 trên Linux; native Windows được kiểm thêm bởi job CI, không suy ra đã kiểm máy phòng khám |
| `pip-audit -r requirements.lock --no-deps --disable-pip` | Không tìm thấy lỗ hổng đã biết tại lần chạy |
| Python compile, JS syntax, `git diff --check` | Đạt |

Có một cảnh báo deprecation từ Starlette TestClient/httpx; không có bài bị bỏ qua trong hai bộ pytest trên. CI tải JUnit, ảnh và PDF tại artifact `synthetic-clinic-test-evidence`. Kết quả CI/Windows phải xem trên đúng commit PR, không dùng báo cáo Linux làm kết quả Windows.

## Các tình huống A–D đã kiểm

**A:** dịch vụ có mã/giá/hiệu lực, giá lịch sử; nháp chưa thu tiền; ba yêu cầu duyệt đồng thời chỉ một khoản; khóa lặp khác dữ liệu bị từ chối; người sai quyền không duyệt; ngừng dịch vụ không sửa phí cũ; điều chỉnh giá có lý do; ứng trước, thu nhiều lần, hoàn tiền và công nợ độc lập; hủy chỉ định và đối soát giảm phí.

**B:** đơn liên kết lượt/thuốc; snapshot đơn vị quy đổi; FEFO theo lô/hạn/cách ly; ba cấp phát đồng thời chỉ một thành công; nhiều dòng cùng thuốc thiếu tổng tồn rollback cả đơn; hủy nháp giữ kho; trả một phần/toàn bộ, giữ lượng phiếu trả chờ duyệt, từ chối trả giải phóng lượng giữ, không trả vượt số đã cấp; duyệt trả/hoàn tiền đồng thời không trùng; tiền trả giảm bảng kê và tồn trả vào cách ly. Khi giảm phí vượt phí còn lại, giao dịch trả rollback cả kho/tiền rồi chỉ tiếp tục sau hoàn tác có lý do. Kiểm riêng thuốc kiểm soát: kê, duyệt bác sĩ độc lập, hai người nhập, cấp, trả, sổ riêng; tài khoản thường bị từ chối cả quản lý đơn vị quy đổi, hủy đơn và hủy lượt có thuốc kiểm soát.

**C:** điều dưỡng chưa được giao/sai người không xem ca hoặc thực hiện y lệnh; người được giao ghi sinh hiệu, chăm sóc và thực hiện đúng một lần; cấm sửa chẩn đoán/duyệt kết quả; khóa lượt khi còn y lệnh; lịch sử có người/thời gian; sinh hiệu không bị phản hồi tải ca ghi đè khi nhập nhanh; khoản tiền không trả cho điều dưỡng thuần quyền.

**D:** chẩn đoán và chỉ định/y lệnh/đơn kiểm soát là điều kiện hoàn tất; bắt buộc phiên bản đã đọc trong LAN, từ chối phiên bản cũ; chuyên môn khóa nhưng công nợ/cấp thuốc độc lập; API và trigger PG bảo vệ bản gốc; phụ lục do người khác duyệt, giữ bản gốc và từ chối duyệt phụ lục cũ; phiên bản/audit/PDF/Word; hủy lượt giữ chứng từ và tiền cần hoàn, chặn thu mới vào lượt hủy.

## Hiệu năng trên môi trường thử

[Số đo JSON và thông số môi trường](benchmarks/v050-linux-synthetic.json). 1.000 bệnh nhân giả lập, 16 MiB attachments, PostgreSQL container giới hạn 2 CPU/1.536 MiB; web chạy Linux, 1 worker/pool4/8 luồng. So với main `e3edb2d`, cả hai dùng profile PostgreSQL có trong đúng cây nguồn. Trình tạo tải không tính vào RAM web; backup đo riêng. Các bộ kiểm thử khác cùng chạy trong workspace nên số đo chỉ là một mẫu, không chứng minh tốc độ tối đa hay SLA.

| Chỉ số | Main trước v0.5 | v0.5 |
|---|---:|---:|
| Yêu cầu API, ba vai trò | 210, không lỗi | 210, không lỗi |
| Độ trễ API p95 | 82,42 ms | 91,12 ms |
| PDF p95 | 177,21 ms | 256,65 ms |
| RAM web RSS đỉnh | 91,26 MiB | 97,09 MiB |
| RAM web USS đỉnh | 63,90 MiB | 70,14 MiB |
| RAM backup RSS đỉnh | 46,16 MiB | 46,18 MiB |
| Database/WAL cuối mẫu | 10,13/16 MiB | 10,20/16 MiB |

Không tuyên bố v0.5 nhanh hơn main: có thêm snapshot và kiểm tra giao dịch, RAM web tăng khoảng 5,83 MiB ở mẫu này. Retry sau ngắt kết nối chỉ có một phiếu thu; kiểm quyền đạt. `fsync`, `synchronous_commit`, `full_page_writes` đều **on**. PostgreSQL RSS có shared pages nên không cộng thô vào web để kết luận RAM toàn hệ thống. Đây không phải benchmark Windows 11/i3-10105, không mô phỏng mất điện vật lý hay SSD đầy thực tế.

## Lỗi đã phát hiện và sửa trong đợt này

- Adapter PostgreSQL tự thêm `RETURNING id` cả bảng có khóa khác tên; sửa nhận diện bảng identity.
- Migration gặp hồ sơ cũ đọc tuple thay record; sửa row factory và thêm so dữ liệu/rollback/restore.
- Xuất kho từng dòng chưa tổng hợp nhu cầu trùng thuốc; kiểm tổng toàn đơn trước xuất.
- Chọn đơn vị thuốc hoặc ca sinh hiệu đang tải có thể bị phản hồi cũ ghi đè; khóa nhập trong lúc tải và kiểm kết quả lưu.
- Phản hồi render cũ ghi đè trang mới hoặc phản hồi nạp phiếu khám xóa chẩn đoán vừa nhập; dùng số thứ tự render, điền biểu mẫu đồng bộ từ snapshot đã tải trước khi cho nhập, trạng thái tải và khóa nội dung đã hoàn tất.
- Trần 24 kết nối Uvicorn tính cả kết nối dự phòng/nhàn rỗi Chrome gây 503 tài nguyên trong sáu phiên; giữ giới hạn hữu hạn 48, keep-alive 2 giây; không tăng worker/pool/luồng.
- Bác sĩ duyệt độc lập không có lượt được giao không mở được hàng đợi; tách công cụ duyệt/danh mục khỏi điều kiện phải có lượt.

## Giới hạn và rủi ro còn lại

Không có lỗi kiểm thử đang biết chưa sửa trong phạm vi A–D. Chưa nghiệm thu thực tế Windows 11/i3, mạng máy trạm, máy in giấy, điện/SSD, quản lý khóa/CA/offsite backup và nghiệp vụ y tế/dược. Cần người phụ trách nghiệm thu độc lập trước dùng thật. Kiểm thử tự động không phải chứng nhận an toàn bảo mật hoặc tuân thủ pháp lý; chưa có chữ ký số chuyên môn, kết nối máy xét nghiệm hoặc thanh toán ngân hàng.

Giữ một đơn thuốc mỗi lượt như schema cũ. Đơn hủy lưu nguyên lịch sử và không tái sử dụng; chưa hỗ trợ đơn thay thế trong cùng lượt. Thuốc trả chỉ vào cách ly; chưa có luồng hủy vật lý hoặc đưa lại vào tồn bán. Không tự đổi đơn văn bản cũ thành đơn cấu trúc. Các giới hạn này được nêu trong hướng dẫn, không cho đi vòng bằng cập nhật database.

Migration thêm bảng có lịch sử ngày càng tăng; giới hạn backup, log, attachments và chỗ trống vẫn giữ nhưng không phải giới hạn cứng cho tổng database/WAL. Theo dõi Preflight/storage_status, không xóa audit/WAL để lấy chỗ. Quay lui dùng bản backup đã xác minh ở đích mới, không chỉ đổi mã nguồn.

## Ảnh thao tác giả lập

[A — chỉ định](v050-screenshots/A-chi-dinh.png) · [B — nhà thuốc](v050-screenshots/B-cap-phat.png) · [C — điều dưỡng](v050-screenshots/C-dieu-duong.png) · [D — hoàn tất/phiên bản](v050-screenshots/D-khoa-luot.png).

Lệnh tái lập:

```sh
python -m pytest tests -q
# CLINIC_TEST_DATABASE_URL trỏ server PostgreSQL cục bộ dành riêng kiểm thử.
python -m pytest lan_tests -q
python tests/browser_smoke.py
sha256sum -c docs/assets-v031.sha256
python -m scripts.benchmark_lan --baseline-ref e3edb2d --iterations 30 --output docs/benchmarks/v050-linux-synthetic.json
```

Benchmark tự tạo/xóa container giả lập, không nhận database phòng khám. Cần Docker, client PostgreSQL 17 và venv đã cài requirements-test.lock; `CLINIC_PG_DUMP`/`CLINIC_PG_RESTORE` dùng khi client không nằm trong PATH. Không đưa mật khẩu hay bản dữ liệu thật vào báo cáo.
