"""Daily backup job for the Windows server (Task Scheduler, 20:00).

backup -> authenticate/verify the new file -> optional copy to a declared
external drive -> status file + warnings. Old good backups are never removed
before a new one is verified; retention comes from CLINIC_BACKUP_KEEP /
CLINIC_OFFSITE_KEEP (30 each in the Windows installer configuration).

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
    return warnings


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
        alert_file.write_text('\r\n'.join(text) + '\r\n', encoding='utf-8-sig')
    except OSError:
        pass
    if os.name == 'nt':
        # Built-in, signed Windows tool; message is ASCII-safe summary only.
        subprocess.run(['eventcreate', '/T', 'WARNING', '/ID', '100', '/L', 'APPLICATION', '/SO', 'MinhDucSaoLuu',
                        '/D', 'Minh Duc: sao luu can kiem tra. Xem tep canh bao tren Desktop.'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def run(args, now=None):
    from scripts.backup_lan import backup, unpack_verified, copy_offsite
    now = now or now_utc()
    state_path = Path(args.state)
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    external = None
    if args.external_config and Path(args.external_config).exists():
        external = json.loads(Path(args.external_config).read_text(encoding='utf-8'))
    code = 0
    state.pop('external_error', None)
    try:
        target = backup(Path(args.directory), args.key)
        verify_root = Path(os.environ.get('CLINIC_DATA_DIR', str(Path(args.directory).parent)))
        with tempfile.TemporaryDirectory(prefix='.verify-', dir=verify_root) as temp:
            manifest = unpack_verified(target, args.key, Path(temp))
        state.update(last_success_utc=now.isoformat(), last_file=target.name,
                     last_size_bytes=target.stat().st_size, last_verified_files=len(manifest['files']))
        state.pop('last_error', None)
    except Exception as error:  # report every failure; keep old good backups
        state['last_error'] = f'{type(error).__name__}: {str(error).splitlines()[0] if str(error) else ""}'[:300]
        state['last_failure_utc'] = now.isoformat()
        code = 1
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
                state['external_error'] = f'{type(error).__name__}: {str(error).splitlines()[0] if str(error) else ""}'[:300]
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
