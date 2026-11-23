"""Ứng dụng dòng lệnh cho OpenAI Agents API."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4


BASE_URL = "https://api.openai.com/v1/agents"
PROJECT = "proj_N2Gij9iuAP23UahuYjJcvF7v"
DEFAULT_MESSAGE = (
    "Hãy tra cứu trang NASA giải thích vì sao sao Hỏa có màu đỏ. "
    "Trả lời trong hai câu và dẫn liên kết nguồn."
)
TURN = "agent.session.turn."


class ApiError(Exception):
    pass


def log(message):
    print(message, file=sys.stderr, flush=True)


@contextmanager
def request(path, body=None, *, stream=False, submission_key=None):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or any(character.isspace() for character in key):
        raise ApiError("Hãy đặt OPENAI_API_KEY thành khóa hợp lệ của dự án.")

    headers = [
        f"Authorization: Bearer {key}",
        f"OpenAI-Project: {PROJECT}",
        "OpenAI-Beta: agents=v1",
        "Content-Type: application/json",
        f"Accept: {'text/event-stream' if stream else 'application/json'}",
    ]
    if submission_key:
        headers.append(f"Idempotency-Key: {submission_key}")

    command = [
        "curl", "--disable", "--silent", "--show-error", "--no-buffer",
        "--dump-header", "-", "--suppress-connect-headers", "--connect-timeout", "15",
        "--max-time", "900" if stream else "60", "--header", "@-",
    ]
    with TemporaryDirectory(prefix="rin-") as directory:
        if body is not None:
            payload = Path(directory) / "request.json"
            payload.write_text(json.dumps(body), encoding="utf-8")
            command += ["--data-binary", f"@{payload}"]
        with subprocess.Popen(
            [*command, BASE_URL + path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={name: value for name, value in os.environ.items() if name != "OPENAI_API_KEY"},
            text=True,
            encoding="utf-8",
        ) as curl:
            try:
                curl.stdin.write("\n".join(headers) + "\n")
                curl.stdin.close()
                while True:
                    status_line = curl.stdout.readline()
                    match = re.match(r"HTTP/\S+ (\d{3})\b", status_line)
                    if not match:
                        raise ApiError("curl không nhận được phản hồi HTTP hợp lệ.")
                    status = int(match[1])
                    response_headers = {}
                    for line in curl.stdout:
                        if line == "\n":
                            break
                        name, _, value = line.partition(":")
                        response_headers[name.lower()] = value.strip()
                    if status >= 200:
                        break

                if not 200 <= status < 300:
                    detail = curl.stdout.read().strip()
                    request_id = response_headers.get("x-request-id", "—")
                    raise ApiError(f"HTTP {status} [{request_id}] {detail}")
                if stream and not response_headers.get("content-type", "").startswith(
                    "text/event-stream"
                ):
                    raise ApiError("API không trả về luồng sự kiện SSE.")
                yield curl
            finally:
                if curl.poll() is None:
                    curl.terminate()


def get_json(path, body=None):
    with request(path, body) as curl:
        raw = curl.stdout.read()
        if curl.wait():
            raise ApiError("Kết nối API bị gián đoạn.")
        return json.loads(raw)


def events(lines):
    data = []
    for line in lines:
        if line == "\n":
            if data:
                yield json.loads("\n".join(data))
                data.clear()
        elif line.startswith("data:"):
            data.append(line[5:].removesuffix("\n").removeprefix(" "))


def resource_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value or ""):
        raise ApiError("Mã tài nguyên không hợp lệ hoặc bị thiếu.")
    return value


def stream_turn(path, *, body=None, session_id=None, message=None):
    printed = {}
    root_turn = None
    with request(path, body, stream=True) as curl:
        if message is not None:
            submission_key = str(uuid4())
            log(f"Mã gửi tin nhắn {submission_key}")
            with request(
                path,
                {"events": [{
                    "type": "agent.session.input.message",
                    "input": [{
                        "role": "user",
                        "content": [{"type": "input_text", "text": message}],
                    }],
                }]},
                submission_key=submission_key,
            ) as submission:
                submission.stdout.read()
                if submission.wait():
                    raise ApiError("Chưa xác định được API đã nhận tin nhắn hay chưa.")

        for event in events(curl.stdout):
            log(json.dumps(event, ensure_ascii=False))
            kind = event["type"]
            if kind == "agent.session.created":
                session_id = resource_id(event.get("session_id") or event["session"]["id"])
                log(f"Mã phiên {session_id}")
            if kind == "agent.session.requires_action":
                session_id = resource_id(session_id or event.get("session_id"))
                session = get_json(f"/sessions/{session_id}")
                log(json.dumps(session.get("required_actions", []), ensure_ascii=False))
                raise ApiError("Phiên cần thao tác bên ngoài cấu hình công cụ của Rin.")
            if kind in {"error", "agent.session.failed", "agent.session.environment.failed"}:
                raise ApiError("Phiên gặp lỗi. Xem sự kiện trên stderr.")

            turn = event.get("turn") or {}
            if kind in {TURN + "created", TURN + "in_progress"} and not turn.get("subagent_id"):
                root_turn = turn.get("id")
            if kind in {TURN + "output_text.delta", TURN + "output_text.done"}:
                if root_turn != event.get("turn_id"):
                    continue
                part = (event["item_id"], event["output_index"], event["content_index"])
                previous = printed.get(part, "")
                if kind.endswith(".delta"):
                    text = event["delta"]
                    printed[part] = previous + text
                else:
                    full = event["text"]
                    text = full[len(previous):] if full.startswith(previous) else "\n" + full
                    printed[part] = full
                print(text, end="", flush=True)

            if not turn.get("subagent_id"):
                if kind == TURN + "completed":
                    print(flush=True)
                    return
                if kind in {TURN + "failed", TURN + "cancelled"}:
                    raise ApiError("Lượt của Rin thất bại hoặc đã bị hủy. Xem sự kiện trên stderr.")

    recovery = f" Chạy inspect {session_id} để xem kết quả đã lưu." if session_id else ""
    raise ApiError("Luồng đã đóng trước khi có kết quả của lượt." + recovery)


def create_agent():
    definition = Path(__file__).with_name("agent.json").read_text(encoding="utf-8")
    return resource_id(get_json("", json.loads(definition)).get("id"))


def main():
    parser = argparse.ArgumentParser(description="Chạy Rin qua OpenAI Agents API.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="Lưu cấu hình Rin và in mã tác tử.")
    start = commands.add_parser("start", help="Mở phiên mới và gửi lời nhắn đầu tiên.")
    start.add_argument("--agent-id", help="Dùng mã đã có. Nếu bỏ qua, tạo cấu hình mới.")
    start.add_argument("message", nargs="?", default=DEFAULT_MESSAGE)
    send = commands.add_parser("send", help="Gửi tin nhắn vào phiên đã có.")
    send.add_argument("session_id")
    send.add_argument("message")
    inspect = commands.add_parser("inspect", help="Đọc trạng thái và các mục đã lưu.")
    inspect.add_argument("session_id")
    args = parser.parse_args()

    try:
        if args.command == "create":
            print(create_agent())
        elif args.command == "start":
            agent_id = resource_id(args.agent_id) if args.agent_id else create_agent()
            log(f"Mã tác tử {agent_id}")
            stream_turn("/sessions", body={
                "agent_id": agent_id,
                "environment": {"type": "none"},
                "input": args.message,
                "stream": True,
            })
        else:
            path = f"/sessions/{resource_id(args.session_id)}"
            if args.command == "send":
                stream_turn(path + "/events", session_id=args.session_id, message=args.message)
            else:
                print(json.dumps({
                    "session": get_json(path),
                    "items": get_json(path + "/items?order=desc&limit=100"),
                }, ensure_ascii=False, indent=2))
    except (ApiError, OSError, ValueError, KeyError) as error:
        log(f"Lỗi: {error}")
        return 1
    except KeyboardInterrupt:
        log("Đã ngắt luồng trên máy này. Phiên vẫn có thể đang chạy.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
