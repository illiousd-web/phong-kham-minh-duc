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


@pytest.mark.parametrize('module,function', [('tests.m6_followup_cases','check_followup'), ('tests.m5_cases','check_m5')])
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
        getattr(importlib.import_module(module),function)(clients,IDS,db,SERVICE)
    finally:
        with psycopg.connect(URL,autocommit=True) as c:
            c.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
