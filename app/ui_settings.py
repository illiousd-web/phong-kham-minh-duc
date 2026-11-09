"""Cài đặt hiển thị giao diện (bật/tắt chức năng phụ), lưu ở tệp JSON phía máy chủ.

Chỉ quyết định giao diện có hiện chức năng hay không. Các API nghiệp vụ vẫn
kiểm tra quyền như cũ, kể cả khi chức năng đang tắt trên giao diện.

Không thêm bảng CSDL. Tệp nằm trong thư mục con 'caidat' cạnh thư mục tệp đính
kèm (mặc định CLINIC_DATA_DIR/caidat/ui_settings.json; trên Windows chỉ thư mục
này cho tài khoản dịch vụ quyền ghi), nên đi cùng dữ liệu khi khôi phục sang thư
mục mới và đổi CLINIC_UPLOAD_DIR. Bản sao lưu LAN chứa tệp này (xem
scripts/backup_lan.py). Tệp thiếu hoặc hỏng: dùng mặc định và ghi cảnh báo.
Mỗi lần đổi được ghi vào audit_log.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, StrictBool

FILE_NAME = 'ui_settings.json'
FOLDER = 'caidat'
DEFAULTS = {
    'advance_payment': False,   # Ứng trước tiền
    'addendum': True,           # Phụ lục đính chính sau khóa hồ sơ
    'controlled_drugs': True,   # Thuốc kiểm soát đặc biệt
}
_lock = threading.Lock()
_warned: set = set()
log = logging.getLogger('clinic')


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    advance_payment: StrictBool | None = None
    addendum: StrictBool | None = None
    controlled_drugs: StrictBool | None = None


def settings_path(uploads: Path) -> Path:
    """CLINIC_UI_SETTINGS nếu có, nếu không thì <cha của thư mục đính kèm>/caidat/ui_settings.json."""
    override = os.environ.get('CLINIC_UI_SETTINGS')
    return Path(override).resolve() if override else (Path(uploads).resolve().parent / FOLDER / FILE_NAME)


def parse_settings(raw: bytes | str) -> dict:
    """Đọc nội dung tệp; ném ValueError nếu không phải đối tượng JSON hợp lệ."""
    stored = json.loads(raw)
    if not isinstance(stored, dict):
        raise ValueError('ui_settings.json không phải đối tượng JSON')
    result = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in stored:
            if not isinstance(stored[key], bool):
                raise ValueError(f'Giá trị {key} không phải true/false')
            result[key] = stored[key]
    return result


def _warn_once(path: Path, reason: str) -> None:
    key = (str(path), reason)
    if key not in _warned:
        _warned.add(key)
        log.warning('Cài đặt giao diện: %s (%s); đang dùng mặc định', reason, path)


def load_settings(path: Path) -> tuple[dict, str]:
    """Trả (cài đặt, nguồn). Nguồn: 'file', 'missing' hoặc 'invalid'."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        _warn_once(path, 'tệp cài đặt chưa có')
        return dict(DEFAULTS), 'missing'
    except OSError:
        _warn_once(path, 'không đọc được tệp cài đặt')
        return dict(DEFAULTS), 'invalid'
    try:
        values = parse_settings(raw)
    except ValueError:
        _warn_once(path, 'tệp cài đặt hỏng')
        return dict(DEFAULTS), 'invalid'
    _warned.discard((str(path), 'tệp cài đặt chưa có'))
    _warned.discard((str(path), 'tệp cài đặt hỏng'))
    return values, 'file'


def read_settings(path: Path) -> dict:
    return load_settings(path)[0]


def serialize(values: dict) -> bytes:
    return json.dumps({k: bool(values[k]) for k in DEFAULTS}, ensure_ascii=False, indent=1).encode('utf-8')


def prepare_settings(path: Path, values: dict) -> Path:
    """Ghi nội dung mới ra tệp tạm cùng thư mục (chưa thay tệp đang dùng)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.ui_settings.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(serialize(values))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return Path(tmp)


def write_settings(path: Path, values: dict) -> None:
    tmp = prepare_settings(path, values)
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def ensure_default_settings(path: Path) -> str:
    """Bộ cài gọi: tạo tệp mặc định nếu chưa có. Không sửa tệp đã có (kể cả hỏng: để KIEM_TRA báo)."""
    if path.exists():
        return 'exists'
    write_settings(path, DEFAULTS)
    return 'created'


def install_ui_settings(app, db, principal, require, audit, uploads: Path):
    path = settings_path(uploads)

    def answer(values, source):
        return {**values, 'source': source}

    @app.get('/api/ui-settings')
    def get_ui_settings(u=Depends(principal)):
        return answer(*load_settings(path))

    @app.put('/api/ui-settings')
    def put_ui_settings(data: SettingsInput, u=Depends(principal)):
        require(u, 'admin')
        changes = {k: v for k, v in data.model_dump().items() if v is not None}
        with _lock:
            current, source = load_settings(path)
            before = dict(current)
            current.update(changes)
            if current != before or source != 'file':
                diff = ', '.join(f'{k}={"bật" if current[k] else "tắt"}' for k in DEFAULTS if current[k] != before[k]) or 'ghi lại tệp cài đặt'
                # Nhất quán: tệp tạm -> nhật ký (commit) -> thay tệp. Nhật ký lỗi thì tệp không đổi.
                tmp = prepare_settings(path, current)
                try:
                    with db(True) as c:
                        audit(c, u, 'ui_settings_changed', 'ui_settings', None, diff)
                    os.replace(tmp, path)
                finally:
                    tmp.unlink(missing_ok=True)
        return answer(current, 'file')
