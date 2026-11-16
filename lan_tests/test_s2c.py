"""PostgreSQL parity for password-confirmed S2c signing and invalidation triggers."""
import pytest
from app.database import db
from tests.s2c_cases import check_signing
from .conftest import IDS, PASSWORDS, SERVICE


@pytest.mark.parametrize('kind', ['rx', 'order', 'lab', 'clinical_rx', 'lab_report'])
def test_s2c_signatures_with_postgres(clients, kind):
    check_signing(clients, IDS, db, SERVICE, PASSWORDS['doctor'], kind)


def test_scoped_and_immutable_signature_as_clinic_app(clients):
    import psycopg
    from pathlib import Path
    from app.database import PGConnection, record_factory
    from app.document_signatures import load_document, valid_signature
    from copy import deepcopy
    from .conftest import URL
    from tests.s2c_cases import check_scoped_signature
    sid = check_scoped_signature(clients, IDS, db, SERVICE, PASSWORDS['doctor'])
    with psycopg.connect(URL, autocommit=True, row_factory=record_factory) as c:
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname='clinic_app'").fetchone()
        if not exists:
            c.execute('CREATE ROLE clinic_app NOLOGIN')
        try:
            for statement in ("UPDATE document_signatures SET username=username WHERE id=%s",
                              "DELETE FROM document_signatures WHERE id=%s",
                              "UPDATE document_signatures SET invalidated=0 WHERE id=%s"):
                with pytest.raises(psycopg.Error):
                    c.execute(statement, (sid,))
            clone = c.execute("INSERT INTO document_signatures(document_kind,document_id,visit_id,signed_by,signed_at,content_hash,image,username) SELECT document_kind,document_id,visit_id,signed_by,signed_at,content_hash,image,username FROM document_signatures WHERE id=%s RETURNING id", (sid,)).fetchone()[0]
            rid = c.execute('SELECT document_id FROM document_signatures WHERE id=%s', (sid,)).fetchone()[0]
            endpoint = f'/api/document-signatures/rx/{rid}'
            state = clients['doctor'].get(endpoint).json()
            assert clients['doctor'].post(endpoint, json={'password':PASSWORDS['doctor'], 'content_hash':state['content_hash']}).status_code == 200
            grants = Path('deploy/postgresql-roles.sql').read_text().replace('DATABASE minhduc', 'DATABASE '+c.info.dbname)
            c.execute(grants)
            c.execute('SET ROLE clinic_app')
            assert c.execute('UPDATE document_signatures SET invalidated=1 WHERE id=%s RETURNING invalidated', (clone,)).fetchone()[0] == 1
            access = PGConnection(c, operational=True)
            model = deepcopy(load_document(access, 'rx', rid)['models'][0])
            model['diagnosis'] += ' thay đổi giả lập'
            assert valid_signature(access, 'rx', rid, models=[model]) is None
            assert c.execute("SELECT invalidated FROM document_signatures WHERE document_kind='rx' AND document_id=%s ORDER BY id DESC LIMIT 1", (rid,)).fetchone()[0] == 1
            for sql in ("UPDATE document_signatures SET username='gia mao' WHERE id=%s",
                        "UPDATE document_signatures SET username=username WHERE id=%s",
                        'DELETE FROM document_signatures WHERE id=%s',
                        'UPDATE document_signatures SET invalidated=0 WHERE id=%s'):
                with pytest.raises(psycopg.Error):
                    c.execute(sql, (sid,))
        finally:
            c.execute('RESET ROLE')
            if not exists:
                c.execute('DROP OWNED BY clinic_app')
                c.execute('DROP ROLE clinic_app')


def test_postgres_018_upgrade_and_downgrade_restores_017():
    import psycopg
    from app.database import PGConnection
    from app.s2c_migration_018 import migrate_018
    from .conftest import URL
    with psycopg.connect(URL) as connection:
        c = PGConnection(connection)
        if connection.execute('SELECT 1 FROM document_signatures LIMIT 1').fetchone():
            with pytest.raises(ValueError, match='đã có bản ký'):
                migrate_018(c, postgres=True, down=True)
        from tests.s2c_cases import empty_signature_evidence_for_rollback
        empty_signature_evidence_for_rollback(connection, postgres=True)
        evidence = connection.execute('SELECT id,invalidated,content_hash,image FROM document_signatures ORDER BY id').fetchall()
        migrate_018(c, postgres=True, down=True)
        old = connection.execute("SELECT pg_get_functiondef('s2c_orders_insert()'::regprocedure)").fetchone()[0]
        assert 'visit_id' in old
        migrate_018(c, postgres=True)
        new = connection.execute("SELECT pg_get_functiondef('s2c_orders_insert()'::regprocedure)").fetchone()[0]
        assert 'document_kind' in new
        assert connection.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 18
        assert connection.execute('SELECT id,invalidated,content_hash,image FROM document_signatures ORDER BY id').fetchall() == evidence
        migrate_018(c, postgres=True, down=True)
        assert connection.execute("SELECT pg_get_functiondef('s2c_orders_insert()'::regprocedure)").fetchone()[0] == old
        connection.rollback()


def test_postgres_order_change_invalidates_only_its_own_documents(clients):
    from tests.s2c_cases import check_order_invalidation_scope
    check_order_invalidation_scope(clients, IDS, db, SERVICE, PASSWORDS['doctor'])


def test_postgres_permanent_invalidation_api(clients):
    from tests.s2c_cases import check_permanent_invalidation
    check_permanent_invalidation(clients, IDS, db, SERVICE, PASSWORDS['doctor'])


def test_postgres_mismatched_hash_invalidates_in_access_transaction(clients):
    from tests.s2c_cases import check_mismatched_hash_invalidates_in_access_transaction
    check_mismatched_hash_invalidates_in_access_transaction(clients, IDS, db, SERVICE, PASSWORDS['doctor'])


@pytest.mark.parametrize('field', ['printed_name', 'printed_title', 'full_name'])
def test_postgres_printed_user_fields_invalidate_permanently(clients, field):
    from tests.s2c_cases import check_user_field_invalidation
    check_user_field_invalidation(clients, IDS, db, SERVICE, PASSWORDS['doctor'], field)


def test_postgres_018_rollback_and_cli_refuse_real_signature(clients, monkeypatch):
    import sys
    from scripts import manage
    from tests.s2c_cases import check_rollback_refuses_existing_signature
    check_rollback_refuses_existing_signature(clients, IDS, db, SERVICE, PASSWORDS['doctor'])
    monkeypatch.setattr(sys, 'argv', ['manage', 'rollback-s2c-018'])
    with pytest.raises(ValueError, match='đã có bản ký'):
        manage.main()
    with db() as c:
        assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 18


def test_postgres_other_user_printed_name_invalidates_signature(clients):
    from tests.s2c_cases import check_user_field_invalidation
    check_user_field_invalidation(clients, IDS, db, SERVICE, PASSWORDS['doctor'], 'printed_title', 'doctor2')


def test_postgres_order_delete_invalidates_real_signature(clients):
    from tests.s2c_cases import check_order_delete_does_not_revive_signature
    check_order_delete_does_not_revive_signature(clients, IDS, db, SERVICE, PASSWORDS['doctor'])
