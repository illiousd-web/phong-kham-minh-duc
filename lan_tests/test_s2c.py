"""PostgreSQL parity for immutable content-bound signatures."""
import pytest
from app.database import db
from tests.s2c_cases import (check_signing, check_content_signatures, check_name_content,
                            check_unprinted_changes, check_stale_read_cannot_invalidate_new_signature,
                            document, signature_image, sign_current)
from .conftest import IDS, PASSWORDS, SERVICE, URL


@pytest.mark.parametrize('kind', ['rx','order','lab','clinical_rx','lab_report'])
def test_signing(clients, kind):
    check_signing(clients, IDS, db, SERVICE, PASSWORDS['doctor'], kind)


@pytest.mark.parametrize('kind', ['rx','order','lab','clinical_rx','lab_report'])
def test_content_signature(clients, kind):
    check_content_signatures(clients, IDS, db, SERVICE, PASSWORDS['doctor'], kind)


@pytest.mark.parametrize('kind', ['rx','order','lab','clinical_rx','lab_report'])
def test_user_names(clients, kind):
    check_name_content(clients, IDS, db, SERVICE, PASSWORDS['doctor'], kind)


def test_unprinted_lab(clients):
    check_unprinted_changes(clients, IDS, db, SERVICE, PASSWORDS['doctor'])


def test_stale_read(clients):
    check_stale_read_cannot_invalidate_new_signature(clients, IDS, db, SERVICE, PASSWORDS['doctor'])


def test_immutable_runtime_role_and_owner(clients):
    import psycopg
    from pathlib import Path
    _, rid, _, _ = document(clients, IDS, db, SERVICE, 'rx')
    assert clients['admin'].put(f'/api/users/{IDS["doctor"]}/signature', files={'file':('fake.png',signature_image(),'image/png')}).status_code == 200
    sign_current(clients['doctor'], 'rx', rid, PASSWORDS['doctor'])
    with psycopg.connect(URL, autocommit=True) as c:
        assert {row[0] for row in c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 's2c_%'")} == {'s2c_signature_guard'}
        sid = c.execute('SELECT id FROM document_signatures ORDER BY id DESC LIMIT 1').fetchone()[0]
        existed = c.execute("SELECT 1 FROM pg_roles WHERE rolname='clinic_app'").fetchone()
        if not existed:
            c.execute('CREATE ROLE clinic_app NOLOGIN')
        try:
            c.execute(Path('deploy/postgresql-roles.sql').read_text().replace('DATABASE minhduc','DATABASE '+c.info.dbname))
            for runtime in (False, True):
                if runtime:
                    c.execute('SET ROLE clinic_app')
                for statement in ('UPDATE document_signatures SET username=username WHERE id=%s','DELETE FROM document_signatures WHERE id=%s',
                                  'INSERT INTO document_signatures SELECT * FROM document_signatures WHERE id=%s ON CONFLICT(id) DO UPDATE SET username=EXCLUDED.username'):
                    with pytest.raises(psycopg.Error) as error:
                        c.execute(statement, (sid,))
                    assert error.value.sqlstate in ('42501', 'P0001')
                if runtime:
                    with pytest.raises(psycopg.Error) as error:
                        c.execute('TRUNCATE document_signatures')
                    assert error.value.sqlstate == '42501'
        finally:
            c.execute('RESET ROLE')
            if not existed:
                c.execute('DROP OWNED BY clinic_app')
                c.execute('DROP ROLE clinic_app')
    from app.s2c_migration import migrate_s2c
    with db(True) as c:
        with pytest.raises(ValueError, match='đã có bản ký'):
            migrate_s2c(c, postgres=True, down=True)
        assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 17


@pytest.mark.parametrize('legacy', ['version', 'column'])
def test_migration_rejects_legacy_s2c_postgres(legacy):
    import psycopg
    from app.database import PGConnection
    from app.s2c_migration import migrate_s2c
    with psycopg.connect(URL) as connection:
        if legacy == 'version':
            connection.execute('INSERT INTO schema_migrations(version) VALUES(18)')
        else:
            connection.execute('ALTER TABLE document_signatures ADD COLUMN invalidated INTEGER')
        with pytest.raises(ValueError, match='CSDL đã chạy bản thử S2c cũ, cần khôi phục bản sao lưu trước S2c'):
            migrate_s2c(PGConnection(connection), postgres=True)
        connection.rollback()
