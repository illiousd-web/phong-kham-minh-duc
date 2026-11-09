# Cài đặt và nâng cấp v0.4.x → v0.5.0

Máy đích giữ nguyên i3-10105, RAM 8 GB, SSD 256 GB, Windows 11 Pro. Không triển khai tự động lên máy phòng khám. Mọi diễn tập dưới đây dùng dữ liệu giả lập, người phụ trách thực hiện trong giờ bảo trì.

Cài mới: làm theo [hướng dẫn Windows ngắn](WINDOWS_8GB_QUICKSTART.md) hoặc [hướng dẫn Linux/Windows chi tiết](LAN_INSTALL.md). Máy trạm không cài Python/PostgreSQL: cài CA công khai, cấu hình tên máy nội bộ, mở URL HTTPS do người cài cung cấp và đăng nhập tài khoản riêng. Không bỏ qua cảnh báo chứng chỉ, không mở router hoặc public tunnel.

## Trước nâng cấp

1. Chạy `deploy\windows\Preflight.bat`, kiểm tra dung lượng trống, RAM, Firewall và trạng thái backup. Không hạ ngưỡng dung lượng để chạy tiếp. Giữ tối thiểu 10 GiB dự phòng trên volume dữ liệu, tính thêm chỗ cho backup, dump và một đích restore độc lập.
2. Dừng web bằng Task Scheduler/terminal hiện dùng; không dừng PostgreSQL khi đang dump. Giữ nguyên mã, requirements, cấu hình và khóa cũ trong nơi bảo vệ. Ghi lại commit nguồn, đường dẫn attachments và tên database. Không chạy hai phiên bản nhận ghi cùng lúc.
3. Dùng **mã v0.4.x đang chạy** để tạo backup mã hóa rồi verify. Chạy restore thử sang database/thư mục rỗng khác theo [vận hành](LAN_OPERATIONS.md). Chỉ có file backup chưa đủ chứng minh khôi phục được. Giữ khóa ở nơi tách biệt; không đưa URL/mật khẩu vào dòng lệnh hay Git.

## Nâng cấp trên bản sao thử trước

Giải nén/checkout v0.5.0 vào thư mục riêng; tạo venv Python 3.12 và cài `requirements.lock`. Cấu hình `owner.env` bảo vệ trỏ vào **database bản sao giả lập**; runtime `clinic.env` dùng tài khoản riêng không sở hữu bảng. Giữ nguyên các đường dẫn và tham số profile 8 GB.

Windows PowerShell, tại thư mục mã nguồn mới:

```powershell
.\.venv\Scripts\python.exe -m scripts.with_env C:\ProgramData\MinhDuc\owner.env scripts.manage migrate
```

Linux:

```sh
.venv/bin/python -m scripts.with_env /etc/minhduc/owner.env scripts.manage migrate
```

Migration chạy dưới owner trong một transaction có khóa ghi chung. Schema 1/2 nâng lên **3**; chạy lại an toàn. Thêm bảng/cột, mã dịch vụ/thuốc, snapshot hồ sơ cũ và các liên kết mới. Không xóa hàng cũ, không tự thu phí cho chỉ định cũ chưa có phí, không tự cấp đơn văn bản. Kiểm thử so sánh toàn bộ giá trị của các cột cũ; khi lỗi DDL thì toàn transaction rollback, không đánh dấu nâng cấp thành công.

Sau migration, người cài chạy `deploy/postgresql-roles.sql` bằng owner trong đúng database (mặc định `minhduc`; nếu đổi tên thì chỉnh dòng GRANT CONNECT tương ứng). Bắt buộc cấp lại quyền SELECT cho views và thu hồi quyền sửa/xóa các bảng chứng cứ mới. Runtime `clinic_app` không là owner/superuser/CREATEDB/CREATEROLE/BYPASSRLS.

Kiểm tra:

```sql
SELECT version FROM schema_migrations ORDER BY version;
SELECT count(*) FROM clinical_revisions;
SELECT count(*) FROM effective_charges;
```

Khởi động bằng `deploy\windows\Start-LAN.bat` hoặc `python -m scripts.with_env ... scripts.run_lan`. `/api/health` phải trả `0.5.0` và `mode=lan`. Web từ chối schema chưa có version 3; không tự chạy DDL bằng tài khoản web.

## Nghiệm thu bản sao

Đăng nhập ít nhất lễ tân, bác sĩ, thu ngân cùng lúc; thêm dược, kỹ thuật viên, điều dưỡng. Kiểm theo [hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md): chỉ định nháp/duyệt; thanh toán nhiều lần/ứng trước (bật tại Cài đặt)/hoàn; đơn cấu trúc/quy đổi/FEFO/thiếu tồn/trả cách ly; phân công/sinh hiệu/y lệnh; hoàn tất và phụ lục. Kiểm số dư, lô, audit và chín biểu mẫu PDF/Word. Sau nâng cấp, tạo backup mới và restore lại một đích rỗng để kiểm cả bảng mới. Cấu hình lịch backup, ngoài máy và khóa giữ nguyên; không coi backup chỉ trên SSD là đủ chống mất máy.

## Quay lui và xử lý lỗi

Không có down migration xóa dữ liệu. Nếu migration lỗi, giữ web dừng, xem lỗi đã được che dữ liệu nhạy cảm và sửa nguyên nhân; có thể chạy lại khi transaction đã rollback. Không sửa trực tiếp marker `schema_migrations`.

Nếu đã ghi dữ liệu bằng v0.5, không checkout mã v0.4 trên database mới rồi cho chạy. Dừng web, giữ một backup hiện trạng v0.5, restore **bản trước nâng cấp** vào database và thư mục rỗng riêng, cấp quyền, đối soát rồi chuyển cấu hình sang đích cũ cùng mã cũ. Những giao dịch phát sinh sau thời điểm backup phải đối soát có thẩm quyền; không nhập lại tự động, không xóa lịch sử. Restore thu hồi các phiên đăng nhập, nhân viên phải đăng nhập lại.

## Tài nguyên và bảo mật

Giữ 1 worker, pool tối đa 4, 8 luồng, 1 lượt xuất biểu mẫu; PostgreSQL `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=20`. Không thêm Redis/Celery/Docker lên máy Windows để chạy bản này. Bảng lịch sử tăng theo nghiệp vụ; không xóa audit/snapshot để giảm đĩa. Chạy Preflight và storage_status hàng ngày, theo dõi backup, thực hiện diễn tập restore định kỳ. Không tắt HTTPS, CSRF, khóa giao dịch, fsync, synchronous_commit, full_page_writes, Defender hoặc Firewall.

Giới hạn cần nghiệm thu thực tế: chưa đo Windows i3 của phòng khám; chưa chứng nhận y tế/dược, chữ ký số hoặc pháp lý. Tham khảo báo cáo kiểm thử v0.5, không suy từ số đo Linux thành năng lực thực tế Windows.
