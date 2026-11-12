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
| Google Chrome trên máy chủ và máy trạm | Chưa có thì cài trước. Máy trạm Windows 7: xem mục 4a. |
| **Một USB riêng để cất khóa sao lưu** | Bắt buộc. Cất nơi an toàn, không cắm thường trực vào máy chủ. |
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
| 11. Lịch sao lưu | "Chỉ sao lưu trên máy chủ (giữ 14 bản)…"; "Sao lưu thử… ĐẠT" | Chờ |
| 12. Tài khoản quản trị | Hỏi tên đăng nhập, họ tên, mật khẩu | Xem dưới |
| 13. Kiểm tra sức khỏe | Bảng **ĐẠT / KHÔNG ĐẠT** từng mục | Đọc kết quả. **Máy mới cài**: mục *Sao lưu* báo KHÔNG ĐẠT vì mới có 1 bản đã kiểm (cần 3) — tự đạt sau 2 đêm sao lưu 20:00 nếu máy bật; các mục khác phải ĐẠT |

**Các câu hỏi có thể gặp** (gõ chữ rồi bấm **Enter**):

- *"Bạn ĐÃ đặt giữ IP cho máy này trên modem chưa?"* — Gõ **C** nếu đã làm ở mục 1. Gõ **K** thì bộ cài dừng và chỉ cách đặt IP.
- *"Chuyển tệp hoán đổi sang Windows tự quản lý?"* — Gõ **C** (khuyên dùng). Sau khi cài xong phải **khởi động lại máy**.
- *Tài khoản quản trị:* tên đăng nhập viết thường, không dấu, ví dụ `quantri.tuan`. Mật khẩu **từ 12 ký tự**, gõ sẽ **không hiện chữ** — đó là bình thường. Gõ lại lần hai cho khớp.

**Khi thấy HOÀN TẤT**, làm ngay 3 việc:

1. Mở thư mục `C:\ProgramData\MinhDuc\quantri` (dán đường dẫn này vào thanh địa chỉ của File Explorer), chép tệp **`backup.key`** sang **USB riêng**, cất nơi an toàn. **Mất tệp này thì không mở được bản sao lưu.**
2. Nếu bộ cài báo cần khởi động lại: **Start → Power → Restart**.
3. Bấm đúp biểu tượng **"Phòng khám Minh Đức"** trên Desktop, đăng nhập bằng tài khoản quản trị vừa tạo.

Chạy lại `CAI_DAT.bat` lần nữa là **an toàn**: không xóa dữ liệu, không đổi mật khẩu, không tạo lại khóa sao lưu hay chứng chỉ đang dùng.

---

## 4. Cài máy trạm (mỗi máy làm một lần)

Bộ cài máy trạm chạy được trên **Windows 7 SP1, 10 và 11**. Nó chỉ dùng công cụ có sẵn của Windows (`certutil`, `cscript`), không cần PowerShell. Màn hình chữ không dấu là bình thường.

1. Trên máy chủ, chép **cả thư mục** `C:\MinhDuc-ChiaSe` sang USB **dành riêng cho việc này** (không dùng USB lạ).
   (Nếu mạng phòng khám đã bật chia sẻ tệp, có thể mở `\\TÊN-MÁY-CHỦ\MinhDuc` từ máy trạm; Windows có thể hỏi tên và mật khẩu tài khoản Windows của máy chủ.)
2. Trên máy trạm, mở thư mục đó, bấm đúp **`CAI_MAY_TRAM.bat`** → **Yes** (Windows 7: **Yes** trong khung *User Account Control*).
3. Màn hình hiện **"Van tay chung chi: XXXXXXXX"**. So với 8 ký tự đã ghi ở bước 8. Giống thì gõ **C**. Khác thì gõ **K** và báo người hỗ trợ.
4. Thấy **HOAN TAT** là xong. Trên Desktop có biểu tượng **"Phòng khám Minh Đức"** mở Chrome (không có Chrome thì Edge).
   - Windows 10/11: bộ cài tự thử kết nối và báo **[DAT] Ket noi duoc may chu**.
   - Windows 7 không có `curl.exe` nên bộ cài **không** báo [DAT] cho bước kết nối mà in **[CAN KIEM TAY]** và dòng *"DA CAI XONG. CON MOT VIEC…"*. Bấm đúp biểu tượng: **thấy trang đăng nhập PHÒNG KHÁM và KHÔNG có cảnh báo chứng chỉ** (không có trang đỏ *"Kết nối của bạn không phải là kết nối riêng tư"*) mới là đạt. Có cảnh báo: dừng, gọi người hỗ trợ.
   - Bộ cài coi **mọi mã lỗi** của `certutil`/`cscript` là lỗi và kiểm tệp biểu tượng `.lnk` thật sự có trên Desktop; báo *DUNG LAI* hoặc *[KHONG DAT]* thì chụp màn hình gửi người hỗ trợ.

Không bao giờ bấm *"Advanced → Proceed"* để bỏ qua cảnh báo chứng chỉ trên Chrome.

## 4a. Máy trạm Windows 7 SP1

Windows 7 đã hết hỗ trợ từ 01/2020; bản Chrome cuối cho Windows 7 là **Chrome 109** (109.0.5414.x, không còn cập nhật bảo mật từ 2023 [CẦN ĐỐI CHIẾU số bản vá cuối]). Máy trạm Windows 7 **chỉ được dùng cho phần mềm phòng khám** và phải tuân thủ quy định an toàn dưới đây.

**Chuẩn bị Chrome 109 bản cài offline**
- Trang tải Chrome hiện tại của Google chỉ phát bản mới (không chạy trên Windows 7); tài liệu này **chưa xác minh** được đường dẫn chính thức cho bản 109 [CẦN ĐỐI CHIẾU nguồn tải]. Vì vậy **chỉ dùng bộ cài do người hỗ trợ cung cấp** (bản offline/standalone hoặc gói doanh nghiệp `.msi`), chép bằng USB dành riêng. Không tải Chrome từ trang web lạ.
- Trước khi cài: bấm chuột phải tệp cài → **Properties → Digital Signatures**, tên ký phải là **Google LLC** và báo *"This digital signature is OK"*. Sai hoặc không có chữ ký: **không cài**, báo người hỗ trợ.
- Cài xong, **không** cài thêm tiện ích (extension) nào. Không dùng Internet Explorer cho phần mềm này (IE trên Windows 7 không đáp ứng HTTPS của máy chủ).

**Cài chứng chỉ phòng khám** — làm đúng mục 4 (`CAI_MAY_TRAM.bat`). Bộ cài dùng `certutil -addstore Root` để đưa `ca.crt` vào kho **Trusted Root Certification Authorities** của **máy** (dùng chung cho mọi tài khoản Windows trên máy đó). Chrome 109 trên Windows 7 đọc kho này nên không hiện cảnh báo.

**Quy định an toàn cho máy trạm Windows 7**
- **Chỉ** mở phần mềm phòng khám bằng biểu tượng "Phòng khám Minh Đức". **Không lướt web**, không mở trang khác, không đăng nhập mạng xã hội.
- **Không mở email**, không mở tệp đính kèm, không tải tệp trên máy này.
- **Không cắm USB lạ.** Chỉ dùng USB dành riêng do người hỗ trợ cấp để cài đặt.
- **Mỗi nhân viên một tài khoản** phần mềm riêng (và tài khoản Windows riêng nếu có thể); không dùng chung, không để trình duyệt nhớ mật khẩu, đăng xuất khi rời máy.
- Không tắt tường lửa Windows; không cài phần mềm khác. Khi có điều kiện, thay máy trạm Windows 7 bằng máy Windows 10/11.

---

## 5. Việc hằng ngày, hằng tuần

- **Hằng ngày:** để máy chủ bật qua **20:00** để sao lưu tự chạy (`--daily`), kể cả khi phòng khám còn làm đến 21:00. Nếu máy tắt lúc 20:00, lần bật sau tác vụ riêng tự xét sao lưu bù (`--catchup`, sau khởi động hai phút); trong giờ 07:00–17:30 thì hoãn tới lịch 20:00, trừ khi chưa có bản thành công hoặc đã quá 48 giờ. Xem [vận hành S1](S1_AN_TOAN_VAN_HANH.md).
- **Nếu trên Desktop máy chủ có tệp "CANH BAO SAO LUU…"**: mở đọc, làm theo, rồi bấm `KIEM_TRA.bat` (mục 7).
- **Số bản sao lưu:** máy chủ giữ **14 bản** gần nhất (khoảng 2 tuần), **không dùng ổ ngoài** theo quyết định của phòng khám. Mỗi bản mới được **giải mã thử và kiểm SHA-256 từng tệp trước** khi xóa bất kỳ bản cũ nào; bản mới lỗi thì bị xóa, bản cũ giữ nguyên và có cảnh báo.
  - *Bản đã kiểm* là bản có SHA-256 thực tế **trùng** SHA-256 ghi lúc kiểm (tệp `.verified`); mỗi lần sao lưu máy tính lại. Bản bị thay đổi nội dung (kể cả cùng dung lượng) là **bản HỎNG**: không tính là đã kiểm, luôn bị xóa trước mọi bản tốt, có cảnh báo trên Desktop và nhật ký sự kiện Windows.
  - Hết ngân sách dung lượng: chỉ xóa bản cũ nhất sau khi bản mới đã kiểm. Ổ gần đầy không đủ chỗ tạo bản mới: được xóa bản cũ nhất (bản hỏng trước) để lấy chỗ. Cả hai trường hợp **giữ tối thiểu 3 bản đã kiểm nếu đang có từ 3 bản trở lên; đang có ít hơn 3 thì giữ tất cả**. Xóa trong giới hạn đó vẫn không đủ chỗ thì **dừng, không xóa bản nào** và báo.
  - `KIEM_TRA` báo mục *Sao lưu* KHÔNG ĐẠT (kèm lý do và việc cần làm) khi vượt ngân sách, khi có dưới 3 bản đã kiểm, hoặc khi có bản hỏng.
  - Máy cài bằng bản cũ (giữ 30 bản) tự chuyển sang 14 khi chạy lại `CAI_DAT.bat` hoặc `CAP_NHAT.bat`, và chỉ xóa bớt sau lần sao lưu mới đầu tiên đã kiểm; mật khẩu không đổi.
- **Không có bản sao lưu ngoài máy chủ: nếu máy chủ hỏng hoặc bị mất thì mất toàn bộ dữ liệu.**
- **Chứng chỉ HTTPS** có hạn 1 năm. Khi còn **dưới 60 ngày**, hoặc khi chứng chỉ bị thiếu/hỏng, tệp cảnh báo trên Desktop và báo cáo `KIEM_TRA` sẽ nhắc. Làm theo mục 6a.
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

**Riêng nâng cấp lần đầu sang D0:** bản cũ chưa chép năm CSV công khai vào thư mục mã. Người hỗ trợ cần dùng script cập nhật từ bộ mới giải nén, chỉ rõ thư mục đã cài; xem [hướng dẫn D0](D0_DANH_MUC_CHUAN.md#cài-đặt-và-cập-nhật). Các lần sau dùng batch đã cài như các bước trên.

## 6a. Gia hạn hoặc phục hồi chứng chỉ HTTPS

Dùng khi tệp cảnh báo hoặc `KIEM_TRA` báo *"Chứng chỉ HTTPS còn … ngày"* hoặc *"Không đọc được chứng chỉ (thiếu hoặc hỏng)"*. **Máy trạm không phải cài lại** (CA giữ nguyên).

1. Chọn lúc vắng bệnh nhân (phần mềm ngắt khoảng 1 phút).
2. Mở `C:\MinhDuc\deploy\windows`, bấm đúp **`GIA_HAN_CHUNG_CHI.bat`** → **Yes**.
3. Máy tự làm: tạo chứng chỉ mới bằng chứng chỉ gốc (CA) đang dùng, đặt tên tạm cạnh tệp cũ → kiểm tài khoản dịch vụ đọc được → thay tệp (giữ bản cũ) → khởi động lại dịch vụ → kiểm trang web dùng đúng chứng chỉ mới.
   - Chứng chỉ hoặc khóa máy chủ **thiếu/hỏng**: bộ gia hạn tự nhận ra và chuyển sang **CHẾ ĐỘ PHỤC HỒI** — cấp chứng chỉ mới từ khóa CA (`ca.key`) hiện có, **không cần đọc chứng chỉ cũ**.
4. Đọc dòng cuối theo **mã kết quả**:
   - **Mã 0**: đạt (*GIA HẠN THÀNH CÔNG* / *PHỤC HỒI CHỨNG CHỈ THÀNH CÔNG*, HTTPS đã kiểm lại đạt).
   - **Mã 50**: gia hạn lỗi nhưng **đã trả chứng chỉ cũ và HTTPS đã kiểm lại đạt**. Chạy `KIEM_TRA.bat`, gửi báo cáo cho người hỗ trợ để gia hạn lại.
   - **Mã 51** (chữ đỏ): **không trả được chứng chỉ cũ / phục hồi không thành công. Phần mềm có thể không truy cập được — gọi người hỗ trợ ngay.** Không bấm bỏ qua cảnh báo chứng chỉ ở máy trạm.
   - **Mã khác**: lỗi, đọc dòng *DỪNG LẠI* và nhật ký `C:\ProgramData\MinhDuc\nhatky\ket-qua-gia-han.json`.
5. Nếu báo *"Không thấy khóa CA"*: chép tệp `ca.key` (đã cất trên USB, nếu có) vào `C:\ProgramData\MinhDuc\quantri\` rồi chạy lại. **Mất hẳn `ca.key` thì không phục hồi được bằng CA cũ: phải tạo CA mới và cài lại CA (`CAI_MAY_TRAM.bat`) cho MỌI máy trạm — gọi người hỗ trợ.**

---

## 7. Kiểm tra và gửi báo cáo

Bấm đúp **`C:\MinhDuc\deploy\windows\KIEM_TRA.bat`** → **Yes**. Sau khoảng 30 giây, trên Desktop có tệp **`MinhDuc-KiemTra-ngày-giờ.txt`**. Gửi tệp này cho người hỗ trợ (Zalo, email). Tệp **không chứa mật khẩu và không chứa dữ liệu bệnh nhân**; có địa chỉ IP nội bộ của máy chủ, không đăng công khai.

Báo cáo gồm: dịch vụ web và PostgreSQL, kết nối cơ sở dữ liệu, trang đăng nhập HTTPS, hạn chứng chỉ, tường lửa, lịch sao lưu, tuổi bản sao lưu gần nhất và số bản đã kiểm, dung lượng trống, RAM, tệp hoán đổi, quyền tệp cấu hình.

---

## 8. Gặp lỗi

Khi bộ cài dừng, dòng **DỪNG LẠI** màu đỏ cho biết lý do; các dòng gạch đầu dòng màu vàng là cách xử lý. **Chưa có dữ liệu nào bị xóa**; sửa xong thì bấm đúp lại `CAI_DAT.bat`.

| Thông báo | Cách xử lý |
|---|---|
| Không có cửa sổ nào hiện ra, hoặc *"Windows protected your PC"* không có nút chạy | Làm lại mục 2, bước **Unblock**, rồi giải nén lại. |
| *"Windows đang chặn script cài đặt (App Control / Smart App Control)"* hoặc *"Smart App Control đang BẬT"* | **Dừng lại, không tự tắt Smart App Control hay App Control**, không tắt Defender/Firewall. Chụp màn hình và **gọi người hỗ trợ**. |
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
| Có tệp *"CANH BAO SAO LUU"* trên Desktop máy chủ | Đọc tệp. Sao lưu thất bại, có bản **HỎNG**, ổ gần đầy hoặc vượt ngân sách dung lượng: chạy `KIEM_TRA.bat`, gửi báo cáo cho người hỗ trợ; không tự xóa thư mục `backups`. Chứng chỉ sắp hết hạn, thiếu hoặc không đọc được: làm mục 6a (`GIA_HAN_CHUNG_CHI.bat` tự phục hồi). |
| Máy trạm Windows 7: Chrome báo lỗi chứng chỉ | Chạy lại `CAI_MAY_TRAM.bat` bằng quyền Administrator; kiểm vân tay. Không bấm bỏ qua cảnh báo. |

Mã kết quả cuối cửa sổ (`Ma ket qua`) giúp người hỗ trợ biết dừng ở bước nào; gửi kèm khi báo lỗi.

---

## 9. Danh sách nghiệm thu sau cài

In trang này, đánh dấu từng ô. Chỉ dùng dữ liệu giả lập khi thử.

- [ ] Bộ cài báo **HOÀN TẤT**; mục KHÔNG ĐẠT duy nhất được chấp nhận ở máy mới cài là *Sao lưu* với lý do "mới có 1 bản đã kiểm, cần ít nhất 3" (sau 2 đêm phải ĐẠT).
- [ ] Khi cài, **gõ mật khẩu có dấu** (ví dụ mật khẩu `postgres` nếu máy đã có PostgreSQL): bộ cài đạt và đăng nhập lại được bằng đúng mật khẩu đó. Ghi rõ ô nào đã gõ có dấu.
- [ ] Đã chép `backup.key` sang USB riêng; USB này cất tách khỏi máy chủ.
- [ ] Đã ghi địa chỉ phần mềm (`https://IP:8443`) và 8 ký tự vân tay chứng chỉ.
- [ ] Khởi động lại máy chủ; **không đăng nhập Windows**, từ máy trạm vẫn mở được phần mềm (dịch vụ tự chạy).
- [ ] Biểu tượng "Phòng khám Minh Đức" trên máy chủ mở Chrome, **không có cảnh báo chứng chỉ**.
- [ ] Đăng nhập được bằng tài khoản quản trị; tạo được từng tài khoản nhân viên tại trang **Tài khoản**.
- [ ] Ít nhất 3 máy trạm đã chạy `CAI_MAY_TRAM.bat`, vân tay khớp, mở được phần mềm không cảnh báo.
- [ ] Một máy **ngoài mạng phòng khám** (ví dụ điện thoại dùng 4G) **không** mở được địa chỉ phần mềm.
- [ ] Sáng hôm sau: `KIEM_TRA.bat` báo bản sao lưu mới hơn 36 giờ, lịch sao lưu ĐẠT.
- [ ] Sau 3 đêm: thư mục `C:\ProgramData\MinhDuc\backups` có các tệp `.mdbackup` kèm tệp `.verified`; `KIEM_TRA.bat` hiện số bản đã kiểm. Chủ phòng khám đã được giải thích: không có bản ngoài máy chủ thì hỏng/mất máy là mất hết dữ liệu.
- [ ] Mỗi máy trạm Windows 7: Chrome 109 cài từ bộ cài có chữ ký Google LLC; nhân viên đã được phổ biến quy định an toàn ở mục 4a.
- [ ] **Windows 7 + Chrome 109**: bấm biểu tượng "Phòng khám Minh Đức" mở trang đăng nhập **không có cảnh báo chứng chỉ** (ổ khóa không gạch đỏ). Ghi tên máy, phiên bản Chrome (`chrome://version`).
- [ ] Trên máy chủ thật: **ghi thời gian một lần sao lưu** (bấm `KIEM_TRA.bat` trước và sau, hoặc xem giờ tạo tệp `.mdbackup` và `.verified`) và **độ trễ thao tác khám trong lúc sao lưu** (mở hồ sơ, lưu phiếu khám trên máy trạm khi sao lưu đang chạy, ghi số giây). Ghi kèm dung lượng CSDL.
- [ ] Chạy thử `GIA_HAN_CHUNG_CHI.bat` một lần: mã 0, báo GIA HẠN THÀNH CÔNG; máy trạm mở được phần mềm không cảnh báo, không phải cài lại.
- [ ] Người hỗ trợ đã diễn tập khôi phục một bản sao lưu sang cơ sở dữ liệu riêng và đối chiếu số liệu giả lập.
- [ ] Chạy lại `CAI_DAT.bat` một lần: vẫn đăng nhập bằng mật khẩu cũ, dữ liệu giả lập còn nguyên.
- [ ] Đã gửi tệp `MinhDuc-KiemTra-….txt` cho người hỗ trợ (được xác nhận) và ghi cấu hình máy, ngày cài, người cài, kết quả các ô trên vào sổ bàn giao.

---

## Phụ lục: bộ cài làm gì (cho người hỗ trợ)

- Phiên bản ghim, kiểm SHA256 trước khi chạy: Python 3.12.10 x64 (bản 3.12 cuối có bộ cài Windows), PostgreSQL 17.11-1 (EnterpriseDB), WinSW 2.12.0. Có thể đặt sẵn các tệp này trong `deploy\windows\taive\` cho máy không có Internet.
- Thư viện Python: `pip install --require-hashes --only-binary=:all: -r requirements.lock`.
- Thư mục: mã ở `C:\MinhDuc` (chỉ quản trị sửa được); dữ liệu, cấu hình, chứng chỉ, sao lưu ở `C:\ProgramData\MinhDuc`; tệp bí mật (`owner.env`, `postgres.env`, `backup.key`, `ca.key`) ở thư mục con `quantri` chỉ Administrators/SYSTEM đọc được; `clinic.env` thêm quyền đọc cho tài khoản dịch vụ `NT SERVICE\MinhDuc`.
- Dịch vụ `MinhDuc` (WinSW) chạy `python -m scripts.with_env clinic.env scripts.run_lan`, khởi động trễ tự động, phụ thuộc `postgresql-x64-17`, tự chạy lại sau 10/30/60 giây; nhật ký xoay vòng 5 tệp × 5 MB trong `logs\service`, nhật ký ứng dụng như cũ.
- PostgreSQL: thêm `include_if_exists = 'minhduc-8gb.conf'` cuối `postgresql.conf` (bản cũ lưu `postgresql.conf.truoc-minhduc-…`), `pg_hba.conf` chỉ còn 127.0.0.1/::1 SCRAM (bản cũ được lưu). Cơ sở dữ liệu tạo với bảng mã UTF8.
- Tường lửa: nhóm quy tắc `MinhDuc`: cho phép TCP 8443 tới IP máy chủ, chỉ từ dải LAN hiện tại, hồ sơ Private/Domain; chặn 5432 từ mạng.
- Sao lưu: tác vụ `MinhDuc - Sao luu 20h` chạy dưới SYSTEM, `scripts.backup_job`: sao lưu mã hóa → giải mã thử và kiểm SHA-256 từng tệp (bản lỗi bị xóa, không xóa bản cũ nào) → ghi tệp đánh dấu `.verified` → **chỉ sau đó** mới xóa theo số lượng (`CLINIC_BACKUP_KEEP=14`, do bộ cài quản lý, `CAI_DAT`/`CAP_NHAT` tự đặt lại) và theo ngân sách `CLINIC_BACKUP_TOTAL_MB`, luôn giữ tối thiểu 3 bản đã kiểm nếu đang có từ 3 bản (ít hơn thì giữ tất cả) → trạng thái `backup-status.json`, cảnh báo trên Desktop chung và nhật ký sự kiện Windows (sao lưu lỗi, bản hỏng, ổ gần đầy, vượt ngân sách, chứng chỉ HTTPS thiếu/hỏng/còn dưới 60 ngày). "Đã kiểm" = SHA-256 thực tế của tệp trùng SHA-256 ghi trong `.verified`. Trước khi tạo bản mới, nếu ổ không đủ chỗ thì chỉ xóa bản cũ (bản hỏng trước) khi việc đó đủ chỗ mà vẫn giữ mức tối thiểu trên; không thì dừng, không xóa. Ổ ngoài là tùy chọn ẩn, mặc định tắt: chỉ bật khi chạy `CAI_DAT` với biến môi trường `MINHDUC_SAO_LUU_NGOAI=1` (ghi `CLINIC_EXTERNAL_BACKUP=1` vào `clinic.env`).
- Gia hạn chứng chỉ: `GIA_HAN_CHUNG_CHI.bat` → `scripts.install_cert` theo giai đoạn `prepare` (ghi `server.*.moi-<thời điểm>` cạnh tệp cũ) → đặt ACL, kiểm `NT SERVICE\MinhDuc` đọc được → `verify` → `commit` (bản cũ thành `server.*.cu-<thời điểm>`) → khởi động lại, kiểm số sê-ri chứng chỉ dịch vụ đang dùng; lỗi ở bất kỳ giai đoạn nào thì `rollback`, chỉ báo "đã trả chứng chỉ cũ" khi HTTPS sau khôi phục đạt (mã 50), khôi phục lỗi thì mã 51. Khóa máy chủ mới, cùng tên/IP, CA giữ nguyên. Kết quả ghi `nhatky\ket-qua-gia-han.json`. `CAI_DAT` chạy lại khi chứng chỉ còn dưới 60 ngày (cùng IP) cũng gia hạn theo cách này.
- Cập nhật lỗi sau khi đã đổi cấu trúc dữ liệu: cơ sở dữ liệu lỗi được **đổi tên** thành `minhduc_loi_<thời điểm>` (không xóa), tệp đính kèm lỗi đổi tên `attachments.loi-<thời điểm>`; khôi phục từ bản sao lưu vừa kiểm tra.
