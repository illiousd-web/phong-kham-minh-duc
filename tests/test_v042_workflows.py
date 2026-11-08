"""E2E business rules A/B/C/D. Synthetic patients only."""
import secrets
import pytest
from tests.test_workflows import client, token, prepare_visit


def _visit():
    pid,vid=prepare_visit()
    return pid,vid


def _service(category='lab',price=75000):
    payload={'name':'Dich vu mock '+secrets.token_hex(6),'price':price,'category':category}
    r=client.post('/api/catalog/services',headers=token('quanly'),json=payload)
    assert r.status_code==201,r.text
    return r.json()['id']


def _medical(vid):
    r=client.put(f'/api/visits/{vid}/clinical',headers=token('bs_noi'),json={'version':0,'diagnosis':'Benh gia lap can kiem tra'})
    assert r.status_code==200,r.text


def test_a_order_priced_once_and_cancel_manager_approval():
    _,v=_visit(); sid=_service(price=85000)
    doc=token('bs_noi');cash=token('thungan'); mgr=token('quanly')
    before=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']
    r=client.post('/api/orders',headers=doc,json={'visit_id':v,'category':'lab','service_id':sid,'request_key':secrets.token_hex(12)})
    assert r.status_code==201,r.text; order=r.json()['id'];assert r.json()['charge_amount']==85000
    after=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']
    assert after-before==85000
    lines=client.get(f'/api/charges/{v}',headers=cash).json()
    assert len([x for x in lines if x['source_type']=='order' and x['source_id']==order])==1
    r=client.post(f'/api/orders/{order}/request-cancel',headers=doc,json={'reason':'Chi dinh sai va can huy'})
    assert r.status_code==201,r.text;rid=r.json()['id']
    assert next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']==after
    assert client.post(f'/api/orders/cancellation-requests/{rid}/review',headers=doc,json={'approve':True}).status_code==403
    assert client.post(f'/api/orders/cancellation-requests/{rid}/review',headers=mgr,json={'approve':True}).status_code==200
    assert next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']==before
    assert client.post(f'/api/orders/cancellation-requests/{rid}/review',headers=mgr,json={'approve':True}).status_code==409


def test_a_invalid_cls_price_mapping_is_rejected():
    _,v=_visit();sid=_service(category='xray')
    bad=client.post('/api/orders',headers=token('bs_noi'),json={'visit_id':v,'category':'lab','service_id':sid,'request_key':secrets.token_hex(12)})
    assert bad.status_code==422


def test_b_stock_dispense_charge_once_and_no_double_issue():
    _,v=_visit(); _medical(v)
    doc=token('bs_noi');pharm=token('duoc');mgr=token('quanly');cash=token('thungan')
    meds=client.get('/api/dispensable-medicines',headers=doc).json()
    med=next(x for x in meds if x['name'].startswith('Thuoc') or x['name'].startswith('Thuốc'))
    pre=client.get('/api/stock',headers=pharm).json()
    before=sum(r['quantity'] for r in pre if r['name']==med['name'])
    assert client.put(f"/api/medicines/{med['id']}/price",headers=pharm,json={'unit_price':12000}).status_code==403
    assert client.put(f"/api/medicines/{med['id']}/price",headers=mgr,json={'unit_price':12000}).status_code==200
    rx=client.post('/api/prescriptions',headers=doc,json={'visit_id':v,'items':[{'medicine_id':med['id'],'quantity':3,'directions':'Uong thu nghiem'}]})
    assert rx.status_code==201,rx.text
    rid=rx.json()['id']
    due_before=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']
    result=client.post(f'/api/prescriptions/{rid}/dispense',headers=pharm)
    assert result.status_code==201,result.text
    assert result.json()['total']==36000
    assert client.post(f'/api/prescriptions/{rid}/dispense',headers=pharm).status_code==409
    after=sum(r['quantity'] for r in client.get('/api/stock',headers=pharm).json() if r['name']==med['name'])
    assert before-after==3
    due_after=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']
    assert due_after-due_before==36000
    assert client.post('/api/payments',headers=cash,json={'visit_id':v,'amount':36000,'method':'cash','idempotency_key':secrets.token_hex(10)}).status_code==201


def test_b_unpriced_or_missing_stock_has_no_side_effects():
    _,v=_visit();_medical(v)
    d=token('bs_noi');pharm=token('duoc');cash=token('thungan')
    meds=client.get('/api/dispensable-medicines',headers=d).json()
    med=next(x for x in meds if not x['unit_price'])
    rx=client.post('/api/prescriptions',headers=d,json={'visit_id':v,'items':[{'medicine_id':med['id'],'quantity':1}]})
    assert rx.status_code==201,rx.text
    bid=rx.json()['id']
    assert client.post(f'/api/prescriptions/{bid}/dispense',headers=pharm).status_code==409
    assert not any(x['prescription_id']==bid for x in client.get('/api/dispensations',headers=pharm).json())


def test_c_nurse_only_assigned_visit_and_vitals_only():
    pid,v=_visit();d=token('bs_noi');n=token('dieuduong')
    visible=[x['id'] for x in client.get('/api/visits',headers=n).json()]
    assert v not in visible
    assert client.get(f'/api/visits/{v}',headers=n).status_code==403
    assert client.put(f'/api/visits/{v}/vitals',headers=n,json={'vitals':'Mạch 80 l/p','version':0}).status_code==403
    nurses=client.get('/api/nurses',headers=d).json();nid=nurses[0]['id']
    assert client.post(f'/api/visits/{v}/nurses',headers=d,json={'nurse_id':nid}).status_code==201
    assert v in [x['id'] for x in client.get('/api/visits',headers=n).json()]
    response=client.get(f'/api/visits/{v}',headers=n)
    assert response.status_code==200,response.text
    assert response.json().get('diagnosis') is None
    assert client.put(f'/api/visits/{v}/vitals',headers=n,json={'vitals':'Mạch 80 l/p; HA 120/80 mmHg','version':0}).status_code==200
    assert client.put(f'/api/visits/{v}/vitals',headers=n,json={'vitals':'Mạch 90 l/p','version':0}).status_code==409
    assert client.put(f'/api/visits/{v}/clinical',headers=n,json={'version':1,'diagnosis':'Khong duoc phep'}).status_code==403
    assert client.get(f'/api/visits/{v}',headers=d).json()['vitals'].startswith('Mạch 80')


def test_d_completion_freezes_record_and_addenda_review():
    _,v=_visit();d=token('bs_noi');mgr=token('quanly');n=token('dieuduong')
    assert client.post(f'/api/visits/{v}/complete',headers=d).status_code==409
    _medical(v)
    res=client.post(f'/api/visits/{v}/complete',headers=d)
    assert res.status_code==200,res.text
    assert client.post(f'/api/visits/{v}/complete',headers=d).status_code==409
    assert client.put(f'/api/visits/{v}/clinical',headers=d,json={'version':res.json()['version'],'diagnosis':'Xoa chan doan'}).status_code==409
    assert client.post('/api/orders',headers=d,json={'visit_id':v,'category':'lab','name':'Xet nghiem cu'}).status_code==409
    assert client.post('/api/prescriptions',headers=d,json={'visit_id':v,'drug_lines':'Thuoc gi'}).status_code==409
    report=client.post(f'/api/visits/{v}/addenda',headers=d,json={'reason':'Bo sung khi kiem tra','content':'Chi tiet bo sung khong thay doi phieu goc'})
    assert report.status_code==201,report.text
    addid=report.json()['id']
    assert client.post(f'/api/visits/addenda/{addid}/review',headers=mgr,json={'approve':True}).status_code==200
    assert client.get(f'/api/visits/{v}',headers=d).json()['diagnosis']=='Benh gia lap can kiem tra'
    assert client.get(f'/api/visits/{v}/addenda',headers=d).json()[0]['status']=='approved'


def test_d_cannot_complete_with_pending_order():
    _,v=_visit();_medical(v);d=token('bs_noi')
    order=client.post('/api/orders',headers=d,json={'visit_id':v,'category':'lab','name':'Order chua duyet'})
    assert order.status_code==201
    assert client.post(f'/api/visits/{v}/complete',headers=d).status_code==409


def test_a_retry_same_order_request_key_does_not_bill_twice():
    _,v=_visit();sid=_service(price=99000);d=token('bs_noi');cash=token('thungan')
    body={'visit_id':v,'category':'lab','service_id':sid,'request_key':secrets.token_hex(12)}
    before=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']
    first=client.post('/api/orders',headers=d,json=body)
    again=client.post('/api/orders',headers=d,json=body)
    assert first.status_code==201 and again.status_code==201
    assert first.json()['id']==again.json()['id'] and again.json()['status']=='already_recorded'
    after=next(x for x in client.get('/api/dues',headers=cash).json() if x['visit_id']==v)['charged']
    assert after-before==99000
    bad=client.post('/api/orders',headers=d,json={**body,'category':'ecg'})
    assert bad.status_code==409
