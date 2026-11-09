"""Cài đặt hiển thị giao diện (bật/tắt chức năng phụ), lưu ở tệp JSON phía máy chủ.

Chỉ quyết định giao diện có hiện chức năng hay không. Các API nghiệp vụ vẫn
kiểm tra quyền như cũ, kể cả khi chức năng đang tắt trên giao diện.
Không thêm bảng CSDL: tệp nằm trong thư mục dữ liệu (CLINIC_DATA_DIR khi chạy
LAN, cạnh tệp SQLite khi chạy demo). Mỗi lần đổi được ghi vào audit_log.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, StrictBool

DEFAULTS = {
    'advance_payment': False,   # Ứng trước tiền
    'addendum': True,           # Phụ lục đính chính sau khóa hồ sơ
    'controlled_drugs': True,   # Thuốc kiểm soát đặc biệt
}
_lock = threading.Lock()


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    advance_payment: StrictBool | None = None
    addendum: StrictBool | None = None
    controlled_drugs: StrictBool | None = None


def settings_path(folder: Path) -> Path:
    return Path(os.environ.get('CLINIC_UI_SETTINGS', str(folder / 'ui_settings.json'))).resolve()


def read_settings(path: Path) -> dict:
    result = dict(DEFAULTS)
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return result
    if isinstance(stored, dict):
        for key in DEFAULTS:
            if isinstance(stored.get(key), bool):
                result[key] = stored[key]
    return result


def write_settings(path: Path, values: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.ui_settings.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(values, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install_ui_settings(app, db, principal, require, audit, folder: Path):
    path = settings_path(folder)

    @app.get('/api/ui-settings')
    def get_ui_settings(u=Depends(principal)):
        return read_settings(path)

    @app.put('/api/ui-settings')
    def put_ui_settings(data: SettingsInput, u=Depends(principal)):
        require(u, 'admin')
        changes = {k: v for k, v in data.model_dump().items() if v is not None}
        with _lock:
            current = read_settings(path)
            before = dict(current)
            current.update(changes)
            if current != before:
                write_settings(path, current)
                diff = ', '.join(f'{k}={"bật" if current[k] else "tắt"}' for k in DEFAULTS if current[k] != before[k])
                with db(True) as c:
                    audit(c, u, 'ui_settings_changed', 'ui_settings', None, diff)
        return current
