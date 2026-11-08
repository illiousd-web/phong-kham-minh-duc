"""API tests with exclusively invented data, no real patient records."""
import os
import tempfile
from pathlib import Path

WORKDIR=Path(tempfile.mkdtemp(prefix='minhduc_test_'))
os.environ.setdefault('CLINIC_DB_PATH',str(WORKDIR/'test.sqlite3'))
os.environ.setdefault('CLINIC_UPLOAD_DIR',str(WORKDIR/'attachments'))
from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)
PASSWORD=os.environ['DEMO_PASSWORD']

def token(user):
    response=client.post('/api/login',json={'username':user,'password':PASSWORD})
    assert response.status_code==200,response.text
    return {'Authorization':'Bearer '+response.json()['access_token']}

def prepare_visit(doctor='bs_noi'):
    r=token('letan')
    p=client.post('/api/patients',headers=r,json={'full_name':'Bệnh nhân mô phỏng Hồng','date_of_birth':'1995-04-21','sex':'Nữ','phone':'0900000000'})
    assert p.status_code==201,p.text
    doctors=client.get('/api/staff',headers=r).json()
    did=next(x['id'] for x in doctors if x['username']==doctor)
    v=client.post('/api/visits',headers=r,json={'patient_id':p.json()['id'],'doctor_id':did,'service_id':1})
    assert v.status_code==201,v.text
    return p.json()['id'],v.json()['id']

def test_login_and_unauthorized():
    assert client.get('/api/patients').status_code==401
    assert client.post('/api/login',json={'username':'quantri','password':'incorrect'}).status_code==401
    assert client.get('/api/health').status_code==200
    assert client.get('/').status_code==200

def test_reception_creates_patient_appointment_and_visit():
    r=token('letan')
    patient=client.post('/api/patients',headers=r,json={'full_name':'Người bệnh giả lập Sao','sex':'Nam','citizen_id':'DEMO-ONLY-0001'}).json()
    doctors=client.get('/api/staff',headers=r).json()
    a=client.post('/api/appointments',headers=r,json={'patient_id':patient['id'],'doctor_id':doctors[0]['id'],'scheduled_at':'2026-11-11T08:00','reason':'Khám giả lập'})
    assert a.status_code==201
    v=client.post('/api/visits',headers=r,json={'patient_id':patient['id'],'doctor_id':doctors[0]['id'],'appointment_id':a.json()['id'],'service_id':1})
    assert v.status_code==201
    assert 'arrived' in [x['status'] for x in client.get('/api/appointments',headers=r).json()]
    duplicated=client.post('/api/patients',headers=r,json={'full_name':'Bệnh nhân khác','citizen_id':'DEMO-ONLY-0001','sex':'Nam'})
    assert duplicated.status_code==409

def test_doctor_scope_and_optimistic_versioning():
    patient,visit=prepare_visit('bs_noi')
    d1,d2=token('bs_noi'),token('bs_san')
    assert client.get(f'/api/visits/{visit}',headers=d2).status_code==403
    assert client.get(f'/api/visits/{visit}',headers=d1).status_code==200
    note={'chief_complaint':'Ghi chú giả lập','history':'Không có','vitals':'Mẫu','diagnosis':'Chưa xác định','treatment':'Chưa xác định','follow_up':None,'version':0}
    assert client.put(f'/api/visits/{visit}/clinical',headers=d1,json=note).status_code==200
    assert client.put(f'/api/visits/{visit}/clinical',headers=d1,json=note).status_code==409
    assert client.put(f'/api/visits/{visit}/clinical',headers=d2,json={**note,'version':1}).status_code==403
    assert client.get(f'/api/patients/{patient}',headers=d2).status_code==403

def test_results_workflow_and_role_enforcement():
    _,visit=prepare_visit('bs_noi')
    doc,tech=token('bs_noi'),token('kythuat')
    o=client.post('/api/orders',headers=doc,json={'visit_id':visit,'category':'lab','name':'Xét nghiệm mẫu'}).json()['id']
    assert client.post(f'/api/orders/{o}/approve',headers=doc).status_code==409
    assert client.put(f'/api/orders/{o}/result',headers=doc,json={'result_text':'Dữ liệu thử nghiệm'}).status_code==403
    assert client.put(f'/api/orders/{o}/result',headers=tech,json={'result_text':'Dữ liệu thử nghiệm'}).status_code==200
    assert client.post(f'/api/orders/{o}/approve',headers=token('bs_san')).status_code==403
    assert client.post(f'/api/orders/{o}/approve',headers=doc).status_code==200
    assert client.put(f'/api/orders/{o}/result',headers=tech,json={'result_text':'Sửa'}).status_code==409

def test_attachment_restrictions():
    _,visit=prepare_visit()
    doc=token('bs_noi');tech=token('kythuat')
    order=client.post('/api/orders',headers=doc,json={'visit_id':visit,'category':'xray','name':'Chụp thử nghiệm'}).json()['id']
    bad=client.post(f'/api/orders/{order}/attachment',headers=tech,files={'file':('danger.exe',b'MZ01','application/octet-stream')})
    assert bad.status_code==415
    valid=client.post(f'/api/orders/{order}/attachment',headers=tech,files={'file':('test.pdf',b'%PDF-1.5\nMOCK', 'application/pdf')})
    assert valid.status_code==200
    assert client.get(f'/api/orders/{order}/attachment',headers=doc).status_code==200
    assert client.get(f'/api/orders/{order}/attachment',headers=token('letan')).status_code==403

def test_prescription_is_draft_and_pharmacy_cannot_edit():
    _,visit=prepare_visit()
    doc,pharm=token('bs_noi'),token('duoc')
    created=client.post('/api/prescriptions',headers=doc,json={'visit_id':visit,'drug_lines':'Thuốc giả lập – không dùng điều trị','instructions':'Chỉ thử nghiệm'})
    assert created.status_code==201 and created.json()['status']=='draft'
    assert client.post('/api/prescriptions',headers=pharm,json={'visit_id':visit,'drug_lines':'Không hợp lệ'}).status_code==403
    result=client.get('/api/prescriptions',headers=pharm)
    assert result.status_code==200 and any(x['visit_id']==visit for x in result.json())

def test_payment_is_bounded_idempotent_and_manager_report_only():
    _,visit=prepare_visit()
    cash=token('thungan');manager=token('quanly');doc=token('bs_noi')
    due=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==visit)
    assert due['charged']>=150000 and due['paid']==0
    over=client.post('/api/payments',headers=cash,json={'visit_id':visit,'amount':due['charged']+1,'method':'cash','idempotency_key':'case-overpaid-123'})
    assert over.status_code==409
    p={'visit_id':visit,'amount':50000,'method':'cash','idempotency_key':'case-payment-456'}
    assert client.post('/api/payments',headers=cash,json=p).status_code==201
    again=client.post('/api/payments',headers=cash,json=p)
    assert again.status_code==201 and again.json()['status']=='already_recorded'
    due2=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==visit)
    assert due2['paid']==50000
    assert client.get('/api/overview',headers=manager).json()['charged']>=150000
    assert 'charged' not in client.get('/api/overview',headers=doc).json()
    assert client.get('/api/dues',headers=doc).status_code==403

def test_role_boundaries_and_audit():
    admin=token('quantri');cash=token('thungan')
    assert client.get('/api/audit',headers=admin).status_code==200
    assert client.get('/api/audit',headers=cash).status_code==403
    assert client.get('/api/stock',headers=cash).status_code==403
    assert client.get('/api/stock',headers=token('duoc')).status_code==200

def test_logout_invalidates_session():
    cred=token('letan')
    assert client.get('/api/me',headers=cred).status_code==200
    assert client.post('/api/logout',headers=cred).status_code==200
    assert client.get('/api/me',headers=cred).status_code==401

def test_stock_receipt_tracks_lots_but_blocks_controlled_medicine():
    pharma=token('duoc')
    meds=client.get('/api/medicines',headers=pharma).json()
    ordinary=next(m for m in meds if not m['controlled'])
    restricted=next(m for m in meds if m['controlled'])
    payload={'medicine_id':ordinary['id'],'lot_number':'LOT-TEST-909','expiry_date':'2028-12-31','quantity':37}
    first=client.post('/api/stock/receipts',headers=pharma,json=payload)
    second=client.post('/api/stock/receipts',headers=pharma,json=payload)
    assert first.status_code==201 and second.status_code==201
    lot=next(x for x in client.get('/api/stock',headers=pharma).json() if x['lot_number']=='LOT-TEST-909')
    assert lot['quantity']==74
    assert client.post('/api/stock/receipts',headers=pharma,json={**payload,'medicine_id':restricted['id']}).status_code==403
    assert client.post('/api/stock/receipts',headers=pharma,json={**payload,'quantity':-3}).status_code==422
    assert client.post('/api/stock/receipts',headers=token('thungan'),json=payload).status_code==403
