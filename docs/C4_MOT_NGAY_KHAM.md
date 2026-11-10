# Nghiệm thu C4: một ngày khám giả lập

Chạy `lan_tests/test_mot_ngay_kham.py` trên PostgreSQL dùng một lần do
`lan_tests/conftest.py` tạo. Mọi thao tác nghiệp vụ dùng HTTPS thật với CA kiểm
tra được; ba lượt đầu đi qua giao diện, mỗi vai trò dùng phiên riêng. Không
thay đổi mã ứng dụng, phân quyền hoặc cấu trúc CSDL.

```bash
CLINIC_TEST_DATABASE_URL=postgresql://USER@127.0.0.1:5432/DB_NGUON \
CHROMIUM_PATH=/duong/dan/chromium109 \
MINHDUC_EXPECT_CHROMIUM_MAJOR=109 \
python -m pytest lan_tests/test_mot_ngay_kham.py -v
```

Tài khoản PostgreSQL kiểm thử cần quyền tạo/xóa CSDL. Dùng thư viện kiểm thử
trong `requirements-test.lock`. Job `test` tự chạy file trong toàn bộ `lan_tests`;
job `browser-chromium-109` chạy lại file với kiểm tra phiên bản 109 bắt buộc.

## Dữ liệu và cách đối chiếu

- Nhập Excel 30 dịch vụ, năm dịch vụ mỗi nhóm trong sáu nhóm, hai ô giá trống.
  Nhập năm thuốc, sáu lô. Thuốc đầu nhập lô xa hạn trước, lô gần hạn sau để
  phân biệt FEFO với FIFO; lượt thứ ba phải cấp qua hai lô, lần lượt 1 và 2 viên.
- Tổng cộng 30 lượt: ba lượt giao diện (thường, thu tạm rồi nhập giá/thu nốt,
  giảm phí), 27 lượt API. Mỗi lượt không hủy có sinh hiệu điều dưỡng, khám bác sĩ,
  bốn loại cận lâm sàng, kết quả kỹ thuật viên/bác sĩ duyệt, đơn, khóa và cấp thuốc.
- Có thu nhiều lần, để nợ, ứng trước, giảm phí được duyệt, hoàn tiền được duyệt,
  hai lượt hủy chưa nhận tiền (một lượt đã có chỉ định và được duyệt hủy chỉ định).
- Lượt được giảm phí sau khi đã thu đủ phải hiện ở bộ lọc **CẦN HOÀN**, cả API
  và giao diện; sau duyệt hoàn tiền phải biến khỏi bộ lọc. Hai lượt khác có
  chỉ định **Thủ thuật**, nhập/duyệt kết quả, ghi phí và thu đủ.
- Hai lượt cuối thuộc 23:50 hôm trước và 00:10 hôm nay theo UTC+7. Chỉ đổi
  `created_at` của lượt, khoản phí và phiếu thu thuộc hai lượt này trong CSDL
  kiểm thử; đây là cách dựng đồng hồ giả lập, không chờ qua nửa đêm. Vì vậy
  có 29 lượt hôm nay và một lượt hôm trước, tổng tra cứu hai ngày là 30.
  Riêng lượt 23:50 hôm trước được thu lúc 00:10 hôm nay: ngày tạo lượt và ngày
  doanh thu được đối chiếu độc lập, không gán doanh thu theo ngày tạo lượt.
- Sổ kỳ vọng tính bằng số nguyên từ giá Excel, số lượng thuốc, số tiền đã yêu cầu
  thu/giảm/hoàn; không gọi lại hàm tính tiền của ứng dụng. Đối chiếu từng lượt,
  tổng hệ thống theo chênh lệch đầu/cuối, tổng tra cứu từng ngày và tổng phiếu
  thu từng loại của báo cáo ngày. Tổng phiếu thu là tiền vào; trừ hoàn đã duyệt
  để đối chiếu số đã thu ròng. Khoản chưa nhập giá được ghi riêng, không coi
  phần giá đã biết là tổng cuối.
- Hàng chờ giao diện phải bằng đúng tập lượt còn nợ hoặc chưa có giá từ API;
  không nhầm danh sách chọn lượt khác (có cả lượt đã đủ) với hàng chờ. Quản lý
  tìm đủ 30 lượt và lọc đủ từng tập tình trạng tiền, cả qua API và giao diện.
- Đối chiếu tồn sáu lô với số nhập/cấp dự tính và sổ biến động; kiểm thứ tự lô
  của từng đơn. Ghi mốc ID nhật ký trước đăng nhập và phân trang tới hết để
  so **toàn bộ** sự kiện phát sinh trong kịch bản theo hai chiều, gồm đăng nhập,
  đọc hồ sơ, xuất phiếu, truy cập API và nghiệp vụ. Kỳ vọng khai báo từ kịch bản
  và hợp đồng HTTP cố định, không lấy từ nhật ký thực tế. Sự kiện thiếu, thừa,
  lạ hoặc sai người đều báo lỗi, in tên sự kiện. Có ca tự kiểm bộ đối chiếu
  phải bắt được sự kiện lạ chèn thêm vào danh sách bản sao trong bộ nhớ.
  Kiểm từ chối thu/cấp thuốc sai vai trò và chặn lễ tân đọc công nợ tại API.
- Tải, mở và trích chữ PDF cho cả ba đơn và mọi phiếu thu của ba lượt giao diện;
  kiểm tên bệnh nhân, đúng loại phiếu và in lại thu tạm sau nhập giá vẫn là thu tạm.

Tệp Excel, sổ đối chiếu JSON, ảnh tra cứu, PDF, phiên bản trình duyệt và JUnit
nằm trong `test_evidence/`, chỉ có dữ liệu giả lập và được CI lưu thành artifact.

## Quyết định nghiệm thu C4-01 đã chốt

Lượt còn khoản chưa có giá **vẫn được nhận tiền**, nhưng máy chủ bắt buộc trả
HTTP 201 với `kind=provisional`; PDF là **PHIẾU THU TẠM**. Lượt còn trong hàng
chờ thu ngân với `unpriced_count>0`, trạng thái `unpriced`, không được coi là
hết nợ; giao diện hiện nút **Thu tạm một phần**. Giữ nguyên API theo quy tắc C3.

Kỳ vọng HTTP 409 trước đây là **sai tiêu chí kiểm thử, không phải lỗi phần mềm**.
Bài `test_c4_01_thu_khi_chua_co_gia_bat_buoc_la_thu_tam` kiểm đầy đủ quyết định
trên. Ca từ chối thật là `test_tu_choi_thu_vuot_sau_khi_da_nhap_du_gia`: sau khi
đã nhập đủ giá, thu vượt số còn phải thu phải trả HTTP 409, không thêm phiếu
thu và không đổi số dư.

## Đo tra cứu ở quy mô lớn

`lan_tests/test_manager_visits_scale.py` giữ 22.000 lượt và 20.000 bệnh nhân.
Mỗi truy vấn có một lần làm nóng rồi năm lần đo; cả sáu kết quả phải giống
nhau. In trung vị, lần chậm nhất và năm mẫu ra log kể cả khi kiểm thử đạt.
Trung vị phải ≤ 1 giây, lần chậm nhất ≤ 2,5 giây. Nếu trung vị trên CI vẫn
vượt 1 giây, dừng và báo số đo; không tự nới ngưỡng hoặc sửa truy vấn/CSDL.
