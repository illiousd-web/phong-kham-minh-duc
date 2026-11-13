from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import hashlib
from io import BytesIO
import os
from pathlib import Path
import secrets
import subprocess
import pytest
from pypdf import PdfReader
from docx import Document
from .conftest import client_for, db, IDS, PASSWORDS, SERVICE, ROOT, URL
from .flows_v042 import create_order,create_rx


def test_no_demo_accounts_or_password_environment():
    assert 'DEMO_PASSWORD' not in os.environ
    with db() as c:
        assert not c.execute("SELECT 1 FROM users WHERE username IN ('letan','quantri','bs_noi','thungan')").fetchone()
    assert client_for().post('/api/login',json={'username':'letan','password':'arbitrary-fake-password'}).status_code==401


def test_cookie_csrf_tls_network_and_host():
    c=client_for('reception')
    response=c.post('/api/login',json={'username':'test_reception','password':PASSWORDS['reception']})
    assert 'access_token' not in response.json()
    cookies=response.headers.get_list('set-cookie')
    assert any('__Host-clinic=' in h and 'HttpOnly' in h and 'Secure' in h and 'SameSite=strict' in h for h in cookies)
    assert c.get('/api/me').status_code==200
    assert c.post('/api/logout',headers={'X-CSRF-Token':''}).status_code==403
    assert c.post('/api/logout',headers={'Origin':'https://attacker.example'}).status_code==403
    assert c.get('/api/health',headers={'Host':'attacker.example'}).status_code==400
    from fastapi.testclient import TestClient
    from app.main import app
    outside=TestClient(app,base_url=os.environ['CLINIC_ORIGIN'],client=('203.0.113.5',99))
    assert outside.get('/api/health',headers={'X-Forwarded-For':'192.168.10.20'}).status_code==403
    plain=TestClient(app,base_url='http://127.0.0.1:58443',client=('192.168.10.20',99))
    assert plain.get('/api/health').status_code==400
    assert c.get('/api/docs').status_code==404
    assert c.get('/api/health').headers['Strict-Transport-Security']
    anonymous=client_for()
    assert anonymous.get('/api/me',headers={'Authorization':'Bearer '+c.cookies['__Host-clinic']}).status_code==401


def test_idle_absolute_logout_and_rotation():
    c=client_for('reception')
    old=c.cookies['__Host-clinic']
    digest=hashlib.sha256(old.encode()).hexdigest()
    with db(True) as con:
        con.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',((datetime.now(timezone.utc)-timedelta(minutes=21)).isoformat(),digest))
    assert c.get('/api/me').status_code==401
    c=client_for('reception')
    digest=hashlib.sha256(c.cookies['__Host-clinic'].encode()).hexdigest()
    with db(True) as con:
        con.execute('UPDATE sessions SET expires_at=? WHERE token_hash=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),digest))
    assert c.get('/api/me').status_code==401
    c=client_for('reception')
    old=c.cookies['__Host-clinic']
    c.post('/api/login',json={'username':'test_reception','password':PASSWORDS['reception']})
    with db() as con:
        assert not con.execute('SELECT 1 FROM sessions WHERE token_hash=?',(hashlib.sha256(old.encode()).hexdigest(),)).fetchone()
    c.headers['X-CSRF-Token']=c.cookies['__Host-clinic-csrf']
    assert c.post('/api/logout').status_code==200
    assert c.get('/api/me').status_code==401


def test_failed_login_lockout_and_audit():
    c=client_for()
    for i in range(5):
        assert c.post('/api/login',json={'username':'nonexistent_fake','password':'wrong'}).status_code==401
    assert c.post('/api/login',json={'username':'nonexistent_fake','password':'wrong'}).status_code==429
    with db() as con:
        assert con.execute("SELECT COUNT(*) FROM audit_log WHERE event='login_failed'").fetchone()[0]>=5


def test_accounts_catalog_and_revocation(clients):
    admin=clients['admin'];reception=clients['reception']
    pwd=secrets.token_urlsafe(24)
    body={'username':'fake_'+secrets.token_hex(4),'full_name':'Nhân viên giả lập riêng','password':pwd,'roles':['reception']}
    assert reception.post('/api/accounts',json=body).status_code==403
    response=admin.post('/api/accounts',json=body);assert response.status_code==201,response.text
    uid=response.json()['id']
    c=client_for();assert c.post('/api/login',json={'username':body['username'],'password':pwd}).status_code==200
    c.headers['X-CSRF-Token']=c.cookies['__Host-clinic-csrf']
    assert admin.put('/api/accounts/'+str(uid),json={'active':False,'roles':['reception']}).status_code==200
    assert c.get('/api/me').status_code==401
    assert admin.put('/api/accounts/'+str(IDS['admin']),json={'active':False,'roles':['admin']}).status_code==409
    service=admin.post('/api/catalog/services',json={'name':'Dịch vụ giả '+secrets.token_hex(4),'price':50000})
    assert service.status_code==201
    assert reception.post('/api/catalog/services',json={'name':'Giả lập','price':1}).status_code==403
    assert clients['manager'].get('/api/overview').status_code==200


def test_password_change_reset_and_redaction(clients):
    admin=clients['admin'];pwd=secrets.token_urlsafe(24);new=secrets.token_urlsafe(24)
    username='fake_'+secrets.token_hex(4)
    uid=admin.post('/api/accounts',json={'username':username,'full_name':'Giả lập','password':pwd,'roles':['cashier']}).json()['id']
    c=client_for();c.post('/api/login',json={'username':username,'password':pwd})
    c.headers['X-CSRF-Token']=c.cookies['__Host-clinic-csrf']
    assert c.post('/api/password',json={'current_password':pwd,'new_password':new}).status_code==200
    assert c.get('/api/me').status_code==401
    assert c.post('/api/login',json={'username':username,'password':new}).status_code==200
    reset=secrets.token_urlsafe(24)
    assert admin.post(f'/api/accounts/{uid}/password',json={'password':reset}).status_code==200
    assert c.get('/api/me').status_code==401
    response=admin.post('/api/accounts',json={'username':'ab','full_name':'Giả lập','password':'SECRET','roles':['doctor']})
    assert response.status_code==422 and 'SECRET' not in response.text


def test_complete_workflow_all_nine_forms(clients,visit):
    doc=clients['doctor'];tech=clients['technician'];cash=clients['cashier'];r=clients['reception']
    note={'version':0,'chief_complaint':'Triệu chứng giả lập LAN','diagnosis':'Chẩn đoán thử','follow_up':'2027-01-01'}
    assert doc.put(f'/api/visits/{visit}/clinical',json=note).status_code==200
    assert clients['doctor2'].get(f'/api/visits/{visit}').status_code==403
    assert cash.get(f'/api/visits/{visit}').json().get('diagnosis') is None
    forms=[(r,'intake',visit),(doc,'visit',visit),(doc,'followup',visit)]
    for category in ('lab','ultrasound','xray','ecg'):
        oid=create_order(clients,visit,category)
        assert doc.get(f'/api/forms/{category}/{oid}').status_code==409
        assert tech.put(f'/api/orders/{oid}/result',json={'version':0,'result_text':'Kết quả giả lập đã duyệt'}).status_code==200
        upload=tech.post(f'/api/orders/{oid}/attachment',files={'file':('fake.pdf',b'%PDF-1.5\nFAKE', 'application/pdf')})
        assert upload.status_code==200
        assert clients['doctor2'].post(f'/api/orders/{oid}/approve').status_code==403
        assert doc.post(f'/api/orders/{oid}/approve').status_code==200
        assert tech.put(f'/api/orders/{oid}/result',json={'version':0,'result_text':'Thay đổi trái phép'}).status_code==409
        assert doc.get(f'/api/orders/{oid}/attachment').content.startswith(b'%PDF-')
        assert r.get(f'/api/orders/{oid}/attachment').status_code==403
        forms.append((doc,category,oid))
        if category=='lab':forms.append((doc,'order',oid))
    rx=create_rx(clients,visit)
    assert rx['status']=='draft';forms.append((doc,'rx',rx['id']))
    assert len(forms)==9
    for client,kind,oid in forms:
        pdf=client.get(f'/api/forms/{kind}/{oid}?fmt=pdf');assert pdf.status_code==200,pdf.text
        assert len(PdfReader(BytesIO(pdf.content)).pages)>=1
        word=client.get(f'/api/forms/{kind}/{oid}?fmt=docx');assert word.status_code==200
        assert Document(BytesIO(word.content)).paragraphs
    assert r.get(f'/api/forms/visit/{visit}').status_code==403
    payment={'visit_id':visit,'amount':150000,'method':'cash','idempotency_key':secrets.token_hex(16)}
    pay=cash.post('/api/payments',json=payment);assert pay.status_code==201,pay.text
    assert cash.post('/api/payments',json=payment).json()['status']=='already_recorded'
    assert cash.get('/api/print/receipt/'+str(pay.json()['id'])).content.startswith(b'%PDF-')
    events=clients['admin'].get('/api/audit').json()
    assert any(x['event']=='payment_recorded_demo' for x in events)


def test_parallel_three_roles_and_lost_update(clients,visit):
    def reception():return clients['reception'].get('/api/patients').status_code
    def doctor():return clients['doctor'].put(f'/api/visits/{visit}/clinical',json={'version':0,'diagnosis':'Ghi đồng thời giả lập'}).status_code
    def cashier():return clients['cashier'].get('/api/dues').status_code
    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(lambda f:f(),[reception,doctor,cashier]))==[200,200,200]
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses=list(executor.map(lambda _:clients['doctor'].put(f'/api/visits/{visit}/clinical',json={'version':1,'diagnosis':'Phiên đồng thời'}).status_code,range(2)))
    assert sorted(statuses)==[200,409]


def test_parallel_payments_no_overcollection(clients,visit):
    def pay(_):
        return clients['cashier'].post('/api/payments',json={'visit_id':visit,'amount':100000,'method':'cash','idempotency_key':secrets.token_hex(16)}).status_code
    with ThreadPoolExecutor(max_workers=3) as executor:statuses=list(executor.map(pay,range(3)))
    assert sorted(statuses)==[201,409,409]
    with db() as con:
        assert con.execute('SELECT SUM(amount) FROM payments WHERE visit_id=?',(visit,)).fetchone()[0]==100000


def test_parallel_stock_fefo_no_negative(clients):
    pharm=clients['pharmacy']
    mid=pharm.post('/api/catalog/medicines',json={'name':'Vật tư giả lập','base_unit':'cái'}).json()['id']
    for lot,qty,expiry in [('FIRST',10,'2028-01-01'),('SECOND',10,'2029-01-01')]:
        assert pharm.post('/api/stock/receipts',json={'medicine_id':mid,'lot_number':lot,'quantity':qty,'expiry_date':expiry}).status_code==201
    def issue(_):return pharm.post('/api/stock/issues',json={'medicine_id':mid,'quantity':15,'purpose':'Xuất thử đồng thời'}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:statuses=list(executor.map(issue,range(2)))
    assert sorted(statuses)==[201,409]
    with db() as con:
        lots=con.execute('SELECT quantity FROM stock_lots WHERE medicine_id=? ORDER BY expiry_date',(mid,)).fetchall()
        assert [x[0] for x in lots]==[0,5]
        assert con.execute('SELECT SUM(quantity) FROM stock_movements WHERE movement_type=? AND stock_lot_id IN (SELECT id FROM stock_lots WHERE medicine_id=?)',('issue',mid)).fetchone()[0]==15


def test_encrypted_backup_restore_and_tamper(tmp_path,clients,visit):
    from scripts.backup_lan import backup,restore,unpack_verified
    import psycopg
    from psycopg import sql
    from urllib.parse import urlsplit,urlunsplit
    from cryptography.exceptions import InvalidTag
    if not __import__('shutil').which(os.getenv('CLINIC_PG_DUMP','pg_dump')):
        pytest.fail('Install PostgreSQL client tools to test real backup/restore')
    key=tmp_path/'key';key.write_bytes(secrets.token_bytes(32))
    name='clinic_restore_'+secrets.token_hex(6)
    target=urlunsplit(urlsplit(URL)._replace(path='/'+name))
    source=Path(os.environ['CLINIC_UPLOAD_DIR']);source.mkdir(exist_ok=True)
    attachment=source/'backup-synthetic.pdf';attachment.write_bytes(b'%PDF-1.5\nFAKE BACKUP')
    with psycopg.connect(URL,autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        path=backup(tmp_path/'backups',key)
        assert b'FAKE BACKUP' not in path.read_bytes()
        restored=restore(path,key,target,tmp_path/'restored-attachments')
        assert (restored/'backup-synthetic.pdf').read_bytes()==attachment.read_bytes()
        with psycopg.connect(target) as c:
            assert c.execute('SELECT COUNT(*) FROM patients').fetchone()[0]>0
            assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
            assert c.execute('SELECT COUNT(*) FROM visits WHERE id=%s',(visit,)).fetchone()[0]==1
            assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='backup_restored'").fetchone()[0]==1
        with pytest.raises(ValueError,match='empty'):
            restore(path,key,target,tmp_path/'another-attachments')
        corrupt=tmp_path/'corrupt.mdbackup';data=bytearray(path.read_bytes());data[-20]^=1;corrupt.write_bytes(data)
        temp=tmp_path/'verify';temp.mkdir()
        with pytest.raises(InvalidTag):unpack_verified(corrupt,key,temp)
        wrong=tmp_path/'wrongkey';wrong.write_bytes(secrets.token_bytes(32))
        with pytest.raises(InvalidTag):unpack_verified(path,wrong,temp)
    finally:
        with psycopg.connect(URL,autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def test_long_exports_preserve_tail_and_intake_hides_clinical(clients,visit):
    doc=clients['doctor'];tech=clients['technician'];rec=clients['reception']
    complaint='Nội dung chuyên môn riêng tư chỉ bác sĩ xem'
    history=('Bệnh sử giả lập dài '*180)+' HISTORY_TAIL_MARKER'
    instructions=('Lời dặn giả lập '*120)+' INSTRUCTION_TAIL_MARKER'
    assert doc.put(f'/api/visits/{visit}/clinical',json={'version':0,'chief_complaint':complaint,'history':history,'diagnosis':'Chẩn đoán giả lập dài'}).status_code==200
    oid=create_order(clients,visit,'lab')
    result=('Kết quả thử '*800)+' RESULT_TAIL_MARKER'
    assert len(result)<=10000
    assert tech.put(f'/api/orders/{oid}/result',json={'version':0,'result_text':result}).status_code==200
    assert doc.post(f'/api/orders/{oid}/approve').status_code==200
    rid=create_rx(clients,visit,instructions=instructions)['id']
    for kind,item,marker in [('visit',visit,'HISTORY_TAIL_MARKER'),('lab',oid,'RESULT_TAIL_MARKER'),('rx',rid,'INSTRUCTION_TAIL_MARKER')]:
        for fmt in ('pdf','docx'):
            response=doc.get(f'/api/forms/{kind}/{item}?fmt={fmt}')
            assert response.status_code==200,response.text
            if fmt=='pdf':text=' '.join(p.extract_text() or '' for p in PdfReader(BytesIO(response.content)).pages)
            else:
                word=Document(BytesIO(response.content))
                text=' '.join([p.text for p in word.paragraphs]+[cell.text for t in word.tables for row in t.rows for cell in row.cells])
            assert marker in text,(kind,fmt)
    response=rec.get(f'/api/forms/intake/{visit}?fmt=docx')
    word=Document(BytesIO(response.content))
    text=' '.join([p.text for p in word.paragraphs]+[cell.text for t in word.tables for row in t.rows for cell in row.cells])
    assert complaint not in text and 'HISTORY_TAIL_MARKER' not in text


def test_parallel_same_idempotency_key_one_payment(clients,visit):
    key=secrets.token_hex(16)
    payload={'visit_id':visit,'amount':50000,'method':'cash','idempotency_key':key}
    with ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(lambda _:clients['cashier'].post('/api/payments',json=payload),range(3)))
    assert all(r.status_code==201 for r in results)
    assert len({r.json()['id'] for r in results})==1
    with db() as c:assert c.execute('SELECT COUNT(*) FROM payments WHERE idempotency_key=?',(key,)).fetchone()[0]==1


def test_postgresql_discount_refund_separation(clients,visit):
    cash=clients['cashier'];manager=clients['manager']
    payment=cash.post('/api/payments',json={'visit_id':visit,'amount':150000,'method':'cash','idempotency_key':secrets.token_hex(16)})
    assert payment.status_code==201
    discount=cash.post('/api/adjustments',json={'visit_id':visit,'kind':'discount','amount':20000,'reason':'Giảm phí giả lập'})
    assert discount.status_code==201,discount.text
    aid=discount.json()['id']
    assert cash.post(f'/api/adjustments/{aid}/review',json={'approve':True}).status_code==403
    assert manager.post(f'/api/adjustments/{aid}/review',json={'approve':True}).status_code==200
    refund=cash.post('/api/adjustments',json={'visit_id':visit,'payment_id':payment.json()['id'],'kind':'refund','amount':20000,'reason':'Hoàn phần dư giả lập'})
    assert refund.status_code==201,refund.text
    aid=refund.json()['id']
    assert manager.post(f'/api/adjustments/{aid}/review',json={'approve':True}).status_code==200
    assert manager.post(f'/api/adjustments/{aid}/review',json={'approve':True}).status_code==409
    due=next(x for x in cash.get('/api/dues').json() if x['visit_id']==visit)
    assert due['paid']==due['charged']==130000
