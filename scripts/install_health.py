"""Vietnamese health report for the Windows LAN server (installer step m, KIEM_TRA).

Windows-only facts (services, firewall, scheduled task, RAM, page file, ACL)
are collected by PowerShell and passed as a JSON file; this module adds the
checks Python can do itself (database, HTTPS, certificate, backups, disk) and
renders ĐẠT / KHÔNG ĐẠT per item.

The report never contains passwords, connection strings or patient data: the
renderer only receives the derived facts below.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import ssl
import sys
import urllib.request

VN = timezone(timedelta(hours=7))
GIB = 1024 ** 3


def collect(env, state_file=None, ca_file=None, timeout=15):
    """Python-side facts. Every failure becomes a short reason, never a secret."""
    facts = {}
    data = Path(env.get('CLINIC_DATA_DIR', '.'))
    try:
        import psycopg
        with psycopg.connect(env['CLINIC_DATABASE_URL'], connect_timeout=5) as c:
            facts['db_ok'] = True
            facts['schema_version'] = c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
            facts['db_size_mib'] = round(c.execute('SELECT pg_database_size(current_database())').fetchone()[0] / 1048576, 1)
    except Exception as error:
        facts['db_ok'] = False
        facts['db_error'] = type(error).__name__
    origin = env.get('CLINIC_ORIGIN', '')
    facts['origin'] = origin
    ca_file = ca_file or str(data / 'tls' / 'ca.crt')
    try:
        context = ssl.create_default_context(cafile=ca_file)
        with urllib.request.urlopen(origin + '/api/health', context=context, timeout=timeout) as response:
            health = json.load(response)
        facts['https_health'] = health.get('status') == 'lan-pilot'
        facts['app_version'] = health.get('version')
        with urllib.request.urlopen(origin + '/', context=context, timeout=timeout) as response:
            page = response.read().decode('utf-8', 'replace')
        facts['login_page'] = response.status == 200 and 'app.js' in page and 'PHÒNG KHÁM' in page
    except Exception as error:
        facts['https_health'] = False
        facts['login_page'] = False
        facts['https_error'] = type(error).__name__
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(Path(env['CLINIC_TLS_CERT']).read_bytes())
        facts['cert_not_after'] = cert.not_valid_after_utc.isoformat()
    except Exception as error:
        facts['cert_error'] = type(error).__name__
    try:
        facts['disk_free_gib'] = round(shutil.disk_usage(data).free / GIB, 1)
    except OSError:
        pass
    backups = Path(env.get('CLINIC_BACKUP_DIR', str(data / 'backups')))
    files = sorted(backups.glob('minhduc-*.mdbackup'), key=lambda p: p.stat().st_mtime) if backups.exists() else []
    facts['backup_count'] = len(files)
    if files:
        facts['backup_newest_utc'] = datetime.fromtimestamp(files[-1].stat().st_mtime, timezone.utc).isoformat()
    if state_file and Path(state_file).exists():
        try:
            state = json.loads(Path(state_file).read_text(encoding='utf-8'))
            facts['backup_state'] = {k: state.get(k) for k in (
                'last_success_utc', 'last_error', 'external_present', 'external_last_copy_utc', 'warnings')}
        except (OSError, ValueError):
            pass
    return facts


def _age_hours(value, now):
    return (now - datetime.fromisoformat(value)).total_seconds() / 3600


def evaluate(facts, now=None):
    """Turn facts into (title, passed, detail) rows. Missing facts fail."""
    now = now or datetime.now(timezone.utc)
    rows = []

    def add(title, passed, detail):
        rows.append({'muc': title, 'dat': bool(passed), 'chi_tiet': detail})

    service = facts.get('service') or {}
    add('Dịch vụ web "MinhDuc" đang chạy và tự khởi động',
        service.get('status') == 'Running' and service.get('start') == 'Automatic',
        f"Trạng thái: {service.get('status', 'không đọc được')}, khởi động: {service.get('start', '?')}")
    pg = facts.get('postgres_service') or {}
    add('Dịch vụ PostgreSQL 17 đang chạy', pg.get('status') == 'Running' and pg.get('start') == 'Automatic',
        f"Trạng thái: {pg.get('status', 'không đọc được')}, phiên bản: {facts.get('postgres_version', '?')}")
    listeners = facts.get('pg_listeners')
    add('PostgreSQL chỉ nhận kết nối trong máy (127.0.0.1)',
        isinstance(listeners, list) and bool(listeners) and all(a in ('127.0.0.1', '::1') for a in listeners),
        'Địa chỉ đang nghe: ' + (', '.join(listeners) if listeners else 'không thấy'))
    version = facts.get('schema_version')
    add('Kết nối cơ sở dữ liệu bằng tài khoản ứng dụng', facts.get('db_ok') and (version or 0) >= 3,
        f'Phiên bản cấu trúc dữ liệu: {version}' if facts.get('db_ok') else f"Lỗi: {facts.get('db_error', 'không rõ')}")
    add('Trang đăng nhập mở được qua HTTPS (chứng chỉ hợp lệ)', facts.get('https_health') and facts.get('login_page'),
        f"Địa chỉ: {facts.get('origin', '?')}" + (f" — lỗi: {facts['https_error']}" if facts.get('https_error') else ''))
    if facts.get('cert_not_after'):
        days = (datetime.fromisoformat(facts['cert_not_after']) - now).days
        add('Chứng chỉ HTTPS còn hạn trên 30 ngày', days > 30, f'Còn {days} ngày')
    else:
        add('Chứng chỉ HTTPS còn hạn trên 30 ngày', False, 'Không đọc được chứng chỉ')
    fw = facts.get('firewall') or {}
    add('Tường lửa chỉ mở cổng web cho mạng nội bộ', fw.get('exists') and fw.get('enabled') and fw.get('scoped'),
        f"Cổng {fw.get('port', '?')} cho {fw.get('remote', '?')}")
    task = facts.get('backup_task') or {}
    add('Lịch sao lưu 20:00 hằng ngày đã đăng ký', task.get('exists') and task.get('enabled', True),
        f"Lần chạy tiếp theo: {task.get('next_run', '?')}; kết quả lần trước: {task.get('last_result', '?')}")
    state = facts.get('backup_state') or {}
    newest = state.get('last_success_utc') or facts.get('backup_newest_utc')
    if newest:
        hours = _age_hours(newest, now)
        add('Bản sao lưu gần nhất mới hơn 36 giờ', hours <= 36 and not state.get('last_error'),
            f'Cách đây {hours:.0f} giờ; số bản trên máy: {facts.get("backup_count", 0)}'
            + (f"; lỗi lần cuối: {state['last_error']}" if state.get('last_error') else ''))
    else:
        add('Bản sao lưu gần nhất mới hơn 36 giờ', False, 'Chưa có bản sao lưu nào')
    external = facts.get('external_declared')
    if external:
        copied = state.get('external_last_copy_utc')
        hours = _age_hours(copied, now) if copied else None
        add('Ổ sao lưu ngoài nhận bản sao trong 3 ngày qua', hours is not None and hours <= 72,
            f'Lần chép gần nhất cách đây {hours:.0f} giờ' if hours is not None else 'Chưa chép được lần nào')
    free = facts.get('disk_free_gib')
    add('Ổ dữ liệu còn trống từ 20 GB', free is not None and free >= 20, f'Còn trống {free} GB')
    memory = facts.get('memory') or {}
    add('RAM tổng từ 8 GB và còn trống từ 1 GB',
        memory.get('total_mib', 0) >= 7168 and memory.get('available_mib', 0) >= 1024,
        f"Tổng {memory.get('total_mib', '?')} MB, trống {memory.get('available_mib', '?')} MB")
    page = facts.get('pagefile') or {}
    add('Tệp hoán đổi (page file) do Windows tự quản lý', page.get('auto') is True, page.get('detail', 'không đọc được'))
    add('Tệp cấu hình chỉ quản trị và dịch vụ đọc được', facts.get('env_acl_ok') is True,
        facts.get('env_acl_detail', 'không đọc được'))
    return rows


def render(rows, facts, title='KẾT QUẢ KIỂM TRA SỨC KHỎE', now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(VN)
    passed = sum(r['dat'] for r in rows)
    lines = [f'PHÒNG KHÁM ĐA KHOA MINH ĐỨC — {title}',
             f'Thời điểm: {now:%d/%m/%Y %H:%M} (giờ Việt Nam)',
             f"Phần mềm: {facts.get('app_version') or '0.5.0'} | Windows: {facts.get('windows', '?')} | "
             f"Python: {facts.get('python_version', '?')} | PostgreSQL: {facts.get('postgres_version', '?')}",
             f"Dung lượng CSDL: {facts.get('db_size_mib', '?')} MB", '']
    for row in rows:
        mark = 'ĐẠT      ' if row['dat'] else 'KHÔNG ĐẠT'
        lines.append(f"[{mark}] {row['muc']}")
        lines.append(f"            {row['chi_tiet']}")
    lines += ['', f'Tổng: {passed}/{len(rows)} mục ĐẠT.']
    if passed < len(rows):
        lines.append('Có mục KHÔNG ĐẠT: gửi tệp này cho người hỗ trợ. Không tắt tường lửa hay phần mềm diệt virus để thử.')
    lines.append('Báo cáo không chứa mật khẩu hay thông tin bệnh nhân.')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-facts', help='JSON do PowerShell thu thập')
    parser.add_argument('--state', help='backup-status.json')
    parser.add_argument('--output', help='Lưu báo cáo .txt')
    parser.add_argument('--title', default='KẾT QUẢ KIỂM TRA SỨC KHỎE')
    args = parser.parse_args(argv)
    facts = {}
    if args.windows_facts:
        facts.update(json.loads(Path(args.windows_facts).read_text(encoding='utf-8-sig')))
    facts.update(collect(os.environ, args.state))
    rows = evaluate(facts)
    text = render(rows, facts, args.title)
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8-sig', newline='\r\n')  # Notepad-friendly
    sys.stdout.buffer.write(text.encode('utf-8'))
    sys.stdout.flush()
    return 0 if all(r['dat'] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
