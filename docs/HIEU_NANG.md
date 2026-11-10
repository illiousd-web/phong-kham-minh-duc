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
  --baseline-ref 2fd1e9c9f811cd0d62f689ef7b18355c3f738113 --output test_evidence/c5/windows.json
```

Trình đo tạo cụm PostgreSQL riêng có SCRAM, chỉ nghe loopback. CSDL khôi phục
cũng mới và riêng. Sau đo, xóa đúng các CSDL do lần đo tạo, không dùng CSDL
của dịch vụ đang vận hành. Bản sao lưu, khóa, tệp đính kèm và dữ liệu giả lập
ở thư mục tạm trên cùng máy; CI chỉ tải lên JSON số đo và bằng chứng kiểm thử.

## Phương pháp và ngưỡng

- Hai phiên trước/sau dùng cùng máy và cùng bộ dữ liệu. Lần C5 ban đầu lấy
  main `76f5628`; lần sửa hàng chờ lấy `2fd1e9c` trước sửa làm mốc.
  Không lấy số đo máy nhanh khác làm kết quả sau trên CI.
- Màn hình thực sự chạy qua Chromium/HTTPS: hàng chờ cả tám vai trò, tìm bệnh
  nhân, mở phiếu khám, tra cứu lượt khám trọn tháng và xuất PDF có mở/đọc lại.
  Theo xác nhận của chủ dự án trong C5, “báo cáo tháng” đo Quản lý → Lượt khám
  với ngày đầu/cuối tháng hiện có; không thêm báo cáo doanh thu tháng riêng.
- Mỗi thao tác làm nóng một lần, đo 20 lần. Trung vị ≤ 1,5 giây; P95 ≤ 3 giây.
  P95 dùng mẫu thứ 19 trong 20 mẫu đã sắp tăng dần; ghi cả mẫu chậm nhất.
  Timeout/lỗi hoặc thiếu mẫu là không đạt, không thay bằng số 0 hoặc bỏ qua.
  Mở phiếu đo từ bấm một lượt đến khi phiếu sẵn sàng. In PDF đo từ bấm nút in
  đến khi tải và mở/đọc PDF xong. Việc vào màn hình trước đó làm ngoài mẫu;
  nếu chuẩn bị lỗi thì phép đo vẫn không đạt. Áp dụng giống nhau trước/sau.
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
`/`, còn tập tệp kiểm lại dùng `\`, nên báo `Backup manifest mismatch` và
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

Lượt đo Windows đầu ở run 55 còn không đạt: thu ngân trung vị 1,754 s,
phiếu khám 2,212 s, PDF 2,905 s. Thu ngân đang vẽ 2.523 nút lượt còn nợ cùng
lúc. C5 phân trang 100 dòng, giữ đủ mọi lượt qua Trang trước/Trang sau và
giữ nguyên dữ liệu API. Phiếu khám chỉ tải chỉ định của lượt đang mở,
dùng chỉ mục sẵn có và giữ nguyên điều kiện phân quyền.

Hai số phiếu/PDF của run 55 cộng cả việc mở lại màn hình trước đó, nên là
thời gian nhiều thao tác. Bộ đo đã tách chuẩn bị như phương pháp ở trên;
giữ nguyên ngưỡng, giữ log cũ và đo lại cả main/bản mới cùng cách. Bản sao
sau sửa đường dẫn ở run 55 kiểm/khôi phục khớp, RAM dịch vụ 112,001 MB,
backup + kiểm 10,733 s, restore 12,430 s; các thao tác chưa đạt vẫn phải đo lại.

Run 56 xác nhận phiếu/PDF đã đạt (0,239/0,196 s trung vị), nhưng kỹ thuật viên
1,992 s và thu ngân 2,561 s còn không đạt. Bộ đo bổ sung EXPLAIN và đối chứng
JIT bật/tắt trên chính máy Windows cho chỉ định, công nợ, phiếu thu; so kết quả
giống nhau và lưu đủ năm mẫu mỗi chế độ. Run 58 cho thấy JIT không được kích
hoạt: công nợ bật/tắt 1,124/1,140 s, chỉ định 0,979/0,973 s; không phải nguyên
nhân. Đã bỏ các lệnh tắt JIT thử nghiệm của ba API, giữ bằng chứng đối chứng.

Mỗi lần vẽ màn hình còn gọi lại cùng danh sách để đếm menu. Hai truy vấn
khoảng một giây tranh CPU, làm màn hình thành khoảng hai giây. C5 dùng số
đếm của danh sách vừa tải cho màn hình đang mở; chỉ hỏi máy chủ các số khác.
Lần hỏi định kỳ/quay lại tab vẫn lấy đầy đủ số mới, không gia hạn phiên.
Không lưu đệm công nợ hoặc bỏ các trang. Bộ định dạng tiền dùng lại một
Intl.NumberFormat thay vì tạo lại hàng nghìn lần; kiểm chữ hiển thị giống cũ
trên Chromium 109, gồm giá chưa biết, số 0, số lớn và số âm.

Run 59: kỹ thuật viên đạt 1,379 s; thu ngân vẫn chưa đạt, trung vị 1,889 s,
P95 3,507 s. EXPLAIN cục bộ cùng SQL chỉ ra bốn truy vấn con của view quét bảng điều
chỉnh rỗng 132.097 lần mỗi bảng. C5 gom ID có dấu vết đổi giá/giá tay/hoàn
thuốc/hủy phí một lần. Khoản không có bất kỳ dấu vết nào dùng snapshot ban
đầu (NULL vẫn là NULL); mọi khoản có dấu vết vẫn đọc nguyên view hiện có.
Không sao chép công thức hoặc thứ tự ưu tiên giá, không sửa view/DDL.
Chỉ định lọc đúng 100 dòng được phép trước khi tra khoản chưa có giá.

Kiểm 14 trạng thái riêng lẻ và chồng nhiều nguồn trên cả SQLite/PostgreSQL:
giá từng dòng, số khoản chưa giá và tính duy nhất đều khớp view cùng giá kỳ
vọng độc lập. Test còn ràng buộc mọi bảng đầu vào của view có mặt trong tập
ID thay đổi để cảnh báo khi view được mở rộng. EXPLAIN cục bộ sau thay đổi
cho thấy bốn truy vấn con không chạy khi tập thay đổi rỗng. Windows đã đạt
theo kết quả nghiệm thu bên dưới.

## Kết quả đo

Mã C5 `245930b`, [run 60](https://github.com/illiousd-web/phong-kham-minh-duc/actions/runs/42766828490):
**cả năm job xanh**, 261 tests, 112 LAN, job Chromium 109 có 32 bài.
Windows đạt **12/12 thao tác**, mỗi thao tác đủ 20 mẫu. Trung vị cao nhất
0,486 s, P95 cao nhất 0,522 s; các ngưỡng 1,5/3 s được giữ nguyên.

Máy đo: Windows Server 2025 (26100), hai CPU logic 0–1, RAM máy 8.187 MiB,
Job Object 8 GiB; Python 3.12.10, PostgreSQL 17.11, Chromium 156.0.8078.4.
Kiểm tương thích giao diện chạy riêng trên Chromium 109; chưa đo máy i3,
Windows 11 hoặc máy trạm Windows 7 vật lý.

Số trước/sau Windows dưới đây lấy **cùng một VM, cùng bộ dữ liệu**, mã trước
`76f5628` và mã sau `245930b`. JSON đủ từng mẫu, EXPLAIN và kiểm khôi phục tại
[artifact c5-windows-performance](https://github.com/illiousd-web/phong-kham-minh-duc/actions/runs/42766828490/artifacts/13740303777):
`windows.json`, `before.json`, `after.json`, `query-probes.json`.

| Thao tác Windows | Trước: trung vị / P95 (s) | Sau: trung vị / P95 (s) | Mẫu chậm nhất sau (s) |
|---|---:|---:|---:|
| Quản trị | 0,067 / 0,137 | 0,069 / 0,110 | 0,133 |
| Quản lý | 0,102 / 0,114 | 0,101 / 0,215 | 0,216 |
| Lễ tân | 0,111 / 0,126 | 0,112 / 0,122 | 0,128 |
| Bác sĩ | Timeout (0/20) | 0,217 / 0,241 | 0,249 |
| Kỹ thuật viên | 0,908 / 0,977 | 0,115 / 0,125 | 0,220 |
| Dược | Timeout (0/20) | 0,101 / 0,114 | 0,119 |
| Thu ngân | 2,183 / 2,574 | 0,288 / 0,320 | 0,332 |
| Điều dưỡng | 0,833 / 1,436 | 0,116 / 0,131 | 0,213 |
| Mở phiếu khám | 3,464 / 4,524 (17/20; lỗi) | 0,214 / 0,220 | 0,223 |
| Tìm bệnh nhân | 0,216 / 0,400 | 0,211 / 0,250 | 0,251 |
| Tra cứu trọn tháng | 0,645 / 0,725 | 0,486 / 0,522 | 0,553 |
| In PDF (tải và mở đọc) | 0,129 / 0,153 | 0,121 / 0,139 | 0,154 |

Bản trước: mở phiếu chỉ hoàn thành 17/20 mẫu rồi lỗi; trung vị/P95 của
17 mẫu được ghi lại nhưng **không đạt**. Timeout 0/20 không có số trung vị.
PDF đo riêng sau khi hồ sơ đã sẵn sàng, đúng phương pháp ở trên.
Số hiển thị làm tròn; điều kiện kiểm dùng số gốc.

| Sao lưu, khôi phục và RAM Windows | Trước C5 | Sau C5 | Ngưỡng/kết quả |
|---|---:|---:|---|
| Sao lưu + giải mã/kiểm SHA-256 | 7,627 s, lỗi manifest | 8,223 s, đạt | ≤ 900 s |
| Khôi phục | Bị chặn vì bản sao chưa kiểm đạt | 13,006 s | Khớp dữ liệu và 2.000 tệp |
| RAM dịch vụ tối đa | 265,949 MB | 118,706 MB | ≤ 500 MB |
| RAM PostgreSQL tối đa | 572,940 MB | 544,965 MB | Ghi riêng, tổng working set |

Bản trước dừng ở bước so tên tệp nên thời gian đó không phải một bản sao đã
kiểm đạt. Bản sau kiểm đủ 2.002 mục trong manifest (dump, cài đặt và 2.000
tệp). Khôi phục khớp số dòng mọi bảng, tổng tiền, từng lô và toàn bộ SHA-256;
phiên đăng nhập về 0 và thêm đúng một sự kiện `backup_restored`.

Truy vấn Quản lý đo một lần làm nóng + năm mẫu trên **cùng máy Ubuntu CI**,
cùng dữ liệu, trước/sau so kết quả giống nhau. Số C4 cũ là 0,935643 s
(trung vị), 0,995045 s (mẫu chậm nhất) tại
[run 49](https://github.com/illiousd-web/phong-kham-minh-duc/actions/runs/42734103351).

| Quản lý, run 60 | Trung vị trước | Trung vị sau | Chậm nhất trước / sau |
|---|---:|---:|---:|
| Một năm, đã đủ, trang vượt cuối | 0,859789 s | 0,177250 s | 0,893099 / 0,178309 s |
| Trung vị cao nhất mọi truy vấn sau (một năm, đã đủ) | — | 0,186076 s | — / 0,292322 s |

Mọi ca sau C5 đạt trung vị ≤ **0,5 s**, mẫu chậm nhất ≤ 2,5 s. Tên có dấu,
không dấu, chữ hoa, lọc tiền, trang cuối và trang trống đều đúng số lượt.
JSON `manager-timings.json` và `manager-explain.json` nằm trong artifact
`synthetic-clinic-test-evidence` của cùng run 60.

Các bài bảo vệ: `test_tu_choi_ten_csdl_khong_phai_dich_c5`,
`test_bat_buoc_xac_nhan_va_loopback_va_thu_muc_moi`,
`test_c5_du_lieu_lien_ket_va_khong_ghi_de_csdl_co_san`,
`test_rx_pages_are_complete_scoped_and_fetch_items_in_batches`,
`test_orders_visit_filter_keeps_doctor_scope_and_old_visit_results`,
`test_cashier_pages_keep_all_old_debts_selectable`,
`test_p95_nearest_rank_va_khong_dung_mau_tot_nhat`,
`test_chuan_bi_khong_cong_hai_thao_tac_va_loi_chuan_bi_van_khong_dat`,
`test_lan_backup_nested_paths_are_portable_and_hashes_stay_required`,
`test_loi_manifest_duoc_ghi_la_khong_dat_khong_co_so_khoi_phuc`,
`test_known_render_count_skips_only_duplicate_query_and_poll_remains_complete`
và `test_known_render_counts_do_not_extend_or_bypass_expired_session` là tên
hai bài ở lượt C5 ban đầu; ở lần sửa tiếp chúng được thay bằng các bài
COUNT SQL/hết hạn phiên ghi dưới đây.
`test_price_query_covers_every_input_of_effective_view`,
`test_price_query_matches_view_and_expected_amounts_sqlite`,
`test_price_query_matches_view_and_expected_amounts_postgresql`, cùng toàn bộ C4 và phân quyền.


## Sửa tiếp PR #14: không cắt mất việc đang chờ

Nguyên nhân: lấy 100 dòng mới nhất rồi JavaScript mới bỏ việc đã xong.
Vì vậy tốc độ đo cũ của kỹ thuật viên chỉ gồm 100/120 chỉ định còn chờ.
Không dùng số đo đó để kết luận hàng chờ đầy đủ.

Hàng chờ mới lọc trạng thái trong SQL, trả đủ việc còn chờ, không có LIMIT.
Giao diện không cần chuyển trang ở các hàng chờ này. COUNT(*) dùng cùng
phạm vi bác sĩ phụ trách/điều dưỡng đang được phân công và điều kiện trạng thái.
Giữ thứ tự ưu tiên vai trò hiện có của tài khoản kiêm nhiệm. Không đổi quyền,
không đổi schema, không thêm chỉ mục. Không đổi tính tiền hoặc trừ kho.

| Danh sách đã rà | Xử lý và lý do |
| --- | --- |
| `/api/orders`, kỹ thuật viên | SQL lấy đủ requested/ordered/pending_review; bảng chờ làm dùng ordered, mục đã gửi dùng pending_review. COUNT lab đếm ordered, không đếm danh sách đã cắt. Khi mở đúng lượt, đọc đủ chỉ định trong phạm vi quyền. Lịch sử tách bằng `history=true`, tối đa 100 việc đã kết thúc. |
| `/api/visits`, lễ tân/bác sĩ/điều dưỡng và các vai trò được phép đọc trước đây | SQL loại completed/cancelled trước khi trả danh sách. Bác sĩ vẫn chỉ lượt phụ trách, điều dưỡng vẫn chỉ phân công active. COUNT dùng chung `visit_predicate`. Lịch sử `history=true` chỉ completed/cancelled, giới hạn 100; bác sĩ có ô mở lịch sử riêng. |
| Điều chỉnh, hủy chỉ định, trả thuốc | Mặc định chỉ pending, không cắt; `history=true` chỉ việc đã xử lý, 100 dòng. Giữ phạm vi người đề nghị/bác sĩ như trước. COUNT manager trực tiếp trong SQL. |
| Phụ lục chờ duyệt | Đã lọc pending trong SQL nhưng còn cắt 100; bỏ giới hạn, COUNT cùng pending và các JOIN. |
| Phiếu nhập thuốc kiểm soát | Tách pending đầy đủ khỏi lịch sử 100, giữ các vai trò controlled_pharmacy/controlled_reviewer; manager chỉ cộng khi có controlled_reviewer và giao diện bật chức năng. |
| Đơn thuốc kiểm soát chờ bác sĩ thứ hai | Đã lọc SQL đúng nhưng cắt 100 việc thực sự còn chờ; bỏ giới hạn. Giữ cả hai quyền doctor + controlled_reviewer. |
| Sửa giá nhập tay | Giữ lọc trạng thái SQL và COUNT có cùng scope; sửa giao diện để tải đủ tất cả các trang 200 dòng theo tổng số. Thu ngân cũng xem đủ đề nghị pending của mình, lịch sử tách riêng. |
| Nhà thuốc — đơn draft | Giữ lọc SQL trước LIMIT, COUNT draft trực tiếp; đủ Trang trước/Trang sau 100 dòng, tổng số trên menu. Không có mẫu cắt trước rồi lọc. |
| Thu ngân — công nợ | Giữ đầy đủ nợ/chưa có giá và phân trang giao diện có tổng số; đổi số menu sang COUNT trực tiếp trên cùng phép tính SQL. Phiếu thu chỉ là lịch sử 100 dòng. |
| Quản lý — tra cứu lượt khám, nhật ký | Giữ phân trang SQL có tổng số của tra cứu; nhật ký là lịch sử limit/offset, không phải việc chờ. |
| Cấp thuốc, sổ thuốc kiểm soát | Giữ lịch sử 100/200; không được dùng làm hàng chờ duyệt hoặc cấp thuốc. |
| Bệnh nhân, lịch hẹn, danh mục | Giữ tìm kiếm/danh sách gần nhất 100 của bệnh nhân/lịch hẹn; giao diện không lọc các dòng này thành hàng chờ trạng thái. Danh mục đang hoạt động không bị cắt. |
| In phiếu, migration, truy vấn một bản ghi | Giữ giới hạn phục vụ in/đọc lô/một kết quả; không dùng để xây hàng chờ hoặc badge. |

Kiểm thử mới dùng cùng dữ liệu trên SQLite và PostgreSQL: 120 ordered xen kẽ
việc đã duyệt rồi thêm 150 việc đã duyệt mới hơn; một lượt chờ trước 150 lượt
completed, đều phân công cùng bác sĩ/điều dưỡng; mỗi loại trong bốn loại duyệt
có một pending trước 150 approved. Đối chiếu cả ID, không trùng, COUNT, lịch sử
và các phản hồi 401/403/phạm vi bác sĩ khác. Sau đó đổi cả 151 yêu cầu mỗi loại
thành pending để chứng minh chính hàng chờ duyệt cũng không còn trần 100.
Chromium 109/390px mở đủ năm màn hình, chọn được chỉ định cũ và mở riêng
lượt đã kết thúc ở chế độ chỉ đọc. Lượt kiểm đầy đủ phát hiện tham số lịch sử
bác sĩ gửi sai tên sau khi tách danh sách; đã sửa về `history=true`. Bài UI
hoàn tất → lập phụ lục vẫn giữ nguyên kiểm tra, mở ô lịch sử trước khi chọn.
Ca C4 thủ thuật đọc chỉ định đã duyệt theo `visit_id`, không đọc hàng chờ;
giữ nguyên mọi khẳng định phí/phiếu thu/tình trạng đã thu đủ.

Tên kiểm thử: `test_pending_queues_sqlite_keep_old_work_counts_and_permissions`,
`test_pending_queues_postgresql_keep_old_work_counts_and_permissions`,
`test_pending_queues_chromium109_show_all_old_work`;
`test_queue_counts_always_count_sql_and_ignore_legacy_known_hint`
kiểm mọi lần đều COUNT SQL, kể cả client cũ gửi known; không gọi API danh sách
để đếm. Giao diện bỏ số đếm suy từ mảng và chờ COUNT xong mới kết thúc tải
màn hình. Bộ đo C5 vì vậy tính cả thời gian số menu sẵn sàng.

Đo lại Windows dùng baseline trước sửa `2fd1e9c` và mã sửa trên cùng VM,
1 lần làm nóng + 20 mẫu, giữ nguyên ngưỡng trung vị/P95. Trình đo đối chiếu
thêm đủ 120 chỉ định và 30 lượt cho lễ tân/bác sĩ/điều dưỡng, badge bằng tổng
số kỳ vọng, không trùng;
thiếu việc thì bản sau không đạt dù nhanh. Kết quả lần đo sửa tiếp sẽ ghi
ở đây sau khi job Windows hoàn tất; số ở bảng run 60 phía trên là lịch sử C5.

## Hoãn

- Ô chọn thu ngân tìm phía máy chủ.
- Bỏ quét tên khi từ khóa là mã hoặc số điện thoại.

Hai việc này chưa thực hiện trong lần sửa hàng chờ, không dùng để giải thích
hoặc thay thế kết quả đo lại.
