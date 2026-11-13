"""Replacement lifecycle and allergy overrides; fake records only."""
import io
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from docx import Document
import pymupdf


def print_text(response, fmt):
    assert response.status_code==200,response.text
    if fmt=='docx':
        d=Document(io.BytesIO(response.content));return ' '.join(p.text for p in d.paragraphs)+' '+' '.join(c.text for t in d.tables for row in t.rows for c in row.cells)
    with pymupdf.open(stream=response.content,filetype='pdf') as d:return ' '.join(p.get_text() for p in d)


def check_followup(clients,ids,db,service):
    a,d,r=clients['admin'],clients['doctor'],clients['reception']
    from app.practitioners import COLUMNS
    original=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==ids['doctor'])
    old_settings=a.get('/api/prescription-settings').json()
    try:
        assert a.put('/api/practitioners/'+str(ids['doctor']),json={'printed_name':'Bác sĩ giả lập dị ứng','practice_license':'GP-GIA-LAP','practice_scopes':['Nội']}).status_code==200
        assert a.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ001'}).status_code==200
        pid=r.post('/api/patients',json={'full_name':'Người giả lập thay đơn '+secrets.token_hex(4),'date_of_birth':'1990-01-01','sex':'Nam','phone':'0900000000','citizen_id':'000000000789'}).json()['id']
        vid=r.post('/api/visits',json={'patient_id':pid,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
        assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập'}).status_code==200
        body={'visit_id':vid,'items':[{'name':'Thuốc giả lập thay thế','ingredient':'Hoạt chất giả lập','strength':'5 mg','timing':'sau ăn','dose':'1','frequency':'2','days':'3','route':'Uống','unit':'viên'}]}
        base=d.post('/api/clinical-prescriptions',json=body);assert base.status_code==201,base.text
        root=base.json()['id'];url=lambda rid:f'/api/clinical-prescriptions/{rid}'
        assert d.post(url(root)+'/lock',json={'version':0}).status_code==200
        snapshot=d.get(url(root)+'/json').json()
        # Existing global SQLite/PG write boundary must serialize competing creates.
        def create(_):return d.post('/api/clinical-prescriptions',json={**body,'replaces_id':root})
        with ThreadPoolExecutor(max_workers=2) as pool:attempts=list(pool.map(create,range(2)))
        assert sorted(x.status_code for x in attempts)==[201,409],[x.text for x in attempts]
        child=next(x.json()['id'] for x in attempts if x.status_code==201)
        # A failed validation cannot cancel the parent or its outbox.
        incomplete={**body,'replaces_id':root,'version':0,'items':[{**body['items'][0],'route':''}]}
        assert d.put(url(child),json=incomplete).status_code==200
        assert d.post(url(child)+'/lock',json={'version':1}).status_code==422
        assert d.get(url(root)).json()['status']=='locked'
        with db() as c:assert c.execute('SELECT status FROM prescription_outbox WHERE prescription_id=?',(root,)).fetchone()[0]=='pending'
        assert d.put(url(child),json={**body,'replaces_id':root,'version':1}).status_code==200
        with db(True) as c:c.execute('UPDATE clinical_prescriptions SET local_code=? WHERE id=?',('ZZ001abcdefg-C',child))
        # Inject failure after the old cancellation and new snapshot update,
        # immediately before outbox serialization: every write/audit must roll back.
        import pytest
        from unittest.mock import patch
        from app.m6 import dump as real_dump
        calls=0
        def failing_dump(value):
            nonlocal calls
            if isinstance(value,dict) and 'schema_version' in value:
                calls+=1
                if calls==2:raise RuntimeError('Lỗi outbox giả lập')
            return real_dump(value)
        with patch('app.m6.dump',side_effect=failing_dump):
            with pytest.raises(RuntimeError,match='Lỗi outbox giả lập'):
                d.post(url(child)+'/lock',json={'version':2})
        with db() as c:
            assert c.execute('SELECT status FROM clinical_prescriptions WHERE id=?',(root,)).fetchone()[0]=='locked'
            assert c.execute('SELECT status FROM prescription_outbox WHERE prescription_id=?',(root,)).fetchone()[0]=='pending'
            assert c.execute('SELECT status FROM clinical_prescriptions WHERE id=?',(child,)).fetchone()[0]=='draft'
            assert not c.execute("SELECT 1 FROM audit_log WHERE event='clinical_rx_replaced' AND object_id=?",(root,)).fetchone()
        locked=d.post(url(child)+'/lock',json={'version':2});assert locked.status_code==200,locked.text
        code=locked.json()['local_code']
        assert len(code)==14 and set(code[5:12])<=set('ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
        assert d.get(url(root)).json()['status']=='cancelled'
        assert d.post('/api/clinical-prescriptions',json={**body,'replaces_id':root}).status_code==409
        for fmt in ('docx','pdf'):
            text=' '.join(print_text(d.get(url(root)+'/form?fmt='+fmt),fmt).split())
            assert 'ĐƠN ĐÃ HỦY – ĐÃ ĐƯỢC THAY THẾ BỞI '+code in text
        with db() as c:
            old=c.execute('SELECT * FROM clinical_prescriptions WHERE id=?',(root,)).fetchone()
            assert old['cancellation_reason']=='Thay thế bởi đơn '+code and json.loads(old['snapshot'])==snapshot
            assert c.execute('SELECT status FROM prescription_outbox WHERE prescription_id=?',(root,)).fetchone()[0]=='cancelled'
            assert c.execute("SELECT COUNT(*) FROM clinical_prescriptions WHERE id IN (?,?) AND status='locked'",(root,child)).fetchone()[0]==1
            assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='clinical_rx_replaced' AND object_id=?",(root,)).fetchone()[0]==1
            assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='clinical_rx_locked' AND object_id=?",(child,)).fetchone()[0]==1
        grand=d.post('/api/clinical-prescriptions',json={**body,'replaces_id':child});assert grand.status_code==201
        grand=grand.json()['id'];assert d.post(url(grand)+'/lock',json={'version':0}).status_code==200
        with db() as c:assert c.execute("SELECT COUNT(*) FROM clinical_prescriptions WHERE id IN (?,?,?) AND status='locked'",(root,child,grand)).fetchone()[0]==1
        # M0 allergy text is checked on save and checked again at lock.
        with db(True) as c:c.execute('UPDATE patients SET allergies=? WHERE id=?',('Amoxicillin',pid))
        medicine={'name':'Tên thương mại giả lập dị ứng','ingredient':'Amoxicillin + Acid clavulanic','brand_name':'Thương mại giả lập','strength':'5 mg + 5 mg','timing':'sau ăn','dose':'1','frequency':'2','days':'3','route':'Uống','unit':'viên'}
        allergic=d.post('/api/clinical-prescriptions',json={'visit_id':vid,'items':[medicine]});assert allergic.status_code==201,allergic.text
        rid=allergic.json()['id'];assert allergic.json()['allergy_warnings'][0]['row']==1
        assert 'amoxicillin' in allergic.json()['allergy_warnings'][0]['message']
        assert d.post(url(rid)+'/lock',json={'version':0}).status_code==422
        version=0
        for ack,reason in [(False,'Đã giải thích giả lập'),(True,'ngắn')]:
            response=d.put(url(rid),json={'visit_id':vid,'version':version,'items':[{**medicine,'allergy_acknowledged':ack,'allergy_reason':reason}]})
            assert response.status_code==200,response.text;version+=1
            assert d.post(url(rid)+'/lock',json={'version':version}).status_code==422
        confirmed={**medicine,'allergy_acknowledged':True,'allergy_reason':'Đã đánh giá giả lập 000000000789'}
        assert d.put(url(rid),json={'visit_id':vid,'version':version,'items':[confirmed]}).status_code==200;version+=1
        # A changed patient allergy invalidates the previous basis, even with a saved tick.
        with db(True) as c:c.execute('UPDATE patients SET allergies=? WHERE id=?',('Acid clavulanic',pid))
        assert d.post(url(rid)+'/lock',json={'version':version}).status_code==422
        assert d.put(url(rid),json={'visit_id':vid,'version':version,'items':[confirmed]}).status_code==200;version+=1
        assert d.post(url(rid)+'/lock',json={'version':version}).status_code==200
        with db() as c:
            stored=json.loads(c.execute('SELECT content FROM clinical_prescription_items WHERE prescription_id=?',(rid,)).fetchone()[0])
            assert stored['allergy_acknowledged'] is True and stored['allergy_reason']==confirmed['allergy_reason']
            event=c.execute("SELECT details FROM audit_log WHERE event='clinical_rx_allergy_acknowledged' AND object_id=?",(rid,)).fetchone()[0]
            assert json.loads(event)['row']==1 and '000000000789' not in event
    finally:
        a.put('/api/practitioners/'+str(ids['doctor']),json={k:original[k] for k in COLUMNS})
        a.put('/api/prescription-settings',json=old_settings)
