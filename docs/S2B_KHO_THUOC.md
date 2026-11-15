# S2b — Kho thuốc

Nhánh `feat/s2b-kho-thuoc`, từ `main df9aa8a`. Chỉ dùng dữ liệu giả lập.

- Quản trị gán quyền phụ **Chủ kho thuốc** trong **Tài khoản**. Chỉ `admin` hoặc
  `stock_owner` nhận giá nhập, giá vốn, giá trị tồn, lãi và VAT từ API kho. Quyền
  `pharmacy` vẫn là điều kiện để nhập/xuất; quyền phụ không thay quyền tác nghiệp.
  Giá bán/doanh thu thuốc không phải giá nhập/vốn/lãi.
- Màn Nhà thuốc → Kho thuốc có tồn theo lô, lọc hạn 60 ngày/tồn tối thiểu,
  phiếu nhập/xuất, báo cáo và Excel. Quản trị/Chủ kho có màn Kho thuốc riêng.
  Tồn tối thiểu trống là không cảnh báo; tính theo tồn còn hạn, không cách ly.
- Giá nhập là VNĐ trên đơn vị cơ sở, trước VAT. Thành tiền phiếu nhập gồm VAT,
  làm tròn đến đồng. Giá trị tồn/giá vốn lấy giá nhập trước VAT. Giá vốn được
  chụp theo đúng lô tại lúc xuất/cấp thuốc; không đổi FEFO hay điều kiện cấp thuốc.
  Nhập thêm cùng số lô chỉ khi hạn dùng, giá và VAT khớp; khác giá phải dùng số lô riêng.
- Phiếu tự đánh số `PN-YYYY-NNNN` / `PX-YYYY-NNNN` theo năm Việt Nam, trong cùng
  giao dịch khóa với ghi kho. Phiếu đã lưu không sửa/xóa. Có thể chọn lại 100 phiếu
  gần nhất để in; API theo ID vẫn đọc/in được phiếu cũ hơn.
- Xuất nội bộ/trả nhà cung cấp giữ FEFO còn hạn, không cách ly. Hủy hết hạn là
  thao tác riêng, phải chọn chính xác lô hết hạn, không cách ly; thuốc kiểm soát
  tiếp tục dùng quy trình riêng hiện có.
- Báo cáo dùng ngày Việt Nam, gồm cả hai đầu kỳ. Tồn đầu/cuối bao gồm các lô
  cách ly/hết hạn; nhập gồm nhập thường, nhập kiểm soát và trả vào cách ly.
  Mỗi thuốc luôn cân `tồn đầu + nhập − xuất = tồn cuối`, kể cả số dư cũ chưa có
  biến động ghi sổ. Doanh thu là giá bán chụp khi cấp, không phải tiền thu tại quầy;
  lãi gộp ở đây = doanh thu cấp thuốc − giá vốn của các lần xuất trong kỳ.
- Lô cũ/biến động cũ không biết giá giữ `NULL` và hiển thị **chưa có giá**, không
  coi là 0. Chủ kho/Quản trị bổ sung giá lô cũ một lần kèm căn cứ; audit lưu trước,
  sau và lý do. Giá vốn của lần xuất đã lưu không bị thay đổi theo giá bổ sung.
- PDF 01-VT/02-VT lấy tên/địa chỉ từ `clinic_profile`; có số lô, hạn dùng,
  số tiền bằng chữ tiếng Việt. Nợ/Có để trống. Bản in và Excel dùng cùng phép
  lọc quyền ở máy chủ như JSON; người không có quyền tiền không nhận cột tiền kho.

## Migration 016

Sao lưu đã kiểm trước khi nâng cấp. PostgreSQL: `python -m scripts.manage migrate`
(chạy với tài khoản chủ schema như quy trình hiện có), rồi áp dụng lại quyền runtime
bằng quy trình cài đặt hiện hành. Không đổi tệp `deploy/`.

SQLite demo tự nâng cấp qua `init_db()`. Có thể chạy riêng trên bản sao CSDL:
`python -m app.s2b_migration --sqlite /duong/dan/csdl.sqlite3`.

Quay lui khi chưa ghi dữ liệu S2b/quyền Chủ kho/tồn tối thiểu:

- PostgreSQL: `python -m scripts.manage rollback-s2b` với chủ schema.
- SQLite: `python -m app.s2b_migration --sqlite /duong/dan/csdl.sqlite3 --down`.

Nếu đã có dữ liệu mới, lệnh từ chối quay lui để bảo toàn chứng từ; dùng bản sao lưu
trước nâng cấp cùng mã nguồn tương ứng. Hai chiều đều chạy trong một giao dịch;
không xóa tồn, số lô, biến động hoặc giá trị cột cũ.

## Kiểm thử

- `tests/test_s2b_stock.py`, `lan_tests/test_s2b_stock.py`: giá vốn hai lô, FEFO,
  giữ cách ly/hạn dùng, cân báo cáo từng thuốc, nhập đồng thời, quyền API/Excel/PDF,
  lô cũ chưa có giá, bổ sung giá có audit và tồn tối thiểu.
- `tests/test_s2b_migration.py`, `lan_tests/test_s2b_migration.py`: lên/xuống,
  chạy lặp, dữ liệu cũ, từ chối rollback có dữ liệu mới, khóa sửa/xóa chứng từ.
- `lan_tests/test_pending_queues.py::test_s2b_stock_390px_sticky_resize_cost_privacy_and_forms`: bảng thật 390px, cuộn hai chiều, sticky đầu/cột,
  số tiền đầy đủ, kéo/nhớ độ rộng và localStorage bị khóa, nhập có VAT, in và Excel.
- Assertion bố cục cũ trong `lan_tests/test_pending_queues.py` được cập nhật theo
  `docs/ui-mau/U_KhoThuoc_v2.html:111–118`: tồn và nhập lô đều rộng 12 cột,
  nhập nằm dưới tồn; form có nhà cung cấp, số/ngày hóa đơn. Phiếu xuất có loại,
  lý do, người nhận theo yêu cầu S2b. Assertion version 15 đổi thành 16 theo yêu cầu
  migration 016; bộ chuẩn bị C5 cũng áp dụng migration 016 và đếm thêm 3 bảng rỗng; các kiểm tra giá trị cũ giữ nguyên.

Chờ S2c.
