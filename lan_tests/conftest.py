"""LAN integration tests create a disposable database on an explicit local server."""
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import pytest
import psycopg
from psycopg import sql

SOURCE=os.getenv('CLINIC_TEST_DATABASE_URL')
if not SOURCE:
    pytest.skip('Set CLINIC_TEST_DATABASE_URL for disposable PostgreSQL integration tests', allow_module_level=True)
parts=urlsplit(SOURCE)
if parts.hostname not in ('127.0.0.1','localhost','::1'):
    raise RuntimeError('LAN tests require a local disposable PostgreSQL server')
NAME='clinic_test_'+secrets.token_hex(6)
with psycopg.connect(SOURCE,autocommit=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(NAME)))
URL=urlunsplit(parts._replace(path='/'+NAME))
TEMP=tempfile.TemporaryDirectory(prefix='minhduc-lan-test-')
ROOT=Path(TEMP.name)
os.environ.update(CLINIC_MODE='lan',CLINIC_DATABASE_URL=URL,CLINIC_DATA_DIR=str(ROOT),
                  CLINIC_UPLOAD_DIR=str(ROOT/'attachments'),CLINIC_ORIGIN='https://127.0.0.1:58443',
                  CLINIC_ALLOWED_CIDRS='192.168.10.0/24,127.0.0.1/32',CLINIC_BIND_IP='127.0.0.1')
os.environ.pop('DEMO_PASSWORD',None)
from app.database import migrate,db
migrate()
from app.auth import pw_hash
from app.accounts import AccountInput,create_account
PASSWORDS={}
IDS={}
with db(True) as c:
    for role in ('admin','manager','reception','doctor','technician','pharmacy','cashier','nurse'):
        PASSWORDS[role]=secrets.token_urlsafe(24)
        IDS[role]=create_account(c,AccountInput(username='test_'+role,full_name='Nhân viên giả lập '+role,password=PASSWORDS[role],roles=[role]),pw_hash)
    PASSWORDS['doctor2']=secrets.token_urlsafe(24)
    IDS['doctor2']=create_account(c,AccountInput(username='test_doctor2',full_name='Bác sĩ giả lập 2',password=PASSWORDS['doctor2'],roles=['doctor']),pw_hash)
    c.execute('INSERT INTO service_catalog(name,price) VALUES(?,?)',('Khám giả lập',150000))
    SERVICE=c.execute('SELECT last_insert_rowid()').fetchone()[0]

from app.main import app
from fastapi.testclient import TestClient


def client_for(role=None):
    client=TestClient(app,base_url=os.environ['CLINIC_ORIGIN'],client=('192.168.10.20',1234))
    client.headers.update({'Origin':os.environ['CLINIC_ORIGIN'],'X-Clinic-Request':'1'})
    if role:
        response=client.post('/api/login',json={'username':'test_'+role,'password':PASSWORDS[role]})
        assert response.status_code==200,response.text
        client.headers['X-CSRF-Token']=client.cookies['__Host-clinic-csrf']
    return client


@pytest.fixture
def clients():
    result={role:client_for(role) for role in ('admin','reception','doctor','doctor2','technician','pharmacy','cashier','manager')}
    yield result
    for client in result.values():client.close()


@pytest.fixture
def visit(clients):
    r=clients['reception']
    patient=r.post('/api/patients',json={'full_name':'Bệnh nhân giả lập LAN','sex':'Nữ','date_of_birth':'1990-01-01'})
    assert patient.status_code==201,patient.text
    result=r.post('/api/visits',json={'patient_id':patient.json()['id'],'doctor_id':IDS['doctor'],'service_id':SERVICE})
    assert result.status_code==201,result.text
    return result.json()['id']


def pytest_sessionfinish(session,exitstatus):
    from app import database
    if database._pool:database._pool.close()
    with psycopg.connect(SOURCE,autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(NAME)))
    TEMP.cleanup()
