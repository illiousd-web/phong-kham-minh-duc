> **Bộ cài tự động:** thay cho các bước cài tay bên dưới, dùng `deploy\windows\CAI_DAT.bat` theo [hướng dẫn từng bước](CAI_DAT_TUNG_BUOC.md). Phần dưới giữ lại để tham khảo kỹ thuật.

> **v0.5.0:** xem [nâng cấp từ v0.4.x](V050_UPGRADE.md) và [hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md). Migration hiện tại là schema 3; chạy bằng owner rồi cấp lại quyền runtime.

# Minh Đức LAN trên máy i3 / RAM 8 GB — hướng dẫn ngắn

Dành cho máy đã xác nhận: **Intel Core i3-10105, RAM 8 GB, SSD 256 GB, Windows 11 Pro 64-bit**. Dùng nguyên máy hiện có. Không cần đổi RAM, SSD hoặc mua máy chủ để chạy thử. Chưa được nhập bệnh nhân thật.

## 1. Kiểm tra máy trước khi cài

Mở thư mục `C:\MinhDuc\deploy\windows`, bấm hai lần **Preflight.bat**. Công cụ chỉ đọc thông tin máy; không cài gói, đổi dịch vụ, đọc mật khẩu, ghi serial/số định danh, hoặc tắt Firewall/Defender.

- **OK:** kiểm tra đó đạt tại thời điểm chạy.
- **WARN:** có việc cần kiểm tra, chưa phải kết luận máy đủ tài nguyên.
- **STOP:** chưa tiếp tục cài/nhập dữ liệu; gửi kết quả cho người phụ trách cài đặt.

Mục tiêu C: còn **ít nhất 40 GiB** trước cài, có **ít nhất 2 GiB RAM trống** khi bắt đầu. C: còn 20–40 GiB: phải tính lại dung lượng backup/khôi phục. Dưới 20 GiB: dừng chuẩn bị nhập dữ liệu. SSD “Healthy” chỉ là trạng thái Windows báo; nếu không đọc được SMART thì kết quả phải là **chưa biết**, không suy ra ổ tốt.

Khi cần lưu báo cáo để gửi riêng cho người cài, mở PowerShell và chạy:

```powershell
cd C:\MinhDuc
.\deploy\windows\Preflight.ps1 -OutputPath "$env:USERPROFILE\Desktop\MinhDuc-Preflight.json"
```

Tên file phải chưa tồn tại. Báo cáo có IP nội bộ nên không đăng công khai. Nếu Windows chặn chạy script, nhờ người cài kiểm tra chữ ký/chính sách; không dùng hướng dẫn tắt bảo vệ hoặc bypass toàn hệ thống.

## 2. Cài lần đầu — người phụ trách cài đặt làm một lần

Bàn giao cho người cài danh sách ngắn này; các lệnh chi tiết ở [hướng dẫn cài LAN](LAN_INSTALL.md):

1. Cài Python **3.12 x64**, PostgreSQL **17**, mã nguồn tại `C:\MinhDuc`; tạo venv và cài `requirements.lock`.
2. Tạo database và tài khoản runtime riêng, mật khẩu riêng; chạy migration bằng owner rồi cấp quyền như v0.4. Không dùng tài khoản demo hoặc tài khoản PostgreSQL superuser cho web.
3. Sao chép `deploy\windows\clinic-8gb.env.example` thành `C:\ProgramData\MinhDuc\clinic.env`; điền mật khẩu, IP cố định và CIDR thực tế. File config và khóa chỉ Administrators/SYSTEM/tài khoản dịch vụ được đọc. Không gửi file này lên GitHub.
4. Dừng PostgreSQL trong giờ bảo trì, sao lưu cấu hình cũ. Đặt `minhduc-8gb.conf` trong thư mục data PostgreSQL; thêm `include_if_exists = 'minhduc-8gb.conf'` ở **cuối** `postgresql.conf`. Dùng file trong `deploy\postgresql\`, không tự sửa fsync/commit/WAL. Khởi động lại PostgreSQL và kiểm chứng các thông số trong [tài liệu kỹ thuật](RESOURCE_LIGHT.md). Không áp file vào database cần giữ mà chưa có backup đã xác minh.
5. Tạo chứng thư HTTPS nội bộ, cài **chỉ CA công khai** vào máy trạm; áp firewall riêng subnet, PostgreSQL chỉ nghe `127.0.0.1`. Tạo tài khoản quản trị rồi từng nhân viên. Giữ BitLocker/ACL, Defender và Firewall; để Windows tự quản lý pagefile.
6. Tạo lịch khởi động và lịch backup 20:00 bằng Task Scheduler theo hướng dẫn LAN. Chạy backup/verify/restore giả lập một lần trước khi bật lịch. Kiểm tra máy tự hoạt động lại sau reboot.

Cấu hình tiết kiệm đã đặt sẵn: **1 worker, pool tối đa 4 kết nối, 8 luồng xử lý, 1 lượt xuất biểu mẫu mỗi lúc**. Không tự tăng các con số để chữa lỗi. Nếu thấy “Đang xuất biểu mẫu khác”, chờ vài giây rồi tải lại. Mọi quyền, HTTPS, kiểm phiên, nhật ký và giao dịch an toàn vẫn hoạt động.

## 3. Mở phần mềm

Nếu đã có lịch chạy máy chủ thì không mở thêm bản thứ hai. Khi cần chạy thử trực tiếp, bấm **Start-LAN.bat**. Giữ cửa sổ chạy trong lúc thử. Máy trạm mở địa chỉ do người cài ghi lại, ví dụ `https://minhduc.internal:8443`, rồi đăng nhập tài khoản riêng.

Trên máy chủ, chỉ mở ứng dụng thực sự cần thiết; đóng tab Chrome/Edge, ứng dụng đồng bộ hoặc tác vụ nặng không dùng. Không tắt Defender, Firewall, backup hoặc kiểm quyền để giảm RAM. Không đưa máy lên Internet, mở port router hoặc dùng public tunnel.

## 4. Giữ SSD không đầy

| Nội dung | Mức mặc định / việc cần làm |
|---|---|
| Tệp kết quả | Tối đa 5 MiB/tệp; kho attachments tối đa 2 GiB. Không dùng kho này để lưu DICOM, ảnh X-quang gốc hoặc phim lớn. |
| PDF/Word | Tạo trong RAM, không giữ cache bản xuất trên server; tối đa 10 MiB/bản xuất, không cắt nội dung âm thầm. Quản lý cả thư mục Downloads nếu tải ngay trên máy chủ. |
| Log ứng dụng | Tối đa khoảng 40 MiB (file 5 MiB + 7 file quay vòng), cho 1 worker mặc định. Không xóa audit trong database. |
| Backup trên SSD | Giữ 7 bản hoàn tất gần nhất, ngân sách 20 GiB; luôn cần thêm chỗ tạo bản mới trước khi bỏ bản cũ. Giới hạn có thể làm lệnh backup dừng và báo lỗi; không được coi là đã backup thành công. |
| PostgreSQL/WAL | Cấu hình và giới hạn mục tiêu ở tài liệu kỹ thuật. Không xóa `pg_wal`, file database hoặc chạy VACUUM FULL để tự giải phóng chỗ. |
| Dung lượng dự phòng | Khi còn dưới 10 GiB trên volume dữ liệu, ứng dụng từ chối giao dịch ghi mới (507), gồm đăng nhập cập nhật phiên. Dùng Preflight để kiểm tra, báo quản trị; không tiếp tục nhập bằng cách hạ ngưỡng. |

Kiểm tra mỗi sáng: C: còn bao nhiêu, Task Scheduler backup có thành công tối qua không, bản ngoài máy có mới không. Khi cần báo cáo dung lượng kho (không có tên bệnh nhân/tên tệp):

```powershell
cd C:\MinhDuc
.\.venv\Scripts\python.exe -m scripts.with_env C:\ProgramData\MinhDuc\clinic.env scripts.storage_status
```

Người quản trị có thể dọn Windows Temporary Files/Recycle Bin sau khi xác minh không chứa hồ sơ cần giữ, đóng app thừa và chuyển tài liệu không thuộc hệ thống sang nơi lưu trữ được phép. Công cụ không tự xóa hồ sơ, audit, attachments đang dùng hay WAL.

## 5. Backup và nghiệm thu

Dùng thiết bị USB/NAS/thư mục mạng **đã có và nằm ngoài máy chủ**, chỉ chứa backup mã hóa. Người cài đặt `CLINIC_BACKUP_OFFSITE_DIR` trỏ đúng thư mục đã mount, đặt `CLINIC_REQUIRE_OFFSITE=1` trước khi cân nhắc dữ liệu thật. Không để khóa giải mã cùng chỗ backup. Cần kiểm tra thực tế đó là nơi ngoài máy, không chỉ một thư mục khác trên cùng SSD.

Nếu nơi ngoài máy mất kết nối, backup báo thất bại; bản mới trên SSD và các bản tốt cũ vẫn được giữ. Sau khi sửa kết nối, chạy lại và diễn tập restore sang đích rỗng. Không coi riêng việc “có file” là bản backup tốt.

Chưa có nơi lưu ngoài máy hoặc chưa nghiệm thu restore/bảo mật/nghiệp vụ: **tiếp tục chỉ dùng dữ liệu giả lập**. Không cần thay phần cứng đã chốt để thực hiện các bước kiểm tra này.

Đợt phát triển đo trên Linux giới hạn tài nguyên và kiểm tra PowerShell qua test; đó không phải số đo Windows 11 trên máy i3 của phòng khám. Người cài phải ghi lại kết quả Preflight, ba máy trạm đồng thời, RAM/CPU và thời gian đáp ứng thực tế trước khi kết luận phù hợp.
