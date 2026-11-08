# Cài đặt LAN thử nghiệm Minh Đức v0.4

Chỉ dùng dữ liệu giả lập. Mã nguồn này chưa được nghiệm thu bảo mật hoặc nghiệp vụ y tế. Không nhập hồ sơ thật, không dùng đơn nháp để cấp thuốc hoặc phiếu thu thử làm chứng từ kế toán. Không mở port forwarding, DMZ, tunnel, public hosting hay UPnP trên router.

## Kiến trúc và giá trị phải thay tại phòng khám

Một máy chủ chạy Python 3.12, PostgreSQL 17 và ổ lưu dữ liệu được mã hóa. Các máy trạm dùng Edge/Chrome qua HTTPS. Ví dụ: IP máy chủ `192.168.10.10`, subnet `192.168.10.0/24`, DNS nội bộ `minhduc.internal`, cổng `8443`. Thay các giá trị ví dụ bằng mạng thực tế; giữ IP cố định/DHCP reservation. PostgreSQL chỉ nghe `127.0.0.1`, không cho máy trạm kết nối cổng 5432.

Ứng dụng có hai chế độ: demo SQLite vẫn chỉ nhận loopback; LAN bắt buộc PostgreSQL, HTTPS, Host đúng và CIDR riêng. `START_WINDOWS.bat`/`START_LINUX_MAC.sh` là launcher demo, không dùng để chạy máy chủ LAN. Máy chủ LAN không cần Internet khi vận hành sau khi cài đủ gói, font, chứng thư và trình duyệt.

Không cần reverse proxy. Launcher `scripts.run_lan` dùng TLS trực tiếp, 2 worker, không tin `X-Forwarded-*`, không bật access log URL chứa tham số tìm bệnh nhân. Chỉ bind một IP đã chọn, từ chối `0.0.0.0`/`::`. Khóa giao dịch PostgreSQL được dùng chung giữa các worker và công cụ backup.

## Linux (Ubuntu 24.04 hoặc bản tương đương)

1. Cài Python 3.12/venv, PostgreSQL 17 server/client, Git, DejaVu Sans, UFW từ kho chính thức. Ví dụ tên gói: `python3-venv postgresql-17 postgresql-client-17 fonts-dejavu-core ufw`. Kho PostgreSQL của hệ điều hành có thể cần cấu hình theo hướng dẫn chính thức của PostgreSQL. Không dùng lệnh tải script không rõ nguồn.
2. Tạo tài khoản dịch vụ riêng `minhduc` không đăng nhập tương tác. Đặt checkout nhánh đã duyệt tại `/opt/minhduc`, tạo venv và cài phiên bản đã kiểm thử:

   ```sh
   cd /opt/minhduc
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.lock
   ```

3. Tạo `/etc/minhduc` và `/var/lib/minhduc/{attachments,backups}`. Tài khoản dịch vụ chỉ đọc mã nguồn/config/chứng thư; chỉ ghi `/var/lib/minhduc`. Chủ sở hữu mã nguồn là tài khoản quản trị triển khai. Thư mục config cấp `0750 root:minhduc`, `clinic.env` cấp `0640`, dữ liệu `0700 minhduc:minhduc`. Dùng LUKS/full disk encryption cho volume chứa CSDL, attachments, backup và vùng tạm. Bảo vệ cả swap, tài khoản quản trị và khóa giải mã.
4. Trong PostgreSQL, tạo database `minhduc` do role riêng `clinic_owner` sở hữu. Tạo `clinic_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`; đặt mật khẩu riêng qua `psql \password clinic_app`. Chủ sở hữu dùng cho migration, không dùng cho web. Trong `postgresql.conf`: `listen_addresses='127.0.0.1'`, `password_encryption='scram-sha-256'`; `pg_hba.conf` chỉ cho host loopback dùng `scram-sha-256`. Kiểm tra các rule có sẵn, khởi động lại PostgreSQL và xác nhận không nghe IP LAN. Không dùng `trust` cho TCP.
5. Sao chép `deploy/clinic.env.example` sang `/etc/minhduc/clinic.env`; điền URL của `clinic_app`, IP, CIDR, origin và đường dẫn thực tế. Mật khẩu trong URL phải percent-encode các ký tự đặc biệt. File là `KEY=VALUE` dạng literal, không thêm dấu nháy hoặc lệnh shell. Không đưa file đã điền vào Git. Tạo file `/etc/minhduc/owner.env` tương tự nhưng URL là role owner, chỉ quản trị đọc được.
6. Chạy migration bằng role owner, sau đó trong `psql` ở database `minhduc` chạy `deploy/postgresql-roles.sql` để cấp quyền cho runtime. Ví dụ từ thư mục mã nguồn, dưới tài khoản được phép đọc `owner.env`:

   ```sh
   .venv/bin/python -m scripts.with_env /etc/minhduc/owner.env scripts.manage migrate
   ```

   Migration lặp lại an toàn ở version 1, không tự nạp tài khoản, bệnh nhân, danh mục hay kho demo. Áp dụng lại grant sau mỗi migration. Runtime được INSERT/SELECT nhật ký, không được UPDATE/DELETE/TRUNCATE; không sở hữu bảng. Không mở quyền superuser cho runtime để chữa lỗi cấp quyền.
7. Tạo chứng thư và CA riêng của phòng khám:

   ```sh
   .venv/bin/python -m scripts.create_lan_certificate --name minhduc.internal --ip 192.168.10.10 --output /etc/minhduc/tls
   ```

   Lệnh yêu cầu thư mục output chưa tồn tại. Cấp quyền đọc `server.crt`, `server.key` cho tài khoản dịch vụ, giữ khóa `0600`; chỉ phân phối `ca.crt`. Chuyển `ca.key` ra thiết bị offline mã hóa, không để cùng web server. Chứng thư máy chủ có hạn 365 ngày; theo dõi hạn, tạo lại và thay trước khi hết hạn. Không xóa CA cũ trước khi cập nhật trust của tất cả máy trạm. Công cụ hiện tạo CA mới mỗi lần; muốn gia hạn giữ CA phải dùng công cụ PKI của quản trị hoặc phân phối CA mới có kiểm soát.
8. Tạo quản trị viên cá nhân qua nhập mật khẩu kín, từ tài khoản dịch vụ:

   ```sh
   .venv/bin/python -m scripts.with_env /etc/minhduc/clinic.env scripts.manage create-admin --username ten.quantri --name 'Quản trị viên giả lập'
   ```

   Mật khẩu tối thiểu 12 ký tự. CLI không nhận mật khẩu trên dòng lệnh. Tạo từng nhân viên tại trang **Tài khoản**; giao mật khẩu riêng ngoài hệ thống, nhân viên đổi tại **Đổi mật khẩu**. Không dùng chung tài khoản. Khóa tài khoản khi nghỉ việc; thay quyền/khóa/reset mật khẩu thu hồi các phiên cũ. Không có tài khoản demo trong database LAN mới.
9. Cài các unit trong `deploy/linux/` vào `/etc/systemd/system/`. Kiểm tra đường dẫn, quyền rồi `systemctl daemon-reload` và `systemctl enable --now minhduc.service`. Xem `systemctl status minhduc` và `journalctl -u minhduc`; log không được chuyển lên nơi công khai. Không cần chạy web bằng root vì dùng cổng 8443.
10. Kiểm tra và áp dụng firewall từ console máy chủ. `deploy/linux/firewall.sh` thêm rule cho IP/subnet/cổng đã chọn; script không tự reset hoặc enable UFW để tránh cắt kết nối quản trị. Giữ rule quản trị cần thiết, đặt mặc định inbound deny, xóa rule allow 8443/Python rộng nếu có rồi bật firewall. Cổng 8443 chỉ cho subnet phòng khám; 5432 bị chặn inbound. Firewall host và ACL router đều phải kiểm tra; `is_private` trong mã không thay thế kiểm tra cấu hình mạng.
11. Quản trị nhập danh mục dịch vụ/giá giả lập tại **Danh mục**, dược tạo mặt hàng và nhập lô tại **Kho thuốc**. Danh mục LAN khởi tạo rỗng có chủ ý. Không nhập tự động database SQLite cũ hoặc tài khoản/mật khẩu demo. Thử `curl --cacert /etc/minhduc/tls/ca.crt https://minhduc.internal:8443/api/health` từ máy trong CIDR.

## Windows 10/11 Pro hoặc Windows Server

Đường triển khai Windows dùng Python/PostgreSQL native; chưa chạy nghiệm thu trên Windows trong phiên phát triển này.

1. Cài Python 3.12 x64, PostgreSQL 17 và Git từ nguồn chính thức. Cài trên ổ NTFS có BitLocker; dùng tài khoản Windows dịch vụ riêng, không cho nhân viên đăng nhập vào máy chủ. Giữ Windows Update/antimalware, đồng bộ giờ và UPS hoạt động.
2. Checkout vào `C:\MinhDuc`. Trong PowerShell:

   ```powershell
   cd C:\MinhDuc
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.lock
   ```

3. Tạo `C:\ProgramData\MinhDuc\attachments`, `backups`, thư mục config. Dùng ACL NTFS: bỏ thừa kế rộng; chỉ Administrators, SYSTEM và tài khoản dịch vụ được đọc config/key; tài khoản dịch vụ được ghi data/backups. Thư mục mã nguồn chỉ cho dịch vụ Read & Execute. `chmod` Python không thay thế ACL Windows. Kiểm tra bằng `icacls`, không cấp Everyone/Users quyền đọc mật khẩu và khóa.
4. Cấu hình PostgreSQL loopback/SCRAM, database owner riêng và role runtime như Linux. Thay các đường dẫn trong `clinic.env` bằng `C:\ProgramData\MinhDuc\...`; `CLINIC_ORIGIN=https://minhduc.internal:8443`, bind IP cố định. Thêm `CLINIC_PG_DUMP=C:\Program Files\PostgreSQL\17\bin\pg_dump.exe` và `CLINIC_PG_RESTORE=...\pg_restore.exe` nếu không có PATH. Bộ nạp env giữ nguyên khoảng trắng trong đường dẫn, không dùng dấu nháy.
5. Tạo `owner.env`, migration, grant quyền trong pgAdmin/psql rồi tạo chứng thư và quản trị:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.with_env C:\ProgramData\MinhDuc\owner.env scripts.manage migrate
   .\.venv\Scripts\python.exe -m scripts.create_lan_certificate --name minhduc.internal --ip 192.168.10.10 --output C:\ProgramData\MinhDuc\tls
   .\.venv\Scripts\python.exe -m scripts.with_env C:\ProgramData\MinhDuc\clinic.env scripts.manage create-admin --username ten.quantri --name 'Quản trị viên giả lập'
   ```

6. Mạng phòng khám phải được đặt profile Private. Chạy `deploy\windows\Firewall.ps1` bằng Administrator với IP, CIDR và đường dẫn Python đúng. Giữ Windows Firewall bật, mặc định inbound Block. Xóa rule Python/8443 rộng do Windows tự hỏi lúc trước; chỉ cho allow 8443 từ CIDR phòng khám trên profile Private. Script chặn inbound PostgreSQL. Không mở cổng trên router.
7. Chạy thử foreground:

   ```powershell
   .\deploy\windows\Run-Clinic.ps1 -Root C:\MinhDuc -Config C:\ProgramData\MinhDuc\clinic.env
   ```

   Nếu chính sách PowerShell của tổ chức chặn script, ký script hoặc xin áp dụng chính sách phù hợp; không tắt bảo vệ toàn máy. Giữ cửa sổ chạy khi thử. Sau kiểm thử, tạo Task Scheduler task chạy lúc khởi động máy dưới tài khoản dịch vụ, **Run whether user is logged on or not**. Action: `powershell.exe -NoProfile -File C:\MinhDuc\deploy\windows\Run-Clinic.ps1 -Root C:\MinhDuc -Config C:\ProgramData\MinhDuc\clinic.env`. Đặt Start in `C:\MinhDuc`, restart on failure 1 phút tối đa 3 lần, không chạy instance trùng, bỏ giới hạn thời gian 3 ngày cho task máy chủ. Lưu credential trong Task Scheduler, không trong script. Kiểm tra Last Run Result và Event Viewer; đây là startup task, không phải Windows Service native.
8. Tạo task backup hằng ngày lúc 20:00 với cùng script và thêm `-Action backup`; không chạy instance trùng, bật chạy bù khi bỏ lỡ, ghi nhận Last Run Result, cảnh báo khi thất bại. Xác minh sau reboot máy chủ. Sao lưu xem tài liệu vận hành.

## Máy trạm

1. Kết nối LAN/VLAN phòng khám được phép; không dùng Wi-Fi khách. DNS nội bộ trỏ `minhduc.internal` về IP máy chủ. Nếu chưa có DNS, thêm hosts bằng quản trị trên từng máy. Có thể dùng URL IP nếu chứng thư SAN có IP đó và đặt `CLINIC_ORIGIN` đúng URL IP; chỉ chọn một origin thống nhất.
2. Quản trị đối chiếu fingerprint CA trực tiếp với máy chủ rồi import **chỉ `ca.crt`** vào Trusted Root Certification Authorities của các máy Windows được quản lý (GPO hoặc Certificate Manager). Linux cài CA vào trust store theo hệ điều hành. Không chép `ca.key`, `server.key`, URL database hoặc khóa backup sang máy trạm. Không bấm bỏ qua cảnh báo chứng thư.
3. Mở `https://minhduc.internal:8443`; trình duyệt phải xác minh chứng thư hợp lệ. Đăng nhập tài khoản cá nhân, đổi mật khẩu, thử đúng vai trò. Lễ tân không được xem nội dung bệnh án, bác sĩ chỉ xem ca được giao, thu ngân chỉ thu/đối soát, dược thao tác kho, kỹ thuật viên nhập kết quả chờ bác sĩ duyệt. Tài khoản nhiều vai trò có bộ chọn vai trò; quyền API luôn kiểm tra tại máy chủ.
4. Khóa màn hình khi rời máy và đăng xuất cuối ca. Phiên không hoạt động 20 phút hoặc quá 8 giờ phải đăng nhập lại. PDF/Word tải xuống chứa dữ liệu giả lập; khi có quyết định dùng dữ liệu thật về sau, cần chính sách bảo vệ/xóa bản tải và bản in. Chưa có tự động xóa file download trên máy trạm.

## Các bước nghiệm thu tại phòng khám còn bắt buộc

Kiểm tra từ ít nhất ba máy vật lý khác nhau; ngoài CIDR/Wi-Fi khách phải không kết nối được. Kiểm tra reboot server, firewall thật, chứng thư/trust, phiên hết hạn, mất mạng khi thu tiền, backup theo lịch, khôi phục trên máy dự phòng và thời gian phục hồi. Kiểm tra phân quyền theo nhân sự thực, chữ ký số/quy chuẩn y tế, quy trình kho/thuế và xử lý malware của tệp đính kèm. Chỉ dùng dữ liệu giả lập cho đến khi nghiệm thu bảo mật và nghiệp vụ y tế riêng được phê duyệt.
