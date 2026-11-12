"""Upgrade actual legacy schemas, verify old columns and restore a v0.5 backup."""
from pathlib import Path
import secrets,json
from urllib.parse import urlsplit,urlunsplit
import psycopg
from psycopg import sql
import pytest
from .conftest import SOURCE

ROOT=Path(__file__).resolve().parents[1]


def database_url(name):return urlunsplit(urlsplit(SOURCE)._replace(path='/'+name))


def create_db(name):
    with psycopg.connect(SOURCE,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    return database_url(name)


def drop_db(name):
    with psycopg.connect(SOURCE,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH(FORCE)').format(sql.Identifier(name)))


def old_data(c,v042):
    c.execute("INSERT INTO users(username,full_name,salt,password_hash) VALUES('fake_legacy','Nhân viên giả lập cũ','00000000000000000000000000000000','FAKE_ONLY')")
    c.execute("INSERT INTO user_roles VALUES(1,'doctor')")
    c.execute("INSERT INTO patients(code,full_name,date_of_birth,sex,phone,created_at) VALUES('FAKE-OLD','Hồ sơ giả lập trước nâng cấp','1990-01-01','Nữ','0900000000','2026-11-08')")
    c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,status,history,diagnosis,treatment,version,created_at) VALUES(1,1,1,'completed','Tiền sử cũ phải giữ','LEGACY_DIAGNOSIS_MARKER','Xử trí cũ giả lập',7,'2026-11-08')")
    c.execute("INSERT INTO service_catalog(name,price) VALUES('Khám cũ giả lập',150000)")
    c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(1,'Phí khám cũ',150000,'2026-11-08')")
    c.execute("INSERT INTO orders(visit_id,category,name,status,requested_by,result_text,created_at) VALUES(1,'lab','Chỉ định cũ','approved',1,'OLD_RESULT_MARKER','2026-11-08')")
    c.execute("INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,created_at) VALUES(1,1,'Đơn văn bản cũ phải giữ','2026-11-08')")
    c.execute("INSERT INTO medicines(name,base_unit) VALUES('Thuốc cũ giả lập','viên')")
    c.execute("INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(1,'OLD-LOT','2029-01-01',9)")
    c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(1,100000,'cash',1,'2026-11-08','OLD-FAKE-PAYMENT')")
    c.execute("INSERT INTO audit_log(user_id,event,object_type,created_at) VALUES(1,'old_legacy','fake','2026-11-08')")
    if v042:
        c.execute("INSERT INTO service_catalog(name,price) VALUES('CLS cũ giả lập',25000)")
        c.execute("INSERT INTO service_categories VALUES(2,'lab')")
        c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(1,'CLS cũ đã ghi',25000,'2026-11-08')")
        c.execute("INSERT INTO charge_sources VALUES(2,'order',1)")
        c.execute("INSERT INTO order_requests VALUES('OLD-FAKE-ORDER',1,1,2,'lab',1)")


def snapshot(c):
    result={}
    for table in ('users','patients','visits','orders','prescriptions','medicines','stock_lots','charges','payments','audit_log'):
        cursor=c.execute('SELECT * FROM '+table+' ORDER BY id')
        columns=[d.name for d in cursor.description]
        result[table]=(columns,cursor.fetchall())
    return result


@pytest.mark.parametrize('version',['v041','v042'])
def test_upgrade_preserves_every_old_column_and_backup_restore(version,tmp_path,monkeypatch):
    from app import database
    from scripts import backup_lan
    name='clinic_migration_'+secrets.token_hex(6);restore_name='clinic_restore_'+secrets.token_hex(6)
    url=create_db(name);target=create_db(restore_name)
    try:
        with psycopg.connect(url) as c:
            c.execute((ROOT/f'tests/fixtures/{version}_schema_pg.sql').read_text())
            old_data(c,version=='v042');before=snapshot(c)
        monkeypatch.setattr(database,'DATABASE_URL',url)
        database.migrate();database.migrate()
        with psycopg.connect(url) as c:
            for table,(columns,rows) in before.items():
                query=sql.SQL('SELECT {} FROM {} ORDER BY id').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table))
                actual=c.execute(query).fetchall()
                if table=='audit_log':
                    assert actual[:len(rows)]==rows,table
                    added=actual[len(rows):]
                    assert len(added)==6
                    assert [r[columns.index('event')] for r in added]==['patient_catalog_seeded']+['standard_catalog_seeded']*5
                    from app.d0_sources import SOURCES
                    assert [json.loads(r[columns.index('details')]) for r in added[1:]]==[
                        {'file':filename,'rows':count,'sha256':sha} for filename,count,sha,*_ in SOURCES.values()]
                    assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]==11
                else:assert actual==rows,table
            assert c.execute('SELECT count(*) FROM schema_migrations WHERE version=3').fetchone()[0]==1
            assert c.execute('SELECT count(*) FROM charges').fetchone()[0]==(2 if version=='v042' else 1)
            assert c.execute('SELECT count(*) FROM order_authorizations').fetchone()[0]==(1 if version=='v042' else 0)
            history=json.loads(c.execute('SELECT snapshot FROM clinical_revisions WHERE visit_id=1 AND version=7').fetchone()[0])
            assert history['diagnosis']=='LEGACY_DIAGNOSIS_MARKER'
        # Trigger enforces the completed record even if runtime accidentally used UPDATE.
        with psycopg.connect(url) as c:
            with pytest.raises(psycopg.errors.CheckViolation):c.execute("UPDATE visits SET diagnosis='tamper' WHERE id=1")
        uploads=tmp_path/'source-files';uploads.mkdir();(uploads/'old.pdf').write_bytes(b'%PDF-1.5\nFAKE_OLD_ATTACHMENT')
        monkeypatch.setenv('CLINIC_UPLOAD_DIR',str(uploads));monkeypatch.setattr(backup_lan,'DATABASE_URL',url)
        key=tmp_path/'key';key.write_bytes(secrets.token_bytes(32))
        path=backup_lan.backup(tmp_path/'backups',key)
        backup_lan.restore(path,key,target,tmp_path/'restored-files')
        assert (tmp_path/'restored-files/old.pdf').read_bytes()==(uploads/'old.pdf').read_bytes()
        with psycopg.connect(target) as c:
            assert c.execute('SELECT diagnosis FROM visits WHERE id=1').fetchone()[0]=='LEGACY_DIAGNOSIS_MARKER'
            assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM clinical_revisions').fetchone()[0]==1
            assert c.execute('SELECT sum(amount) FROM effective_charges').fetchone()[0]==(175000 if version=='v042' else 150000)
    finally:drop_db(name);drop_db(restore_name)


def test_failed_additive_migration_rolls_back_schema_and_markers(monkeypatch):
    from app import database,migrations
    name='clinic_rollback_'+secrets.token_hex(6);url=create_db(name)
    try:
        with psycopg.connect(url) as c:
            c.execute((ROOT/'tests/fixtures/v041_schema_pg.sql').read_text());old_data(c,False)
        monkeypatch.setattr(database,'DATABASE_URL',url)
        with monkeypatch.context() as patch:
            patch.setattr(migrations,'ADDITIONS',{**migrations.ADDITIONS,'nonexistent_fake_table':[('bad','TEXT')]})
            with pytest.raises(psycopg.errors.UndefinedTable):database.migrate()
        with psycopg.connect(url) as c:
            assert not c.execute('SELECT 1 FROM schema_migrations WHERE version IN (2,3)').fetchone()
            assert not c.execute("SELECT 1 FROM information_schema.columns WHERE table_name='service_catalog' AND column_name='code'").fetchone()
            assert c.execute('SELECT diagnosis FROM visits').fetchone()[0]=='LEGACY_DIAGNOSIS_MARKER'
        database.migrate()
    finally:drop_db(name)


def test_runtime_grants_keep_new_evidence_immutable(monkeypatch):
    from app import database
    name='clinic_permissions_'+secrets.token_hex(6);role='fake_runtime_'+secrets.token_hex(6);url=create_db(name)
    try:
        monkeypatch.setattr(database,'DATABASE_URL',url);database.migrate()
        with psycopg.connect(url) as c:
            c.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS').format(sql.Identifier(role)))
            grants=(ROOT/'deploy/postgresql-roles.sql').read_text().replace('minhduc TO clinic_app',name+' TO '+role).replace('clinic_app',role)
            c.execute(grants)
            c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            assert c.execute('SELECT count(*) FROM effective_charges').fetchone()[0]==0
            for table in ('clinical_revisions','nursing_notes','nursing_executions','charge_price_history','charge_credits','controlled_ledger','audit_log','schema_migrations','payments','charges','dispensations','dispensation_items','stock_movements'):
                for command in ('UPDATE '+table+' SET '+('version=version' if table in ('clinical_revisions','schema_migrations') else ('task_id=task_id' if table=='nursing_executions' else 'id=id')),'DELETE FROM '+table,'TRUNCATE '+table):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with c.transaction():c.execute(command)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with c.transaction():c.execute('CREATE TABLE forbidden_runtime_ddl(id INTEGER)')
    finally:
        drop_db(name)
        with psycopg.connect(SOURCE,autocommit=True) as c:c.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
