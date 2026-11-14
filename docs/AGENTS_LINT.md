# Báo cáo AGENTS và linter

## Đã làm gì

- Nhánh `chore/agents-lint`, gốc `main` theo mốc được chỉ định `cf54de7`.
- Giữ 12 quy tắc; sửa quy tắc 10, thêm chuẩn giao diện v2 và bảng chọn test.
- Ghim Ruff `0.17.5`, ESLint `9.39.5` (bản 9.x ổn định mới nhất npm trả về khi thực hiện).
- Workflow chỉ thêm hai bước Ruff và ESLint trong job `audit`.
- Giữ nguyên `app/static/*`; không sửa nhánh PR #33, không đổi hành vi hay định dạng lại mã cũ.

Thống kê Ruff ban đầu, trước khi sửa:

| Rule | Ban đầu | Đã xử lý | Ignore |
|---|---:|---:|---:|
| F401 | 81 | 81 | 0 |
| F811 | 31 | 31 | 0 |
| F841 | 5 | 4 | 1 |
| F541 | 2 | 0 | 2 |
| Các rule F/E9 khác | 0 | 0 | 0 |
| Tổng | 119 | 116 | 3 |

F401: xóa 66 import thừa; giữ 15 import fixture pytest bằng alias tường minh
`https_server as https_server` hoặc `prescription as prescription`.
F811: 30 cảnh báo fixture được xử lý bằng các alias này; xóa import `Response`
trùng trong `app/main.py` (dòng 1019 ở bản gốc).
F841: bỏ biến `nurse_id`, `first`; bỏ phần gán `cash`, `n` không dùng nhưng giữ
nguyên các lệnh đăng nhập `token(...)` trong `tests/test_v042_workflows.py`.

Ba ignore Python có chú thích ngay tại dòng:

- `scripts/ui_screenshots.py:46`, F841, `pharmacy`: giữ đăng nhập vai trò dược và vòng đời client.
- `lan_tests/test_v050_abcd.py:142`, F541: giữ nguyên assertion cũ có f-string hằng.
- `tests/test_v02_features.py:141`, F541: cùng lý do giữ nguyên assertion.

Thống kê ESLint lần đầu, trước khi khai báo tên dùng chung giữa các script:

| Rule | Ban đầu | Xử lý cấu hình | Miễn trừ |
|---|---:|---:|---:|
| no-undef | 191 | 191 | 0 |
| no-unused-vars | 9 | 0 | 9 |
| no-dupe-keys, no-redeclare, no-unreachable, no-dupe-else-if, no-self-assign | 0 | 0 | 0 |

191 cảnh báo no-undef là các tên dùng chung giữa `app.js`, `m6.js`, `m5.js`
(được tải bằng script defer tại `index.html:30–32`) và API trình duyệt
`scrollY`, `innerHeight`. Chỉ khai báo tên do script khác cung cấp theo từng tệp;
không tắt no-undef.

Chín miễn trừ no-unused-vars chỉ áp dụng cho `app/static/app.js`, có tên và lý do
trong `eslint.config.js`: `patientList`, `dueList` (dòng 23), `patientHead` (124),
`groups` (233), `visits` (249), ba catch binding `e` (146, 151, 276), `boot` (707).
Tám trường hợp đầu là phần thừa vô hại, giữ vì phạm vi cấm sửa static;
`boot` được `m6.js:62` gọi sau khi tải các script.

**Lỗi thật cần sửa sau:** Không phát hiện biến chưa định nghĩa, khóa trùng,
mã không thể chạy hoặc lỗi hành vi nào trong phạm vi các rule đã chọn.

## Kiểm bằng gì

- `ruff check app scripts tests lan_tests`: đạt.
- `npx --yes eslint@9.39.5 app/static`: đạt (cache npm cục bộ đặt trong `/tmp`).
- Kiểm cấu hình qua stdin: cả bảy rule ESLint đều bắt được lỗi mẫu;
  miễn trừ ở app.js vẫn bắt tên biến thừa mới và tên chưa định nghĩa mới.
- So AST: toàn bộ assertion cũ trong các tệp test đã sửa giữ nguyên.
- `git diff --check`: đạt; đối chiếu `app/static/*` với `cf54de7`: không thay đổi.
- `python -m pytest tests/ -q`: 376 đạt, 4 lỗi do thiếu Chromium ở đường dẫn mặc định Playwright.
- Chạy lại đúng 4 bài lỗi với `CHROMIUM_PATH=/usr/bin/chromium`: 4 đạt trong 9,50 giây.
  Tổng 380 bài được xác minh đạt qua hai lượt; không sửa test hoặc tăng timeout.

## Chưa kiểm được gì và vì sao

- Chưa có kết quả 5 job CI; chỉ được xác nhận hoàn tất sau khi cả 5 job xanh.
- Không chạy toàn bộ `lan_tests` hoặc Windows tại chỗ theo phạm vi lệnh.

## Người cài/người dùng cần làm gì

Không cần thao tác. Người phát triển dùng requirements-test.lock để cài Ruff;
ESLint chạy bằng lệnh npx đã ghim ở trên.
