"""Daily backup job for the Windows server (Task Scheduler, 20:00).

backup -> authenticate/verify the new file -> optional copy to a declared
external drive -> status file + warnings. Old good backups are never removed
before a new one is verified; retention comes from CLINIC_BACKUP_KEEP (14 on the
server in the Windows installer configuration) and the CLINIC_BACKUP_TOTAL_MB
budget, always keeping at least 3 verified backups. The external drive copy is an
opt-in (CLINIC_EXTERNAL_BACKUP=1), off by default. Also warns when the HTTPS
certificate is missing/unreadable or has < 60 days left.

The external drive is recognised by a marker file, not by drive letter, so a
USB stick that comes back as E: or F: is still found. A drive on the same
volume as the data folder is rejected: it would not survive an SSD failure.

Exit codes: 0 = backup verified (external copy done or absent < 3 days),
3 = backup verified but a warning needs attention, 1 = backup failed.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import string
import subprocess
import sys
import tempfile

MARKER_DIR = 'MinhDuc-SaoLuu'
MARKER_FILE = 'minhduc-backup-target.json'
ABSENT_LIMIT = timedelta(days=3)
CERT_WARNING_DAYS = 60


def now_utc():
    return datetime.now(timezone.utc)


def parse(value):
    return datetime.fromisoformat(value) if value else None


def candidate_roots():
    if os.name == 'nt':
        return [Path(f'{letter}:\\') for letter in string.ascii_uppercase if letter not in 'AB']
    return [Path(p) for p in ('/media', '/mnt')]


def find_external(roots, target_id, data_dir):
    """Return the marker directory whose id matches, on a different volume."""
    try:
        data_device = os.stat(data_dir).st_dev
    except OSError:
        data_device = None
    for root in roots:
        folder = Path(root) / MARKER_DIR
        try:
            marker = json.loads((folder / MARKER_FILE).read_text(encoding='utf-8'))
            if marker.get('id') != target_id:
                continue
            if data_device is not None and os.stat(folder).st_dev == data_device:
                continue  # same SSD as the clinic data: not an external copy
            return folder
        except (OSError, ValueError):
            continue
    return None


def evaluate(state, external_config, now):
    """Pure decision: list of Vietnamese warnings for the operator."""
    warnings = []
    if state.get('last_error'):
        warnings.append('Sao lưu tối gần nhất THẤT BẠI: ' + state['last_error'])
    last_ok = parse(state.get('last_success_utc'))
    if last_ok is None or now - last_ok > timedelta(hours=36):
        warnings.append('Chưa có bản sao lưu thành công trong 36 giờ qua.')
    if external_config:
        since = parse(state.get('external_last_copy_utc')) or parse(external_config.get('declared_at'))
        if since and now - since > ABSENT_LIMIT:
            days = (now - since).days
            warnings.append(f'Ổ sao lưu ngoài "{external_config.get("label", "")}" đã {days} ngày chưa nhận bản sao lưu '
                            '(vắng mặt hoặc lỗi). Cắm lại ổ và chạy KIEM_TRA.bat.')
        if state.get('external_error'):
            warnings.append('Chép ra ổ ngoài lỗi: ' + state['external_error'])
    if state.get('over_budget'):
        warnings.append(f'Bản sao lưu vượt ngân sách dung lượng: đã giữ tối thiểu {MIN_VERIFIED} bản đã kiểm, '
                        'chưa xóa được thêm. Dọn ổ đĩa hoặc báo người hỗ trợ tăng ngân sách (CLINIC_BACKUP_TOTAL_MB).')
    if state.get('cert_unreadable'):
        warnings.append('Không đọc được chứng chỉ HTTPS của máy chủ (thiếu hoặc hỏng). Bấm KIEM_TRA.bat và báo người hỗ trợ; '
                        'nếu còn khóa CA, bấm GIA_HAN_CHUNG_CHI.bat.')
    days = state.get('cert_days_left')
    if days is not None and days < CERT_WARNING_DAYS:
        warnings.append(f'Chứng chỉ HTTPS của máy chủ còn {days} ngày. Bấm đúp GIA_HAN_CHUNG_CHI.bat '
                        '(máy trạm không phải cài lại).')
    return warnings


def cert_days_left(cert_path, now):
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
        return (cert.not_valid_after_utc - now).days
    except (OSError, ValueError, ImportError):
        return None


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name('.' + path.name + '.tmp')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(pending, path)


def publish_alert(alert_file, warnings, now):
    if not alert_file:
        return
    alert_file = Path(alert_file)
    if not warnings:
        alert_file.unlink(missing_ok=True)
        return
    text = ['CẢNH BÁO SAO LƯU - PHÒNG KHÁM MINH ĐỨC', f'Thời điểm kiểm tra (UTC): {now.isoformat(timespec="minutes")}', '']
    text += ['- ' + w for w in warnings]
    text += ['', 'Việc cần làm: bấm đúp KIEM_TRA.bat trong thư mục C:\\MinhDuc\\deploy\\windows và gửi tệp kết quả cho người hỗ trợ.',
             'Tệp này tự biến mất khi sao lưu bình thường trở lại.']
    try:
        alert_file.write_text('\n'.join(text) + '\n', encoding='utf-8-sig', newline='\r\n')
    except OSError:
        pass
    if os.name == 'nt':
        # Built-in, signed Windows tool; message is ASCII-safe summary only.
        subprocess.run(['eventcreate', '/T', 'WARNING', '/ID', '100', '/L', 'APPLICATION', '/SO', 'MinhDucSaoLuu',
                        '/D', 'Minh Duc: sao luu can kiem tra. Xem tep canh bao tren Desktop.'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


VERIFIED_SUFFIX = '.verified'
MIN_VERIFIED = 3


def list_backups(directory):
    """Backups newest first, with size and whether this job verified them (sidecar)."""
    items = []
    for path in Path(directory).glob('minhduc-*.mdbackup'):
        stat = path.stat()
        marker = path.with_name(path.name + VERIFIED_SUFFIX)
        verified = False
        if marker.exists():
            try:
                verified = json.loads(marker.read_text(encoding='utf-8')).get('size') == stat.st_size
            except (OSError, ValueError):
                verified = False
        items.append({'path': path, 'name': path.name, 'size': stat.st_size, 'mtime': stat.st_mtime, 'verified': verified})
    return sorted(items, key=lambda i: (i['mtime'], i['name']), reverse=True)


def plan_prune(items, keep, budget_bytes, min_verified=MIN_VERIFIED):
    """Pure retention decision, run only AFTER the newest backup (items[0]) is verified.

    Oldest first: drop backups beyond `keep`, then while the total exceeds the
    budget. Never drops the newest one and never lets the number of verified
    backups fall below `min_verified`. Returns (to_delete, still_over_budget).
    """
    remaining = list(items)
    deleted = []

    def drop_oldest():
        verified_left = sum(1 for i in remaining if i['verified'])
        for index in range(len(remaining) - 1, 0, -1):
            candidate = remaining[index]
            if candidate['verified'] and verified_left - 1 < min_verified:
                continue
            deleted.append(remaining.pop(index))
            return True
        return False

    while len(remaining) > keep and drop_oldest():
        pass
    while sum(i['size'] for i in remaining) > budget_bytes and drop_oldest():
        pass
    return deleted, sum(i['size'] for i in remaining) > budget_bytes


def external_enabled(external_config):
    """External drive copies are an opt-in (hidden) option: off unless clinic.env says 1."""
    return bool(external_config) and os.environ.get('CLINIC_EXTERNAL_BACKUP', '0') == '1'


def _error_text(error):
    return f'{type(error).__name__}: {str(error).splitlines()[0] if str(error) else ""}'[:300]


def run(args, now=None):
    from scripts.backup_lan import backup, unpack_verified, copy_offsite, checksum
    from app.resources import LIMITS
    now = now or now_utc()
    directory = Path(args.directory)
    state_path = Path(args.state)
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    external = None
    if args.external_config and Path(args.external_config).exists():
        external = json.loads(Path(args.external_config).read_text(encoding='utf-8'))
    if not external_enabled(external):
        external = None
    code = 0
    target = None
    for key in ('external_error', 'over_budget', 'pruned'):
        state.pop(key, None)
    try:
        # 1. New backup WITHOUT deleting anything and without the budget stop.
        target = backup(directory, args.key, prune=False, enforce_budget=False)
        # 2. Verify it (decrypt + SHA-256 of every file). A bad file is removed; old ones stay.
        verify_root = Path(os.environ.get('CLINIC_DATA_DIR', str(directory.parent)))
        try:
            with tempfile.TemporaryDirectory(prefix='.verify-', dir=verify_root) as temp:
                manifest = unpack_verified(target, args.key, Path(temp))
        except Exception as error:
            target.unlink(missing_ok=True)
            raise RuntimeError('Bản sao lưu mới không kiểm được nên đã xóa bản lỗi; không xóa bản cũ nào. '
                               + _error_text(error)) from error
        marker = {'size': target.stat().st_size, 'sha256': checksum(target), 'verified_at': now.isoformat(),
                  'files': len(manifest['files'])}
        target.with_name(target.name + VERIFIED_SUFFIX).write_text(json.dumps(marker), encoding='utf-8')
        state.update(last_success_utc=now.isoformat(), last_file=target.name,
                     last_size_bytes=target.stat().st_size, last_verified_files=len(manifest['files']))
        state.pop('last_error', None)
        # 3. Only now: retention (CLINIC_BACKUP_KEEP) and size budget, keeping >= 3 verified.
        keep = int(os.getenv('CLINIC_BACKUP_KEEP', '14'))
        to_delete, over = plan_prune(list_backups(directory), keep, LIMITS.backup_total_bytes)
        for item in to_delete:
            item['path'].unlink(missing_ok=True)
            item['path'].with_name(item['name'] + VERIFIED_SUFFIX).unlink(missing_ok=True)
        state['pruned'] = [i['name'] for i in to_delete]
        if over:
            state['over_budget'] = True
    except Exception as error:  # report every failure on the Desktop and Event Log
        state['last_error'] = _error_text(error) if not isinstance(error, RuntimeError) else str(error)[:400]
        state['last_failure_utc'] = now.isoformat()
        code = 1
    items = list_backups(directory)
    state['backup_count'] = len(items)
    state['verified_count'] = sum(1 for i in items if i['verified'])
    if external and code == 0:
        folder = find_external(candidate_roots(), external['id'], os.environ.get('CLINIC_DATA_DIR', args.directory))
        if folder is None:
            state['external_present'] = False
        else:
            state['external_present'] = True
            try:
                copy_offsite(target, folder)
                keep = int(os.getenv('CLINIC_OFFSITE_KEEP', '30'))
                for old in sorted(folder.glob('minhduc-*.mdbackup'), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]:
                    old.unlink()
                state['external_last_copy_utc'] = now.isoformat()
            except Exception as error:
                state['external_error'] = _error_text(error)
    if os.environ.get('CLINIC_TLS_CERT'):
        state['cert_days_left'] = cert_days_left(os.environ['CLINIC_TLS_CERT'], now)
        state['cert_unreadable'] = state['cert_days_left'] is None
    state['last_run_utc'] = now.isoformat()
    warnings = evaluate(state, external, now)
    state['warnings'] = warnings
    write_json(state_path, state)
    publish_alert(args.alert_file, warnings, now)
    for line in warnings:
        print('CANH BAO:', line)
    if code == 0:
        print('Sao luu va kiem tra ban sao luu: DAT', state['last_file'])
        if warnings:
            code = 3
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--external-config')
    parser.add_argument('--alert-file')
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
