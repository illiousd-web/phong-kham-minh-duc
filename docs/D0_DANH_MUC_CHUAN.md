# D0 — Danh mục dùng chung

Migration 10 chỉ thêm danh mục chuẩn, lịch sử nạp và các liên kết được duyệt. Không đổi giá, tiền, quyền. Sao lưu đã xác minh trước nâng cấp. LAN chạy `python -m scripts.manage migrate` bằng chủ CSDL; web yêu cầu schema 10. Không tự mã hóa hồ sơ chữ cũ.

## Nhập file gốc

Quản trị → Danh mục → D0. Chọn loại, số văn bản, ngày (dd/mm/yyyy), nguồn, phiên bản, dòng tiêu đề; ánh xạ JSON trường nội bộ → tiêu đề thực tế của file gốc. Mẫu CSV UTF-8 rỗng ở `templates/nhap_lieu/d0_*.csv`; Excel .xlsx cũng nhận (tệp nhiều sheet chọn bằng `"__sheet":"Tên sheet gốc"` trong ánh xạ), không công thức/ô lỗi. Tệp tối đa 5 MB (giữ trong giới hạn toàn bộ yêu cầu 6 MB), Excel giải nén tối đa 20 MB. Mã phải là ô chữ (đặc biệt 7 chữ số CLS và số 0 đầu). Không tự sinh mã. Chỉ nhập tệp của cơ quan ban hành đã đối chiếu; dữ liệu giả lập dùng riêng cho test.

Bấm Xem trước; lỗi báo dòng/cột, không ghi dở. Chỉ sau xem trước thành công mới hiện xác nhận. Máy chủ ràng buộc SHA-256 với bytes, loại, metadata, ánh xạ, dòng tiêu đề và bằng chứng đã xem của cùng tài khoản. Ghi thiếu/sai mã, đổi tệp/nguồn/ánh xạ đều 422. Mỗi lần nạp lưu nguồn, số/ngày văn bản, phiên bản, hash, người và thời điểm; ghi audit. Nạp là phiên bản đầy đủ: cập nhật theo mã, mục thiếu đánh dấu ngừng dùng, không xóa liên kết cũ. Nhãn chẩn đoán/snapshot đã khóa giữ nguyên.

ICD-10: cờ dùng 0/1; giới tính để trống (chung), Nam hoặc Nữ. `replacement_codes` giữ chuỗi mã thay thế từ file. Ánh xạ có thể là tên cột hoặc cấu hình như `"not_primary":{"column":"Cột hạn chế gốc","values":{"X":"1"}}`; giá trị chỉ đổi theo ánh xạ tường minh do Quản trị khai, không suy đoán. Giữ nguyên bytes file gốc, kể cả nhiều sheet. Ánh xạ cột 24–29 phải đối chiếu file gốc; không suy diễn giá trị cờ. Chờ file thật để kiểm cấu trúc, cách biểu diễn và ngữ nghĩa chính xác.

## Dùng trong hồ sơ

Bác sĩ tìm mã hoặc tên không dấu, chọn bệnh chính/bệnh kèm và lưu mã riêng; ô chẩn đoán chữ giữ nguyên. API kiểm mã còn dùng, vị trí chính, tử vong, giới tính và mã chi tiết thay thế; không khuyến khích bệnh chính chỉ cảnh báo. Hoàn tất lượt/khóa đơn M6 kiểm lại. Bắt buộc mã bệnh chính mặc định BẬT; Quản trị có thể tắt chạy song song, mỗi lần đổi ghi audit. Khi nâng cấp chưa có file ICD, phải nạp file trước hoặc chủ động bật chế độ song song; phần mềm không tự tắt. Hồ sơ cũ hiện “Chưa mã hóa”. Mã và tên lúc chọn in cùng mô tả chữ; đơn khóa/JSON giữ snapshot. Không tự sửa bản đã khóa.

Dịch vụ chưa gắn mã: chọn dịch vụ và một/nhiều mã kỹ thuật đã nạp (gói dùng nhiều mã khi đánh dấu xác nhận dịch vụ gói; dịch vụ lẻ nhiều mã bị 422, loại liên kết gói suy ra từ số mã và lưu xác nhận trong audit, không đổi logic tính tiền). Chỉ số chưa gắn mã: chọn mã dùng chung đã nạp; mã LOINC/thuộc tính lấy theo dòng đó. Không ghi vào cột giá. Phiếu M5 đã duyệt giữ mã và phiên bản trong snapshot, sửa danh mục không sửa phiếu.

ĐVHC: bảng chính thức độc lập mã TMS. Ghép duy nhất theo tên tỉnh + tên xã không dấu; mục mơ hồ/không có báo để Quản trị ghép tay bằng mã trong file đã nạp. Không đoán mã. Hồ sơ mới/cập nhật giữ mã chính thức song song; JSON M6 có official_province_code/official_commune_code; không thay bằng TMS khi mã chính thức trống. Hồ sơ cũ không bị tự gán hàng loạt.

Nghề nghiệp: tìm/chọn khi đã nạp danh mục; chữ tự do vẫn nhận, occupation_code trống là cờ “chưa chuẩn hóa”. Không mặc định nghề. Danh mục nghề Bộ Y tế [CẦN ĐỐI CHIẾU] nguồn và văn bản.

## Chờ nguồn và nghiệm thu

Chưa có file gốc ICD-10 TT 06/2026, kỹ thuật, mã dùng chung CLS, ĐVHC chính thức hoặc nghề nghiệp; repo không có mã thật của các danh mục này. Tỉnh/xã TMS và dân tộc công khai đã được chủ dự án cho phép từ L1 giữ nguyên. Xem [sổ văn bản](SO_DANG_KY_VAN_BAN.md); mọi ngày/hiệu lực chưa xác minh đều đánh dấu cần đối chiếu. Không gọi mạng liên thông; không thêm diễn giải điều luật.

Chỉ mục `(active,search_key)` chứa tên/mã đã bỏ dấu; tìm kiếm/phân trang/COUNT ở SQL, không tải cả ICD vào dropdown. Kiểm p95 trên 12.000+ dòng giả lập; số đo CI không thay nghiệm thu máy Windows thật. Chrome 109/390px kiểm tìm/chọn, nhập/xem trước và không tràn ngang.

Mã giao diện D0 gộp vào app.js hiện có để không thêm yêu cầu tài nguyên song song vào giới hạn kết nối LAN. Bộ chuẩn bị C5 gọi đủ migration 10 trước profile mới; không đổi thuật toán đo/ngưỡng, số mẫu hay dữ liệu C5.
