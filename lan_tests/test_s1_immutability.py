"""Direct runtime-role attacks must fail even outside application endpoints."""
import secrets
from pathlib import Path
import psycopg
from psycopg import sql
import pytest
from .conftest import URL, db, IDS


def test_runtime_role_cannot_change_locked_evidence(visit):
    with db(True) as c:
        c.execute("INSERT INTO drugs(name,name_key,strength_key) VALUES(?,?,?)", ('Giả lập bất biến', secrets.token_hex(8), ''))
        did = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO drugs(name,name_key,strength_key) VALUES(?,?,?)", ('Đích gộp giả lập', secrets.token_hex(8), ''))
        other_did = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO clinical_prescriptions(visit_id,doctor_id,status,snapshot,created_at) VALUES(?,?,'draft',NULL,'synthetic')", (visit, IDS['doctor']))
        rid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO clinical_prescription_items(prescription_id,drug_id,position,content) VALUES(?,?,1,'{}')", (rid,did))
        c.execute("UPDATE clinical_prescriptions SET status='locked',snapshot='{}' WHERE id=?", (rid,))
        c.execute("INSERT INTO prescription_outbox(prescription_id,schema_version,payload,created_at) VALUES(?,'1','{}','synthetic')",(rid,))
        c.execute("INSERT INTO orders(visit_id,category,name,requested_by,created_at) VALUES(?,'lab','Giả lập bất biến',?,'synthetic')",(visit,IDS['doctor']))
        oid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO lab_tests(code,name,abbreviation,group_name,result_type) VALUES(?,?,?,'other','number')",('S1-'+secrets.token_hex(8),'Chỉ số giả lập','S1'))
        tid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO lab_reports(order_id,created_at) VALUES(?,'synthetic')",(oid,))
        lab=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO lab_results(report_id,test_id,definition,value) VALUES(?,?,'{}','1')",(lab,tid))
        c.execute("UPDATE lab_reports SET status='approved',snapshot='{}' WHERE id=?",(lab,))
    role = 's1_app_' + secrets.token_hex(6)
    root = Path(__file__).resolve().parents[1]
    try:
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
            grants = (root/'deploy/postgresql-roles.sql').read_text().replace('clinic_app',role).replace('DATABASE minhduc','DATABASE '+c.info.dbname)
            c.execute(grants)
            c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            with pytest.raises(psycopg.Error):
                c.execute('UPDATE clinical_prescription_items SET drug_id=%s WHERE prescription_id=%s', (other_did, rid))
            for merge_from, merge_to in ((other_did, other_did), (did, did), (did, other_did)):
                with pytest.raises(psycopg.Error), c.transaction():
                    c.execute("SELECT set_config('clinic.merge_from', %s, true), set_config('clinic.merge_to', %s, true)", (str(merge_from), str(merge_to)))
                    c.execute('UPDATE clinical_prescription_items SET drug_id=%s WHERE prescription_id=%s', (other_did, rid))
            assert not c.execute("SELECT has_any_column_privilege(current_user, 'clinical_prescription_items', 'UPDATE')").fetchone()[0]
            # Caller-owned temporary context is rejected, never trusted or read as owner.
            c.execute('CREATE TEMP TABLE s1_merge_context(source_id integer,target_id integer)')
            c.execute('INSERT INTO s1_merge_context VALUES(%s,%s)', (did,other_did))
            with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
                c.execute('SELECT clinic_merge_drug(%s,%s,%s,%s)', (did,other_did,IDS['admin'],'Gộp giả lập kiểm quyền'))
            c.execute('DROP TABLE s1_merge_context')
            for statement in ("UPDATE clinical_prescriptions SET snapshot='tampered' WHERE id=%s", "DELETE FROM clinical_prescription_items WHERE prescription_id=%s", "DELETE FROM clinical_prescriptions WHERE id=%s"):
                with pytest.raises(psycopg.Error):
                    c.execute(statement,(rid,))
            for statement in ("UPDATE lab_reports SET snapshot='tampered' WHERE id=%s", "DELETE FROM lab_results WHERE report_id=%s", "DELETE FROM lab_reports WHERE id=%s"):
                with pytest.raises(psycopg.Error):
                    c.execute(statement,(lab,))
            for statement in ("UPDATE prescription_outbox SET payload='tampered' WHERE prescription_id=%s", "DELETE FROM prescription_outbox WHERE prescription_id=%s", "UPDATE clinical_prescription_items SET content='tampered' WHERE prescription_id=%s"):
                with pytest.raises(psycopg.Error):
                    c.execute(statement,(rid,))
    finally:
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


@pytest.mark.parametrize('module,function', [('tests.m6_followup_cases','check_followup'), ('tests.m6_cases','check_m6'), ('tests.m5_cases','check_m5')])
def test_runtime_role_allows_supported_api_lifecycles(clients, monkeypatch, module, function):
    from contextlib import contextmanager
    import importlib
    from app import database
    from .conftest import SERVICE
    role = 's1_runtime_' + secrets.token_hex(6)
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS').format(sql.Identifier(role)))
        c.execute((root/'deploy/postgresql-roles.sql').read_text().replace('clinic_app',role).replace('DATABASE minhduc','DATABASE '+c.info.dbname))
    class RuntimePool:
        @contextmanager
        def connection(self):
            with psycopg.connect(URL, row_factory=database.record_factory, autocommit=True) as c:
                c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
                yield c
    try:
        monkeypatch.setattr(database, 'pool', lambda: RuntimePool())
        with db() as c:
            before=c.execute("SELECT count(*) FROM audit_log WHERE event='drug_merged'").fetchone()[0]
        getattr(importlib.import_module(module),function)(clients,IDS,db,SERVICE)
        if function=='check_m6':
            with db() as c:
                assert c.execute("SELECT count(*) FROM audit_log WHERE event='drug_merged'").fetchone()[0]==before+1
    finally:
        with psycopg.connect(URL,autocommit=True) as c:
            c.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_c5_profile_upgrade_installs_snapshot_guards():
    """C5 must start the same protected schema as an installed clinic server."""
    from urllib.parse import urlsplit,urlunsplit
    from .conftest import SOURCE
    from app.database import PGConnection,record_factory
    from app.migrations import migrate_v050
    from app.manual_price_migration import migrate_manual_prices
    from scripts.do_hieu_nang import migrate_profile_schema
    name='s1_c5_upgrade_'+secrets.token_hex(5)
    parts=urlsplit(SOURCE);url=urlunsplit(parts._replace(path='/'+name))
    with psycopg.connect(SOURCE,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(url,row_factory=record_factory) as c:
            root=Path(__file__).resolve().parents[1]
            c.execute((root/'schema.postgresql.sql').read_text(encoding='utf-8'))
            adapted=PGConnection(c);migrate_v050(adapted,postgres=True);migrate_manual_prices(adapted,postgres=True)
            migrate_profile_schema(adapted)
            rows=c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 's1_%'").fetchall()
            assert {'s1_prescription_immutable','s1_prescription_items_immutable','s1_lab_immutable','s1_lab_results_immutable','s1_outbox_immutable'}.issubset({r['tgname'] for r in rows})
    finally:
        with psycopg.connect(SOURCE,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def test_installed_s1_upgrade_refreshes_drug_guard():
    from app.s1_migration import migrate_s1
    with db(True) as c:
        assert c.execute('SELECT 1 FROM schema_migrations WHERE version=12').fetchone()
        # Simulate the older installed function, then run the owner upgrade again.
        c.connection.execute("CREATE OR REPLACE FUNCTION s1_prescription_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$")
        migrate_s1(c)
        source = c.execute("SELECT pg_get_functiondef('s1_prescription_item_guard()'::regprocedure)").fetchone()[0]
        assert 'clinic.merge_from' not in source and 'clinic.merge_to' not in source
        assert 'current_user' in source and 's1_merge_context' in source
        f=c.execute("SELECT prosecdef,proconfig,proowner FROM pg_proc WHERE oid='clinic_merge_drug(integer,integer,integer,text)'::regprocedure").fetchone()
        assert f['prosecdef'] and 'search_path=pg_catalog, public, pg_temp' in f['proconfig']
        assert f['proowner']==c.execute("SELECT relowner FROM pg_class WHERE oid='clinical_prescription_items'::regclass").fetchone()[0]


def test_merge_definer_rolls_back_audit_and_catalog_together(visit):
    import json
    with db(True) as c:
        drugs=[]
        for name in ('Nguồn gộp giả lập','Đích gộp giả lập'):
            c.execute('INSERT INTO drugs(name,name_key,strength_key) VALUES(?,?,?)',(name,secrets.token_hex(8),''))
            drugs.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
        source,target=drugs
        c.execute("INSERT INTO clinical_prescriptions(visit_id,doctor_id,status,created_at) VALUES(?,?,'draft','synthetic')",(visit,IDS['doctor']))
        rx=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO clinical_prescription_items(prescription_id,drug_id,position,content) VALUES(?,?,1,'{}')",(rx,source))
        frozen=json.dumps({'synthetic_only':True})
        c.execute("UPDATE clinical_prescriptions SET status='locked',snapshot=? WHERE id=?",(frozen,rx))
    # Even the table owner cannot repoint a locked row outside the definer context.
    with pytest.raises(psycopg.errors.CheckViolation), db(True) as c:
        c.execute('UPDATE clinical_prescription_items SET drug_id=? WHERE prescription_id=?',(target,rx))
    with pytest.raises(RuntimeError,match='Rollback giả lập'), db(True) as c:
        c.execute('SELECT clinic_merge_drug(?,?,?,?)',(source,target,IDS['admin'],'Gộp giả lập kiểm giao dịch'))
        assert c.execute("SELECT 1 FROM audit_log WHERE event='drug_merged' AND object_id=?",(str(source),)).fetchone()
        raise RuntimeError('Rollback giả lập')
    with db() as c:
        assert c.execute('SELECT drug_id FROM clinical_prescription_items WHERE prescription_id=?',(rx,)).fetchone()[0]==source
        assert c.execute('SELECT merged_into FROM drugs WHERE id=?',(source,)).fetchone()[0] is None
        assert c.execute('SELECT snapshot FROM clinical_prescriptions WHERE id=?',(rx,)).fetchone()[0]==frozen
        assert not c.execute("SELECT 1 FROM audit_log WHERE event='drug_merged' AND object_id=?",(str(source),)).fetchone()
