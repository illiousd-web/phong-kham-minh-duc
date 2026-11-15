"""SQLite S2a up/down preserves legacy data; refuses destructive rollback."""
import sqlite3

import pytest

from app.s2a_migration import migrate_s2a
from tests.test_manual_price_migration import legacy, snapshot
from tests.s2a_cases import signature_image


def test_sqlite_migration_up_down_idempotence_and_legacy_data(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    legacy(path)
    before = snapshot(path)
    with sqlite3.connect(path) as c:
        c.execute('BEGIN IMMEDIATE')
        migrate_s2a(c)
        migrate_s2a(c)
        assert c.execute('SELECT * FROM clinic_profile').fetchall() == [(1, '', '', '', '', '')]
        assert c.execute('SELECT COUNT(*) FROM user_signatures').fetchone()[0] == 0
    assert snapshot(path) == before
    with sqlite3.connect(path) as c:
        c.execute('BEGIN IMMEDIATE')
        migrate_s2a(c, down=True)
        migrate_s2a(c, down=True)
        assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone()
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name IN ('clinic_profile','user_signatures')").fetchall()
    assert snapshot(path) == before
    with sqlite3.connect(path) as c:
        migrate_s2a(c)
        assert not c.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('data', ['profile', 'signature'])
def test_sqlite_down_refuses_data_and_preserves_tables(tmp_path, data):
    path = tmp_path/'legacy.sqlite3'
    legacy(path)
    with sqlite3.connect(path) as c:
        migrate_s2a(c)
        if data == 'profile':
            c.execute("UPDATE clinic_profile SET name='Phòng khám giả lập'")
        else:
            c.execute('INSERT INTO user_signatures VALUES(?,?,?,?,?)', (1, signature_image(), 'image/png', '2026-11-15', 1))
    with pytest.raises(ValueError, match='Chưa quay lui S2a'), sqlite3.connect(path) as c:
        c.execute('BEGIN IMMEDIATE')
        migrate_s2a(c, down=True)
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone()
        assert c.execute('SELECT COUNT(*) FROM clinic_profile').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM user_signatures').fetchone()[0] == (data == 'signature')


def test_sqlite_singleton_signature_fk_and_size_constraints(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    legacy(path)
    with sqlite3.connect(path) as c:
        c.execute('PRAGMA foreign_keys=ON')
        migrate_s2a(c)
        for statement, params in (
                ('INSERT INTO clinic_profile(id) VALUES(2)', ()),
                ('INSERT INTO user_signatures VALUES(?,?,?,?,?)', (999, b'x', 'image/png', 'now', 1)),
                ('INSERT INTO user_signatures VALUES(?,?,?,?,?)', (1, b'', 'image/png', 'now', 1)),
                ('INSERT INTO user_signatures VALUES(?,?,?,?,?)', (1, bytes(307201), 'image/png', 'now', 1))):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(statement, params)


def test_sqlite_upgrade_failure_is_atomic(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    legacy(path)
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE user_signatures(existing TEXT)')
    with pytest.raises(sqlite3.OperationalError), sqlite3.connect(path) as c:
        c.execute('BEGIN IMMEDIATE')
        migrate_s2a(c)
    with sqlite3.connect(path) as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='clinic_profile'").fetchone()
        assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone()
