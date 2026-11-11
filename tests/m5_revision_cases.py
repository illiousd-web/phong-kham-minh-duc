"""M5 follow-up: closed encounter remains closed; all fixtures are synthetic."""
import io,json,secrets
from docx import Document
import pymupdf


def setup_report(clients,ids,db,service):
    a,r,d,t=[clients[k] for k in ('admin','reception','doctor','technician')];suffix=secrets.token_hex(4)
    definition={'code':'REV-'+suffix,'name':'Chỉ số sửa tiếp giả lập '+suffix,'abbreviation':'FAKE','group_name':'hematology','result_type':'number','unit':'đv giả lập','decimals':2,'references':[{'sex':'chung','lower_value':'4','upper_value':'5'}]}
    tid=a.post('/api/lab/catalog',json=definition).json()['id']
    with db(True) as c:
        c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)',('Dịch vụ sửa tiếp giả lập '+suffix,12345,'M5REV-'+suffix));sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(sid,'lab'))
    assert a.put('/api/lab/services/'+str(sid),json={'test_ids':[tid]}).status_code==200
    pid=r.post('/api/patients',json={'full_name':'Người sửa tiếp giả lập '+suffix,'date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':pid,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
    assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập'}).status_code==200
    oid=d.post('/api/orders',json={'visit_id':vid,'service_id':sid,'category':'lab','request_key':'m5-rev-'+suffix}).json()['id']
    rid=t.post(f'/api/lab/orders/{oid}/reports').json()['id']
    data={'version':0,'sample_at':'2026-01-02T08:00:00+07:00','result_at':'2026-01-02T09:00:00+07:00','items':[{'test_id':tid,'value':'5.004'}]}
    return pid,vid,oid,rid,tid,data


def document_text(response,fmt):
    assert response.status_code==200,response.text
    if fmt=='docx':
        d=Document(io.BytesIO(response.content));return ' '.join(p.text for p in d.paragraphs)+' '+' '.join(c.text for t in d.tables for r in t.rows for c in r.cells)
    with pymupdf.open(stream=response.content,filetype='pdf') as pdf:return ' '.join(p.get_text() for p in pdf)


def check_closed_correction(clients,ids,db,service):
    pid,vid,oid,rid,tid,data=setup_report(clients,ids,db,service);d,t,r=[clients[k] for k in ('doctor','technician','reception')];url=f'/api/lab/reports/{rid}'
    # The exact displayed value and its flag are identical on both sides of each bound.
    for version,(raw,shown,flag) in enumerate([('5.004','5,00',''),('5.006','5,01','H'),('3.996','4,00',''),('3.994','3,99','L'),('5.004','5,00','')]):
        data['version']=version;data['items'][0]['value']=raw
        assert t.put(url,json=data).status_code==200
        item=t.get(url).json()['items'][0]
        assert (item['raw_value'],item['display_value'],item['flag'])==(raw,shown,flag)
        assert item['reference_text']=='4,00 – 5,00'
        for fmt in ('docx','pdf'):
            text=document_text(t.get(url+'/form?group=hematology&fmt='+fmt),fmt)
            assert shown in text and '4,00 – 5,00' in text
    assert t.post(url+'/submit',json={'version':5}).status_code==200
    assert d.post(url+'/approve',json={'version':6}).status_code==200
    visit=d.get('/api/visits/'+str(vid)).json()
    assert d.post(f'/api/visits/{vid}/complete',json={'version':visit['version']}).status_code==200
    with db() as c:
        snapshot=c.execute('SELECT snapshot FROM lab_reports WHERE id=?',(rid,)).fetchone()[0]
        visit_before=dict(c.execute('SELECT * FROM visits WHERE id=?',(vid,)).fetchone())
    counts_before={role:clients[role].get('/api/queue-counts').json() for role in ('doctor','technician')}
    def still_closed():
        with db() as c:
            assert dict(c.execute('SELECT * FROM visits WHERE id=?',(vid,)).fetchone())==visit_before
            assert c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()[0]=='approved'
            assert c.execute('SELECT snapshot FROM lab_reports WHERE id=?',(rid,)).fetchone()[0]==snapshot
        assert oid not in [x['id'] for x in t.get('/api/orders').json()]
        assert vid not in [x['id'] for x in d.get('/api/doctor/queue').json()['visits']]
        current={role:clients[role].get('/api/queue-counts').json() for role in counts_before}
        assert current['doctor']['doctor']==counts_before['doctor']['doctor']
        assert current['technician']==counts_before['technician']
    new=t.post(url+'/adjust',json={'version':7,'reason':'Sửa sai sót giả lập sau đóng lượt'});assert new.status_code==201,new.text
    new_id=new.json()['id'];still_closed()
    def discover(client,status,expected):
        q=client.get(f'/api/lab/queue?visit_id={vid}&status={status}&limit=1').json()
        assert q['total']==expected and len(q['items'])==expected
        if expected:
            row=q['items'][0];assert row['order_id']==oid and row['visit_status']=='completed' and row['replaces_id']==rid
            return f"/api/lab/reports/{row['report_id']}"
    new_url=discover(t,'working',1);assert new_url.endswith('/'+str(new_id))
    correction={**data,'version':0,'items':[{'test_id':tid,'value':'5,006'}]}
    assert t.put(new_url,json=correction).status_code==200;still_closed();new_url=discover(t,'working',1)
    assert t.post(new_url+'/submit',json={'version':1}).status_code==200;still_closed()
    discover(t,'working',0);new_url=discover(d,'pending_review',1)
    assert clients['doctor2'].get(f'/api/lab/queue?visit_id={vid}&status=pending_review').json()['total']==0
    assert d.get('/api/queue-counts').json()['lab_pending_review']==counts_before['doctor']['lab_pending_review']+1
    q=d.get('/api/lab/queue?status=pending_review&limit=1').json();assert q['total']==d.get('/api/queue-counts').json()['lab_pending_review']
    rows=d.get('/api/orders',params={'visit_id':vid}).json();assert rows[0]['lab_report_status']=='pending_review'
    assert d.get(new_url+'/review').status_code==200
    assert clients['doctor2'].post(new_url+'/approve',json={'version':2}).status_code==403
    assert d.post(new_url+'/approve',json={'version':2}).status_code==200;still_closed()
    discover(d,'pending_review',0);discover(t,'working',0)
    assert d.get('/api/queue-counts').json()['lab_pending_review']==counts_before['doctor']['lab_pending_review']
    with db() as c:
        order=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone();assert '5,01' in order['result_text'] and '[H]' in order['result_text']
        details=c.execute("SELECT details FROM audit_log WHERE event='lab_adjusted_after_close' AND object_id=?",(new_id,)).fetchone()[0]
        assert json.loads(details)=={'old_report_id':rid,'new_report_id':new_id}
        frozen=json.loads(c.execute('SELECT snapshot FROM lab_reports WHERE id=?',(new_id,)).fetchone()[0])
        assert frozen['items'][0]['raw_value']=='5.006' and frozen['items'][0]['display_value']=='5,01' and frozen['items'][0]['flag']=='H'
    assert d.get(f'/api/lab/visits/{vid}/results').json()['adjusted_after_close']
    assert d.get(f'/api/lab/visits/{vid}/history/{tid}').json()[0]['adjusted_after_close']
    next_visit=r.post('/api/visits',json={'patient_id':pid,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
    history=d.get(f'/api/visits/{next_visit}/patient-history').json();assert next(x for x in history if x['id']==vid)['adjusted_after_close']
    for fmt in ('docx','pdf'):
        text=document_text(r.get(url+'/form?group=hematology&fmt='+fmt),fmt)
        assert 'ĐÃ ĐƯỢC THAY THẾ BỞI PHIẾU #'+str(new_id) in ' '.join(text.split())
    with db() as c:assert c.execute('SELECT snapshot FROM lab_reports WHERE id=?',(rid,)).fetchone()[0]==snapshot


def check_cancelled_writes(clients,ids,db,service):
    _,vid,_,rid,_,data=setup_report(clients,ids,db,service);t,d=clients['technician'],clients['doctor'];url=f'/api/lab/reports/{rid}'
    assert t.put(url,json=data).status_code==200
    assert t.post(url+'/submit',json={'version':1}).status_code==200
    assert d.post(url+'/approve',json={'version':2}).status_code==200
    child=t.post(url+'/adjust',json={'version':3,'reason':'Điều chỉnh giả lập trước hủy'}).json()['id'];path=f'/api/lab/reports/{child}'
    # Fault/state fixture only; no billing mutation or permission bypass in application code.
    with db(True) as c:c.execute("UPDATE visits SET status='cancelled' WHERE id=?",(vid,))
    with db() as c:before=[dict(x) for x in c.execute('SELECT * FROM lab_reports WHERE order_id=(SELECT order_id FROM lab_reports WHERE id=?) ORDER BY id',(rid,))]
    for response in [t.put(path,json=data),t.post(path+'/submit',json={'version':0}),d.post(path+'/approve',json={'version':0}),t.post(url+'/adjust',json={'version':3,'reason':'Thử ghi sau hủy giả lập'})]:assert response.status_code==409,response.text
    with db() as c:assert [dict(x) for x in c.execute('SELECT * FROM lab_reports WHERE order_id=(SELECT order_id FROM lab_reports WHERE id=?) ORDER BY id',(rid,))]==before


def check_preview_gate(clients):
    from app.m5_import import workbook,file_fingerprint
    from app.m5 import TestInput
    a=clients['admin'];suffix=secrets.token_hex(4)
    item=TestInput(code='PREVIEW-'+suffix,name='Danh mục xem trước giả lập',group_name='other')
    raw=workbook([item.model_dump()]);changed=workbook([{**item.model_dump(),'name':'Đã đổi tệp giả lập'}])
    def post(data,preview,fingerprint=None):
        form={'preview':str(preview).lower()}
        if fingerprint is not None:form['fingerprint']=fingerprint
        return a.post('/api/lab/catalog-import',files={'file':('fake.xlsx',data)},data=form)
    assert post(raw,False).status_code==422
    assert post(raw,False,file_fingerprint(raw)).status_code==422 # A computed hash alone is not a server-issued preview.
    preview=post(raw,True);assert preview.status_code==200
    proof=preview.json()['fingerprint'];assert proof==file_fingerprint(raw) and len(proof)==64
    assert post(changed,False,proof).status_code==422
    assert post(raw,False,'0'*64).status_code==422
    assert post(raw,False,proof).status_code==200
