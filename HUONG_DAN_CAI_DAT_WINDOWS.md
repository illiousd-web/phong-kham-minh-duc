# Hướng dẫn cài và chạy Windows — Minh Đức v0.3 (bản sửa bộ khởi động)

> Đây là phần mềm thử nghiệm trên **máy tính Windows**, chỉ sử dụng dữ liệu giả lập. Không phải phần mềm đã nghiệm thu sử dụng bệnh nhân thật. File `.bat` không chạy trên điện thoại Android.

## Bước 1. Chuẩn bị máy tính
- Windows 10/11 64-bit, có Chrome hoặc Edge.
- Python **3.12 64-bit** là lựa chọn dễ tương thích. Nếu đã có Python 3.11 hoặc 3.13 thì không cần cài lại.
- Cài Python từ <https://www.python.org/downloads/windows/>. Nếu trình cài đặt có lựa chọn **Add python.exe to PATH**, hãy chọn; nếu có **Python Launcher**, hãy cài.
- Mở **Command Prompt** (Win+R → `cmd`) và chạy `py --version`. Nếu báo không có `py`, thử `python --version`. Một trong hai lệnh phải nhận Python 3.11–3.13.

## Bước 2. Giải nén đúng chỗ
- Tải ZIP về máy, nhấp phải → **Extract All…** (Giải nén tất cả).
- Dùng thư mục gốc của repository sau khi clone hoặc giải nén bản tải từ GitHub; nơi này phải có quyền ghi.
- Mở thư mục này và **phải thấy cùng cấp** `START_WINDOWS.bat`, `requirements.txt`, `app` và `data`. Không nhấp chạy tệp `.bat` bên trong cửa sổ ZIP.

## Bước 3. Khởi động
- Nhấp đúp `START_WINDOWS.bat`. Lần đầu cần kết nối Internet để cài các thư viện vào `.venv` (máy có thể mất vài phút, phụ thuộc Internet).
- Cửa sổ dòng lệnh sẽ dừng ở `Uvicorn running on http://127.0.0.1:8000` khi máy chủ hoạt động; **giữ nguyên cửa sổ**.
- Mở Chrome/Edge trên **cùng máy** và gõ `http://127.0.0.1:8000` (đúng `http`, không phải `https`).
- Tài khoản `letan`, mật khẩu bạn nhập khi khởi động. Các tài khoản khác trong `README.md`.

## Bước 4. Thử chức năng
- Đăng nhập lễ tân → thêm bệnh nhân **giả lập** → tạo lượt khám và phân `bs_noi`.
- Đăng xuất → `bs_noi` → khám bệnh, tạo chỉ định, nhập đơn nháp, xuất phiếu khám/đơn nháp.
- Các PDF/Word có dấu thử nghiệm, không dùng kê đơn chính thức.

## Bước 5. Tắt và chạy lại
- Muốn tắt: chuyển về cửa sổ đen và nhấn `Ctrl+C` (chọn Y nếu được hỏi).
- Lần sau chỉ cần chạy `START_WINDOWS.bat`. Dữ liệu demo trong `data/minh_duc_demo.sqlite3` vẫn còn.

## Lỗi thường gặp

**Nhấp BAT không mở được hoặc cửa sổ đóng ngay:** mở thư mục phần mềm, gõ `cmd` vào thanh địa chỉ File Explorer và Enter; sau đó nhập `START_WINDOWS.bat`. Giữ cửa sổ để đọc lỗi.

**`py is not recognized` / `python was not found`:** cài Python 3.12; đóng mở lại CMD; chạy `py --version` hoặc `python --version`. Bộ khởi động mới nhận **cả `py` và `python`**.

**`No module named ...` / `pip install` lỗi:** bảo đảm Internet; mở CMD trong thư mục và nhập `.venv\Scripts\python.exe -m pip install -r requirements.txt`. Nếu mạng bị chặn bởi proxy, thử mạng khác.

**`Address already in use` / `WinError 10048`:** cổng 8000 đang có ứng dụng khác. Khi chạy uvicorn trực tiếp, cần đặt DEMO_PASSWORD trong môi trường trước. Đóng cửa sổ chạy cũ hoặc trong CMD chạy `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001`; sau đó vào `http://127.0.0.1:8001`.

**Trình duyệt báo không kết nối được:** kiểm tra cửa sổ đen vẫn đang mở, dòng `Uvicorn running ...`; mở đúng địa chỉ `http://127.0.0.1:8000` trên máy đang chạy. Trên điện thoại `127.0.0.1` là điện thoại, **không phải máy tính**.

**Không giải nén được ZIP:** xác minh tải đủ và dùng Extract All/7-Zip; giải nén vào đường dẫn ngắn như `C:\MinhDucDemo`. Không chạy từ thư mục ZIP hoặc OneDrive đồng bộ bị khóa quyền ghi.

**Sai mật khẩu / không đăng nhập được:** dùng đúng tài khoản `letan`, mật khẩu bạn nhập khi khởi động (phân biệt chữ hoa/thường); không dùng bệnh nhân thật.

## Cách khởi động thủ công (nếu BAT vẫn lỗi)
Mở CMD trong thư mục `MinhDuc_Clinic_v0.3`:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\run_demo.py
```

Nếu `python` không nhận nhưng `py` nhận, thay dòng đầu bằng `py -3.12 -m venv .venv` (hoặc đúng phiên bản đã cài).

## Ranh giới bảo mật
Phần mềm chỉ dùng cục bộ, dữ liệu giả lập. Không đổi `--host` sang `0.0.0.0`, không mở cổng ra mạng hay Internet và không nhập dữ liệu sức khỏe hoặc thông tin bệnh nhân thật. Để vận hành thật cần nghiệm thu nghiệp vụ y tế, an toàn thông tin, dữ liệu và pháp lý.
