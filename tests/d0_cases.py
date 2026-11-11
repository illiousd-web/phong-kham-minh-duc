"""Only synthetic codes and identities. Shared SQLite/PostgreSQL D0 contracts."""
import csv,io,json,secrets,time,statistics
from .m5_revision_cases import document_text
from app.d0 import COLUMNS,LABELS

def raw(kind,rows):
    s=io.StringIO();w=csv.writer(s);w.writerow([LABELS[x] for x in COLUMNS[kind]])
    for row in rows:w.writerow([row.get(x,'') for x in COLUMNS[kind]])
    return s.getvalue().encode()

def upload(a,kind,rows,**extra):
    b=raw(kind,rows);meta=json.dumps({'document_number':'VĂN BẢN GIẢ LẬP','document_date':'2026-01-01','source':'Nguồn giả lập không dùng thực tế','version':extra.pop('version','test-1')})
    def send(preview,proof='',data=b):return a.post('/api/standards/'+kind+'/import',files={'file':('fake.csv',data)},data={'metadata':meta,'preview':str(preview).lower(),'proof':proof,**extra})
    assert send(False).status_code==422
    preview=send(True);assert preview.status_code==200,preview.text
    proof=preview.json()['fingerprint'];assert len(proof)==64
    assert send(False,proof,b+b'\n').status_code==422
    result=send(False,proof);assert result.status_code==200,result.text
    return result.json()

def check_d0(clients,ids,db,service):
    a,d,r=[clients[k] for k in ('admin','doctor','reception')];suffix=secrets.token_hex(4)
    with db(True) as c:c.execute("DELETE FROM prescription_settings WHERE key='require_primary_icd10'")
    assert a.get('/api/standards/config').json()['require_primary_icd10'] is True
    assert r.put('/api/standards/settings',json={'require_primary_icd10':False}).status_code==403
    codes=[{'code':'FAKE-'+suffix+'-'+str(i),'name_vi':'Bệnh giả lập '+str(i),**flags} for i,flags in enumerate([{}, {'not_primary':'1'},{'death_only':'1'},{'sex':'Nam'},{'replaced':'1','replacement_codes':'FAKE-DETAIL'},{'discouraged_primary':'1'}])]
    upload(a,'icd10',codes)
    assert d.get('/api/standards/icd10?q=benh gia lap').json()['total']==6
    pid=r.post('/api/patients',json={'full_name':'Người D0 giả lập '+suffix,'sex':'Nữ','date_of_birth':'1990-01-01','occupation':'Nghề chữ giả lập','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':pid,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
    assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Mô tả chữ giả lập'}).status_code==200
    assert d.post(f'/api/visits/{vid}/complete',json={'version':1}).status_code==422
    for i in (1,2,3,4):
        assert d.put(f'/api/visits/{vid}/diagnosis-codes',json={'version':1,'primary':codes[i]['code']}).status_code==422
    assert r.put(f'/api/visits/{vid}/diagnosis-codes',json={'version':1,'primary':codes[0]['code']}).status_code==403
    warn=d.put(f'/api/visits/{vid}/diagnosis-codes',json={'version':1,'primary':codes[5]['code'],'secondary':[codes[1]['code']]});assert warn.status_code==200 and warn.json()['warnings']
    for fmt in ('docx','pdf'):
        txt=document_text(d.get(f'/api/visits/{vid}/forms/clinical?format={fmt}'),fmt)
        assert codes[5]['code'] in txt and 'Mô tả chữ giả lập' in txt
    with db() as c:before=c.execute('SELECT diagnosis_codes FROM visits WHERE id=?',(vid,)).fetchone()[0]
    upload(a,'icd10',[{**codes[0],'name_vi':'Tên mới giả lập'}],version='test-2')
    with db() as c:assert c.execute('SELECT diagnosis_codes FROM visits WHERE id=?',(vid,)).fetchone()[0]==before
    assert d.post(f'/api/visits/{vid}/complete',json={'version':2}).status_code==422 # deactivated code is not selectable at closure
    assert d.put(f'/api/visits/{vid}/diagnosis-codes',json={'version':2,'primary':codes[0]['code']}).status_code==200
    assert d.post(f'/api/visits/{vid}/complete',json={'version':3}).status_code==200
    tech='FAKE-TECH-'+suffix;upload(a,'tech_catalog',[{'code':tech,'name':'Kỹ thuật giả lập'},{'code':tech+'-PACK','name':'Kỹ thuật trong gói giả lập'}])
    with db() as c:old=dict(c.execute('SELECT * FROM service_catalog WHERE id=?',(service,)).fetchone())
    assert a.put('/api/standards/services/'+str(service),json={'codes':[tech]}).status_code==200
    assert a.put('/api/standards/services/'+str(service),json={'codes':[tech,tech+'-PACK']}).status_code==422
    assert a.put('/api/standards/services/'+str(service),json={'codes':[tech,tech+'-PACK'],'package':True}).status_code==200
    with db() as c:assert dict(c.execute('SELECT * FROM service_catalog WHERE id=?',(service,)).fetchone())==old
    shared='7654321';upload(a,'shared_lab_codes',[{'code':shared,'name':'Chỉ số giả lập','tech_code':tech,'loinc':'FAKE-LOINC','unit':'đv giả lập'}])
    tid=a.get('/api/standards/unlinked/lab-tests').json()[0]['id']
    assert a.put('/api/standards/lab-tests/'+str(tid),json={'code':shared}).status_code==200
    assert a.put('/api/standards/lab-tests/'+str(tid),json={'code':'missing'}).status_code==422
    occ='FAKE-OCC-'+suffix;upload(a,'occupation_catalog',[{'code':occ,'name':'Nghề chuẩn giả lập'}])
    assert r.patch(f'/api/patients/{pid}/administrative',json={'occupation_code':occ}).status_code==200
    with db() as c:assert c.execute('SELECT occupation FROM patients WHERE id=?',(pid,)).fetchone()[0]=='Nghề chuẩn giả lập'
    # Isolated fake names in the existing TMS catalog; never a real official code.
    pc,cc='FAKE-P-'+suffix,'FAKE-C-'+suffix
    with db(True) as c:
        c.execute("INSERT INTO patient_catalog(kind,code,name,parent_code) VALUES('province',?,?,'')",(pc,'Tỉnh giả lập '+suffix))
        c.execute("INSERT INTO patient_catalog(kind,code,name,parent_code) VALUES('commune',?,?,?)",(cc,'Xã giả lập '+suffix,pc))
    geo=upload(a,'official_addresses',[{'code':'OFF-P-'+suffix,'name':'Tỉnh giả lập '+suffix,'province_name':'Tỉnh giả lập '+suffix,'province_code':'OFF-P-'+suffix,'kind':'province'},{'code':'OFF-C-'+suffix,'name':'Xã giả lập '+suffix,'province_name':'Tỉnh giả lập '+suffix,'province_code':'OFF-P-'+suffix,'kind':'commune'}])
    assert geo['unmatched'] # all real TMS names intentionally unmatched against fake official file
    assert r.patch(f'/api/patients/{pid}/administrative',json={'province_code':pc,'commune_code':cc}).status_code==200
    with db() as c:
        p=c.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone();assert p['official_commune_code']=='OFF-C-'+suffix and p['commune_code']==cc
        assert c.execute('SELECT COUNT(*) FROM catalog_imports').fetchone()[0]>=6
    assert a.put('/api/standards/settings',json={'require_primary_icd10':False}).status_code==200
    with db() as c:assert c.execute("SELECT 1 FROM audit_log WHERE event='icd10_requirement_changed'").fetchone()

def check_standard_snapshots(clients,ids,db,service):
    from tests.m5_revision_cases import setup_report
    a,d,r,t=[clients[k] for k in ('admin','doctor','reception','technician')]
    suffix=secrets.token_hex(4);code='FAKE-RX-'+suffix
    upload(a,'icd10',[{'code':code,'name_vi':'Bệnh chuẩn giả lập'}])
    assert a.put('/api/standards/settings',json={'require_primary_icd10':True}).status_code==200
    old=a.get('/api/prescription-settings').json()
    from app.practitioners import COLUMNS as PRACTITIONER
    person=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==ids['doctor'])
    try:
        a.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ001','clinic_name':'Cơ sở giả lập'})
        a.put('/api/practitioners/'+str(ids['doctor']),json={'practice_license':'FAKE-LICENSE','practice_scopes':['Nội','Xét nghiệm']})
        pid,vid,oid,rid,tid,data=setup_report(clients,ids,db,service)
        line={'name':'Thuốc D0 giả lập '+suffix,'ingredient':'Hoạt chất giả lập','unit':'viên','dose':'1','frequency':'1','days':'2','route':'Uống'}
        rx=d.post('/api/clinical-prescriptions',json={'visit_id':vid,'items':[line]});assert rx.status_code==201,rx.text
        rxurl='/api/clinical-prescriptions/'+str(rx.json()['id'])
        blocked=d.post(rxurl+'/lock',json={'version':0});assert blocked.status_code==422 and 'ICD-10' in blocked.text
        assert d.put(f'/api/visits/{vid}/diagnosis-codes',json={'version':1,'primary':code}).status_code==200
        assert d.post(rxurl+'/lock',json={'version':0}).status_code==200
        exported=d.get(rxurl+'/json');assert exported.status_code==200
        payload=exported.json();assert payload['encounter']['primary_icd10']==code and code in payload['encounter']['diagnosis']
        assert 'official_commune_code' in payload['patient']
        for fmt in ('docx','pdf'):assert code in document_text(d.get(rxurl+'/form?fmt='+fmt),fmt)
        upload(a,'shared_lab_codes',[{'code':'1234567','name':'Chỉ số chuẩn giả lập','loinc':'FAKE-LNC'}])
        assert a.put('/api/standards/lab-tests/'+str(tid),json={'code':'1234567'}).status_code==200
        url=f'/api/lab/reports/{rid}'
        assert t.put(url,json=data).status_code==200
        assert t.post(url+'/submit',json={'version':1}).status_code==200
        assert d.post(url+'/approve',json={'version':2}).status_code==200
        frozen=d.get(url).json();assert frozen['items'][0]['standard_code']['loinc']=='FAKE-LNC'
        upload(a,'shared_lab_codes',[{'code':'1234567','name':'Đổi tên giả lập','loinc':'FAKE-NEW'}],version='fake-new')
        assert d.get(url).json()==frozen
        assert d.get(rxurl+'/json').content==exported.content
    finally:
        a.put('/api/prescription-settings',json=old)
        a.put('/api/practitioners/'+str(ids['doctor']),json={k:person[k] for k in PRACTITIONER})
        a.put('/api/standards/settings',json={'require_primary_icd10':False})
