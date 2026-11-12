"""Shared SQLite/PostgreSQL M6 cases. All data is synthetic."""
import io
import json
import secrets
from docx import Document
import pymupdf


def check_m6(clients, ids, db, service):
    d, r, a, pharmacy = [clients[k] for k in ('doctor','reception','admin','pharmacy')]
    suffix = secrets.token_hex(4)
    old_settings = a.get('/api/prescription-settings').json()
    old_practitioner = next(p for p in a.get('/api/practitioners').json()['items'] if p['id']==ids['doctor'])
    from app.practitioners import COLUMNS
    prior = {k:old_practitioner[k] for k in COLUMNS}
    try:
        assert a.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ001','clinic_name':'Cơ sở giả lập','clinic_address':'Địa chỉ cơ sở giả lập','clinic_phone':'0900000000'}).status_code==200
        assert r.put('/api/prescription-settings',json={}).status_code==403
        assert a.put('/api/practitioners/'+str(ids['doctor']),json={'printed_name':'Người kê giả lập','printed_title':'BS','practice_license':'GP-GIA-LAP','practice_scopes':['Nội']}).status_code==200
        p=r.post('/api/patients',json={'full_name':'Người giả lập M6 '+suffix,'date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000','citizen_id':'000000000123','address':'Nhà cũ giả lập','province_code':'06','commune_code':'11311067'})
        assert p.status_code==201,p.text
        v=r.post('/api/visits',json={'patient_id':p.json()['id'],'doctor_id':ids['doctor'],'service_id':service});assert v.status_code==201,v.text
        vid=v.json()['id']
        assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập M6'}).status_code==200
        line={'name':'Thuốc giả lập M6 '+suffix,'strength':'5 mg','unit':'viên','dose':'1','frequency':'2','route':'Uống','timing':'sau ăn','days':'7','notes':'Chỉ kiểm thử'}
        body={'visit_id':vid,'items':[line], 'lifestyle_advice':'Sinh hoạt giả lập','follow_up_advice':'Tái khám giả lập','purchase_advice':'Mua thuốc giả lập'}
        for forbidden in (r, pharmacy, a, clients['manager']):
            assert forbidden.post('/api/clinical-prescriptions',json=body).status_code==403
        created=d.post('/api/clinical-prescriptions',json=body);assert created.status_code==201,created.text
        rid=created.json()['id'];url=f'/api/clinical-prescriptions/{rid}'
        assert pharmacy.get(url).status_code==403
        detail=d.get(url).json(); assert detail['items'][0]['quantity']=='14'
        assert len(detail['local_code'])==14 and detail['local_code'].startswith('ZZ001')
        draft=d.get(url+'/form?fmt=docx');assert draft.status_code==200
        draft_doc=Document(io.BytesIO(draft.content));assert draft_doc.paragraphs[0].text.startswith('Mã đơn thuốc:');draft_text=' '.join(x.text for x in draft_doc.paragraphs)
        assert detail['local_code'] in draft_text and 'NHÁP – CHƯA CÓ GIÁ TRỊ' in draft_text
        assert 'CHƯA CÓ MÃ CƠ SỞ' not in draft_text
        did=detail['items'][0]['drug_id']
        drug=next(x for x in a.get('/api/drugs').json() if x['id']==did)
        assert drug['review_status']=='unreviewed' and not drug['ingredient']
        error=d.post(url+'/lock',json={'version':0});assert error.status_code==422,error.text
        assert {'row':1,'field':'ingredient','message':'Bổ sung hoạt chất để in đúng tên theo TT 26/2025'} in error.json()['detail']['errors']
        body['items'][0]['ingredient']='Hoạt chất giả lập A';body['version']=0
        assert d.put(url,json=body).status_code==200
        drug=next(x for x in a.get('/api/drugs').json() if x['id']==did)
        assert drug['ingredient']=='Hoạt chất giả lập A' and drug['review_status']=='unreviewed'
        # Spelling/different case and accents reuse the same catalog entry.
        from app.m6 import fold
        other={**body,'items':[{**body['items'][0],'name':fold(line['name']).upper(),'strength':'5 MG'}]}
        second=d.post('/api/clinical-prescriptions',json=other);assert second.status_code==201,second.text
        assert d.get('/api/clinical-prescriptions/'+str(second.json()['id'])).json()['items'][0]['drug_id']==did
        # Mandatory use fields and duration, without destroying the draft.
        version=1
        for change in ({'dose':''},{'frequency':''},{'route':''},{'days':''},{'days':'31'},{'ingredient':'A giả lập + B giả lập','brand_name':''}):
            probe={**body,'version':version,'items':[{**body['items'][0],**change}]}
            assert d.put(url,json=probe).status_code==200;version+=1
            assert d.post(url+'/lock',json={'version':version}).status_code==422
        body['version']=version
        assert d.put(url,json=body).status_code==200;version+=1
        # Practitioner requirement is a lock gate, not a draft-save gate.
        assert a.put('/api/practitioners/'+str(ids['doctor']),json={}).status_code==200
        assert d.post(url+'/lock',json={'version':version}).status_code==422
        assert a.put('/api/practitioners/'+str(ids['doctor']),json={'practice_license':'GP-GIA-LAP','practice_scopes':[]}).status_code==200
        assert d.post(url+'/lock',json={'version':version}).status_code==422
        assert a.put('/api/practitioners/'+str(ids['doctor']),json={'printed_name':'Người kê giả lập','printed_title':'BS','practice_license':'GP-GIA-LAP','practice_scopes':['Nội']}).status_code==200
        from app.config import LAN
        if LAN:
            configured=a.get('/api/prescription-settings').json()
            assert a.put('/api/prescription-settings',json={}).status_code==200
            missing=d.post(url+'/lock',json={'version':version})
            assert missing.status_code==422 and 'mã cơ sở' in missing.text
            assert a.put('/api/prescription-settings',json=configured).status_code==200
        # Restrictive catalog flags are checked again at lock time.
        from app.m6 import DrugInput
        editable={k:drug[k] for k in DrugInput.model_fields}
        for controlled_type in ('N','H','precursor'):
            editable.update(controlled_type=controlled_type)
            assert a.put('/api/drugs/'+str(did),json=editable).status_code==200
            blocked=d.post(url+'/lock',json={'version':version});assert blocked.status_code==422 and 'Đơn N/H chưa hỗ trợ' in blocked.text
        editable.update(controlled_type='',toxic=True)
        assert a.put('/api/drugs/'+str(did),json=editable).status_code==200
        # Add an ordinary line first; toxic item must be printed first.
        body['items']=[{**line,'name':'Thuốc giả lập thường '+suffix,'ingredient':'Hoạt chất giả lập B','quantity':'3','quantity_acknowledged':True,'quantity_reason':'Số lượng nhập tay giả lập'},line]
        body['version']=version
        assert d.put(url,json=body).status_code==200;version+=1
        locked=d.post(url+'/lock',json={'version':version});assert locked.status_code==200,locked.text
        code=locked.json()['local_code'];assert code==detail['local_code'];assert len(code)==14 and code.startswith('ZZ001') and code.endswith('-C')
        assert d.put(url,json={**body,'version':version+1}).status_code==409
        value=d.get(url+'/json').json()
        assert value['schema_version']=='1.0' and value['national_code'] is None and value['items'][0]['toxic']
        assert value['items'][0]['display_name'].startswith('Hoạt chất giả lập A')
        assert value['patient']['address']=='Nhà cũ giả lập, Xã Cát Thành, Tỉnh Ninh Bình'
        assert all(k in value for k in ('patient','facility','prescriber','encounter','items','advice'))
        assert pharmacy.get(url).status_code==200 and 'snapshot' not in pharmacy.get(url).json()
        assert r.get(url+'/json').status_code==403
        expected=['ZZ001','Cơ sở giả lập','Địa chỉ cơ sở giả lập','0900000000','000000000123','01/01/1990','Nữ','Mã số BHYT','Nhà cũ giả lập','Chẩn đoán giả lập M6','Hoạt chất giả lập A','Sinh hoạt giả lập','Tái khám giả lập','Mua thuốc giả lập','Bác sỹ/Y sỹ khám bệnh','Người kê giả lập','Khám lại xin mang theo đơn này.','CHƯA LIÊN THÔNG']
        for fmt in ('docx','pdf'):
            res=r.get(url+'/form?fmt='+fmt);assert res.status_code==200,res.text
            if fmt=='docx':
                doc=Document(io.BytesIO(res.content));text=' '.join(p.text for p in doc.paragraphs)+' '+' '.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
            else:
                with pymupdf.open(stream=res.content,filetype='pdf') as pdf:text=' '.join(p.get_text() for p in pdf)
            text=' '.join(text.split())
            for word in expected:assert word in text,(fmt,word,text)
            assert text.index(code)<text.index('Cơ sở giả lập')<text.index('Người giả lập M6')
        # Merge changes only references; snapshot/JSON remains exactly identical.
        with db() as c:
            target=c.execute('SELECT drug_id FROM clinical_prescription_items WHERE prescription_id=? AND drug_id<>?',(rid,did)).fetchone()[0]
        assert a.post('/api/drugs/'+str(did)+'/merge',json={'keep_id':target}).status_code==200
        assert d.get(url+'/json').json()==value
        assert a.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ002'}).status_code==200
        assert d.get(url+'/json').json()==value
        replacement=d.post('/api/clinical-prescriptions',json={**body,'items':[{'name':'Thay thế giả lập '+suffix,'ingredient':'Chất giả lập C','dose':'1','frequency':'1','days':'2','route':'Uống','unit':'viên'}],'replaces_id':rid});assert replacement.status_code==201,replacement.text
        assert r.post(url+'/cancel',json={'version':version+1,'reason':'Lý do giả lập'}).status_code==403
        assert d.post(url+'/cancel',json={'version':version+1,'reason':'Lý do giả lập 000000000123'}).status_code==200
        with db() as c:
            history=c.execute('SELECT status,snapshot FROM clinical_prescriptions WHERE id=?',(rid,)).fetchone()
            assert history['status']=='cancelled' and json.loads(history['snapshot'])==value
            for event in c.execute("SELECT details FROM audit_log WHERE object_type='clinical_prescription' AND object_id=?",(rid,)):
                assert '000000000123' not in event[0]
            assert c.execute('SELECT status FROM prescription_outbox WHERE prescription_id=?',(rid,)).fetchone()[0]=='cancelled'
        # SQL count and SQL status page have exactly the same conditions.
        page=r.get('/api/clinical-prescriptions?status=locked&limit=1').json()
        assert all(x['status']=='locked' for x in page['items'])
        assert r.get('/api/clinical-prescriptions?status=draft').json()['total']==0
        # Child guard is evaluated at lock, so an incomplete child draft still saves.
        child=r.post('/api/patients',json={'full_name':'Trẻ M6 giả lập','date_of_birth':'2025-01-01','sex':'Nam','phone':'0900000000'}).json()['id']
        cv=r.post('/api/visits',json={'patient_id':child,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
        assert d.put(f'/api/visits/{cv}/clinical',json={'version':0,'diagnosis':'Chẩn đoán trẻ giả lập'}).status_code==200
        compound={'name':'Hỗn hợp giả lập '+suffix,'ingredient':'Chất X giả lập + Chất Y giả lập','brand_name':'Thương mại giả lập','strength':'5 mg + 5 mg','timing':'sau ăn','dose':'1','frequency':'2','days':'3','route':'Uống','unit':'viên'}
        cr=d.post('/api/clinical-prescriptions',json={'visit_id':cv,'items':[compound,{**compound,'name':'Trùng hoạt chất giả lập '+suffix,'ingredient':'Chất X giả lập','brand_name':''}]});assert cr.status_code==201,cr.text
        assert cr.json()['warnings']
        brand_matches=a.get('/api/drugs',params={'q':'thuong mai gia lap'}).json()
        assert any(x['name']==compound['name'] and x['brand_name']=='Thương mại giả lập' for x in brand_matches)
        curl='/api/clinical-prescriptions/'+str(cr.json()['id'])
        assert d.post(curl+'/lock',json={'version':0}).status_code==422
        assert d.put(f'/api/visits/{cv}/child-details',json={'version':1,'weight_kg':12}).status_code==200
        assert d.post(curl+'/lock',json={'version':0}).status_code==422
        assert d.put(f'/api/visits/{cv}/child-details',json={'version':2,'weight_kg':12,'escort_name':'Người đưa trẻ giả lập'}).status_code==200
        assert d.post(curl+'/lock',json={'version':0}).status_code==200
        child_payload=d.get(curl+'/json').json()
        assert child_payload['patient']['age_months']<72 and child_payload['patient']['escort_name']=='Người đưa trẻ giả lập'
        assert child_payload['items'][0]['display_name']=='Thương mại giả lập'
        from app.prescription_gateway import FakePrescriptionGateway
        fake=FakePrescriptionGateway();assert fake.submit(value)['national_code'] is None and fake.received==[value]
    finally:
        a.put('/api/prescription-settings',json=old_settings)
        a.put('/api/practitioners/'+str(ids['doctor']),json=prior)
