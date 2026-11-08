# Minh Đức v0.4 — thử nghiệm máy chủ LAN

Nhánh này bổ sung PostgreSQL, HTTPS nội bộ, tài khoản nhân viên riêng, quản lý phiên/phân quyền, nhật ký, sao lưu mã hóa và khôi phục. Giữ giao diện xanh ngọc–trắng, logo và 9 mẫu Word gốc. **Chỉ dùng dữ liệu giả lập; chưa nghiệm thu bảo mật và nghiệp vụ y tế.**

- [Cài đặt Linux/Windows và máy trạm](docs/LAN_INSTALL.md)
- [Vận hành, backup/restore, xử lý sự cố](docs/LAN_OPERATIONS.md)
- [Rà soát mã nguồn và kết quả kiểm thử](docs/LAN_VALIDATION.md)

Dùng `python -m scripts.run_lan` với cấu hình LAN; các launcher cũ bên dưới vẫn là demo loopback. Không public hosting, không port forwarding và không tự triển khai dữ liệu thật.

---

# Phòng khám đa khoa Minh Đức — phần mềm thử nghiệm v0.3.0

**Trạng thái:** ĐÃ CHẠY VÀ KIỂM THỬ TRÊN MÔI TRƯỜNG CỤC BỘ. Đây là phiên bản thử nghiệm với dữ liệu giả lập; **không được sử dụng cho người bệnh thật, kê đơn hợp pháp, cấp phát thuốc thực tế, giao dịch tài chính thật hoặc mở ra Internet.**

> **Bản đóng gói v0.3.1 (sửa khởi động Windows):** có thêm `HUONG_DAN_CAI_DAT_WINDOWS.md`; `START_WINDOWS.bat` nhận cả `py` lẫn `python`. Mã ứng dụng và các chức năng vẫn là v0.3.0.

## 1. Cài và chạy trên Windows

1. Cài **Python 3.11 trở lên** (khuyến nghị 3.12/3.13), bảo đảm có trình khởi động `py`. Trong quá trình cài Python, chọn thêm Python vào PATH nếu được hỏi.
2. Clone repository hoặc tải mã nguồn vào thư mục riêng, ví dụ `C:\MinhDucDemo`. Mã nguồn hiện nằm trực tiếp ở gốc repository.
3. Nhấp đúp **`START_WINDOWS.bat`**. Lần đầu chương trình tạo `.venv` và tải thư viện Python; bước này cần Internet. Không đóng cửa sổ màu đen khi đang sử dụng.
4. Khi thấy máy chủ khởi động, mở Chrome/Edge trên **chính máy tính đó** tại địa chỉ **http://127.0.0.1:8000**.
5. Chọn tài khoản demo và nhập mật khẩu thử nghiệm chung: mật khẩu bạn nhập khi khởi động.
6. Dừng máy chủ bằng `Ctrl+C` trong cửa sổ chạy phần mềm.

Nếu không chạy được bằng chuột, mở PowerShell ngay trong thư mục và chạy:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\run_demo.py
```

Trên Linux/macOS: chạy `sh START_LINUX_MAC.sh` và mở cùng địa chỉ localhost.

**Không đổi `--host 127.0.0.1` thành `0.0.0.0`, không mở cổng Internet, không cho truy cập từ điện thoại/thiết bị khác đối với phiên bản demo này.** Tính tương thích bố cục điện thoại đã kiểm bằng trình duyệt giả lập, không tương đương với cho phép truy cập từ xa có bảo mật.

## 2. Các tài khoản dùng thử

| Tài khoản | Công việc |
|---|---|
| `letan` | Tiếp đón, bệnh nhân, lịch hẹn, tạo lượt khám, tải phiếu tiếp đón |
| `bs_noi` | Khám người bệnh được phân công, chỉ định, duyệt kết quả mô phỏng, tạo đơn thuốc nháp, xuất phiếu |
| `bs_san` | Tài khoản bác sĩ khác, kiểm thử giới hạn hồ sơ được phân công |
| `kythuat` | Nhập, gửi chờ duyệt và đính kèm kết quả cận lâm sàng |
| `duoc` | Kho mẫu theo lô và nhập/xuất FEFO cho mặt hàng thông thường |
| `thungan` | Thu tiền mô phỏng, công nợ, phiếu thu, đề nghị giảm giá / hoàn tiền |
| `quanly` | Báo cáo mô phỏng, duyệt/từ chối điều chỉnh tiền, xem kho |
| `quantri` | Truy cập nhật ký và công cụ quản trị sơ bộ |
| `dieuduong` | Tài khoản điều dưỡng; quyền xem bệnh án vẫn hạn chế vì chưa phân công từng hồ sơ |

Mật khẩu chung được dùng **chỉ để thử nghiệm**. Không tạo tài khoản bệnh nhân thật hoặc lưu thông tin nhạy cảm trong phiên bản này.

## 3. Chức năng đã chạy

- Lưu hồ sơ bệnh nhân mô phỏng và tìm kiếm; tiếp nhận trực tiếp hoặc qua lịch hẹn; lập lượt khám theo bác sĩ.
- Nhập phiếu khám chi tiết có bảo vệ phiên bản chỉnh sửa; bác sĩ chỉ xem được hồ sơ được giao.
- Tạo chỉ định xét nghiệm, siêu âm, X-quang, điện tim; kỹ thuật viên nhập kết quả và đính kèm PDF/PNG/JPEG; bác sĩ phụ trách duyệt trong quy trình thử nghiệm.
- Đơn thuốc **nháp**, không ký số/không cấp thuốc; giấy hẹn; tải phiếu từ **dữ liệu SQLite đã lưu** dưới dạng **Word hoặc PDF** (9 mẫu gốc tích hợp).
- Ghi khoản phải thu, nhận tiền mặt/chuyển khoản thủ công, in phiếu thu PDF; giới hạn thanh toán vượt tiền cần thu, tránh ghi trùng giao dịch.
- Thu ngân đề nghị giảm giá/hoàn phần tiền trả thừa; **quản lý phê duyệt**; sổ ghi điều chỉnh không bị xóa.
- Kho giả lập: quản lý lô, hạn dùng, nhập và xuất nội bộ theo ưu tiên hạn dùng FEFO; từ chối xuất âm kho, lô hết hạn/cách ly; **khóa giao dịch thuốc phải kiểm soát đặc biệt**.
- Đăng nhập theo vai trò, nhật ký thao tác và mẫu dữ liệu demo; thiết kế responsive xanh ngọc – trắng, logo Minh Đức.

## 4. Kiểm tra và sao lưu

Kết quả kiểm thử chi tiết ở **`KET_QUA_KIEM_THU_V03.md`**.

Để chạy kiểm thử tự động trên Windows sau khi cài xong:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe -m pytest -q
```

Tùy chọn kiểm giao diện bằng Chromium/Playwright cần cài trình duyệt riêng; lệnh `python tests/browser_smoke.py` được thử thành công trong môi trường Linux Chromium đã cài sẵn, không bảo đảm chạy trên mọi Windows chưa chuẩn bị môi trường.

Sao lưu CSDL demo và tệp đính kèm một cách nhất quán bằng cách nhấp **`SAO_LUU_THU_NGHIEM_WINDOWS.bat`**, hoặc:

```powershell
.venv\Scripts\python.exe scripts\backup_demo.py create
.venv\Scripts\python.exe scripts\backup_demo.py verify backups\TEN_TEP_SAO_LUU.zip
```

Sao lưu là bản ZIP **không mã hóa**, chỉ dành cho dữ liệu mô phỏng. Không sử dụng bản sao lưu này để lưu thông tin y tế thật.

## 5. Cấu trúc

- `app/main.py` — API FastAPI và cơ sở dữ liệu SQLite, kiểm tra quyền.
- `app/static/` — giao diện HTML/CSS/JS và logo.
- `app/forms.py`, `app/forms_api.py` — tự động điền Word và xuất PDF từ hồ sơ đã lưu.
- `app/print_forms.py` — PDF phiếu thu và các phiếu minh họa bổ sung.
- `app/templates/` — **9 mẫu Word đã thiết kế của Phòng khám Minh Đức**.
- `scripts/backup_demo.py` — sao lưu, xác minh checksum và khả năng mở lại CSDL.
- `schema.sql` — cấu trúc dữ liệu hiện hành có bảng yêu cầu điều chỉnh tiền.
- `tests/` — bài kiểm thử API, quyền, chứng từ và Chromium.
- `test_evidence/` — ảnh màn hình và PDF minh họa từ luồng kiểm thử dùng bệnh nhân giả lập.

Khi chạy lần đầu, ứng dụng tự tạo `data/minh_duc_demo.sqlite3`. Nếu muốn reset demo, **tắt chương trình, sao lưu lại**, rồi đổi tên file này; khởi động lại sẽ tạo CSDL trống cho bệnh nhân và tái tạo tài khoản/danh mục demo.

## 6. Hạng mục chưa đủ điều kiện sử dụng thật

Không có chữ ký số và liên thông đơn thuốc điện tử; chưa kiểm nghiệm quy trình chuyên môn theo giấy phép cơ sở, mẫu in pháp lý, mã định danh, dữ liệu lâm sàng; chưa có kết nối máy y tế thực tế, DICOM/PACS/HL7, tài khoản và quyền cấp phép ở phạm vi thật; chưa có xác thực nhiều yếu tố, quản lý thiết bị, mã hóa CSDL khi lưu, đánh giá an toàn thông tin, cơ chế hồi phục vận hành đạt yêu cầu; chưa có thuế/hóa đơn điện tử, kế toán, chi phí giá vốn đầy đủ, nhà thuốc hợp pháp, quản lý thuốc đặc biệt.

Các máy in Canon, Epson, máy siêu âm, X-quang, xét nghiệm và điện tim **chưa được kết nối/kiểm thử trực tiếp**. Mọi biểu mẫu, chứng từ và kết quả in vẫn đóng dấu **BẢN THỬ NGHIỆM**. Đánh giá lâm sàng, pháp lý và bảo mật độc lập là điều kiện bắt buộc trước khi cân nhắc triển khai thực tế.

## Phát triển từ mã nguồn

Mã FastAPI nằm ở `app/`, kiểm thử ở `tests/`, schema ở `schema.sql`. Logo và cả 9 mẫu Word gốc được giữ nguyên; các bản trong `app/templates/`, `assets/forms/` và `templates/` giữ nguyên để bảo toàn tương thích.

Trên Linux/macOS, tạo virtualenv, cài `requirements-test.txt`, rồi chạy `python -m pytest -q`. Chạy `python tests/browser_smoke.py` nếu đã cài Chromium tại `/usr/bin/chromium`. Ảnh/PDF kiểm thử được sinh vào `test_evidence/` và không đưa vào Git.

Khởi động bằng `python scripts/run_demo.py` trong virtualenv. Chương trình hỏi mật khẩu không hiện ký tự và không lưu mật khẩu vào tệp. Có thể truyền `DEMO_PASSWORD` từ môi trường tiến trình; không đưa giá trị vào mã nguồn hoặc Git. Nếu gọi uvicorn trực tiếp, phải cung cấp biến này trước. Mật khẩu chỉ dùng để tạo tài khoản khi khởi tạo CSDL; đổi biến không thay đổi mật khẩu của tài khoản đã tồn tại. Giữ mật khẩu đã dùng cho CSDL demo đó.

Không commit dữ liệu trong `data/`, `backups/`, tệp đính kèm, bản xuất, `.env` hoặc khóa bí mật. Chỉ dùng dữ liệu giả lập. Chưa mở truy cập LAN; nâng cấp triển khai nội bộ là công việc tiếp theo.
