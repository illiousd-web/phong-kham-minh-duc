"""End-to-end role, finance, stock and print tests. Fake patients only."""
from io import BytesIO
from fastapi.testclient import TestClient
from tests.test_workflows import client, token, prepare_visit
import fitz
from docx import Document


def test_local_health_and_logo():
    r=client.get('/api/health')
    assert r.status_code==200 and r.json()['version']=='0.4.2'
    logo=client.get('/assets/logo_minh_duc.png')
    assert logo.status_code==200 and logo.content.startswith(b'\x89PNG')
    ui=client.get('/assets/app.js')
    assert ui.status_code==200 and b'exportMedicalForm' in ui.content


def test_intake_print_from_persisted_patient():
    patient_id,visit=prepare_visit()
    pdf=client.get(f'/api/print/intake/{visit}',headers=token('letan'))
    assert pdf.status_code==200 and pdf.content[:5]==b'%PDF-'
    with fitz.open(stream=pdf.content,filetype='pdf') as d:
        assert len(d)==1
        content=' '.join(page.get_text() for page in d)
        assert 'Minh Đức' in content and 'Hồng' in content and 'MD000' in content
    assert client.get(f'/api/print/intake/{visit}',headers=token('thungan')).status_code==403


def test_clinical_pdf_and_docx_from_saved_data():
    _,visit=prepare_visit('bs_noi')
    r=token('bs_noi')
    payload=dict(chief_complaint='Đau bụng thử nghiệm',history='Bệnh sử giả định',vitals='Mạch 80; HA 120/80',
                 diagnosis='Chẩn đoán giả lập',treatment='Không dùng điều trị thật',follow_up='16/11/2026',version=0)
    assert client.put(f'/api/visits/{visit}/clinical',headers=r,json=payload).status_code==200
    pdf=client.get(f'/api/print/clinical/{visit}',headers=r)
    assert pdf.status_code==200
    with fitz.open(stream=pdf.content,filetype='pdf') as d:
        t=' '.join(p.get_text() for p in d)
        assert 'Đau bụng thử nghiệm' in t and 'Chẩn đoán giả lập' in t
    docx=client.get(f'/api/visits/{visit}/forms/clinical?format=docx',headers=r)
    assert docx.status_code==200 and docx.content[:2]==b'PK'
    document=Document(BytesIO(docx.content))
    assert len(document.paragraphs)>10
    assert client.get(f'/api/print/clinical/{visit}',headers=token('bs_san')).status_code==403
    follow=client.get(f'/api/print/follow_up/{visit}',headers=r)
    assert follow.status_code==200
    with fitz.open(stream=follow.content,filetype='pdf') as d:
        assert d[0].rect.width < 500  # A5


def test_orders_result_requires_approved_state_for_pdf():
    _,visit=prepare_visit('bs_noi')
    doctor=token('bs_noi');tech=token('kythuat')
    order=client.post('/api/orders',headers=doctor,json={'visit_id':visit,'category':'lab','name':'Xét nghiệm tổng hợp mô phỏng'}).json()['id']
    assert client.get(f'/api/print/order/{order}',headers=doctor).status_code==200
    assert client.get(f'/api/print/result/{order}',headers=doctor).status_code==409
    assert client.put(f'/api/orders/{order}/result',headers=tech,json={'result_text':'Giá trị giả định 123'}).status_code==200
    assert client.post(f'/api/orders/{order}/approve',headers=doctor).status_code==200
    pdf=client.get(f'/api/print/result/{order}',headers=doctor)
    assert pdf.status_code==200
    with fitz.open(stream=pdf.content,filetype='pdf') as d:
        assert 'Giá trị giả định 123' in d[0].get_text()
    assert client.get(f'/api/print/result/{order}',headers=token('bs_san')).status_code==403


def test_rx_is_only_draft_and_print_scoped():
    _,visit=prepare_visit('bs_noi')
    doctor=token('bs_noi')
    body={'visit_id':visit,'drug_lines':'Thuốc giả lập A | 5 viên | không sử dụng điều trị',
        'instructions':'Nháp, chỉ thử nghiệm','follow_up':'2026-11-21'}
    blocked=client.post('/api/prescriptions',headers=doctor,json=body)
    assert blocked.status_code==409 and 'chẩn đoán' in blocked.json()['detail']
    assert client.put(f'/api/visits/{visit}/clinical',headers=doctor,json={'version':0,'diagnosis':'Chẩn đoán giả lập'}).status_code==200
    p=client.post('/api/prescriptions',headers=doctor,json=body)
    assert p.status_code==201
    pdf=client.get(f"/api/print/rx/{p.json()['id']}",headers=doctor)
    assert pdf.status_code==200
    with fitz.open(stream=pdf.content,filetype='pdf') as d:
        assert d[0].rect.width<500
        assert 'Thuốc giả lập A' in d[0].get_text()
    assert client.get(f"/api/print/rx/{p.json()['id']}",headers=token('bs_san')).status_code==403


def test_receipt_pdf_amount_and_scope():
    _,visit=prepare_visit()
    cash=token('thungan')
    pay=client.post('/api/payments',headers=cash,json={
        'visit_id':visit,'amount':80000,'method':'cash','idempotency_key':'receipt-v02-08'}).json()['id']
    pdf=client.get(f'/api/print/receipt/{pay}',headers=cash)
    assert pdf.status_code==200
    with fitz.open(stream=pdf.content,filetype='pdf') as d:
        s=d[0].get_text();assert '80.000' in s and 'Phiếu' in s or 'PHIẾU' in s
    assert client.get(f'/api/print/receipt/{pay}',headers=token('letan')).status_code==403
    assert any(x['id']==pay for x in client.get('/api/payments',headers=cash).json())


def test_fefo_stock_issue_is_atomic_and_blocks_controlled():
    pharmacy=token('duoc')
    stock=client.get('/api/stock',headers=pharmacy).json()
    med=next(x for x in stock if not x['controlled'] and x['quantity']>=120)
    first=med['id'];med_id=next(x for x in client.get('/api/medicines',headers=pharmacy).json() if x['name']==med['name'])['id']
    pre=client.get('/api/stock',headers=pharmacy).json()
    resp=client.post('/api/stock/issues',headers=pharmacy,json={'medicine_id':med_id,'quantity':130,'purpose':'Sử dụng mô phỏng không điều trị'})
    assert resp.status_code==201,resp.text
    used=resp.json()['lots'];assert sum(x['quantity'] for x in used)==130
    after=client.get('/api/stock',headers=pharmacy).json()
    assert sum(x['quantity'] for x in pre if x['name']==med['name'])-sum(x['quantity'] for x in after if x['name']==med['name'])==130
    before_failed=sum(x['quantity'] for x in after if x['name']==med['name'])
    assert client.post('/api/stock/issues',headers=pharmacy,json={'medicine_id':med_id,'quantity':100000,'purpose':'Quá nhiều số lượng mô phỏng'}).status_code==409
    assert before_failed==sum(x['quantity'] for x in client.get('/api/stock',headers=pharmacy).json() if x['name']==med['name'])
    controlled=next(x for x in client.get('/api/medicines',headers=pharmacy).json() if x['controlled'])
    assert client.post('/api/stock/issues',headers=pharmacy,json={'medicine_id':controlled['id'],'quantity':1,'purpose':'Dùng mô phỏng'}).status_code==403
    assert client.post('/api/stock/issues',headers=token('thungan'),json={'medicine_id':med_id,'quantity':1,'purpose':'Sai quyền'}).status_code==403


def test_discount_approval_and_refund_overpayment_path():
    _,visit=prepare_visit()
    cash=token('thungan');manager=token('quanly')
    payment=client.post('/api/payments',headers=cash,json={
        'visit_id':visit,'amount':150000,'method':'cash','idempotency_key':'paid-full-130'}).json()['id']
    a=client.post('/api/adjustments',headers=cash,json={
        'visit_id':visit,'kind':'discount','amount':25000,'reason':'Giảm giá giả lập theo chính sách đã duyệt'}).json()['id']
    assert client.post(f'/api/adjustments/{a}/review',headers=cash,json={'approve':True}).status_code==403
    assert client.post(f'/api/adjustments/{a}/review',headers=manager,json={'approve':True}).status_code==200
    assert client.post(f'/api/adjustments/{a}/review',headers=manager,json={'approve':True}).status_code==409
    due=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==visit)
    assert due['charged']==125000 and due['paid']==150000
    req=client.post('/api/adjustments',headers=cash,json={
        'visit_id':visit,'kind':'refund','payment_id':payment,'amount':25000,'reason':'Hoàn phần đã trả thừa sau giảm giá'}).json()['id']
    assert client.post(f'/api/adjustments/{req}/review',headers=manager,json={'approve':True}).status_code==200
    due2=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==visit)
    assert due2['charged']==due2['paid']==125000
    assert client.post('/api/adjustments',headers=cash,json={
        'visit_id':visit,'kind':'refund','payment_id':payment,'amount':25000,'reason':'Hoàn thêm lần nữa không hợp lệ'}).status_code==201
    pending=client.get('/api/adjustments',headers=manager).json()[0]
    assert client.post(f"/api/adjustments/{pending['id']}/review",headers=manager,json={'approve':True}).status_code==409


def test_admin_cannot_export_unassigned_clinical():
    _,visit=prepare_visit('bs_noi')
    assert client.get(f'/api/print/clinical/{visit}',headers=token('quantri')).status_code==403
    assert client.get(f'/api/print/rx/999999',headers=token('quantri')).status_code==404
    # Denial must not expose a patient note to an unauthorized cashier
    assert client.get(f'/api/visits/{visit}',headers=token('thungan')).json().get('diagnosis') is None
