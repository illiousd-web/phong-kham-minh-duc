from .conftest import IDS,SERVICE
from app.database import db
from tests.m5_cases import check_m5


def test_m5_lifecycle_snapshot_adjustment_print_permissions_and_queue(clients):
    check_m5(clients,IDS,db,SERVICE)


def test_m5_populated_snapshot_survives_encrypted_backup_restore(clients,tmp_path):
    import secrets,psycopg
    from psycopg import sql
    from urllib.parse import urlsplit,urlunsplit
    from .conftest import URL
    from scripts.backup_lan import backup,restore
    from app.m5_migration import TABLES
    check_m5(clients,IDS,db,SERVICE)
    key=tmp_path/'fake-test.key';key.write_bytes(secrets.token_bytes(32))
    name='m5_restore_'+secrets.token_hex(6);target=urlunsplit(urlsplit(URL)._replace(path='/'+name))
    with psycopg.connect(URL,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(URL) as c:
            before={t:c.execute('SELECT * FROM '+t+' ORDER BY '+('service_id,test_id' if t=='lab_service_tests' else 'id')).fetchall() for t in TABLES}
            assert c.execute("SELECT COUNT(*) FROM lab_reports WHERE status='approved'").fetchone()[0]>0
        path=backup(tmp_path/'backups',key);restore(path,key,target,tmp_path/'restored-attachments')
        with psycopg.connect(target) as c:
            after={t:c.execute('SELECT * FROM '+t+' ORDER BY '+('service_id,test_id' if t=='lab_service_tests' else 'id')).fetchall() for t in TABLES}
        assert after==before
    finally:
        with psycopg.connect(URL,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def test_m5_upgrade_main_schema_8_preserves_legacy_results_and_money():
    import secrets,psycopg
    from psycopg import sql
    from urllib.parse import urlsplit,urlunsplit
    from pathlib import Path
    from .conftest import URL
    from app.database import PGConnection,record_factory
    from app.migrations import migrate_v050
    from app.manual_price_migration import migrate_manual_prices
    from app.m0_migration import migrate_m0
    from app.administrative_migration import migrate_administrative
    from app.patient_catalog import migrate_public_catalog
    from app.m6_migration import migrate_m6
    from app.m5_migration import migrate_m5
    name='m5_upgrade_'+secrets.token_hex(6);target=urlunsplit(urlsplit(URL)._replace(path='/'+name))
    with psycopg.connect(URL,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(target,row_factory=record_factory) as connection:
            connection.execute((Path(__file__).resolve().parents[1]/'schema.postgresql.sql').read_text())
            c=PGConnection(connection)
            migrate_v050(c,postgres=True);migrate_manual_prices(c,postgres=True);migrate_m0(c);migrate_administrative(c);migrate_public_catalog(c);migrate_m6(c,postgres=True)
            c.execute("INSERT INTO users(username,full_name,salt,password_hash) VALUES('fake','Nhân viên giả lập','fake','fake')")
            c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES('FAKE','Người bệnh cũ giả lập','Nữ','2026-01-01T00:00:00+00:00')")
            c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(1,1,1,'2026-01-01T00:00:00+00:00')")
            c.execute("INSERT INTO orders(visit_id,category,name,status,requested_by,result_text,file_name,file_key,created_at) VALUES(1,'lab','Chỉ định cũ giả lập','approved',1,'Kết quả chữ cũ giả lập','fake.pdf','fake-key.pdf','2026-01-01T00:00:00+00:00')")
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(1,'Phí giả lập',12345,'2026-01-01T00:00:00+00:00')")
            tables=[x['tablename'] for x in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'schema_migrations' ORDER BY tablename")]
            def contents():return {t:sorted([__import__('json').dumps(dict(x),sort_keys=True,default=str) for x in c.execute('SELECT * FROM '+t)]) for t in tables}
            before=contents();migrate_m5(c,postgres=True);migrate_m5(c,postgres=True)
            assert contents()==before
            assert c.execute('SELECT 1 FROM schema_migrations WHERE version=9').fetchone()
            assert c.execute('SELECT COUNT(*) FROM lab_reference_ranges').fetchone()[0]==0
    finally:
        with psycopg.connect(URL,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def test_m5_closed_correction_rounding_snapshot_audit_and_print(clients):
    from tests.m5_revision_cases import check_closed_correction
    check_closed_correction(clients,IDS,db,SERVICE)


def test_m5_cancelled_visit_blocks_all_result_writes(clients):
    from tests.m5_revision_cases import check_cancelled_writes
    check_cancelled_writes(clients,IDS,db,SERVICE)


def test_m5_import_requires_issued_preview_of_exact_file(clients):
    from tests.m5_revision_cases import check_preview_gate
    check_preview_gate(clients)
