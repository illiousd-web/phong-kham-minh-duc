"""Daily backup job for the Windows server (Task Scheduler, 20:00).

backup -> authenticate/verify the new file -> optional copy to a declared
external drive -> status file + warnings. Old good backups are never removed
before a new one is verified; retention comes from CLINIC_BACKUP_KEEP (14 on the
server in the Windows installer configuration) and the CLINIC_BACKUP_TOTAL_MB
budget, always keeping at least 3 verified backups (all of them when fewer than 3
exist). "Verified" means the file's SHA-256 still equals the one recorded right after
the decrypt check; a mismatch marks the backup corrupt. When the disk is too full to
create the new backup, old ones (corrupt first, then oldest) are deleted only if that
frees enough space under the same floor; otherwise nothing is deleted and the job stops. The external drive copy is an
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
GIB = 1024 ** 3


def now_utc():
    return datetime.now(timezone.utc)


def parse(value):
    return datetime.fromisoformat(value) if value else None


def should_defer_catchup(state, now):
    from datetime import time
    local = now.astimezone(timezone(timedelta(hours=7)))
    start = time.fromisoformat(os.getenv('CLINIC_WORK_START', '07:00'))
    end = time.fromisoformat(os.getenv('CLINIC_WORK_END', '17:30'))
    current = local.time().replace(tzinfo=None)
    working = start <= current < end if start <= end else current >= start or current < end
    last = parse(state.get('last_success_utc'))
    return bool(working and last and now - last <= timedelta(hours=48))


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
    for name in state.get('corrupt') or []:
        warnings.append(f'Bản sao lưu {name} bị HỎNG: nội dung không còn khớp SHA-256 đã ghi lúc kiểm. '
                        'Bản này không được tính là bản đã kiểm và luôn bị xóa trước mọi bản tốt. '
                        'Báo người hỗ trợ kiểm tra ổ đĩa máy chủ.')
    if state.get('freed_for_space'):
        warnings.append(f'Ổ đĩa gần đầy: đã xóa {len(state["freed_for_space"])} bản sao lưu cũ để có chỗ tạo bản mới '
                        f'(vẫn giữ tối thiểu {MIN_VERIFIED} bản đã kiểm). Báo người hỗ trợ dọn ổ đĩa.')
    if state.get('over_budget'):
        warnings.append(f'Bản sao lưu vượt ngân sách dung lượng nhưng không xóa thêm được: phải giữ tối thiểu {MIN_VERIFIED} '
                        'bản đã kiểm (đang có ít hơn thì giữ tất cả). Báo người hỗ trợ dọn ổ đĩa hoặc tăng ngân sách '
                        '(CLINIC_BACKUP_TOTAL_MB).')
    if state.get('cert_unreadable'):
        warnings.append('Không đọc được chứng chỉ HTTPS của máy chủ (thiếu hoặc hỏng). Bấm đúp GIA_HAN_CHUNG_CHI.bat: '
                        'tự chuyển sang chế độ phục hồi, cấp chứng chỉ mới từ khóa CA hiện có (máy trạm không phải cài lại). '
                        'Nếu nó báo mất cả ca.key: gọi người hỗ trợ, phải cài lại CA cho mọi máy trạm.')
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


def _sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def list_backups(directory):
    """Backups newest first. 'verified' only when the file's ACTUAL SHA-256 equals the
    SHA-256 recorded in its .verified marker (written right after the decrypt check).
    A marker whose size or hash no longer matches means the file changed after it was
    checked: 'corrupt' (never counted as verified, deleted before any good backup)."""
    items = []
    for path in Path(directory).glob('minhduc-*.mdbackup'):
        stat = path.stat()
        marker = path.with_name(path.name + VERIFIED_SUFFIX)
        verified = corrupt = False
        if marker.exists():
            try:
                recorded = json.loads(marker.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                recorded = {}
            if recorded.get('sha256'):
                verified = recorded.get('size') == stat.st_size and _sha256(path) == recorded['sha256']
                corrupt = not verified
        items.append({'path': path, 'name': path.name, 'size': stat.st_size, 'mtime': stat.st_mtime,
                      'verified': verified, 'corrupt': corrupt})
    return sorted(items, key=lambda i: (i['mtime'], i['name']), reverse=True)


def _deletion_order(items, protect_newest):
    """Candidates to delete: corrupt backups first (oldest first), then every other backup
    oldest first. A corrupt backup is therefore never kept while a good one is removed."""
    pool = items[1:] if protect_newest else list(items)
    oldest_first = list(reversed(pool))
    return [i for i in oldest_first if i.get('corrupt')] + [i for i in oldest_first if not i.get('corrupt')]


def _can_drop(candidate, remaining, min_verified):
    """Keep at least `min_verified` verified backups; with fewer than that, keep them all."""
    if not candidate['verified']:
        return True
    return sum(1 for i in remaining if i['verified']) - 1 >= min_verified


def plan_prune(items, keep, budget_bytes, min_verified=MIN_VERIFIED):
    """Pure retention decision, run only AFTER the newest backup (items[0]) is verified.

    Drops (corrupt first, then oldest) backups beyond `keep`, then while the total
    exceeds the budget. Never drops the newest one; never lets the number of verified
    backups fall below `min_verified` (with fewer verified, none of them is dropped).
    Returns (to_delete, still_over_budget).
    """
    remaining = list(items)
    deleted = []

    def drop_one():
        for candidate in _deletion_order(remaining, protect_newest=True):
            if _can_drop(candidate, remaining, min_verified):
                remaining.remove(candidate)
                deleted.append(candidate)
                return True
        return False

    while len(remaining) > keep and drop_one():
        pass
    while sum(i['size'] for i in remaining) > budget_bytes and drop_one():
        pass
    return deleted, sum(i['size'] for i in remaining) > budget_bytes


def plan_space(items, deficit_bytes, min_verified=MIN_VERIFIED):
    """Disk too full to CREATE the new backup: which old backups to delete first.

    Same order and the same floor as plan_prune (corrupt first, then oldest; at least
    `min_verified` verified backups stay, all of them when fewer exist). Returns the list
    to delete, or None when even the allowed deletions would not free enough space:
    then nothing at all is deleted.
    """
    if deficit_bytes <= 0:
        return []
    remaining = list(items)
    chosen = []
    freed = 0
    for candidate in _deletion_order(remaining, protect_newest=False):
        if freed >= deficit_bytes:
            break
        if _can_drop(candidate, remaining, min_verified):
            remaining.remove(candidate)
            chosen.append(candidate)
            freed += candidate['size']
    return chosen if freed >= deficit_bytes else None


def disk_free(path):
    from app.storage import free_bytes
    return free_bytes(path)


def space_required(directory):
    from scripts.backup_lan import space_required as required
    return required(directory)


def _delete(item):
    item['path'].unlink(missing_ok=True)
    item['path'].with_name(item['name'] + VERIFIED_SUFFIX).unlink(missing_ok=True)


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
    if getattr(args, 'catchup', False) and should_defer_catchup(state, now):
        print('Sao lưu bù tạm hoãn trong giờ làm việc; lịch 20:00 tiếp tục chạy.')
        return 0
    external = None
    if args.external_config and Path(args.external_config).exists():
        external = json.loads(Path(args.external_config).read_text(encoding='utf-8'))
    if not external_enabled(external):
        external = None
    code = 0
    target = None
    items = None
    corrupt = set()
    for key in ('external_error', 'over_budget', 'pruned', 'freed_for_space', 'space_error'):
        state.pop(key, None)
    try:
        # 0. Disk too full for the new backup: delete old ones (corrupt first, then oldest)
        #    only if that frees enough while keeping >= 3 verified; otherwise stop, delete nothing.
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        need = space_required(directory)
        free = disk_free(directory)
        if free < need:
            listed = list_backups(directory)
            corrupt.update(i['name'] for i in listed if i['corrupt'])
            plan = plan_space(listed, need - free)
            if plan is None:
                state['space_error'] = True
                raise RuntimeError(
                    f'Ổ đĩa không đủ chỗ tạo bản sao lưu mới (cần {need / GIB:.1f} GB trống, còn {free / GIB:.1f} GB). '
                    f'Xóa bớt bản cũ vẫn không đủ mà phải giữ tối thiểu {MIN_VERIFIED} bản đã kiểm, nên KHÔNG xóa bản nào. '
                    'Báo người hỗ trợ dọn ổ đĩa; không tự xóa thư mục backups.')
            for item in plan:
                _delete(item)
            state['freed_for_space'] = [i['name'] for i in plan]
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
        listed = list_backups(directory)
        corrupt.update(i['name'] for i in listed if i['corrupt'])
        to_delete, over = plan_prune(listed, keep, LIMITS.backup_total_bytes)
        for item in to_delete:
            _delete(item)
        items = [i for i in listed if i not in to_delete]
        state['pruned'] = [i['name'] for i in to_delete]
        if over:
            state['over_budget'] = True
    except Exception as error:  # report every failure on the Desktop and Event Log
        state['last_error'] = _error_text(error) if not isinstance(error, RuntimeError) else str(error)[:400]
        state['last_failure_utc'] = now.isoformat()
        code = 1
    if items is None:
        items = list_backups(directory) if directory.exists() else []
    corrupt.update(i['name'] for i in items if i['corrupt'])
    state['backup_count'] = len(items)
    state['verified_count'] = sum(1 for i in items if i['verified'])
    # Every corrupt backup seen in this run (kept or already deleted first) is reported.
    state['corrupt'] = sorted(corrupt)
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
    schedule = parser.add_mutually_exclusive_group()
    schedule.add_argument('--daily', '--scheduled', dest='daily', action='store_true', help='Lịch 20:00, luôn chạy kể cả trong giờ làm việc')
    schedule.add_argument('--catchup', action='store_true', help='Chạy bù; hoãn trong giờ làm nếu bản tốt chưa quá 48 giờ')
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
