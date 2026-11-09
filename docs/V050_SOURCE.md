# Nguồn của v0.5.0

Main kiểm tra tại commit `e3edb2d18b6a621aaf80d380af63e6ab975c1b1d` (đã chứa PR #4/Issue #3). Nhánh phát triển `feat/v0.5.0-clinical-workflows` bắt đầu từ main này.

Đã đọc ZIP `phong-kham-minh-duc-v0.4.1.zip` do người dùng đính kèm, SHA-256 `6ad8331722c63a9b9289397ee698f721f0f99c4821d2b098423d8ba4d018924e`. ZIP có 146 mục, CRC hợp lệ. Không đưa ZIP, tệp runtime hay dữ liệu vào Git.

Có nhánh chưa merge `feat/v042-clinic-abcd`, commit `fc8902dfdf4643ce0487be7c8762546f174b7200` (PR #5). Đã cherry-pick commit này để giữ các sửa giao diện/biểu mẫu v0.4.1 và tiếp tục phần nghiệp vụ; không merge PR #5.

Đối chiếu tệp nguồn trong ZIP với cây sau cherry-pick, trước khi phát triển v0.5: 112 tệp trùng từng byte, 12 tệp khác, không thiếu tệp nguồn. Khác biệt gồm schema, API nghiệp vụ, catalog, JS, kiểm thử A–D và xuống dòng BAT. Đã kiểm tra riêng các thay đổi v0.4.1 về ngày Việt Nam, sinh hiệu/BMI, thông tin bệnh nhân bắt buộc, bảng kết quả/chữ ký và chứng chỉ TLS; phần tương ứng đã có. v0.5 tiếp tục sửa API, JS, migration và phụ lục biểu mẫu trên nền đó.

Chín mẫu DOCX và logo gốc giữ nguyên; dùng `sha256sum -c docs/assets-v031.sha256` để xác minh. `tests/fixtures/v041_schema_pg.sql` lấy từ schema PostgreSQL trong ZIP; fixture v042 lấy từ commit trên, dùng kiểm thử nâng cấp dữ liệu giả lập.
