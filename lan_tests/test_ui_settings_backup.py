"""Cài đặt giao diện đi cùng bản sao lưu mã hóa và được khôi phục cùng dữ liệu."""
import json
import logging
import os
import secrets
import shutil
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

from .conftest import URL


def _new_db():
    name = 'clinic_restore_' + secrets.token_hex(6)
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    return name, urlunsplit(urlsplit(URL)._replace(path='/' + name))


def _drop(name):
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


def test_backup_restore_keeps_ui_settings_and_defaults_on_bad_file(tmp_path, clients, caplog):
    from scripts.backup_lan import backup, restore, unpack_verified
    from app.ui_settings import settings_path, load_settings, DEFAULTS
    if not shutil.which(os.getenv('CLINIC_PG_DUMP', 'pg_dump')):
        pytest.fail('Install PostgreSQL client tools to test real backup/restore')
    admin = clients['admin']
    live = settings_path(Path(os.environ['CLINIC_UPLOAD_DIR']))
    key = tmp_path / 'key'
    key.write_bytes(secrets.token_bytes(32))
    chosen = {'advance_payment': True, 'addendum': False, 'controlled_drugs': False}
    created = []
    try:
        assert admin.put('/api/ui-settings', json=chosen).json() == {**chosen, 'source': 'file'}
        good = backup(tmp_path / 'backups', key)
        verify = tmp_path / 'verify'
        verify.mkdir()
        manifest = unpack_verified(good, key, verify)
        assert 'ui_settings.json' in manifest['files'] and manifest['ui_settings_source'] == 'file'

        # Khôi phục sang CSDL và thư mục mới: cài đặt nằm đúng chỗ ứng dụng sẽ đọc.
        name, target = _new_db()
        created.append(name)
        uploads = tmp_path / 'restored' / 'attachments'
        restore(good, key, target, uploads)
        restored = settings_path(uploads)
        assert restored == tmp_path / 'restored' / 'ui_settings.json'
        assert load_settings(restored) == (chosen, 'file')

        # Không bao giờ ghi đè cài đặt đang có ở đích.
        name2, target2 = _new_db()
        created.append(name2)
        with pytest.raises(ValueError, match='settings destination already exists'):
            restore(good, key, target2, tmp_path / 'restored' / 'other-attachments')

        # Tệp hỏng: ứng dụng dùng mặc định, ghi cảnh báo; bản sao mới chứa mặc định.
        live.write_text('{hỏng', encoding='utf-8')
        with caplog.at_level(logging.WARNING, logger='clinic'):
            answer = admin.get('/api/ui-settings').json()
        assert answer == {**DEFAULTS, 'source': 'invalid'}
        assert any('tệp cài đặt hỏng' in r.getMessage() for r in caplog.records)
        bad = backup(tmp_path / 'backups', key)
        check = tmp_path / 'verify2'
        check.mkdir()
        assert unpack_verified(bad, key, check)['ui_settings_source'] == 'invalid'
        assert json.loads((check / 'ui_settings.json').read_text(encoding='utf-8')) == DEFAULTS

        # Tệp thiếu: cũng dùng mặc định.
        live.unlink()
        assert admin.get('/api/ui-settings').json() == {**DEFAULTS, 'source': 'missing'}
    finally:
        for name in created:
            _drop(name)
        live.unlink(missing_ok=True)
        admin.put('/api/ui-settings', json=DEFAULTS)
