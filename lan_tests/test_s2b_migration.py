"""Actual PostgreSQL 016 upgrade/downgrade with legacy stock and immutability."""
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
import pytest

from app.database import PGConnection, record_factory
from app.s2b_migration import migrate_s2b, restore_s2b_function_acl
from tests.test_s2b_migration import legacy, old_snapshot
from .test_v050_migration import create_db, drop_db
from .conftest import SOURCE

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_016_up_down_legacy_and_immutable():
    name = 's2b_migration_' + secrets.token_hex(5)
    url = create_db(name)
    try:
        with psycopg.connect(url, row_factory=record_factory) as raw:
            raw.execute((ROOT/'schema.postgresql.sql').read_text())
            c = PGConnection(raw)
            legacy(c)
            before = old_snapshot(c)
            migrate_s2b(c, postgres=True)
            migrate_s2b(c, postgres=True)
            assert old_snapshot(c) == before
            assert tuple(raw.execute('SELECT quantity,unit_cost,vat_rate,receipt_id FROM stock_lots').fetchone().values()) == (19, None, None, None)
            migrate_s2b(c, postgres=True, down=True)
            migrate_s2b(c, postgres=True, down=True)
            assert old_snapshot(c) == before
            migrate_s2b(c, postgres=True)
            raw.execute("INSERT INTO stock_receipts(document_no,created_by,created_at) VALUES('PN-2026-0001',1,'2026-11-15')")
            raw.execute("INSERT INTO stock_issues(document_no,reason,purpose,created_by,created_at) VALUES('PX-2026-0001','internal','Giả lập',1,'2026-11-15')")
            for table in ('stock_receipts', 'stock_issues', 'stock_movements'):
                for statement in (f'UPDATE {table} SET id=id', f'DELETE FROM {table}', f'TRUNCATE {table} CASCADE'):
                    with pytest.raises(psycopg.errors.CheckViolation):
                        with raw.transaction():
                            raw.execute(statement)
            with pytest.raises(ValueError, match='Chưa quay lui S2b'):
                migrate_s2b(c, postgres=True, down=True)
    finally:
        drop_db(name)


def schema_snapshot(raw):
    """Inspect real definitions/ACLs and visible column order; never replace fingerprint()."""
    queries = {
        'tables': """SELECT r.relname,r.relkind,pg_get_userbyid(r.relowner),r.relacl::text
            FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace
            WHERE n.nspname='public' AND r.relkind IN ('r','v','m','S') ORDER BY 1""",
        'columns': """SELECT r.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
            a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),a.attacl::text
            FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=r.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE n.nspname='public' AND r.relkind IN ('r','v','m') AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY r.relname,a.attnum""",
        'constraints': """SELECT r.relname,c.conname,pg_get_constraintdef(c.oid)
            FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid
            JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='public' ORDER BY 1,2""",
        'triggers': """SELECT r.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled
            FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=r.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2""",
        'functions': """SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid),
            pg_get_userbyid(p.proowner),p.proacl::text
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prokind IN ('f','p') ORDER BY 1""",
        'indexes': "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2",
        'sequences': """SELECT sequencename,sequenceowner,data_type,start_value,min_value,max_value,
            increment_by,cycle,cache_size FROM pg_sequences WHERE schemaname='public' ORDER BY 1""",
        'versions': 'SELECT version FROM schema_migrations ORDER BY version',
    }
    return {key: [tuple(row.values()) if isinstance(row, dict) else tuple(row) for row in raw.execute(query)]
            for key, query in queries.items()}


def stock_sequence_values(raw):
    names = raw.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' AND sequencename LIKE 'stock_%' ORDER BY 1").fetchall()
    return {row[0]: tuple(raw.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(row[0]))).fetchone()) for row in names}


def migration_database(monkeypatch, *, before_016=False):
    from app import database, s2b_migration
    name = 's2b_schema_' + secrets.token_hex(5)
    url = create_db(name)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(database, 'DATABASE_URL', url)
            if before_016:
                patch.setattr(s2b_migration, 'migrate_s2b', lambda *args, **kwargs: None)
            database.migrate()
        return name, url
    except BaseException:
        drop_db(name)
        raise


def test_postgres_016_down_restores_full_schema_and_s1_definitions(monkeypatch):
    name, url = migration_database(monkeypatch, before_016=True)
    try:
        with psycopg.connect(url, row_factory=record_factory) as raw:
            c = PGConnection(raw)
            legacy(c)
            before, values = schema_snapshot(raw), old_snapshot(c)
            assert len([r for r in before['functions'] if r[0].startswith('s1_')]) >= 6
            migrate_s2b(c, postgres=True)
            during = schema_snapshot(raw)
            assert [r for r in during['triggers'] if r[1].startswith('s1_')] == [r for r in before['triggers'] if r[1].startswith('s1_')]
            assert [r for r in during['functions'] if r[0].startswith('s1_')] == [r for r in before['functions'] if r[0].startswith('s1_')]
            migrate_s2b(c, postgres=True, down=True)
            restore_s2b_function_acl(c)
            after = schema_snapshot(raw)
            for component in before:
                assert after[component] == before[component], component
            assert old_snapshot(c) == values
    finally:
        drop_db(name)


def test_postgres_016_backup_restore_keeps_schema_acl_sequences_and_stock(tmp_path, monkeypatch, capsys):
    import json
    import subprocess
    import os
    import shutil
    from scripts import backup_lan, install_db
    name, url = migration_database(monkeypatch)
    target_name = 's2b_restore_' + secrets.token_hex(5)
    target = create_db(target_name)
    runtime = 's2b_restore_runtime_' + secrets.token_hex(5)
    with psycopg.connect(SOURCE, autocommit=True) as raw:
        raw.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(runtime)))
    try:
        with psycopg.connect(url, row_factory=record_factory) as raw:
            c = PGConnection(raw)
            legacy(c)
            raw.execute("INSERT INTO stock_receipts(document_no,created_by,created_at) VALUES('PN-2026-0007',1,'2026-11-15')")
            raw.execute("INSERT INTO stock_issues(document_no,reason,purpose,created_by,created_at) VALUES('PX-2026-0009','internal','Giả lập',1,'2026-11-15')")
            raw.execute("INSERT INTO stock_document_sequences VALUES('PN',2026,7),('PX',2026,9)")
            raw.execute("INSERT INTO stock_lots(id,medicine_id,lot_number,expiry_date,quantity,unit_cost,vat_rate,receipt_id) VALUES(2,1,'S2B-RESTORE','2029-01-01',4,1300,5,1)")
            raw.execute("INSERT INTO stock_movements(id,stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost,vat_rate,receipt_id) VALUES(3,2,'receipt',5,1,'2026-11-15',1300,5,1)")
            raw.execute("INSERT INTO stock_movements(id,stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost,issue_id) VALUES(4,2,'issue',1,1,'2026-11-15',1300,1)")
            raw.execute("SELECT setval(pg_get_serial_sequence('stock_lots','id'),2)")
            raw.execute("SELECT setval(pg_get_serial_sequence('stock_movements','id'),4)")
        install_db.grant(url, runtime, name)
        tables = ('stock_receipts', 'stock_issues', 'stock_document_sequences', 'stock_lots', 'stock_movements')
        with psycopg.connect(url) as raw:
            assert not raw.execute("SELECT has_function_privilege(%s,'public.s2b_stock_immutable()','EXECUTE')", (runtime,)).fetchone()[0]
            before = schema_snapshot(raw)
            data = {t: raw.execute(f'SELECT * FROM {t} ORDER BY 1,2').fetchall() for t in tables}
            counters = stock_sequence_values(raw)
            audit_count = raw.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
        fingerprint = install_db.fingerprint(url)
        uploads = tmp_path/'source-files'
        uploads.mkdir()
        (uploads/'gia-lap.pdf').write_bytes(b'%PDF-1.4 fake')
        key = tmp_path/'backup.key'
        key.write_bytes(secrets.token_bytes(32))
        monkeypatch.setattr(backup_lan, 'DATABASE_URL', url)
        monkeypatch.setenv('CLINIC_UPLOAD_DIR', str(uploads))
        backup = backup_lan.backup(tmp_path/'backups', key)
        unpacked = tmp_path/'unpacked'
        unpacked.mkdir()
        backup_lan.unpack_verified(backup, key, unpacked)
        # Use the actual bin directory selected by backup(), including Debian pg_wrapper.
        import re
        tool_env = backup_lan.pg_env(url)
        dump_path = shutil.which(os.getenv('CLINIC_PG_DUMP', 'pg_dump'))
        assert dump_path, 'Không tìm thấy pg_dump của luồng sao lưu'
        dump_tool = Path(dump_path).absolute()
        dump_version = subprocess.run([str(dump_tool), '--version'], env=tool_env, check=True,
                                      capture_output=True, text=True).stdout
        version = re.search(r'\d+\.\d+', dump_version).group()
        if dump_tool.resolve().name == 'pg_wrapper':
            dump_tool = Path('/usr/lib/postgresql')/version.split('.')[0]/'bin/pg_dump'
        assert dump_tool.is_file(), f'Không tìm thấy pg_dump thực: {dump_tool}'
        restore_tool = dump_tool.with_name('pg_restore' + dump_tool.suffix)
        assert restore_tool.is_file(), f'Không có pg_restore cùng bộ với {dump_tool}'
        restore_version = subprocess.run([str(restore_tool), '--version'], env=tool_env, check=True,
                                         capture_output=True, text=True).stdout
        assert re.search(r'\d+\.\d+', restore_version).group() == version, (dump_version, restore_version)
        # Diagnose the old PATH invocation without using it to validate the archive.
        path_restore = shutil.which('pg_restore')
        if path_restore and Path(path_restore).resolve() != restore_tool.resolve():
            probe = subprocess.run([path_restore, '--list', str(unpacked/'database.dump')],
                                   env=tool_env, capture_output=True, text=True)
            if probe.returncode:
                with capsys.disabled():
                    print(f'Chẩn đoán pg_restore trên PATH: exit {probe.returncode}; stderr={probe.stderr}', flush=True)
        monkeypatch.setenv('CLINIC_PG_RESTORE', str(restore_tool))
        try:
            listing = subprocess.run([str(restore_tool), '--list', str(unpacked/'database.dump')],
                                     env=tool_env, check=True, capture_output=True, text=True).stdout
        except subprocess.CalledProcessError as error:
            pytest.fail(f'pg_restore --list exit {error.returncode}: {error.stderr}')
        for relation in ('stock_receipts', 'stock_issues', 'stock_document_sequences', 'stock_receipts_id_seq', 'stock_issues_id_seq'):
            assert relation in listing
        backup_lan.restore(backup, key, target, tmp_path/'restored-files')
        install_db.grant(target, runtime, target_name)
        with psycopg.connect(target) as raw:
            assert not raw.execute("SELECT has_function_privilege(%s,'public.s2b_stock_immutable()','EXECUTE')", (runtime,)).fetchone()[0]
            after = schema_snapshot(raw)
            actual = {t: raw.execute(f'SELECT * FROM {t} ORDER BY 1,2').fetchall() for t in tables}
            assert stock_sequence_values(raw) == counters
            # Restore deliberately appends one audit event; that counter is data, not schema.
            assert raw.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0] == audit_count + 1
            assert raw.execute('SELECT event FROM audit_log ORDER BY id DESC LIMIT 1').fetchone()[0] == 'backup_restored'
            for table in ('stock_receipts', 'stock_issues', 'stock_movements'):
                for statement in (f'UPDATE {table} SET id=id', f'DELETE FROM {table}', f'TRUNCATE {table} CASCADE'):
                    with pytest.raises(psycopg.errors.CheckViolation), raw.transaction():
                        raw.execute(statement)
        evidence = Path('test_evidence/s2b-review')
        evidence.mkdir(parents=True, exist_ok=True)
        differences = {component: {'before': before[component], 'after': after[component]}
                       for component in before if before[component] != after[component]}
        (evidence/'schema-restore-diff.json').write_text(json.dumps(differences, ensure_ascii=False, indent=2, default=str))
        for component in before:
            assert after[component] == before[component], (component, differences[component])
        assert actual == data
        assert install_db.fingerprint(target) == fingerprint
        assert (tmp_path/'restored-files/gia-lap.pdf').read_bytes() == (uploads/'gia-lap.pdf').read_bytes()
    finally:
        drop_db(name)
        drop_db(target_name)
        with psycopg.connect(SOURCE, autocommit=True) as raw:
            raw.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(runtime)))
