"""PostgreSQL LAN integration coverage for workflows A/B/C/D; only synthetic data."""
import secrets
from .conftest import client_for, IDS, db
from .flows_v042 import create_order, create_rx


def test_priced_order_idempotent_and_void_requires_manager(clients, visit):
    doc=clients['doctor'];manager=clients['manager'];cashier=clients['cashier']
    initial=next(x for x in cashier.get('/api/dues').json() if x['visit_id']==visit)['charged']
    oid=create_order(clients,visit,'lab')
    after=next(x for x in cashier.get('/api/dues').json() if x['visit_id']==visit)['charged']
    assert after-initial==33000
    charge=cashier.get(f'/api/charges/{visit}')
    assert charge.status_code==200
    assert len([x for x in charge.json() if x['source_type']=='order' and x['source_id']==oid])==1
    reason={'reason':'Chỉ định sai, đề nghị hủy và điều chỉnh phí'}
    requested=doc.post(f'/api/orders/{oid}/request-cancel',json=reason)
    assert requested.status_code==201,requested.text
    rid=requested.json()['id']
    assert cashier.get(f'/api/charges/{visit}').json()[-1]['void_reason'] is None
    assert manager.post(f'/api/orders/cancellation-requests/{rid}/review',json={'approve':True}).status_code==200
    assert next(x for x in cashier.get('/api/dues').json() if x['visit_id']==visit)['charged']==initial
    assert cashier.get(f'/api/charges/{visit}').json()[-1]['void_reason']==reason['reason']


def test_reject_unpriced_order_in_lan(clients,visit):
    doc=clients['doctor']
    resp=doc.post('/api/orders',json={'visit_id':visit,'category':'lab','name':'Chỉ định không có giá'})
    assert resp.status_code==422,resp.text


def test_stock_and_cashier_dispense_exact_once(clients,visit):
    doc=clients['doctor'];pharmacy=clients['pharmacy'];cashier=clients['cashier'];manager=clients['manager']
    assert doc.put(f'/api/visits/{visit}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập'}).status_code==200
    med=manager.post('/api/catalog/medicines',json={'name':'Thuốc cấu trúc giả lập '+secrets.token_hex(5),'base_unit':'viên'})
    assert med.status_code==201
    mid=med.json()['id']
    assert manager.put(f'/api/medicines/{mid}/price',json={'unit_price':7500}).status_code==200
    assert pharmacy.post('/api/stock/receipts',json={'medicine_id':mid,'lot_number':'TEST-LOT-A','expiry_date':'2029-12-31','quantity':6}).status_code==201
    rx=doc.post('/api/prescriptions',json={'visit_id':visit,'items':[{'medicine_id':mid,'quantity':3,'directions':'Chỉ mô phỏng'}]})
    assert rx.status_code==201,rx.text
    before=next(x for x in cashier.get('/api/dues').json() if x['visit_id']==visit)['charged']
    result=pharmacy.post(f"/api/prescriptions/{rx.json()['id']}/dispense")
    assert result.status_code==201,result.text
    assert result.json()['total']==22500
    assert pharmacy.post(f"/api/prescriptions/{rx.json()['id']}/dispense").status_code==409
    assert next(x for x in cashier.get('/api/dues').json() if x['visit_id']==visit)['charged']==before+22500
    remaining=[x for x in pharmacy.get('/api/stock').json() if x['lot_number']=='TEST-LOT-A'][0]['quantity']
    assert remaining==3


def test_nurse_assignment_and_close_lock_lan(clients,visit):
    d=clients['doctor'];n=client_for('nurse')
    try:
        assert n.get(f'/api/visits/{visit}').status_code==403
        assert d.post(f'/api/visits/{visit}/nurses',json={'nurse_id':IDS['nurse']}).status_code==201
        r=n.get(f'/api/visits/{visit}')
        assert r.status_code==200,r.text
        assert 'diagnosis' not in r.json()
        assert n.put(f'/api/visits/{visit}/vitals',json={'vitals':'Mạch 80 l/p','version':0}).status_code==200
        assert d.put(f'/api/visits/{visit}/clinical',json={'version':1,'diagnosis':'Kết luận giả lập'}).status_code==200
        assert d.post(f'/api/visits/{visit}/complete',json={'version':d.get(f'/api/visits/{visit}').json()['version']}).status_code==200
        assert n.put(f'/api/visits/{visit}/vitals',json={'vitals':'Mạch 82 l/p','version':3}).status_code==409
        assert d.put(f'/api/visits/{visit}/clinical',json={'version':3,'diagnosis':'Sửa sau khóa'}).status_code==409
        assert d.post('/api/prescriptions',json={'visit_id':visit,'drug_lines':'Đơn thử'}).status_code==409
        add=d.post(f'/api/visits/{visit}/addenda',json={'reason':'Bổ sung nội dung','content':'Ghi thêm hậu kiểm, không sửa phiếu gốc'})
        assert add.status_code==201,add.text
        assert clients['manager'].post(f"/api/visits/addenda/{add.json()['id']}/review",json={'approve':True}).status_code==200
    finally:n.close()
