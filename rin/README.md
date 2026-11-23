# Rin qua OpenAI Agents API

Công cụ dòng lệnh độc lập cho dự án OpenAI `proj_N2Gij9iuAP23UahuYjJcvF7v`. Python gọi trực tiếp HTTP API bằng `curl` với các tiêu đề `OpenAI-Project` và `OpenAI-Beta: agents=v1`.

## Chuẩn bị

Cài Python 3.9 trở lên và curl 7.60 trở lên. Tạo [khóa API](https://platform.openai.com/api-keys) trong dự án trên với quyền `api.agents.read`, `api.agents.write` và `api.responses.write`. Trong Bash, nhập khóa vào biến môi trường:

```bash
read -rs -p 'OPENAI_API_KEY > ' OPENAI_API_KEY
echo
export OPENAI_API_KEY
```

## Chạy

Từ thư mục gốc của kho mã, chạy lệnh sau để lưu cấu hình, tạo phiên bằng mã tác tử API vừa trả về và gửi câu hỏi mẫu về sao Hỏa:

```bash
python3 rin/run.py start
```

Giữ mã tác tử để dùng lại cho các phiên khác. Có thể lưu cấu hình riêng bằng `create`, rồi chỉ định mã đã có:

```bash
agent_id=$(python3 rin/run.py create)
python3 rin/run.py start --agent-id "$agent_id" 'Bạn có thể giúp gì?'
```

Lấy mã phiên từ dòng `Mã phiên` trên stderr. Thay `MA_PHIEN` bằng mã thực:

```bash
python3 rin/run.py send MA_PHIEN 'Hãy tóm tắt câu trả lời trong một câu.'
python3 rin/run.py inspect MA_PHIEN
```

Văn bản của Rin hiện ngay trên stdout. stderr ghi sự kiện JSON, gồm kết quả tìm kiếm web, hoạt động của tác tử phụ và kết quả từng lượt. OpenAI chạy các công cụ này trong runtime được quản lý. Cấu hình phiên chọn `environment.type: "none"` vì Rin tra cứu và trả lời qua các công cụ tích hợp. Cấu hình này không cần cài sandbox hoặc executor.

Nếu API yêu cầu tác vụ phía máy khách, công cụ đọc và in `required_actions`. Cấu hình Rin chỉ dùng công cụ tích hợp nên không có trình xử lý hàm tùy biến.

Nếu luồng bị ngắt, dùng `inspect` để xem trạng thái và tối đa 100 mục đã lưu gần nhất trước khi gửi lại. Việc ngắt luồng bằng Ctrl+C chỉ dừng theo dõi tại máy khách. Mỗi lần dùng `send` là một lượt gửi mới có mã idempotency riêng.

[Tổng quan Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview) · [Cấu hình tác tử](https://developers.openai.com/api/docs/guides/agents-api/configuration) · [Sự kiện và dữ liệu phiên](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)
