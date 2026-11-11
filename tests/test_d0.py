import sqlite3
from tests.test_administrative import context
from app.main import db
from tests.d0_cases import check_d0

def test_d0_file_proof_rules_links_history_and_forms():
    clients,ids=context();check_d0(clients,ids,db,1)

def test_d0_migration_preserves_main_data_and_is_idempotent(tmp_path):
    from app.d0_migration import migrate_d0,TABLES
    c=sqlite3.connect(tmp_path/'legacy.sqlite');c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)');c.execute('INSERT INTO schema_migrations VALUES(9)')
    for name in ('users','visits','patients','lab_tests','service_catalog'):
        c.execute('CREATE TABLE '+name+'(id INTEGER PRIMARY KEY,content TEXT)');c.execute('INSERT INTO '+name+" VALUES(1,'Chữ cũ giả lập')")
    migrate_d0(c);migrate_d0(c)
    for name in ('visits','patients','lab_tests','service_catalog'):assert c.execute('SELECT content FROM '+name).fetchone()[0]=='Chữ cũ giả lập'
    assert c.execute('SELECT primary_icd10,diagnosis_codes FROM visits').fetchone()==(None,'[]')
    for table in TABLES:assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0

def test_d0_missing_column_mapping_and_12000_search_p95():
    from tests.d0_cases import upload,raw
    import time,statistics,json
    clients,_=context();a=clients['admin']
    rows=[{'code':'FAKE'+str(i).zfill(5),'name_vi':'Bệnh mô phỏng tìm kiếm '+str(i)} for i in range(12500)]
    upload(a,'icd10',rows)
    samples=[]
    for i in range(30):
        start=time.perf_counter();result=a.get('/api/standards/icd10?q=benh mo phong&limit=20&offset=20');samples.append(time.perf_counter()-start)
        assert result.status_code==200 and result.json()['total']==12500 and len(result.json()['items'])==20
    p95=sorted(samples)[int(len(samples)*.95)-1];assert p95<.3,p95
    meta=json.dumps({'document_number':'Giả lập','document_date':'2026-01-01','source':'Giả lập','version':'fake'})
    bad=a.post('/api/standards/icd10/import',data={'metadata':meta},files={'file':('bad.csv',b'Ma sai\nFAKE\n')})
    assert bad.status_code==422 and 'Tên tiếng Việt' in bad.text

def test_d0_prescription_lock_json_and_approved_lab_snapshot():
    from tests.d0_cases import check_standard_snapshots
    clients,ids=context();check_standard_snapshots(clients,ids,db,1)

def test_d0_excel_mapping_row_errors_and_metadata_proof():
    from tests.d0_cases import raw
    import io,json
    from openpyxl import Workbook
    clients,_=context();a=clients['admin'];b=Workbook();w=b.active
    from app.d0 import COLUMNS,LABELS
    headers=[LABELS[x] for x in COLUMNS['icd10']];headers[0]='Mã từ file giả lập';w.title='MaGoc';b.create_sheet('GhiChu');w.append(['Tệp giả lập']);w.append(headers);w.append(['FAKE-MAP','Tên giả lập','','','X','0','0','','0',''])
    out=io.BytesIO();b.save(out);content=out.getvalue()
    meta={'document_number':'Giả lập','document_date':'2026-01-01','source':'Nguồn giả lập','version':'fake'}
    data={'metadata':json.dumps(meta),'mapping':json.dumps({'__sheet':'MaGoc','code':headers[0],'not_primary':{'column':headers[4],'values':{'X':'1'}}}),'header_row':'2'}
    def post(preview=True,proof='',**changes):return a.post('/api/standards/icd10/import',files={'file':('fake.xlsx',content)},data={**data,'preview':str(preview).lower(),'proof':proof,**changes})
    pre=post();assert pre.status_code==200,pre.text
    assert post(mapping=json.dumps({'__sheet':'MaGoc','code':{'column':headers[0],'values':{'FAKE-MAP':'MA-TU-TAO'}}})).status_code==422
    assert post(False,pre.json()['fingerprint'],metadata=json.dumps({**meta,'version':'changed'})).status_code==422
    assert post(False,pre.json()['fingerprint']).status_code==200
    with db() as c:assert c.execute("SELECT not_primary FROM icd10 WHERE code='FAKE-MAP'").fetchone()[0]==1
    w.append(['FAKE-MAP','Dòng trùng giả lập']);out=io.BytesIO();b.save(out);content=out.getvalue()
    with db() as c:before=c.execute('SELECT COUNT(*) FROM catalog_imports').fetchone()[0]
    error=post();assert error.status_code==422 and error.json()['detail']['errors'][0]['row']==4
    with db() as c:assert c.execute('SELECT COUNT(*) FROM catalog_imports').fetchone()[0]==before
