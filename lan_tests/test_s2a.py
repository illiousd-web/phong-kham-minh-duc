"""S2a PostgreSQL API, migration and encrypted-backup regression."""
import secrets

import psycopg
import pytest
from psycopg import sql

from app.database import PGConnection, record_factory
from app.s2a_migration import migrate_s2a
from tests.s2a_cases import PROFILE, check_pharmacy_allergies, check_profile_and_signatures, signature_image
from .conftest import IDS, SERVICE, URL, client_for, db
from .test_ui_settings_backup import _new_db, _drop


def test_postgres_pharmacy_allergies_and_private_signature_contracts(clients):
    nurse = client_for('nurse')
    try:
        check_pharmacy_allergies({**clients, 'nurse': nurse}, IDS, SERVICE)
        check_profile_and_signatures({**clients, 'nurse': nurse}, IDS, db)
    finally:
        nurse.close()


@pytest.mark.parametrize('data', ['empty', 'profile', 'signature'])
def test_postgres_migration_up_down_preserves_legacy_and_refuses_data(data):
    # Isolated transactional schema; rollback removes it without touching the live test schema.
    with psycopg.connect(URL, row_factory=record_factory) as connection:
        try:
            schema = 's2a_' + secrets.token_hex(8)
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            c = PGConnection(connection)
            c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
            c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,full_name TEXT)')
            c.execute("INSERT INTO users VALUES(1,'Nhân viên giả lập')")
            before = c.execute('SELECT * FROM users').fetchall()
            migrate_s2a(c, postgres=True)
            migrate_s2a(c, postgres=True)
            assert c.execute('SELECT * FROM users').fetchall() == before
            assert c.execute('SELECT COUNT(*) FROM clinic_profile').fetchone()[0] == 1
            if data == 'profile':
                c.execute('UPDATE clinic_profile SET name=?', (PROFILE['name'],))
            elif data == 'signature':
                c.execute('INSERT INTO user_signatures VALUES(?,?,?,?,?)', (1, signature_image(), 'image/png', '2026-11-15', 1))
            if data != 'empty':
                with pytest.raises(ValueError, match='Chưa quay lui S2a'):
                    migrate_s2a(c, postgres=True, down=True)
                assert c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone()
                assert c.execute('SELECT COUNT(*) FROM clinic_profile').fetchone()[0] == 1
                if data == 'signature':
                    assert bytes(c.execute('SELECT image FROM user_signatures').fetchone()[0]) == signature_image()
            else:
                migrate_s2a(c, postgres=True, down=True)
                migrate_s2a(c, postgres=True, down=True)
                assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone()
                assert c.execute('SELECT to_regclass(?)', (schema+'.user_signatures',)).fetchone()[0] is None
                assert c.execute('SELECT * FROM users').fetchall() == before
                migrate_s2a(c, postgres=True)
        finally:
            connection.rollback()


def test_encrypted_backup_restores_clinic_signature_and_audit(tmp_path, clients, monkeypatch):
    from app.main import FILES
    from scripts.backup_lan import backup, restore
    monkeypatch.setenv('CLINIC_UPLOAD_DIR', str(FILES))
    admin = clients['admin']
    before = admin.get('/api/clinic-profile').json()
    payload = signature_image()
    name, target = _new_db()
    key = tmp_path/'backup.key'
    key.write_bytes(secrets.token_bytes(32))
    try:
        assert admin.put('/api/clinic-profile', json=PROFILE).status_code == 200
        assert admin.put(f'/api/users/{IDS["doctor"]}/signature', files={'file': ('fake.png', payload, 'image/png')}).status_code == 200
        source = backup(tmp_path/'backups', key)
        restore(source, key, target, tmp_path/'restored'/'attachments')
        with psycopg.connect(target) as c:
            assert c.execute('SELECT name FROM clinic_profile').fetchone()[0] == PROFILE['name']
            signature = c.execute('SELECT image,uploaded_by FROM user_signatures WHERE user_id=%s', (IDS['doctor'],)).fetchone()
            assert bytes(signature[0]) == payload and signature[1] == IDS['admin']
            assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='user_signature_changed'").fetchone()[0] > 0
    finally:
        _drop(name)
        admin.put('/api/clinic-profile', json=before)
        with db(True) as c:
            c.execute('DELETE FROM user_signatures WHERE user_id=?', (IDS['doctor'],))


def test_postgres_failed_upgrade_rolls_back_schema_and_version():
    with psycopg.connect(URL, row_factory=record_factory) as connection:
        try:
            schema = 's2a_failure_' + secrets.token_hex(8)
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
            c = PGConnection(connection)
            c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
            c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
            c.execute('CREATE TABLE user_signatures(existing TEXT)')
            with pytest.raises(psycopg.errors.DuplicateTable), connection.transaction():
                migrate_s2a(c, postgres=True)
            assert c.execute('SELECT to_regclass(?)', (schema+'.clinic_profile',)).fetchone()[0] is None
            assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone()
        finally:
            connection.rollback()
