"""v0.5 business acceptance: synthetic data only, real PostgreSQL transactions."""
from concurrent.futures import ThreadPoolExecutor
import json,secrets
from io import BytesIO
import pytest
from pypdf import PdfReader
from docx import Document
from .conftest import client_for,db,IDS


def service(clients,price=45000):
    r=clients['manager'].post('/api/catalog/services',json={'name':'Dịch vụ giả lập '+secrets.token_hex(4),'code':'DV'+secrets.token_hex(4),'category':'lab','price':price})
    assert r.status_code==201,r.text
    return r.json()['id']


def order(clients,visit,draft=False):
    body={'visit_id':visit,'category':'lab','service_id':service(clients),'request_key':secrets.token_hex(12),'defer_approval':draft}
    r=clients['doctor'].post('/api/orders',json=body);assert r.status_code==201,r.text
    return r.json()['id'],body


def medical(clients,visit):
    d=clients['doctor'];v=d.get(f'/api/visits/{visit}').json()
    r=d.put(f'/api/visits/{visit}/clinical',json={'version':v['version'],'diagnosis':'Chẩn đoán giả lập v0.5','treatment':'Hướng xử trí giả lập'})
    assert r.status_code==200,r.text


def medicine(clients,quantity=40):
    m=clients['manager'].post('/api/catalog/medicines',json={'name':'Thuốc thường giả lập '+secrets.token_hex(4),'base_unit':'viên'}).json()['id']
    assert clients['manager'].put(f'/api/medicines/{m}/price',json={'unit_price':1000}).status_code==200
    assert clients['pharmacy'].post('/api/stock/receipts',json={'medicine_id':m,'lot_number':'LOT-'+secrets.token_hex(4),'expiry_date':'2029-01-01','quantity':quantity}).status_code==201
    return m


def rx(clients,visit,mid,qty=4,unit=None):
    medical(clients,visit)
    r=clients['doctor'].post('/api/prescriptions',json={'visit_id':visit,'items':[{'medicine_id':mid,'quantity':qty,'unit_id':unit,'directions':'Chỉ dùng thử nghiệm'}]})
    assert r.status_code==201,r.text
    return r.json()['id']


def state(clients,visit):return clients['cashier'].get(f'/api/visits/{visit}/settlement').json()


def test_a_draft_authorization_and_request_retry_exact_once(clients,visit):
    initial=state(clients,visit)['billing']['charged'];oid,body=order(clients,visit,True)
    assert state(clients,visit)['billing']['charged']==initial
    repeat=clients['doctor'].post('/api/orders',json=body)
    assert repeat.status_code==201 and repeat.json()['id']==oid
    assert clients['technician'].put(f'/api/orders/{oid}/result',json={'result_text':'Không được thực hiện trước duyệt'}).status_code==409
    assert clients['cashier'].post(f'/api/orders/{oid}/authorize').status_code==403
    with ThreadPoolExecutor(max_workers=3) as executor:
        responses=list(executor.map(lambda _:clients['doctor'].post(f'/api/orders/{oid}/authorize'),range(3)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert state(clients,visit)['billing']['charged']==initial+45000
    with db() as c:assert c.execute("SELECT COUNT(*) FROM charge_sources WHERE source_type='order' AND source_id=?",(oid,)).fetchone()[0]==1
    assert state(clients,visit)['clinical_status']=='waiting_results'


def test_a_catalog_active_snapshot_reprice_and_advance_refund(clients,visit):
    oid,body=order(clients,visit);sid=body['service_id']
    manager=clients['manager'];doc=clients['doctor'];cash=clients['cashier']
    assert manager.put(f'/api/catalog/services/{sid}',json={'code':'STOP'+str(sid),'name':'Ngừng dùng giả '+str(sid),'price':90000,'category':'lab','active':False}).status_code==200
    assert doc.post('/api/orders',json={**body,'request_key':secrets.token_hex(12)}).status_code==422
    assert state(clients,visit)['billing']['charged']==195000
    paid=cash.post('/api/payments',json={'visit_id':visit,'amount':250000,'method':'cash','idempotency_key':secrets.token_hex(12),'prepayment':True})
    assert paid.status_code==201,paid.text
    lines=cash.get(f'/api/charges/{visit}').json();cid=next(l['id'] for l in lines if l['source_type']=='order')
    change={'amount':20000,'reason':'Điều chỉnh giá giả lập đã đối soát','request_key':secrets.token_hex(12)}
    assert doc.post(f'/api/charges/{cid}/reprice',json=change).status_code==403
    assert manager.post(f'/api/charges/{cid}/reprice',json=change).status_code==200
    assert manager.post(f'/api/charges/{cid}/reprice',json=change).json()['status']=='already_recorded'
    assert manager.post(f'/api/charges/{cid}/reprice',json={**change,'amount':19000}).status_code==409
    assert state(clients,visit)['billing']['refund_due']==80000
    proposal=cash.post('/api/adjustments',json={'visit_id':visit,'payment_id':paid.json()['id'],'kind':'refund','amount':80000,'reason':'Hoàn phần ứng dư sau điều chỉnh'})
    assert proposal.status_code==201,proposal.text
    aid=proposal.json()['id']
    assert manager.post(f'/api/adjustments/{aid}/review',json={'approve':True}).status_code==200
    assert state(clients,visit)['billing']['paid']==170000
    with db() as c:assert c.execute('SELECT amount FROM charges WHERE id=?',(cid,)).fetchone()[0]==45000


def test_b_conversion_fefo_concurrent_dispense_and_partial_return(clients,visit):
    mid=medicine(clients,40)
    unit=clients['manager'].post(f'/api/medicines/{mid}/units',json={'name':'vỉ','base_factor':10}).json()['id']
    rid=rx(clients,visit,mid,2,unit)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(lambda _:clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense'),range(3)))
    assert sorted(r.status_code for r in results)==[201,409,409]
    result=next(r.json() for r in results if r.status_code==201)
    assert result['total']==20000
    assert state(clients,visit)['billing']['charged']==170000
    item=clients['pharmacy'].get('/api/dispensations/'+str(result['dispensation_id'])+'/items').json()[0]
    request={'reason':'Trả thuốc giả lập nguyên trạng để cách ly','request_key':secrets.token_hex(12),'items':[{'dispensation_item_id':item['id'],'quantity':5}]}
    r=clients['pharmacy'].post('/api/dispensations/'+str(result['dispensation_id'])+'/returns',json=request)
    assert r.status_code==201,r.text;ret=r.json()['id']
    assert clients['pharmacy'].post('/api/dispensations/'+str(result['dispensation_id'])+'/returns',json=request).json()['id']==ret
    with ThreadPoolExecutor(max_workers=2) as executor:
        reviews=list(executor.map(lambda _:clients['manager'].post(f'/api/medication-returns/{ret}/review',json={'approve':True}),range(2)))
    assert sorted(r.status_code for r in reviews)==[200,409]
    assert state(clients,visit)['billing']['charged']==165000
    with db() as c:
        assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=? AND quarantined=0',(mid,)).fetchone()[0]==20
        assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=? AND quarantined=1',(mid,)).fetchone()[0]==5
    bad={**request,'request_key':secrets.token_hex(12),'items':[{'dispensation_item_id':item['id'],'quantity':16}]}
    assert clients['pharmacy'].post('/api/dispensations/'+str(result['dispensation_id'])+'/returns',json=bad).status_code==409


def test_b_duplicate_rx_lines_shortage_rolls_back_all(clients,visit):
    mid=medicine(clients,5);medical(clients,visit)
    r=clients['doctor'].post('/api/prescriptions',json={'visit_id':visit,'items':[{'medicine_id':mid,'quantity':3},{'medicine_id':mid,'quantity':3}]})
    assert r.status_code==201
    rid=r.json()['id'];before=state(clients,visit)['billing']
    assert clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense').status_code==409
    assert state(clients,visit)['billing']==before
    with db() as c:
        assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=?',(mid,)).fetchone()[0]==5
        assert not c.execute('SELECT 1 FROM dispensations WHERE prescription_id=?',(rid,)).fetchone()


def test_b_cancel_undispensed_preserves_inventory(clients,visit):
    mid=medicine(clients,9);rid=rx(clients,visit,mid)
    assert clients['pharmacy'].post(f'/api/prescriptions/{rid}/cancel',json={'reason':'Hủy đơn nháp giả lập trước cấp'}).status_code==200
    assert clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense').status_code==409
    with db() as c:assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=?',(mid,)).fetchone()[0]==9


def test_c_care_task_ownership_history_and_complete_preconditions(clients,visit):
    doc=clients['doctor'];n=client_for('nurse')
    try:
        assert n.get(f'/api/visits/{visit}/care').status_code==403
        assert doc.post(f'/api/visits/{visit}/nurses',json={'nurse_id':IDS['nurse']}).status_code==201
        content={'content':'Theo dõi chăm sóc giả lập','request_key':secrets.token_hex(12)}
        assert n.post(f'/api/visits/{visit}/care-notes',json=content).status_code==201
        task=doc.post(f'/api/visits/{visit}/nursing-tasks',json={**content,'request_key':secrets.token_hex(12),'nurse_id':IDS['nurse']})
        assert task.status_code==201,task.text;tid=task.json()['id']
        medical(clients,visit)
        v=doc.get(f'/api/visits/{visit}').json()
        assert doc.post(f'/api/visits/{visit}/complete',json={'version':v['version']}).status_code==409
        assert n.post(f'/api/nursing-tasks/{tid}/execute',json={'content':'Đã theo dõi, chỉ dữ liệu giả'}).status_code==200
        assert n.post(f'/api/nursing-tasks/{tid}/execute',json={'content':'Gửi trùng'}).status_code==409
        assert n.post(f'/api/orders/1/approve').status_code==403
        assert n.put(f'/api/visits/{visit}/clinical',json={'version':v['version'],'diagnosis':'Trái quyền'}).status_code==403
        assert doc.post(f'/api/visits/{visit}/complete',json={'version':v['version']}).status_code==200
        assert n.post(f'/api/visits/{visit}/care-notes',json={**content,'request_key':secrets.token_hex(12)}).status_code==409
        notes=doc.get(f'/api/visits/{visit}/care').json()
        assert notes['notes'][0]['nurse_id']==IDS['nurse'] and notes['tasks'][0]['executed_at']
    finally:n.close()


def test_d_lock_versions_addendum_prints_without_mutating_original(clients,visit):
    doc=clients['doctor'];manager=clients['manager'];medical(clients,visit)
    v=doc.get(f'/api/visits/{visit}').json();version=v['version']
    assert doc.post(f'/api/visits/{visit}/complete',json={'version':version-1}).status_code==409
    assert doc.post(f'/api/visits/{visit}/complete',json={'version':version}).status_code==200
    snapshot=doc.get(f'/api/visits/{visit}').json()
    assert doc.put(f'/api/visits/{visit}/clinical',json={'version':snapshot['version'],'diagnosis':'Không sửa lén'}).status_code==409
    a=doc.post(f'/api/visits/{visit}/addenda',json={'reason':'Đính chính dữ liệu giả lập có hậu kiểm','content':'APPENDIX_V050_MARKER giữ nguyên nội dung chẩn đoán gốc'})
    assert a.status_code==201,a.text;aid=a.json()['id']
    assert manager.post(f'/api/visits/addenda/{aid}/review',json={'approve':True}).status_code==200
    latest=doc.get(f'/api/visits/{visit}').json()
    assert latest['diagnosis']==snapshot['diagnosis'] and latest['version']==snapshot['version']+1
    revisions=doc.get(f'/api/visits/{visit}/revisions').json()
    assert len({r['version'] for r in revisions})==len(revisions)>=3
    for fmt in ('pdf','docx'):
        result=doc.get(f'/api/forms/visit/{visit}?fmt={fmt}');assert result.status_code==200,result.text
        if fmt=='pdf':text=' '.join(p.extract_text() or '' for p in PdfReader(BytesIO(result.content)).pages)
        else:
            word=Document(BytesIO(result.content));text=' '.join(p.text for p in word.paragraphs)
        assert 'APPENDIX_V050_MARKER' in text
    assert state(clients,visit)['clinical_status']=='completed'
    assert state(clients,visit)['payment_status']=='due'


def test_d_manager_cancel_keeps_financial_refund_separate(clients,visit):
    cash=clients['cashier'];manager=clients['manager']
    pay=cash.post('/api/payments',json={'visit_id':visit,'amount':150000,'method':'cash','idempotency_key':secrets.token_hex(12)})
    assert pay.status_code==201
    assert manager.post(f'/api/visits/{visit}/cancel',json={'reason':'Hủy lượt giả lập trước khám theo đối soát'}).status_code==200
    assert state(clients,visit)['billing']['refund_due']==150000
    assert cash.post('/api/payments',json={'visit_id':visit,'amount':1000,'method':'cash','idempotency_key':secrets.token_hex(12),'prepayment':True}).status_code==409
    assert clients['doctor'].post('/api/visits/'+str(visit)+'/complete',json={'version':1}).status_code==409


def actor(clients,roles):
    username='fake_v050_'+secrets.token_hex(5);password=secrets.token_urlsafe(24)
    r=clients['admin'].post('/api/accounts',json={'username':username,'full_name':'Nhân viên giả lập kiểm soát','password':password,'roles':roles})
    assert r.status_code==201,r.text
    c=client_for();login=c.post('/api/login',json={'username':username,'password':password});assert login.status_code==200,login.text
    c.headers['X-CSRF-Token']=c.cookies['__Host-clinic-csrf']
    return c,r.json()['id']


def test_controlled_separate_permissions_two_person_custody_and_return(clients):
    prescriber,pid=actor(clients,['doctor','controlled_prescriber'])
    reviewer,rid=actor(clients,['doctor','controlled_reviewer'])
    pharma,phid=actor(clients,['pharmacy','controlled_pharmacy'])
    manager,mid=actor(clients,['manager','controlled_reviewer'])
    try:
        normal=clients['manager'].post('/api/catalog/medicines',json={'name':'Không được tự tạo kiểm soát','base_unit':'viên','controlled':True})
        assert normal.status_code==403
        med=manager.post('/api/catalog/medicines',json={'name':'Thuốc kiểm soát chỉ giả lập '+secrets.token_hex(4),'base_unit':'viên','controlled':True})
        assert med.status_code==201,med.text;medicine_id=med.json()['id']
        assert clients['manager'].post(f'/api/medicines/{medicine_id}/units',json={'name':'hộp','base_factor':10}).status_code==403
        assert manager.put(f'/api/medicines/{medicine_id}/price',json={'unit_price':2000,'reason':'Duyệt giá giả lập có kiểm soát'}).status_code==200
        receipt={'medicine_id':medicine_id,'lot_number':'CONTROL-FAKE-'+secrets.token_hex(4),'expiry_date':'2029-01-01','quantity':5,'reason':'Nhập thuốc giả lập theo sổ riêng','register_ref':'SO-GIA-LAP-001','request_key':secrets.token_hex(12)}
        assert clients['pharmacy'].post('/api/controlled-receipts',json=receipt).status_code==403
        stock=pharma.post('/api/controlled-receipts',json=receipt);assert stock.status_code==201,stock.text
        requestid=stock.json()['id']
        assert manager.post(f'/api/controlled-receipts/{requestid}/review',json={'approve':True}).status_code==200
        assert pharma.post('/api/controlled-receipts',json=receipt).json()['id']==requestid
        patient=clients['reception'].post('/api/patients',json={'full_name':'Người giả lập thuốc kiểm soát','date_of_birth':'1995-01-01','sex':'Nữ','phone':'0900000022'}).json()['id']
        vid=clients['reception'].post('/api/visits',json={'patient_id':patient,'doctor_id':pid,'service_id':1}).json()['id']
        assert prescriber.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập cần quy trình kiểm soát'}).status_code==200
        prescription=prescriber.post('/api/prescriptions',json={'visit_id':vid,'items':[{'medicine_id':medicine_id,'quantity':2,'directions':'KHÔNG ĐIỀU TRỊ'}]})
        assert prescription.status_code==201,prescription.text;rxid=prescription.json()['id']
        assert clients['pharmacy'].post(f'/api/prescriptions/{rxid}/cancel',json={'reason':'Không được hủy thuốc kiểm soát bằng quyền thường'}).status_code==403
        assert clients['manager'].post(f'/api/visits/{vid}/cancel',json={'reason':'Không được hủy lượt để vượt quyền kiểm soát'}).status_code==403
        assert pharma.post(f'/api/prescriptions/{rxid}/dispense').status_code==409
        assert prescriber.post(f'/api/visits/{vid}/complete',json={'version':1}).status_code==409
        queue=reviewer.get('/api/controlled-review-queue');assert queue.status_code==200
        assert any(x['id']==rxid for x in queue.json())
        assert reviewer.post(f'/api/prescriptions/{rxid}/controlled-approval',json={'reason':'Duyệt độc lập đơn thuốc giả lập','register_ref':'SO-GIA-LAP-RX'}).status_code==200
        assert clients['pharmacy'].post(f'/api/prescriptions/{rxid}/dispense').status_code==403
        assert prescriber.post(f'/api/visits/{vid}/complete',json={'version':1}).status_code==200
        disp=pharma.post(f'/api/prescriptions/{rxid}/dispense');assert disp.status_code==201,disp.text
        item=disp.json()['lots'][0]
        ret=pharma.post('/api/dispensations/'+str(disp.json()['dispensation_id'])+'/returns',json={'reason':'Trả kiểm soát giả lập vào cách ly','request_key':secrets.token_hex(12),'items':[{'dispensation_item_id':item['id'],'quantity':1}]})
        assert ret.status_code==201,ret.text
        assert clients['manager'].post('/api/medication-returns/'+str(ret.json()['id'])+'/review',json={'approve':True}).status_code==403
        assert manager.post('/api/medication-returns/'+str(ret.json()['id'])+'/review',json={'approve':True}).status_code==200
        ledger=manager.get('/api/controlled-ledger').json()
        own=[x for x in ledger if x['medicine_id']==medicine_id]
        assert {x['event'] for x in own}=={'receipt','dispense','return_quarantine'}
        assert all(x['register_ref'] for x in own)
    finally:
        for c in (prescriber,reviewer,pharma,manager):c.close()


def test_return_reservations_rejection_full_credit_and_refund(clients,visit):
    mid=medicine(clients,12);rid=rx(clients,visit,mid,4)
    disp=clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense').json();did=disp['dispensation_id'];iid=disp['lots'][0]['id']
    paid=clients['cashier'].post('/api/payments',json={'visit_id':visit,'amount':154000,'method':'cash','idempotency_key':secrets.token_hex(12)}).json()['id']
    def proposal(qty):
        return clients['pharmacy'].post(f'/api/dispensations/{did}/returns',json={'reason':'Trả thuốc giả lập kiểm tra đối soát','request_key':secrets.token_hex(12),'items':[{'dispensation_item_id':iid,'quantity':qty}]})
    pending=proposal(3);assert pending.status_code==201
    assert proposal(2).status_code==409 # Pending quantities reserve the original issue.
    assert clients['manager'].post('/api/medication-returns/'+str(pending.json()['id'])+'/review',json={'approve':False}).status_code==200
    approved=proposal(4);assert approved.status_code==201
    assert clients['manager'].post('/api/medication-returns/'+str(approved.json()['id'])+'/review',json={'approve':True}).status_code==200
    assert state(clients,visit)['billing']['refund_due']==4000
    refund=clients['cashier'].post('/api/adjustments',json={'visit_id':visit,'payment_id':paid,'kind':'refund','amount':4000,'reason':'Hoàn tiền thuốc sau trả toàn bộ giả lập'})
    assert refund.status_code==201,refund.text;aid=refund.json()['id']
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:clients['manager'].post(f'/api/adjustments/{aid}/review',json={'approve':True}),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    assert state(clients,visit)['billing']['refund_due']==0
    with db() as c:
        assert c.execute('SELECT status FROM prescriptions WHERE id=?',(rid,)).fetchone()[0]=='returned'
        assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=? AND quarantined=0',(mid,)).fetchone()[0]==8
        assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=? AND quarantined=1',(mid,)).fetchone()[0]==4


def test_independent_addenda_stale_review_and_scoped_nurse_task(clients,visit):
    doc=clients['doctor'];manager=clients['manager'];n,nid=actor(clients,['nurse'])
    assigned=client_for('nurse')
    try:
        assert doc.post(f'/api/visits/{visit}/nurses',json={'nurse_id':IDS['nurse']}).status_code==201
        body={'nurse_id':IDS['nurse'],'content':'Theo dõi giả lập riêng','request_key':secrets.token_hex(12)}
        tid=doc.post(f'/api/visits/{visit}/nursing-tasks',json=body).json()['id']
        assert n.post(f'/api/nursing-tasks/{tid}/execute',json={'content':'Không được phân công'}).status_code==403
        assert n.get(f'/api/visits/{visit}/care').status_code==403
        assert assigned.get(f'/api/visits/{visit}/settlement').json()['billing']['due'] is None
        assert doc.post(f'/api/nursing-tasks/{tid}/cancel',json={'reason':'Hủy y lệnh giả lập trước hoàn tất'}).status_code==200
        medical(clients,visit);version=doc.get(f'/api/visits/{visit}').json()['version']
        assert doc.post(f'/api/visits/{visit}/complete',json={'version':version}).status_code==200
        data={'reason':'Bổ sung sau khóa có đối chiếu giả lập','content':'Ghi chú giả lập không thay nội dung gốc'}
        a=doc.post(f'/api/visits/{visit}/addenda',json=data).json()['id'];b=doc.post(f'/api/visits/{visit}/addenda',json=data).json()['id']
        assert manager.post(f'/api/visits/addenda/{a}/review',json={'approve':True}).status_code==200
        assert manager.post(f'/api/visits/addenda/{b}/review',json={'approve':True}).status_code==409
        assert assigned.put(f'/api/visits/{visit}/vitals',json={'version':version,'vitals':'Không sửa sau khóa'}).status_code==409
    finally:n.close();assigned.close()


def test_return_rolls_back_when_discount_exceeds_remaining_then_explicit_reverse(clients,visit):
    mid=medicine(clients,10);rid=rx(clients,visit,mid,4)
    disp=clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense').json();did=disp['dispensation_id'];iid=disp['lots'][0]['id']
    adj=clients['cashier'].post('/api/adjustments',json={'visit_id':visit,'kind':'discount','amount':153000,'reason':'Giảm phí giả lập kiểm tra hoàn tác có lý do'})
    assert adj.status_code==201,adj.text;aid=adj.json()['id']
    assert clients['manager'].post(f'/api/adjustments/{aid}/review',json={'approve':True}).status_code==200
    ret=clients['pharmacy'].post(f'/api/dispensations/{did}/returns',json={'reason':'Trả giả lập cần đối soát giảm phí','request_key':secrets.token_hex(12),'items':[{'dispensation_item_id':iid,'quantity':4}]}).json()['id']
    assert clients['manager'].post(f'/api/medication-returns/{ret}/review',json={'approve':True}).status_code==409
    with db() as c:
        assert not c.execute('SELECT 1 FROM stock_lots WHERE medicine_id=? AND quarantined=1',(mid,)).fetchone()
        assert not c.execute('SELECT 1 FROM charge_credits cc JOIN charges ch ON ch.id=cc.charge_id WHERE ch.visit_id=?',(visit,)).fetchone()
    assert clients['manager'].post(f'/api/adjustments/{aid}/reverse',json={'reason':'Hoàn tác giảm phí trước khi duyệt trả thuốc'}).status_code==200
    assert clients['manager'].post(f'/api/medication-returns/{ret}/review',json={'approve':True}).status_code==200
    assert state(clients,visit)['billing']['charged']==150000
