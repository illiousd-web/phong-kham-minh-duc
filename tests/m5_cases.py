"""Synthetic M5 lifecycle, same assertions on SQLite and PostgreSQL."""
import io,json,secrets
from docx import Document
import pymupdf


def check_m5(clients,ids,db,service):
    a,r,d,t=[clients[k] for k in ('admin','reception','doctor','technician')]
    suffix=secrets.token_hex(4)
    test={'code':'FAKE-'+suffix,'name':'Chỉ số giả lập '+suffix,'abbreviation':'FAKE','group_name':'hematology','result_type':'number','unit':'đv giả lập','decimals':2,'print_order':1,'references':[{'sex':'chung','age_from':0,'age_to':1800,'lower_value':'100','upper_value':'200'},{'sex':'Nữ','age_from':0,'age_to':1800,'lower_value':'10','upper_value':'20'}]}
    for forbidden in (r,t,d):assert forbidden.post('/api/lab/catalog',json=test).status_code==403
    result=a.post('/api/lab/catalog',json=test);assert result.status_code==201,result.text
    tid=result.json()['id']
    other={**test,'code':'NOREF-'+suffix,'name':'Chỉ số không tham chiếu giả lập','group_name':'biochemistry','references':[]}
    oid=a.post('/api/lab/catalog',json=other).json()['id']
    choice={**other,'code':'QUAL-'+suffix,'name':'Chỉ số định tính giả lập','result_type':'choice','choices':['Mẫu A giả lập','Mẫu B giả lập'],'group_name':'urine','references':[{'sex':'chung','normal_value':'Mẫu A giả lập'}]}
    qid=a.post('/api/lab/catalog',json=choice).json()['id']
    with db(True) as c:
        c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)',('Dịch vụ xét nghiệm giả lập '+suffix,12345,'LAB-'+suffix));sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(sid,'lab'))
    assert a.put('/api/lab/services/'+str(sid),json={'test_ids':[tid,oid,qid]}).status_code==200
    assert r.put('/api/lab/services/'+str(sid),json={'test_ids':[]}).status_code==403
    patient=r.post('/api/patients',json={'full_name':'Người bệnh giả lập M5 '+suffix,'sex':'Nữ','date_of_birth':'2020-01-02','address':'Địa chỉ giả lập','phone':'0900000000'}).json()['id']
    visit=r.post('/api/visits',json={'patient_id':patient,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
    order=d.post('/api/orders',json={'visit_id':visit,'category':'lab','service_id':sid,'request_key':'m5-'+suffix});assert order.status_code==201,order.text
    order_id=order.json()['id']
    with db() as c:money_before=[tuple(x) for x in c.execute('SELECT label,amount FROM charges WHERE visit_id=? ORDER BY id',(visit,))]
    assert r.post(f'/api/lab/orders/{order_id}/reports').status_code==403
    opened=t.post(f'/api/lab/orders/{order_id}/reports');assert opened.status_code==201,opened.text
    rid=opened.json()['id'];url=f'/api/lab/reports/{rid}'
    assert len(t.get(url).json()['items'])==3
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=waiting_sample').json()['total']==1
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=working').json()['total']==0
    assert d.get(url).json()['items']==[]
    assert r.get(url).status_code==403
    assert d.get(url+'/review').status_code==409
    data={'version':0,'sample_at':'2026-01-01T17:00:00+00:00','result_at':'2026-01-02T01:00:00+07:00','comment':'Nhận xét giả lập','items':[{'test_id':tid,'value':'21,5','note':'Ghi chú giả lập'},{'test_id':oid,'value':'-4.1'},{'test_id':qid,'value':'Mẫu B giả lập'}]}
    assert r.put(url,json=data).status_code==403
    saved=t.put(url,json=data);assert saved.status_code==200,saved.text
    p=t.get(url).json();items={x['test_id']:x for x in p['items']}
    assert p['patient']['age_months']==72
    assert items[tid]['value']=='21.50' and items[tid]['flag']=='H' and items[tid]['reference']['sex']=='Nữ'
    assert items[oid]['flag']=='' and items[oid]['reference_text']=='Chưa có khoảng tham chiếu'
    assert items[qid]['flag']=='Bất thường'
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=working').json()['total']==1
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=waiting_sample').json()['total']==0
    assert t.post(url+'/submit',json={'version':1}).status_code==200
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=pending_review').json()['total']==1
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=approved').json()['total']==0
    assert d.get(url).json()['items']==[]
    listed=next(x for x in d.get('/api/orders',params={'visit_id':visit}).json() if x['id']==order_id)
    assert listed['result_text'] is None and listed['file_name'] is None
    assert d.get(url+'/form?group=hematology').status_code==403
    review=d.get(url+'/review');assert review.status_code==200,review.text
    assert len(review.json()['items'])==3
    assert r.get('/api/lab/queue?status=pending_review').json()['total']==0
    assert t.post(url+'/approve',json={'version':2}).status_code==403
    assert clients['doctor2'].post(url+'/approve',json={'version':2}).status_code==403
    assert d.get(f'/api/lab/visits/{visit}/results').json()['reports']==[]
    # No bypass through the legacy text/approval APIs.
    assert t.put(f'/api/orders/{order_id}/result',json={'version':0,'result_text':'không được sửa'}).status_code==409
    assert d.post(f'/api/orders/{order_id}/approve').status_code==409
    approved=d.post(url+'/approve',json={'version':2});assert approved.status_code==200,approved.text
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=approved').json()['total']==1
    assert t.get(f'/api/lab/queue?visit_id={visit}&status=pending_review').json()['total']==0
    snapshot=d.get(url).json()
    assert snapshot['status']=='approved' and snapshot['performer_name'] and snapshot['approver_name']
    assert t.put(url,json={**data,'version':3}).status_code==409
    assert len(d.get(f'/api/lab/visits/{visit}/results').json()['reports'])==1
    assert r.get(url).status_code==200
    with db() as c:old_snapshot=c.execute('SELECT snapshot FROM lab_reports WHERE id=?',(rid,)).fetchone()[0]
    changed={**test,'active':False,'name':'Tên đã sửa giả lập','unit':'đơn vị mới giả lập','references':[{'sex':'chung','lower_value':'0','upper_value':'1000'}]}
    assert a.put('/api/lab/catalog/'+str(tid),json=changed).status_code==200
    assert d.get(url).json()==snapshot
    assert a.put('/api/lab/services/'+str(sid),json={'test_ids':[tid]}).status_code==422
    for fmt in ('docx','pdf'):
        for group in ('hematology','biochemistry','urine'):
            res=r.get(url+'/form?group='+group+'&fmt='+fmt);assert res.status_code==200,res.text
            if fmt=='docx':
                doc=Document(io.BytesIO(res.content));text=' '.join(p.text for p in doc.paragraphs)+' '+' '.join(c.text for table in doc.tables for row in table.rows for c in row.cells)
            else:
                with pymupdf.open(stream=res.content,filetype='pdf') as pdf:text=' '.join(page.get_text() for page in pdf)
            text=' '.join(text.split())
            for word in ['Tên chỉ số','Kết quả','Cờ','Khoảng tham chiếu','Đơn vị','Người thực hiện','Người duyệt','Nhận xét giả lập','2026']:
                assert word in text,(fmt,group,word,text)
            if group=='hematology':assert '21,50' in text and '10,00 – 20,00' in text and test['name'] in text and other['name'] not in text
    assert r.get(url+'/form?group=other').status_code==404
    assert d.post(url+'/approve',json={'version':3}).status_code==409
    assert r.post(url+'/adjust',json={'version':3,'reason':'Lý do giả lập'}).status_code==403
    assert t.post(url+'/adjust',json={'version':3,'reason':'ngắn'}).status_code==422
    adjusted=t.post(url+'/adjust',json={'version':3,'reason':'Điều chỉnh giả lập 000012345678'});assert adjusted.status_code==201,adjusted.text
    new=adjusted.json()['id'];new_url=f'/api/lab/reports/{new}'
    assert t.post(url+'/adjust',json={'version':3,'reason':'Điều chỉnh lần hai giả lập'}).status_code==409
    correction={**data,'version':0,'items':[{**x,'value':'5'} if x['test_id']==tid else x for x in data['items']]}
    assert t.put(new_url,json=correction).status_code==200
    assert t.post(new_url+'/submit',json={'version':1}).status_code==200
    assert d.post(new_url+'/approve',json={'version':2}).status_code==200
    assert d.get(url).json()==snapshot
    with db() as c:
        assert c.execute('SELECT snapshot FROM lab_reports WHERE id=?',(rid,)).fetchone()[0]==old_snapshot
        assert [tuple(x) for x in c.execute('SELECT label,amount FROM charges WHERE visit_id=? ORDER BY id',(visit,))]==money_before
    current=d.get(f'/api/lab/visits/{visit}/results').json()['reports'];assert [x['id'] for x in current]==[new]
    history=d.get(f'/api/lab/visits/{visit}/history/{tid}').json();assert history[0]['value']=='5.00' and len(history)==1
    pdf=r.get(new_url+'/form?group=hematology&fmt=pdf')
    with pymupdf.open(stream=pdf.content,filetype='pdf') as f:text=' '.join(p.get_text() for p in f)
    assert 'BẢN ĐIỀU CHỈNH' in text and 'XN-'+str(rid) in text
    q=t.get('/api/lab/queue?status=approved&limit=1').json()
    assert q['total']>=1 and len(q['items'])==1
    q2=t.get('/api/lab/queue?status=approved&limit=1&offset='+str(q['total'])).json();assert q2['items']==[] and q2['total']==q['total']
    with db() as c:
        events={x[0] for x in c.execute("SELECT event FROM audit_log WHERE object_type='lab_report' AND object_id IN (?,?)",(rid,new))}
        assert {'lab_draft_updated','lab_approved','lab_adjusted','lab_printed','lab_review_viewed'}<=events
        assert '000012345678' not in c.execute("SELECT details FROM audit_log WHERE event='lab_adjusted' AND object_id=?",(new,)).fetchone()[0]
    from app.lab_result_source import FakeLabResultSource
    from app.m5 import ResultInput
    source=FakeLabResultSource({order_id:ResultInput(**data)});received=source.receive(order_id=order_id);received.comment='Không sửa gốc';assert source.receive(order_id=order_id).comment=='Nhận xét giả lập'

    # A second encounter contributes a separate chronological point, not the superseded revision.
    v2=r.post('/api/visits',json={'patient_id':patient,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
    # Keep the existing service link: inactive catalog items do not erase historical links/results.
    order2=d.post('/api/orders',json={'visit_id':v2,'category':'lab','service_id':sid,'request_key':'m5-second-'+suffix}).json()['id']
    # Reactivate before opening the new report, as inactive indices cannot enter a new report.
    assert a.put('/api/lab/catalog/'+str(tid),json={**changed,'active':True}).status_code==200
    rid2=t.post(f'/api/lab/orders/{order2}/reports').json()['id'];path2=f'/api/lab/reports/{rid2}'
    second={**data,'version':0,'sample_at':'2026-02-02T08:00:00+07:00','result_at':'2026-02-02T09:00:00+07:00'}
    assert t.put(path2,json=second).status_code==200
    assert t.post(path2+'/submit',json={'version':1}).status_code==200
    assert d.post(path2+'/approve',json={'version':2}).status_code==200
    history=d.get(f'/api/lab/visits/{v2}/history/{tid}').json()
    assert [h['report_id'] for h in history]==[new,rid2] and [h['flag'] for h in history]==['','']
