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
- Hai lượt cuối thuộc 23:50 hôm trước và 00:10 hôm nay theo UTC+7. Chỉ đổi
  `created_at` của lượt, khoản phí và phiếu thu thuộc hai lượt này trong CSDL
  kiểm thử; đây là cách dựng đồng hồ giả lập, không chờ qua nửa đêm. Vì vậy
  có 29 lượt hôm nay và một lượt hôm trước, tổng tra cứu hai ngày là 30.
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
  của từng đơn. Phân trang nhật ký tới hết để kiểm từng thao tác và đúng người.
  Kiểm từ chối thu/cấp thuốc sai vai trò và chặn lễ tân đọc công nợ tại API.
- Tải, mở và trích chữ PDF cho cả ba đơn và mọi phiếu thu của ba lượt giao diện;
  kiểm tên bệnh nhân, đúng loại phiếu và in lại thu tạm sau nhập giá vẫn là thu tạm.

Tệp Excel, sổ đối chiếu JSON, ảnh tra cứu, PDF, phiên bản trình duyệt và JUnit
nằm trong `test_evidence/`, chỉ có dữ liệu giả lập và được CI lưu thành artifact.

## Điểm chờ quyết định C4-01

C4 yêu cầu một lượt **bị từ chối thu đủ khi còn khoản chưa có giá**. API hiện
không có chế độ yêu cầu thu đủ riêng: yêu cầu không ứng trước vẫn được nhận
với HTTP 201, tự ghi `provisional` và giữ trạng thái `unpriced`. Giao diện chỉ
cho thu tạm. Đây là quy tắc C3 đang ghi trong hướng dẫn sử dụng.

`test_tu_choi_thu_du_khi_con_khoan_chua_co_gia` giữ kỳ vọng HTTP 409 theo
tiêu chí C4, nên đang đỏ. Không `xfail`, không bỏ qua và chưa sửa nghiệp vụ.
Cần chủ dự án chốt giữ cách hiểu C3 (không tất toán nhưng vẫn nhận thu tạm),
hoặc phê duyệt thiết kế chế độ thu đủ để có thể từ chối rõ giao dịch đó.
Không được coi C4 đã nghiệm thu hoặc hợp nhất PR trước khi giải quyết điểm này.
