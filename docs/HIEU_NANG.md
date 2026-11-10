# Hiệu năng C5 — dữ liệu hai năm

Chỉ dùng dữ liệu giả lập. Nhánh C5 không thêm chỉ mục, không đổi schema và
không đổi công thức tiền hoặc quyền truy cập.

## Dữ liệu và cách chạy an toàn

`scripts/tao_du_lieu_gia.py` tạo CSDL **mới** tên
`clinic_perf_test_<12 ký tự hex>`. Nguồn quản trị bắt buộc là PostgreSQL
`/postgres` ở loopback, không nhận URL CSDL phòng khám. Phải truyền xác nhận
`--xac-nhan TAO_DU_LIEU_GIA_C5`. CSDL hoặc thư mục đã có đều bị từ chối,
kể cả khi đúng tên và mã xác nhận. Script không có TRUNCATE hoặc đường ghi đè.

```bash
# Đặt CLINIC_PERF_SOURCE_DATABASE_URL bằng cơ chế môi trường riêng,
# trỏ tới /postgres; không ghi mật khẩu vào lệnh hoặc Git.
python -m scripts.tao_du_lieu_gia \
  --ten-csdl clinic_perf_test_123456789abc \
  --thu-muc test_evidence/clinic_perf_test_123456789abc \
  --xac-nhan TAO_DU_LIEU_GIA_C5
```

Mặc định: 20.000 bệnh nhân, 22.000 lượt rải trong 731 ngày, 88.000 chỉ định,
22.000 đơn có dòng thuốc, hơn 132.000 khoản phí, hơn 20.000 phiếu thu,
hơn 546.000 dòng nhật ký, cùng nhập/cấp/tồn kho và chăm sóc điều dưỡng.
Có 30 lượt đang làm việc. Có nợ và khoản chưa có giá để hàng chờ thu ngân
không chỉ chứa lượt hôm nay. Có 2.000 PDF hợp lệ, mỗi tệp 64 KiB, tổng 125 MiB;
phần đệm ngẫu nhiên tránh đo sao lưu trên các tệp giống nhau nén gần về 0.
Tài khoản và mật khẩu giả lập riêng chỉ lưu trong thư mục kiểm thử, không đưa vào Git.

Chạy toàn bộ phép đo:

```powershell
python -m scripts.do_hieu_nang --pg-bin "C:\Program Files\PostgreSQL\17\bin" `
  --baseline-ref 76f5628 --output test_evidence/c5/windows.json
```

Trình đo tạo cụm PostgreSQL riêng có SCRAM, chỉ nghe loopback. CSDL khôi phục
cũng mới và riêng. Sau đo, xóa đúng các CSDL do lần đo tạo, không dùng CSDL
của dịch vụ đang vận hành. Bản sao lưu, khóa, tệp đính kèm và dữ liệu giả lập
ở thư mục tạm trên cùng máy; CI chỉ tải lên JSON số đo và bằng chứng kiểm thử.

## Phương pháp và ngưỡng

- Đo cùng máy, cùng bộ dữ liệu, trước C5 tại main `76f5628` và sau C5 tại mã PR.
  Không lấy số đo máy nhanh khác làm kết quả sau trên CI.
- Màn hình thực sự chạy qua Chromium/HTTPS: hàng chờ cả tám vai trò, tìm bệnh
  nhân, mở phiếu khám, tra cứu lượt khám trọn tháng và xuất PDF có mở/đọc lại.
  Theo xác nhận của chủ dự án trong C5, “báo cáo tháng” đo Quản lý → Lượt khám
  với ngày đầu/cuối tháng hiện có; không thêm báo cáo doanh thu tháng riêng.
- Mỗi thao tác làm nóng một lần, đo 20 lần. Trung vị ≤ 1,5 giây; P95 ≤ 3 giây.
  P95 dùng mẫu thứ 19 trong 20 mẫu đã sắp tăng dần; ghi cả mẫu chậm nhất.
  Timeout/lỗi hoặc thiếu mẫu là không đạt, không thay bằng số 0 hoặc bỏ qua.
- Sao lưu thật bằng pg_dump, mã hóa, giải mã và kiểm SHA-256 toàn bộ; tổng
  sao lưu + kiểm phải ≤ 900 giây. Khôi phục pg_restore thật, so số dòng mọi
  bảng, tổng tiền, từng lô và SHA-256 của toàn bộ 2.000 tệp. Hai khác biệt đúng
  thiết kế được kiểm rõ: phiên đăng nhập về 0 và nhật ký thêm đúng một
  `backup_restored`. Mọi dữ liệu nghiệp vụ khác phải giữ nguyên.
- Dừng app giả lập sau khi đo màn hình, đợi kết nối đóng rồi chụp trạng thái
  nguồn để đối chiếu backup/restore cùng thời điểm; không đo tải đồng thời
  trong lúc sao lưu. Không dừng hệ thống phòng khám thật.
- Lấy mẫu RAM 50 ms/lần. Trên Windows dùng thêm peak working set do hệ điều
  hành giữ. RAM dịch vụ gồm tiến trình app và con, phải ≤ 500.000.000 byte;
  trình duyệt, trình đo và pg_dump không nằm trong số này. PostgreSQL báo riêng
  tổng RSS các tiến trình, có thể đếm lặp vùng nhớ chia sẻ. Ghi cả MB và MiB.
- Job Windows đặt affinity hai CPU logic và giới hạn Windows Job Object
  8 GiB cho trình đo cùng các tiến trình con mới (app, trình duyệt, PostgreSQL).
  Cụm PostgreSQL kiểm thử dùng shared_buffers=256MB, work_mem=4MB, pool app=4,
  một worker. Không tắt fsync/synchronous_commit/full_page_writes.
  Đây là giới hạn nhóm tiến trình trên máy CI, không phải máy i3 vật lý hoặc
  giới hạn toàn bộ cache/RAM hệ điều hành. JSON ghi đúng OS/CPU/RAM/trình duyệt.

## Nguyên nhân chậm và thay đổi

Truy vấn Quản lý cũ lấy số tiền hiệu lực hai lần cho mỗi khoản: một lần cộng
tiền, một lần đếm khoản chưa có giá. EXPLAIN của 66.022 khoản cho thấy các
truy vấn con chạy 66.022 lần cho mỗi nhánh. Trang vượt cuối còn tính lại cả
tập lần nữa để lấy tổng. Vì vậy CPU hoặc cache chậm hơn làm số đo tăng rõ;
0,2 giây trên một máy không bảo đảm máy CI cũng đạt như vậy. Cụ thể, số
0,94 giây của C4 là ca **trang vượt cuối**, còn các ca một trang khác trên CI
khoảng 0,42–0,51 giây. Không có log máy báo 0,2 giây để khẳng định đó là cùng
ca hoặc cùng cấu hình. C5 đo đối chứng cùng máy để loại khác biệt này.

C5 giữ kết quả giá hiệu lực một lần bằng CTE MATERIALIZED. Kết quả lọc được
dùng chung cho đếm và lấy trang; LEFT JOIN giữ tổng kể cả trang trống.
Không sửa view, không sao chép hoặc đổi công thức tiền, không thêm chỉ mục.
Trả về cùng các dòng, cùng tổng và cùng quyền như trước.

Windows phát hiện lỗi có sẵn khi backup chứa tệp đính kèm: manifest ghi dấu
`/`, còn tập tệp kiểm lại dùng `\\`, nên báo `Backup manifest mismatch` và
không thể tới bước khôi phục. C5 dùng đường dẫn POSIX thống nhất ở cả hai
phía. Vẫn từ chối tệp thừa, sai SHA-256, archive không an toàn và CSDL đích
không rỗng. Không ghi đè bản sao hoặc dữ liệu đang dùng. Bản trước được ghi
đúng là kiểm thất bại, không chạy restore từ bản chưa kiểm đạt.

Đơn thuốc cũ tải toàn bộ lịch sử rồi đọc từng đơn riêng. C5 lấy dòng thuốc
theo lô truy vấn, bác sĩ tải đơn theo lượt đang mở, nhà thuốc phân trang 100
đơn chờ cấp. Có Trang trước/Trang sau, không bỏ các đơn ở trang sau. Bộ đếm
nhà thuốc COUNT trực tiếp trên toàn bộ đơn nháp. Đường API cũ vẫn trả đủ lịch
sử khi không truyền giới hạn. Công nợ dùng cùng giá hiệu lực, chỉ giữ kết quả
một lần trước cộng/đếm để tránh lặp tính toán.

## Kết quả đo

Kết quả Windows CI trên mã C5 đang được chạy; chưa coi đây là nghiệm thu cuối.
Số trước đã có từ CI C4: ca Quản lý chậm nhất có trung vị **0,935643 giây**,
mẫu chậm nhất **0,995045 giây** tại [run 49](https://github.com/illiousd-web/phong-kham-minh-duc/actions/runs/42734103351).

Đo cục bộ trước/sau cùng dữ liệu 22.000 lượt (không giả là kết quả Windows):
ca trang vượt cuối giảm trung vị từ khoảng **0,626 xuống 0,252 giây**.
Test C5 yêu cầu trung vị mọi truy vấn Quản lý trên CI ≤ **0,5 giây**,
giữ cách đo một lần làm nóng + năm mẫu; đồng thời đo lại mã trước C5 và
so toàn bộ kết quả trước/sau giống nhau. Log và JSON lưu đủ mẫu cùng EXPLAIN.

Đối chứng cùng máy Ubuntu CI, cùng dữ liệu tại
[run 52](https://github.com/illiousd-web/phong-kham-minh-duc/actions/runs/42752785299)
(mã tối ưu `3556508`, PostgreSQL 17):

| Truy vấn Quản lý | Trung vị trước | Trung vị sau | Chậm nhất trước / sau |
|---|---:|---:|---:|
| Một năm, đã đủ, trang vượt cuối | 0,859136 s | 0,336436 s | 0,899079 / 0,337997 s |
| Ca chậm nhất trong toàn bộ truy vấn sau C5 (trang cuối) | — | 0,344078 s | — / 0,390416 s |

Mọi ca sau C5 đạt trung vị ≤ 0,5 giây. Tên có dấu, không dấu, chữ hoa,
lọc tiền, trang cuối và trang trống đều kiểm đúng số dòng/kết quả.
Số này là truy vấn PostgreSQL; bảng Windows bên dưới đo cả thao tác trình duyệt.

| Hạng mục Windows | Trước C5 | Sau C5 | Ngưỡng |
|---|---:|---:|---|
| Hàng chờ từng vai trò | Chờ số đo CI | Chờ số đo CI | Trung vị 1,5 s; P95 3 s |
| Tìm bệnh nhân / phiếu khám / tra cứu tháng / PDF | Chờ số đo CI | Chờ số đo CI | Trung vị 1,5 s; P95 3 s |
| Sao lưu + kiểm SHA-256 | Chờ số đo CI | Chờ số đo CI | 900 s |
| Khôi phục và đối chiếu | Chờ số đo CI | Chờ số đo CI | Khớp dữ liệu và tệp |
| RAM tối đa dịch vụ / PostgreSQL | Chờ số đo CI | Chờ số đo CI | Dịch vụ ≤ 500 MB |

Các bài bảo vệ: `test_tu_choi_ten_csdl_khong_phai_dich_c5`,
`test_bat_buoc_xac_nhan_va_loopback_va_thu_muc_moi`,
`test_c5_du_lieu_lien_ket_va_khong_ghi_de_csdl_co_san`,
`test_rx_pages_are_complete_scoped_and_fetch_items_in_batches`,
`test_p95_nearest_rank_va_khong_dung_mau_tot_nhat`,
`test_lan_backup_nested_paths_are_portable_and_hashes_stay_required`,
`test_loi_manifest_duoc_ghi_la_khong_dat_khong_co_so_khoi_phuc`, cùng toàn bộ C4 và phân quyền.
