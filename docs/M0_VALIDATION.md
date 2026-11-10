# Kiểm chứng M0

Dữ liệu giả lập, Linux cloud. Không thay nghiệm thu Windows 11/i3 tại phòng khám.

- `tests`: 264 đạt (81,46 giây).
- Toàn bộ `lan_tests`: 98 đạt, 1 bỏ qua trên Linux (bài dành cho Windows).
- C4 `lan_tests/test_mot_ngay_kham.py`: 12 đạt (48,37 giây), giữ nguyên tệp và tiêu chí.
- API M0 trên SQLite và PostgreSQL đạt; có kiểm nhật ký dị ứng dài hơn 500 ký tự, quyền bác sĩ khác, lý do đóng, tiền/phí/cấp thuốc và số đếm.
- HTTPS/Chromium 156: chọn lượt, sáu phần hồ sơ, F2/F8/Esc, dị ứng, không tràn ngang ở 1366/1280/900/390px. CI chạy cùng bài với Chromium 109; ảnh trong artifact `chromium-109-evidence/m0/` và `synthetic-clinic-test-evidence/m0/`.

## C5 trên dữ liệu có sẵn

Lệnh: `python -m scripts.do_hieu_nang --baseline-ref origin/main --output test_evidence/m0-c5-final/report.json --pg-pid <PID PostgreSQL giả lập>`; `CLINIC_PERF_SOURCE_DATABASE_URL` trỏ đến PostgreSQL loopback kiểm thử riêng.

Dùng nguyên bộ tạo C5: 22.000 lượt, 20.000 bệnh nhân, 88.000 chỉ định, 22.000 đơn thuốc, 2.000 tệp đính kèm. Đo 20 mẫu sau một lần làm nóng cho mỗi thao tác; không chọn mẫu tốt nhất.

| Phép đo sau migration | Trung vị | p95 |
|---|---:|---:|
| Tải màn hình bác sĩ | 0,2138 giây | 0,2287 giây |
| Mở phiếu khám | 0,2200 giây | 0,2552 giây |

Cả hai dưới ngưỡng trung vị 1,5 giây và p95 3 giây của C5. Migration 5 trên cùng database sau profile main mất 0,0016 giây; chạy lại không đổi dữ liệu. Số dòng (trừ marker migration), tiền và tồn kho giữ nguyên. C5 sau thay đổi đạt cả sao lưu đã kiểm, khôi phục đối soát và đủ hàng chờ/số đếm. Bộ đo tạo kết quả JSON trong `test_evidence/m0-c5-final/`, không chứa dữ liệu bệnh nhân thật.

Bài `lan_tests/test_m0_scale.py` còn đối chiếu SHA-256 từng dòng các bảng patients/visits/charges/payments/stock_lots trước/sau migration trên quy mô C5; chỉ bỏ trường allergies mới khi so.


F4 tìm người bệnh; sáu nút điều hướng cuộn, tô sáng phần đang xem. F2/F8 chỉ hoạt động khi lượt đang mở thuộc danh sách đang hiển thị.

## Sửa tiếp PR 15

- Lọc loại lượt đang mở: đóng chi tiết, F2/F8 không ghi; Chromium kiểm A → lọc B → F2/F8 → A giữ version/lịch sử, chọn B rồi lưu vào B.
- Thanh toán dựa invoice và phiếu thu thật, kiểm đủ sáu trạng thái; giao diện đối chiếu phiếu thu 200 đ và còn nợ 800 đ.
- Bác sĩ chỉ sửa dị ứng khi có lượt mở của mình; bác sĩ chỉ có lượt hoàn tất nhận 403.
- Lịch sử 300 lượt dùng một truy vấn đơn thuốc và một truy vấn kết quả; kiểm thời gian trung vị không quá 1,5 giây.
- Lỗi đóng lượt có phí hướng dẫn liên hệ Quản lý, không bỏ qua phí. Lễ tân/bác sĩ không có API tạo yêu cầu hủy lượt, nên không hiện nút dẫn đến chức năng không được phân quyền.
