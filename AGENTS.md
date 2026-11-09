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
10. Xong khi: toàn bộ tests, lan_tests và 5 job CI (test, audit, browser-chromium-109,
    windows-preflight, windows-install-e2e) đều xanh. Kiểm thử hỏng thỉnh thoảng thì tìm
    nguyên nhân, không tăng timeout cho qua.
11. Mô tả PR bằng tiếng Việt, đúng 4 mục: Đã làm gì; Kiểm bằng gì (tên bài kiểm thử,
    kết quả CI); Chưa kiểm được gì và vì sao; Người cài/người dùng cần làm gì.
12. Khi nhận yêu cầu SỬA TIẾP: sửa trên cùng nhánh, trả lời từng mục đã sửa bằng bài kiểm thử nào.
