"""All source codes below are read from owner-authorized public CSVs; people fake."""
import hashlib,math,time,json
from app.d0_sources import SOURCES,ROOT,parse_source

def check_seeded(c):
    for kind,(file,count,sha,*_) in SOURCES.items():
        raw=(ROOT/file).read_bytes();assert raw.startswith(b'\xef\xbb\xbf') and hashlib.sha256(raw).hexdigest()==sha
        rows,errors=parse_source(raw,kind);assert not errors and len(rows)==count
        assert c.execute('SELECT COUNT(*) FROM '+kind+' WHERE active=1').fetchone()[0]==count
        imp=c.execute('SELECT row_count,fingerprint FROM catalog_imports WHERE kind=? ORDER BY id DESC LIMIT 1',(kind,)).fetchone()
        assert (imp[0],imp[1])==(count,sha)
    from app.config import LAN
    if LAN:print('D0 CSDL sau nạp bytes:',c.execute('SELECT pg_database_size(current_database())').fetchone()[0])
    else:print('D0 SQLite sau nạp bytes:',c.execute('PRAGMA page_count').fetchone()[0]*c.execute('PRAGMA page_size').fetchone()[0])
    assert c.execute('SELECT COUNT(*) FROM tech_catalog_pl01 WHERE active=1').fetchone()[0]==19438
    assert c.execute("SELECT ma_xa FROM official_addresses WHERE ten_xa='Xã Cát Thành' AND ten_tinh='Tỉnh Ninh Bình'").fetchone()[0]=='14056'
    assert c.execute("SELECT x.official_code FROM patient_catalog x JOIN patient_catalog p ON p.code=x.parent_code AND p.kind='province' WHERE x.kind='commune' AND x.name='Xã Cát Thành' AND p.name='Tỉnh Ninh Bình'").fetchone()[0]=='14056'
    assert c.execute('SELECT COUNT(*) FROM tech_pl02_links WHERE EXISTS(SELECT 1 FROM tech_catalog_pl02 p WHERE p.id=tech_pl02_links.pl02_id AND p.active=1)').fetchone()[0]==8252
    assert c.execute('SELECT COUNT(*) FROM tech_pl02_links WHERE needs_review=1 AND EXISTS(SELECT 1 FROM tech_catalog_pl02 p WHERE p.id=tech_pl02_links.pl02_id AND p.active=1)').fetchone()[0]==909
    assert not c.execute("SELECT 1 FROM tech_pl02_links l WHERE l.needs_review=0 AND NOT EXISTS(SELECT 1 FROM tech_catalog_pl01 p WHERE p.ma_ky_thuat=l.raw_token)").fetchone()
    assert c.execute('SELECT code FROM tech_catalog_pl01 WHERE code LIKE ? LIMIT 1',('BS_%',)).fetchone()

def check_source_api(clients,ids,db,service):
    admin=clients['admin']
    prior=admin.get('/api/standards/config').json()['require_primary_icd10']
    try:_check_source_api(clients,ids,db,service)
    finally:admin.put('/api/standards/settings',json={'require_primary_icd10':prior})

def _check_source_api(clients,ids,db,service):
    from tests.d0_isolation import service as fresh_service,lab
    service=fresh_service(db)
    a,d,r=clients['admin'],clients['doctor'],clients['reception']
    a.put('/api/standards/settings',json={'require_primary_icd10':True})
    from app.d0_sources import seed_sources
    with db(True) as c:
        from app.config import LAN
        if LAN and c.execute('SELECT COUNT(*) FROM patients').fetchone()[0]==0:
            print('D0 PostgreSQL nạp sẵn, 0 bệnh nhân/0 lượt, bytes:',c.execute('SELECT pg_database_size(current_database())').fetchone()[0])
        seed_sources(c,'2026-11-11T00:00:00+00:00');check_seeded(c)
    p=r.post('/api/patients',json={'full_name':'Người kiểm nguồn giả lập','date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'}).json()['id']
    v=r.post('/api/visits',json={'patient_id':p,'doctor_id':ids['doctor'],'service_id':service}).json()['id']
    d.put(f'/api/visits/{v}/clinical',json={'version':0,'diagnosis':'Mô tả lâm sàng giả lập'})
    assert d.post(f'/api/visits/{v}/complete',json={'version':1}).status_code==422
    line={'name':'Thuốc kiểm nguồn giả lập','ingredient':'Hoạt chất giả lập','strength':'5 mg','timing':'sau ăn','unit':'viên','dose':'1','frequency':'1','days':'2','route':'Uống'}
    rx=d.post('/api/clinical-prescriptions',json={'visit_id':v,'items':[line]});assert rx.status_code==201,rx.text
    rxurl='/api/clinical-prescriptions/'+str(rx.json()['id'])
    blocked=d.post(rxurl+'/lock',json={'version':0});assert blocked.status_code==422 and 'primary_icd10' in blocked.text
    with db() as c:
        flags=[c.execute('SELECT code FROM icd10 WHERE active=1 AND '+condition+' LIMIT 1').fetchone()[0] for condition in ('not_primary=1','death_only=1',"sex='Nam'",'replaced=1')]
        warning=c.execute("SELECT code FROM icd10 WHERE active=1 AND discouraged_primary=1 AND not_primary=0 AND death_only=0 AND replaced=0 AND sex IN ('','Nữ') LIMIT 1").fetchone()[0]
        glyph_row=c.execute("SELECT code,ma_benh_khong_dau FROM icd10 WHERE active=1 AND (code LIKE ? OR code LIKE ?) AND not_primary=0 AND death_only=0 AND replaced=0 AND sex IN ('','Nữ') LIMIT 1",('%†%','%*%')).fetchone()
        glyph=glyph_row['code']
    for code in flags:assert d.put(f'/api/visits/{v}/diagnosis-codes',json={'version':1,'primary':code}).status_code==422
    children=d.get('/api/standards/icd10/'+flags[3]+'/children');assert children.status_code==200 and children.json()
    warn=d.put(f'/api/visits/{v}/diagnosis-codes',json={'version':1,'primary':warning});assert warn.status_code==200 and warn.json()['warnings']
    saved=d.put(f'/api/visits/{v}/diagnosis-codes',json={'version':2,'primary':glyph_row['ma_benh_khong_dau']});assert saved.status_code==200
    from tests.m5_revision_cases import document_text
    for fmt in ('docx','pdf'):assert glyph in document_text(d.get(f'/api/visits/{v}/forms/clinical?format={fmt}'),fmt)
    with db() as c:
        entries=json.loads(c.execute('SELECT diagnosis_codes FROM visits WHERE id=?',(v,)).fetchone()[0]);assert entries[0]['canonical_code']
    from app.practitioners import COLUMNS as PROFILE
    prior=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==ids['doctor'])
    clinic=a.get('/api/prescription-settings').json()
    try:
        assert a.put('/api/practitioners/'+str(ids['doctor']),json={'practice_license':'GIAY-PHEP-GIA-LAP','practice_scopes':['Nội','Xét nghiệm']}).status_code==200
        a.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ001','clinic_name':'Cơ sở giả lập'})
        locked=d.post(rxurl+'/lock',json={'version':0});assert locked.status_code==200,locked.text
        payload=d.get(rxurl+'/json').json();assert payload['encounter']['primary_icd10']==glyph
        assert payload['encounter']['primary_icd10_canonical']==entries[0]['canonical_code']
        for fmt in ('docx','pdf'):assert glyph in document_text(d.get(rxurl+'/form?fmt='+fmt),fmt)
    finally:
        a.put('/api/practitioners/'+str(ids['doctor']),json={k:prior[k] for k in PROFILE})
        a.put('/api/prescription-settings',json=clinic)
    assert d.post(f'/api/visits/{v}/complete',json={'version':3}).status_code==200
    found=d.get('/api/standards/icd10?q=cholera').json();assert found['total']>0
    found=d.get('/api/standards/shared_lab_codes?q=prothrombin').json();assert found['items']
    chosen=found['items'][0]
    tid=lab(a)
    assert a.put('/api/standards/lab-tests/'+str(tid),json={'code':chosen['code']}).status_code==200
    with db() as c:
        assert c.execute('SELECT shared_code FROM lab_tests WHERE id=?',(tid,)).fetchone()[0]==chosen['code']
        link=c.execute('SELECT pl02_id,pl01_code FROM tech_pl02_links WHERE needs_review=0 AND NOT EXISTS(SELECT 1 FROM tech_pl02_links bad WHERE bad.pl02_id=tech_pl02_links.pl02_id AND bad.needs_review=1) AND EXISTS(SELECT 1 FROM tech_catalog_pl02 p WHERE p.id=tech_pl02_links.pl02_id AND p.active=1) LIMIT 1').fetchone();old=dict(c.execute('SELECT * FROM service_catalog WHERE id=?',(service,)).fetchone())
    assert a.put('/api/standards/services/'+str(service),json={'codes':[link['pl01_code']],'pl02_ids':[str(link['pl02_id'])]}).status_code==200
    with db() as c:assert dict(c.execute('SELECT * FROM service_catalog WHERE id=?',(service,)).fetchone())==old
    from tests.m5_revision_cases import setup_report
    _,lab_vid,_,report_id,lab_tid,body=setup_report(clients,ids,db,service)
    assert a.put('/api/standards/lab-tests/'+str(lab_tid),json={'code':chosen['code']}).status_code==200
    path=f'/api/lab/reports/{report_id}'
    assert clients['technician'].put(path,json=body).status_code==200
    assert clients['technician'].post(path+'/submit',json={'version':1}).status_code==200
    assert d.post(path+'/approve',json={'version':2}).status_code==200
    frozen=d.get(path).json();assert frozen['items'][0]['standard_code']['ma_dung_chung']==chosen['code']
    cls_raw=(ROOT/SOURCES['shared_lab_codes'][0]).read_bytes()
    cls_meta=json.dumps({'document_number':'QĐ 1227/QĐ-BYT 2025','document_date':None,'source':'Tệp công khai cung cấp','version':'Kiểm snapshot nạp lại'})
    cls_args={'files':{'file':('QD1227_MA_DUNG_CHUNG_CLS_DOT1.csv',cls_raw)},'data':{'metadata':cls_meta,'preview':'true'}}
    pre=a.post('/api/standards/shared_lab_codes/import',**cls_args);assert pre.status_code==200
    cls_args['data'].update(preview='false',proof=pre.json()['fingerprint'])
    assert a.post('/api/standards/shared_lab_codes/import',**cls_args).status_code==200
    assert d.get(path).json()==frozen
    # A new PL02 edition reuses source STT, never the internal identity chosen before.
    with db() as c:
        old_pl02=dict(c.execute('SELECT * FROM tech_catalog_pl02 WHERE id=?',(link['pl02_id'],)).fetchone())
        old_fragments=[dict(x) for x in c.execute('SELECT * FROM tech_pl02_links WHERE pl02_id=? ORDER BY position',(link['pl02_id'],))]
    pl02_raw=(ROOT/SOURCES['tech_catalog_pl02'][0]).read_bytes()
    pl02_args={'files':{'file':('TT23_PL02_DANH_MUC_KY_THUAT_TU_01072026.csv',pl02_raw)},'data':{'metadata':json.dumps({'document_number':'TT 23/2024/TT-BYT','document_date':None,'source':'Tệp công khai cung cấp','version':'Kiểm phiên bản PL02'}),'preview':'true'}}
    pre=a.post('/api/standards/tech_catalog_pl02/import',**pl02_args);assert pre.status_code==200 and pre.json()['total']==9128
    pl02_args['data'].update(preview='false',proof=pre.json()['fingerprint'])
    result=a.post('/api/standards/tech_catalog_pl02/import',**pl02_args);assert result.status_code==200 and result.json()['needs_review']==909
    with db() as c:
        retained=dict(c.execute('SELECT * FROM tech_catalog_pl02 WHERE id=?',(link['pl02_id'],)).fetchone())
        assert retained=={**old_pl02,'active':0}
        assert [dict(x) for x in c.execute('SELECT * FROM tech_pl02_links WHERE pl02_id=? ORDER BY position',(link['pl02_id'],))]==old_fragments
        assert c.execute('SELECT pl02_id FROM service_pl02_codes WHERE service_id=?',(service,)).fetchone()[0]==link['pl02_id']
        newer=c.execute('SELECT id FROM tech_catalog_pl02 WHERE stt=? AND active=1',(old_pl02['stt'],)).fetchone()[0]
        assert newer!=link['pl02_id']
    # Exact original file >6 MB passes only the standards route, and proof binds it.
    raw=(ROOT/SOURCES['icd10'][0]).read_bytes();meta=json.dumps({'document_number':'TT 06/2026/TT-BYT','document_date':None,'source':'Tệp công khai chủ dự án cung cấp','version':'Kiểm API file gốc'})
    def upload(preview,proof=''):return a.post('/api/standards/icd10/import',data={'metadata':meta,'preview':str(preview).lower(),'proof':proof},files={'file':('ICD10_TT06_2026.csv',raw)})
    assert upload(False).status_code==422
    preview=upload(True);assert preview.status_code==200 and preview.json()['total']==15844,preview.text
    assert upload(False,'sai').status_code==422
    assert upload(False,preview.json()['fingerprint']).status_code==200
    sample=[]
    for _ in range(30):
        start=time.perf_counter();result=d.get('/api/standards/icd10?q=cholera');sample.append(time.perf_counter()-start);assert result.status_code==200 and result.json()['items']
    assert sorted(sample)[math.ceil(.95*len(sample))-1]<.3
    assert a.put('/api/standards/settings',json={'require_primary_icd10':False}).status_code==200
