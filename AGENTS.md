# Quy tắc làm việc

Kỹ sư trưởng là Claude: mọi PR của bạn được Claude rà và quyết HỢP NHẤT/SỬA TIẾP.
Chủ dự án là người duy nhất bấm Merge.

## QUY TẮC

1. Đọc trước khi làm: README.md, docs/HUONG_DAN_SU_DUNG.md, docs/CAI_DAT_TUNG_BUOC.md,
   .github/workflows/clinic-tests.yml, và các tệp sẽ sửa.
2. Mỗi lệnh một nhánh mới từ main, một PR. Không bao giờ hợp nhất, không đẩy thẳng lên main,
   không sửa nhánh của PR khác.
3. Làm đúng phạm vi lệnh. Gặp điểm phải chọn về nghiệp vụ, tiền, phân quyền hoặc cần đổi CSDL:
   dừng lại hỏi, không tự đoán.
4. Không nới phân quyền. Kiểm tra quyền ở API, không chỉ ẩn trên giao diện.
5. Mọi thao tác có thể mất dữ liệu phải: kiểm điều kiện trước khi sửa, có đường quay lại,
   và chỉ báo "đạt/đã khôi phục" khi đã kiểm lại thật.
6. Máy chủ Windows 11 (i3, RAM 8GB); máy trạm Windows 7 + Chrome 109. Giao diện không dùng
   tính năng JS/CSS mà Chrome 109 không có. Dùng được ở bề rộng 390px.
7. Quyết định đã chốt, không tự đổi: chỉ mạng nội bộ (LAN); không sao lưu ra ngoài máy chủ
   (giữ 14 bản đã kiểm); không hướng dẫn tắt Smart App Control; lễ tân không xem công nợ.
8. Không đưa mật khẩu, khóa, clinic.env, dữ liệu bệnh nhân thật vào Git.
9. Mọi chữ người dùng thấy là tiếng Việt; ngày dd/mm/yyyy; giờ Việt Nam.
10. Trong lúc làm: chỉ chạy các test liên quan mà lệnh nêu. Bộ test đầy đủ để CI chạy.
    Xong khi: 5 job CI (test, audit, browser-chromium-109, windows-preflight,
    windows-install-e2e) đều xanh. Test hỏng thỉnh thoảng thì tìm nguyên nhân,
    không tăng timeout cho qua.
11. Mô tả PR bằng tiếng Việt, đúng 4 mục: Đã làm gì; Kiểm bằng gì (tên bài kiểm thử,
    kết quả CI); Chưa kiểm được gì và vì sao; Người cài/người dùng cần làm gì.
12. Khi nhận yêu cầu SỬA TIẾP: sửa trên cùng nhánh, trả lời từng mục đã sửa bằng bài kiểm thử nào.

## GIAO DIỆN (chuẩn v2)

- Mẫu bắt buộc nằm ở docs/ui-mau (PNG và HTML). Làm đúng bố cục, thứ tự khối,
  màu, cỡ chữ của mẫu; không tự sáng tác.
- Chữ nhỏ nhất 13px. Nút, tab, mục menu cao ít nhất 44px. Ở 390px, nút rộng
  ít nhất 88px, nhãn nút không xuống quá 2 dòng.
- Viền ô nhập #6F8F7E. Màu chính #008249, xanh dương #0069C7, chữ #0B1F17,
  chữ phụ #1F3A31, đỏ #B42318.
- Dải "Bản thử nghiệm" luôn hiện, kể cả màn đăng nhập.
- Thanh dính (sticky) không bị header che (dùng stickyOffset). Bản in không có hiệu ứng kính.
- Không thêm data-action trùng với selector đã có; nút phụ dùng tên action riêng.
- Mỗi hàm JS mới viết nhiều dòng, không dồn cả hàm trên 1 dòng.
  Không định dạng lại mã cũ nếu lệnh không yêu cầu.

## KIỂM THỬ

- Không nới hoặc xóa assertion cũ để test qua. Chỉ được đổi assertion khi
  nó mâu thuẫn với docs/ui-mau; phải nêu dòng mẫu làm căn cứ trong commit.
- Lỗi giao diện tìm thấy khi chạy thật thì thêm test Chromium cho lỗi đó.
- Bảng chọn test theo vùng sửa:

| Vùng sửa | Test liên quan |
|---|---|
| reception/prices/login | `lan_tests/test_browser_https.py -k u1r2` |
| doctor/kê đơn | `lan_tests/test_m6_browser.py`, `lan_tests/test_browser_https.py -k "u1b or u1c"`, `lan_tests/test_m0_browser.py` |
| thu ngân/hành chính | `lan_tests/test_administrative_browser.py` |
| deploy/windows | Để CI windows chạy |
| Python backend | `tests/` liên quan theo tên tệp |
