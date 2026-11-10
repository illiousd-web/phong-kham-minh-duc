# Kiểm chứng M0

Dữ liệu giả lập, Linux cloud. Không thay nghiệm thu Windows 11/i3 tại phòng khám.

- `tests`: 264 đạt (81,46 giây).
- C4 `lan_tests/test_mot_ngay_kham.py`: 12 đạt (48,37 giây), giữ nguyên tệp và tiêu chí.
- API M0 trên SQLite và PostgreSQL đạt; có kiểm nhật ký dị ứng dài hơn 500 ký tự, quyền bác sĩ khác, lý do đóng, tiền/phí/cấp thuốc và số đếm.
- HTTPS/Chromium 156: chọn lượt, sáu phần hồ sơ, F2/F8/Esc, dị ứng, không tràn ngang ở 1366/1280/900/390px. CI chạy cùng bài với Chromium 109; ảnh trong artifact `chromium-109-evidence/m0/` và `synthetic-clinic-test-evidence/m0/`.

## C5 trên dữ liệu có sẵn

Lệnh: `python -m scripts.do_hieu_nang --baseline-ref origin/main --output test_evidence/m0-c5/report.json --pg-pid <PID PostgreSQL giả lập>`; `CLINIC_PERF_SOURCE_DATABASE_URL` trỏ đến PostgreSQL loopback kiểm thử riêng.

Dùng nguyên bộ tạo C5: 22.000 lượt, 20.000 bệnh nhân, 88.000 chỉ định, 22.000 đơn thuốc, 2.000 tệp đính kèm. Đo 20 mẫu sau một lần làm nóng cho mỗi thao tác; không chọn mẫu tốt nhất.

| Phép đo sau migration | Trung vị | p95 |
|---|---:|---:|
| Tải màn hình bác sĩ | 0,2211 giây | 0,2332 giây |
| Mở phiếu khám | 0,2414 giây | 0,2630 giây |

Cả hai dưới ngưỡng trung vị 1,5 giây và p95 3 giây của C5. Migration 5 trên cùng database sau profile main mất 0,0033 giây; chạy lại không đổi dữ liệu. Số dòng (trừ marker migration), tiền và tồn kho giữ nguyên. C5 sau thay đổi đạt cả sao lưu đã kiểm, khôi phục đối soát và đủ hàng chờ/số đếm. Bộ đo tạo kết quả JSON trong `test_evidence/m0-c5/`, không chứa dữ liệu bệnh nhân thật.

Bài `lan_tests/test_m0_scale.py` còn đối chiếu SHA-256 từng dòng các bảng patients/visits/charges/payments/stock_lots trước/sau migration trên quy mô C5; chỉ bỏ trường allergies mới khi so.

## Điểm chưa chốt

F3 trùng phím Tìm tiếp của Chrome; chưa chiếm phím khi chủ dự án chưa chốt. Sáu nút hiện điều hướng cuộn trong trang, giữ các phần luôn hiện để C4 chạy nguyên vẹn; đang chờ chủ dự án chốt cách chuyển tab. PR giữ trạng thái nháp.
