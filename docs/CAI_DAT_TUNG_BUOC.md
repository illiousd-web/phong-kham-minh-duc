# Cài đặt phần mềm Phòng khám Minh Đức — từng bước

Tài liệu cho người cài đặt **không cần biết lập trình**. Chỉ cần biết tải tệp, giải nén, bấm đúp và đọc thông báo.

> Phần mềm đang ở giai đoạn thử nghiệm. **Chỉ nhập dữ liệu giả lập** cho tới khi phòng khám nghiệm thu bảo mật và nghiệp vụ.

Máy chủ của phòng khám dùng Windows **giao diện tiếng Anh**. Vì vậy tài liệu ghi tên nút, tên menu đúng như chữ trên màn hình (ví dụ "Yes", "Properties"), kèm giải thích tiếng Việt.

---

## 1. Chuẩn bị

| Cần có | Ghi chú |
|---|---|
| Máy chủ Windows 10/11 64-bit, RAM từ 8 GB, ổ C còn từ 20 GB | Máy hiện tại (i3-10105, 8 GB) đạt. |
| Tài khoản Windows có quyền quản trị | Khi Windows hỏi, phải chọn được "Yes". |
| Internet trong lúc cài | Cài xong thì phần mềm chạy trong mạng nội bộ, không cần Internet. |
| Google Chrome trên máy chủ và máy trạm | Chưa có thì cài trước. |
| **Một USB riêng để cất khóa sao lưu** | Bắt buộc. Không dùng chung với ổ sao lưu. |
| Một USB hoặc ổ cứng gắn ngoài để chép bản sao lưu | Nên có. Cắm sẵn khi cài. |
| Giấy bút | Ghi lại địa chỉ phần mềm và 8 ký tự "vân tay". |

**Trước khi cài**, đặt giữ IP cho máy chủ trên modem (mục *DHCP Reservation*, *Address Reservation* hoặc *Static Lease*, tùy loại modem). Nếu không vào được modem, xem mục 8, lỗi "IP động".

---

## 2. Tải và giải nén

1. Tải tệp cài đặt `.zip` do người hỗ trợ gửi (hoặc từ GitHub: nút **Code** → **Download ZIP**).
2. **Bỏ chặn tệp tải về** (bắt buộc, nếu không Windows sẽ chặn bộ cài):
   - Bấm chuột phải vào tệp `.zip` → **Properties**.
   - Ở cuối thẻ **General**, đánh dấu ô **Unblock** → bấm **OK**.
   - Nếu không thấy ô **Unblock** thì bỏ qua bước này.
3. Bấm chuột phải vào tệp `.zip` → **Extract All...** → **Extract**.
4. Mở thư mục vừa giải nén, đi vào `deploy` → `windows`.

---

## 3. Cài máy chủ

1. Bấm đúp **`CAI_DAT.bat`**.
2. Windows hỏi *"Do you want to allow this app to make changes to your device?"* → bấm **Yes**.
   - Nếu hiện khung xanh *"Windows protected your PC"*: bấm **More info** → **Run anyway**. Nếu không có nút **Run anyway**, quay lại bước 2 mục 2 (Bỏ chặn).
3. Một cửa sổ chữ hiện ra. **Không tắt cửa sổ này** cho tới khi thấy dòng **HOÀN TẤT** hoặc **DỪNG LẠI**. Toàn bộ mất khoảng **15–30 phút**.

Bộ cài làm 13 bước, mỗi bước in **[ĐẠT]**, **[LƯU Ý]** hoặc **[KHÔNG ĐẠT]**:

| Bước | Màn hình sẽ thấy | Bạn cần làm |
|---|---|---|
| 1. Kiểm tra máy | Danh sách Windows, RAM, ổ C, Internet, IP, tệp hoán đổi, App Control | Trả lời câu hỏi nếu có (xem dưới) |
| 2. Cài Python 3.12 | "Đang tải…", "Đã tải và kiểm SHA256" | Chờ |
| 3. Cài PostgreSQL 17 | "Đang cài PostgreSQL… 3–10 phút" | Chờ, không bấm gì |
| 4. Chép mã, cài thư viện | "Đã cài thư viện (đúng mã băm)" | Chờ |
| 5. Tạo cơ sở dữ liệu | "Đã tạo clinic.env với mật khẩu ngẫu nhiên mạnh" | Chờ |
| 6. Cấu hình PostgreSQL | "PostgreSQL chỉ nghe 127.0.0.1" | Chờ |
| 7. Cập nhật cấu trúc dữ liệu | "Cấu trúc dữ liệu đã cập nhật" | Chờ |
| 8. Chứng chỉ HTTPS | **"Vân tay chứng chỉ (8 ký tự đầu…): XXXXXXXX"** | **Ghi 8 ký tự này ra giấy** |
| 9. Dịch vụ Windows | "Dịch vụ "MinhDuc" đang chạy tại https://…:8443" | **Ghi địa chỉ này ra giấy** |
| 10. Tường lửa | Có thể hỏi chuyển mạng sang "Riêng tư" | Gõ **C** |
| 11. Lịch sao lưu | Hỏi có ổ USB/ổ ngoài không; "Sao lưu thử… ĐẠT" | Xem dưới |
| 12. Tài khoản quản trị | Hỏi tên đăng nhập, họ tên, mật khẩu | Xem dưới |
| 13. Kiểm tra sức khỏe | Bảng **ĐẠT / KHÔNG ĐẠT** từng mục | Đọc kết quả |

**Các câu hỏi có thể gặp** (gõ chữ rồi bấm **Enter**):

- *"Bạn ĐÃ đặt giữ IP cho máy này trên modem chưa?"* — Gõ **C** nếu đã làm ở mục 1. Gõ **K** thì bộ cài dừng và chỉ cách đặt IP.
- *"Chuyển tệp hoán đổi sang Windows tự quản lý?"* — Gõ **C** (khuyên dùng). Sau khi cài xong phải **khởi động lại máy**.
- *"Có ổ USB hoặc ổ cứng gắn ngoài… không?"* — Cắm ổ, gõ **C**, rồi gõ chữ cái của ổ (ví dụ **E**). Không có thì gõ **K**.
- *Tài khoản quản trị:* tên đăng nhập viết thường, không dấu, ví dụ `quantri.tuan`. Mật khẩu **từ 12 ký tự**, gõ sẽ **không hiện chữ** — đó là bình thường. Gõ lại lần hai cho khớp.

**Khi thấy HOÀN TẤT**, làm ngay 3 việc:

1. Mở thư mục `C:\ProgramData\MinhDuc\quantri` (dán đường dẫn này vào thanh địa chỉ của File Explorer), chép tệp **`backup.key`** sang **USB riêng**, cất nơi an toàn. **Mất tệp này thì không mở được bản sao lưu.** Không để USB này cắm cùng ổ sao lưu.
2. Nếu bộ cài báo cần khởi động lại: **Start → Power → Restart**.
3. Bấm đúp biểu tượng **"Phòng khám Minh Đức"** trên Desktop, đăng nhập bằng tài khoản quản trị vừa tạo.

Chạy lại `CAI_DAT.bat` lần nữa là **an toàn**: không xóa dữ liệu, không đổi mật khẩu, không tạo lại khóa sao lưu hay chứng chỉ đang dùng.

---

## 4. Cài máy trạm (mỗi máy làm một lần)

1. Trên máy chủ, chép **cả thư mục** `C:\MinhDuc-ChiaSe` sang USB.
   (Nếu mạng phòng khám đã bật chia sẻ tệp, có thể mở `\\TÊN-MÁY-CHỦ\MinhDuc` từ máy trạm; Windows có thể hỏi tên và mật khẩu tài khoản Windows của máy chủ.)
2. Trên máy trạm, mở thư mục đó, bấm đúp **`CAI_MAY_TRAM.bat`** → **Yes**.
3. Màn hình hiện **"Vân tay chứng chỉ: XXXXXXXX"**. So với 8 ký tự đã ghi ở bước 8. Giống thì gõ **C**. Khác thì gõ **K** và báo người hỗ trợ.
4. Thấy **HOÀN TẤT** là xong. Trên Desktop có biểu tượng **"Phòng khám Minh Đức"**.

Không bao giờ bấm *"Advanced → Proceed"* để bỏ qua cảnh báo chứng chỉ trên Chrome.

---

## 5. Việc hằng ngày, hằng tuần

- **Hằng ngày:** để máy chủ bật qua **20:00** để sao lưu tự chạy. Nếu máy tắt lúc 20:00, lần bật sau máy tự sao lưu bù.
- **Nếu trên Desktop máy chủ có tệp "CANH BAO SAO LUU…"**: mở đọc, làm theo, rồi bấm `KIEM_TRA.bat` (mục 7).
- **Hằng tuần:** cắm ổ sao lưu ngoài ít nhất một lần. Ổ vắng mặt **quá 3 ngày** thì máy sẽ cảnh báo.
- Không tắt **Microsoft Defender** hay **Windows Firewall**.

---

## 6. Cập nhật phần mềm

1. Tải tệp cập nhật `.zip` vào thư mục **Downloads** của máy chủ. Bỏ chặn tệp như mục 2.
2. Chọn lúc vắng bệnh nhân (máy trạm sẽ không vào được khoảng 5–10 phút).
3. Mở `C:\MinhDuc\deploy\windows`, bấm đúp **`CAP_NHAT.bat`** → **Yes**.
4. Bộ cập nhật hỏi dùng tệp `.zip` mới nhất trong Downloads → gõ **C**.
5. Máy tự làm: sao lưu → kiểm bản sao lưu → dừng dịch vụ → thay mã → cài thư viện → cập nhật cấu trúc dữ liệu → bật dịch vụ → kiểm tra.
   - Thấy **CẬP NHẬT THÀNH CÔNG** là xong.
   - Thấy **ĐÃ QUAY VỀ BẢN CŨ**: phần mềm vẫn chạy bản trước, dữ liệu được khôi phục về lúc trước cập nhật. Gửi thư mục `C:\ProgramData\MinhDuc\nhatky` cho người hỗ trợ.

---

## 7. Kiểm tra và gửi báo cáo

Bấm đúp **`C:\MinhDuc\deploy\windows\KIEM_TRA.bat`** → **Yes**. Sau khoảng 30 giây, trên Desktop có tệp **`MinhDuc-KiemTra-ngày-giờ.txt`**. Gửi tệp này cho người hỗ trợ (Zalo, email). Tệp **không chứa mật khẩu và không chứa dữ liệu bệnh nhân**; có địa chỉ IP nội bộ của máy chủ, không đăng công khai.

Báo cáo gồm: dịch vụ web và PostgreSQL, kết nối cơ sở dữ liệu, trang đăng nhập HTTPS, hạn chứng chỉ, tường lửa, lịch sao lưu, tuổi bản sao lưu gần nhất, ổ sao lưu ngoài, dung lượng trống, RAM, tệp hoán đổi, quyền tệp cấu hình.

---

## 8. Gặp lỗi

Khi bộ cài dừng, dòng **DỪNG LẠI** màu đỏ cho biết lý do; các dòng gạch đầu dòng màu vàng là cách xử lý. **Chưa có dữ liệu nào bị xóa**; sửa xong thì bấm đúp lại `CAI_DAT.bat`.

| Thông báo | Cách xử lý |
|---|---|
| Không có cửa sổ nào hiện ra, hoặc *"Windows protected your PC"* không có nút chạy | Làm lại mục 2, bước **Unblock**, rồi giải nén lại. |
| *"Windows đang chặn script cài đặt (App Control / Smart App Control)"* hoặc *"Smart App Control đang BẬT"* | Mở **Windows Security → App & browser control → Smart App Control settings → Off**. Chỉ tắt riêng mục này, **giữ** Defender và Firewall. Hỏi người phụ trách trước: trên một số bản Windows, muốn bật lại Smart App Control phải cài lại Windows. Nếu máy do bộ phận CNTT quản lý, nhờ họ cho phép thư mục `C:\MinhDuc`. |
| *"running scripts is disabled on this system"* (chữ đỏ tiếng Anh) | Máy có chính sách nhóm chặn script. Nhờ người quản trị CNTT; không tự tắt bảo vệ. |
| *"IP … đang do modem tự cấp (IP động)"* | Cách 1: vào trang quản trị modem (thường in ở mặt dưới modem), đặt giữ IP cho máy chủ. Cách 2: **Settings → Network & internet → Ethernet → IP assignment → Edit → Manual**, bật **IPv4**, nhập đúng các số bộ cài in ra. Xong chạy lại, gõ **C** khi được hỏi. |
| *"IP máy đã đổi từ … sang …"* | Đặt lại IP cũ cho máy chủ (hoặc giữ IP trên modem) rồi chạy lại. Không tự đổi sang IP mới vì máy trạm và chứng chỉ đang dùng IP cũ. |
| *"Ổ C chỉ còn … GB trống"* | **Settings → System → Storage → Temporary files** để dọn tệp tạm, dọn Thùng rác. Không xóa tệp sao lưu. |
| *"Máy chưa vào được Internet"* | Kiểm tra dây mạng/modem, mở thử một trang web, chạy lại. |
| *"có mã kiểm tra SHA256 không khớp"* | Tệp tải về bị lỗi hoặc bị thay đổi; bộ cài đã xóa và **không chạy**. Chạy lại sau ít phút. Lặp lại nhiều lần: báo người hỗ trợ. |
| *"Cài PostgreSQL thất bại"* hoặc *"Cài Python thất bại"* | Khởi động lại máy, chạy lại `CAI_DAT.bat`. |
| *"Đã có PostgreSQL nhưng không phải bản 17"* | Máy đang có PostgreSQL khác. **Không gỡ** khi chưa hỏi người hỗ trợ (có thể có dữ liệu). |
| *"Cổng 5432/8443 đang bị phần mềm khác dùng"* | Báo người hỗ trợ, gửi kèm báo cáo `KIEM_TRA`. |
| *"Dịch vụ web chưa trả lời sau 2 phút"* | Khởi động lại máy, chạy `KIEM_TRA.bat`, gửi tệp báo cáo. |
| Máy trạm: *"Chưa kết nối được"* | Máy trạm và máy chủ phải cùng mạng phòng khám (không dùng Wi-Fi khách). Máy chủ phải đang bật. Chạy `KIEM_TRA.bat` trên máy chủ. |
| Có tệp *"CANH BAO SAO LUU"* trên Desktop máy chủ | Đọc tệp. Nếu là ổ ngoài vắng mặt: cắm ổ lại, tối nay máy tự chép. Nếu sao lưu thất bại: chạy `KIEM_TRA.bat`, gửi báo cáo. |

Mã kết quả cuối cửa sổ (`Ma ket qua`) giúp người hỗ trợ biết dừng ở bước nào; gửi kèm khi báo lỗi.

---

## 9. Danh sách nghiệm thu sau cài

In trang này, đánh dấu từng ô. Chỉ dùng dữ liệu giả lập khi thử.

- [ ] Bộ cài báo **HOÀN TẤT: tất cả mục ĐẠT** (hoặc đã xử lý xong các mục KHÔNG ĐẠT).
- [ ] Đã chép `backup.key` sang USB riêng; USB này cất tách khỏi máy chủ và ổ sao lưu.
- [ ] Đã ghi địa chỉ phần mềm (`https://IP:8443`) và 8 ký tự vân tay chứng chỉ.
- [ ] Khởi động lại máy chủ; **không đăng nhập Windows**, từ máy trạm vẫn mở được phần mềm (dịch vụ tự chạy).
- [ ] Biểu tượng "Phòng khám Minh Đức" trên máy chủ mở Chrome, **không có cảnh báo chứng chỉ**.
- [ ] Đăng nhập được bằng tài khoản quản trị; tạo được từng tài khoản nhân viên tại trang **Tài khoản**.
- [ ] Ít nhất 3 máy trạm đã chạy `CAI_MAY_TRAM.bat`, vân tay khớp, mở được phần mềm không cảnh báo.
- [ ] Một máy **ngoài mạng phòng khám** (ví dụ điện thoại dùng 4G) **không** mở được địa chỉ phần mềm.
- [ ] Sáng hôm sau: `KIEM_TRA.bat` báo bản sao lưu mới hơn 36 giờ, lịch sao lưu ĐẠT.
- [ ] Ổ sao lưu ngoài có thư mục `MinhDuc-SaoLuu` chứa tệp `.mdbackup` mới; **không có** tệp `backup.key` trên ổ đó.
- [ ] Rút ổ ngoài 4 ngày (thử nghiệm): Desktop máy chủ xuất hiện tệp cảnh báo; cắm lại thì cảnh báo tự hết sau lần sao lưu kế tiếp.
- [ ] Người hỗ trợ đã diễn tập khôi phục một bản sao lưu sang cơ sở dữ liệu riêng và đối chiếu số liệu giả lập.
- [ ] Chạy lại `CAI_DAT.bat` một lần: vẫn đăng nhập bằng mật khẩu cũ, dữ liệu giả lập còn nguyên.
- [ ] Tệp `MinhDuc-KiemTra-….txt` đã gửi người hỗ trợ và được xác nhận.
- [ ] Đã ghi lại cấu hình máy, ngày cài, người cài, kết quả các ô trên vào sổ bàn giao.

---

## Phụ lục: bộ cài làm gì (cho người hỗ trợ)

- Phiên bản ghim, kiểm SHA256 trước khi chạy: Python 3.12.10 x64 (bản 3.12 cuối có bộ cài Windows), PostgreSQL 17.11-1 (EnterpriseDB), WinSW 2.12.0. Có thể đặt sẵn các tệp này trong `deploy\windows\taive\` cho máy không có Internet.
- Thư viện Python: `pip install --require-hashes --only-binary=:all: -r requirements.lock`.
- Thư mục: mã ở `C:\MinhDuc` (chỉ quản trị sửa được); dữ liệu, cấu hình, chứng chỉ, sao lưu ở `C:\ProgramData\MinhDuc`; tệp bí mật (`owner.env`, `postgres.env`, `backup.key`, `ca.key`) ở thư mục con `quantri` chỉ Administrators/SYSTEM đọc được; `clinic.env` thêm quyền đọc cho tài khoản dịch vụ `NT SERVICE\MinhDuc`.
- Dịch vụ `MinhDuc` (WinSW) chạy `python -m scripts.with_env clinic.env scripts.run_lan`, khởi động trễ tự động, phụ thuộc `postgresql-x64-17`, tự chạy lại sau 10/30/60 giây; nhật ký xoay vòng 5 tệp × 5 MB trong `logs\service`, nhật ký ứng dụng như cũ.
- PostgreSQL: thêm `include_if_exists = 'minhduc-8gb.conf'` cuối `postgresql.conf` (bản cũ lưu `postgresql.conf.truoc-minhduc-…`), `pg_hba.conf` chỉ còn 127.0.0.1/::1 SCRAM (bản cũ được lưu). Cơ sở dữ liệu tạo với bảng mã UTF8.
- Tường lửa: nhóm quy tắc `MinhDuc`: cho phép TCP 8443 tới IP máy chủ, chỉ từ dải LAN hiện tại, hồ sơ Private/Domain; chặn 5432 từ mạng.
- Sao lưu: tác vụ `MinhDuc - Sao luu 20h` chạy dưới SYSTEM, `scripts.backup_job`: sao lưu mã hóa → giải mã thử và kiểm SHA-256 từng tệp → chép ra ổ ngoài (nhận ra bằng tệp đánh dấu, không theo chữ cái ổ) → giữ 30 bản mỗi nơi → trạng thái `backup-status.json`, cảnh báo trên Desktop chung và nhật ký sự kiện Windows.
- Cập nhật lỗi sau khi đã đổi cấu trúc dữ liệu: cơ sở dữ liệu lỗi được **đổi tên** thành `minhduc_loi_<thời điểm>` (không xóa), tệp đính kèm lỗi đổi tên `attachments.loi-<thời điểm>`; khôi phục từ bản sao lưu vừa kiểm tra.
