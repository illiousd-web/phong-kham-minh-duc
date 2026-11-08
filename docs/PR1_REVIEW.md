# Rà soát PR #1

Ngày rà soát: 08/11/2026 (Asia/Saigon).

## Kết luận

Đủ điều kiện về mã nguồn và kiểm thử để hợp nhất PR chuẩn hóa vào main sau khi chủ repository phê duyệt. Kết luận chỉ áp dụng bản demo cục bộ dùng dữ liệu giả lập; không chấp thuận triển khai LAN hoặc dữ liệu bệnh nhân thật. Chưa merge hay triển khai. GitHub API trả Forbidden nên không xác nhận được trạng thái CI, branch protection hoặc approval trên GitHub.

## Nguồn đối chiếu

Git ref refs/pull/1/head ban đầu trỏ 1de59679ed27e2ba55c97684f89b4573cf2a7108, trùng nhánh chore/normalize-v031-source. Main tại thời điểm kiểm tra là 3f19d119286f2467e9e7c20666f7ccba8ec43cf8.

ZIP v0.3.1 có SHA-256 a4c50f4d4da3d1facfbc3ac8b3a3a265816927b42a8e7a023d2ea79c2defe74e, CRC đạt. Không thiếu tệp nguồn ngoài phần test_evidence đã chủ động loại khỏi Git. Sai khác nguồn đã rà gồm ignore, hướng dẫn, khởi động, bỏ mật khẩu cố định, sửa kiểm thử và bảo vệ cục bộ; không phát hiện mất thành phần nghiệp vụ.

31 tệp PNG/DOCX đối chiếu từng byte với ZIP đều khớp; kiểm tra lại manifest docs/assets-v031.sha256 đạt. Đủ 9 mẫu Word runtime và các bản sao gốc. Cả 9 DOCX mở được, CRC đạt, không thấy VBA project hay relationship External. Bộ kiểm thử xuất DOCX/PDF bao phủ đủ các loại biểu mẫu; không đồng nghĩa kiểm định pháp lý hoặc độ giống bố cục tuyệt đối giữa PDF và Word.

## Bảo mật và dữ liệu

- Tệp Git được quét theo tên và chữ ký SQLite: không có CSDL hay dữ liệu thử phát sinh được track. data/ và backups/ chỉ có .keep. test_evidence bị ignore.
- Không tìm thấy mật khẩu demo cũ hoặc mẫu private key, GitHub token, AWS access key, OpenAI project key trong tệp nguồn được kiểm tra. Không phải bảo đảm phát hiện mọi loại bí mật hoặc xác minh mọi chuỗi nội dung y tế.
- Mật khẩu demo lấy từ môi trường hoặc nhập kín, không có giá trị mặc định; tests tự tạo mật khẩu ngẫu nhiên. Mật khẩu lưu dưới dạng PBKDF2-HMAC-SHA256 với salt riêng; token phiên tạo ngẫu nhiên, lưu hash, có hạn dùng và logout.
- Các truy vấn có dữ liệu người dùng được truyền tham số; trường hợp dựng cột INSERT lấy từ schema Pydantic, không từ tên cột tùy ý do client gửi. Đã đọc kiểm soát vai trò, bác sĩ được phân công, biểu mẫu và đính kèm; bộ kiểm thử có kiểm tra truy cập trái quyền.
- Bổ sung ignore cho chứng thư chứa khóa .p12/.pfx và các bản sao SQLite có hậu tố. Kiểm tra ignore cho CSDL, WAL, attachments, backup, .env, khóa và kết quả thử đều đạt.

## Lỗi đã sửa trên nhánh PR

1. Host bất kỳ trước sửa được HTTP 200 trên /api/health dù ứng dụng chỉ dành cho cục bộ. Thêm TrustedHostMiddleware chỉ nhận 127.0.0.1, localhost và tên testserver dành cho TestClient. Kiểm thử hostname giả nhận 400 và client ngoài loopback nhận 403.
2. Launcher không vô hiệu proxy headers của Uvicorn. Thêm --no-proxy-headers để không dùng X-Forwarded-For như địa chỉ kết nối thực.
3. getpass có thể rơi về chế độ echo khi không có terminal an toàn. Chuyển GetPassWarning thành lỗi, dừng trước khi đọc mật khẩu theo cách không ẩn; dùng biến môi trường khi chạy không tương tác.

## Xác minh sau sửa

- pytest: 43 passed (36 bài cũ và 7 trường hợp bảo vệ mới), 1 cảnh báo Starlette/TestClient/httpx.
- Chromium: luồng tiếp đón, khám, chỉ định, duyệt kết quả, đơn nháp, thu tiền, quản lý đạt; tải PDF đạt; desktop/mobile đạt; 0 lỗi JavaScript. Browser smoke dùng API bridge trong tiến trình, không phải duyệt trực tiếp qua HTTP.
- Chạy launcher thật: health, đăng nhập mật khẩu ngẫu nhiên, /api/me đạt; Host lạ nhận 400; header X-Forwarded-For giả bị bỏ qua.
- pip check: không có phụ thuộc hỏng. Đây không phải quét CVE của toàn bộ chuỗi phụ thuộc.
- Kiểm tra manifest tài sản và git diff --check đạt.

## Giới hạn còn lại

ZIP và mật khẩu demo từng công khai vẫn còn trong lịch sử main; xóa tệp ở đầu nhánh không xóa lịch sử. Không dùng lại mật khẩu đó. Các tài khoản demo dùng chung mật khẩu người chạy chọn; chưa có chính sách đổi mật khẩu từng người, giới hạn đăng nhập thất bại, MFA hay mã hóa CSDL/backup. Chưa đánh giá tải đồng thời hoặc sao lưu khi có ghi tệp đính kèm đồng thời. Kiểm tra chữ ký đầu tệp upload chưa thay thế quét mã độc. Phụ thuộc dùng khoảng phiên bản, chưa có lockfile hay báo cáo CVE độc lập. Chưa chạy trực tiếp Windows hoặc kiểm thử xâm nhập toàn diện.

Các điểm này cần được xử lý/đánh giá trong giai đoạn nâng cấp nội bộ, trước khi cân nhắc dữ liệu thật. Giữ host loopback và dữ liệu giả lập trong PR này.
