import os
import psycopg
from .conftest import client_for,db


def test_database_outage_reports_503_without_leaking(monkeypatch):
    from app import database
    def unavailable():
        raise psycopg.OperationalError('private database password and internal host')
    monkeypatch.setattr(database,'pool',unavailable)
    response=client_for().get('/api/health')
    assert response.status_code==503
    assert 'private database password' not in response.text
    assert response.headers['retry-after']=='5'


def test_transaction_rollback_covers_business_and_audit():
    try:
        with db(True) as c:
            c.execute('INSERT INTO service_catalog(name,price) VALUES(?,?)',('ROLLBACK_FAKE_TEST',1))
            c.execute('INSERT INTO audit_log(event,object_type,created_at) VALUES(?,?,?)',('ROLLBACK_FAKE_TEST','test','2026-01-01'))
            raise RuntimeError('simulated process failure before commit')
    except RuntimeError:pass
    with db() as c:
        assert not c.execute('SELECT 1 FROM service_catalog WHERE name=?',('ROLLBACK_FAKE_TEST',)).fetchone()
        assert not c.execute('SELECT 1 FROM audit_log WHERE event=?',('ROLLBACK_FAKE_TEST',)).fetchone()


def test_upload_body_limit_before_multipart_parse():
    c=client_for('technician')
    response=c.post('/api/orders/1/attachment',content=b'fake',headers={'Content-Length':str(7*1024*1024),'Content-Type':'application/octet-stream'})
    assert response.status_code==413


def test_invalid_lan_configuration_fails_closed():
    import subprocess,sys
    env=os.environ.copy();env['CLINIC_ALLOWED_CIDRS']='0.0.0.0/0'
    result=subprocess.run([sys.executable,'-c','import app.config'],env=env,capture_output=True)
    assert result.returncode!=0
    env=os.environ.copy();env['CLINIC_DATABASE_URL']='sqlite:///fake'
    result=subprocess.run([sys.executable,'-c','import app.config'],env=env,capture_output=True)
    assert result.returncode!=0


def test_database_runtime_role_cannot_mutate_audit():
    from .conftest import URL
    from psycopg import sql
    import secrets
    role='clinic_runtime_'+secrets.token_hex(6)
    with psycopg.connect(URL,autocommit=True) as c:
        c.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        try:
            c.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('REVOKE UPDATE,DELETE,TRUNCATE ON audit_log FROM {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            c.execute("INSERT INTO audit_log(event,object_type,created_at) VALUES('role_test','fake','2026-11-08')")
            assert c.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]>0
            for command in ('DELETE FROM audit_log','UPDATE audit_log SET event=event','TRUNCATE audit_log'):
                import pytest
                with pytest.raises(psycopg.errors.InsufficientPrivilege):c.execute(command)
        finally:
            c.execute('RESET ROLE')
            c.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_appointment_validation_and_single_arrival(clients):
    from .conftest import IDS,SERVICE
    r=clients['reception']
    patient=r.post('/api/patients',json={'full_name':'Lịch hẹn giả lập'}).json()['id']
    body={'patient_id':patient,'doctor_id':IDS['doctor'],'scheduled_at':'not-a-valid-date'}
    assert r.post('/api/appointments',json=body).status_code==422
    body['scheduled_at']='2027-01-01T08:00'
    appointment=r.post('/api/appointments',json=body)
    assert appointment.status_code==201
    payload={'patient_id':patient,'doctor_id':IDS['doctor'],'service_id':SERVICE,'appointment_id':appointment.json()['id']}
    assert r.post('/api/visits',json=payload).status_code==201
    assert r.post('/api/visits',json=payload).status_code==422
    assert clients['doctor2'].get('/api/appointments').json()==[]
