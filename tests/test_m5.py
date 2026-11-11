import sqlite3
from tests.test_administrative import context
from app.main import db
from tests.m5_cases import check_m5


def test_m5_lifecycle_snapshot_adjustment_print_permissions_and_queue():
    clients,ids=context();check_m5(clients,ids,db,1)


def test_m5_reference_boundaries_sex_no_reference_and_vietnam_sample_age():
    from app.m5 import evaluate,age_at
    d={'result_type':'number'}
    refs=[dict(sex='chung',age_from=0,age_to=71,lower_value='100',upper_value='200',normal_value=''),dict(sex='Nam',age_from=72,age_to=120,lower_value='10',upper_value='20',normal_value='')]
    assert evaluate(d,refs,'99','Nữ',71)['flag']=='L'
    assert evaluate(d,refs,'100','Nữ',71)['flag']==''
    assert evaluate(d,refs,'200','Nữ',71)['flag']==''
    assert evaluate(d,refs,'201','Nữ',71)['flag']=='H'
    assert evaluate(d,refs,'9','Nam',72)['flag']=='L'
    assert evaluate(d,refs,'21','Nam',120)['flag']=='H'
    assert evaluate(d,refs,'9','Nam',121)['flag']==''
    assert evaluate(d,refs,'9','Nữ',72)['flag']==''
    assert evaluate(d,refs,'9','Nam',None)['flag']==''
    assert evaluate({'result_type':'choice'},refs,'Mẫu giả lập','Nam',72)['flag']==''
    assert age_at('2020-01-02','2026-01-01T16:59:59+00:00')==71
    assert age_at('2020-01-02','2026-01-01T17:00:00+00:00')==72


def test_m5_migration_legacy_and_idempotence(tmp_path):
    from app.m5_migration import migrate_m5,FRAMEWORK,TABLES
    c=sqlite3.connect(tmp_path/'old.sqlite');c.execute('PRAGMA foreign_keys=ON')
    c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)');c.execute('INSERT INTO schema_migrations VALUES(8)')
    for table in ('users','service_catalog','orders'):
        c.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY,content TEXT)');c.execute('INSERT INTO '+table+' VALUES(1,?)',('Kết quả chữ/tệp cũ giả lập',))
    before=c.execute('SELECT * FROM orders').fetchall();migrate_m5(c);migrate_m5(c)
    assert c.execute('SELECT * FROM orders').fetchall()==before
    assert c.execute('SELECT COUNT(*) FROM lab_tests').fetchone()[0]==sum(len(x) for x in FRAMEWORK.values())
    assert c.execute('SELECT COUNT(*) FROM lab_reference_ranges').fetchone()[0]==0
    assert c.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()==[(8,),(9,)]
    for name in TABLES[1:]:assert c.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]==0


def test_m5_excel_preview_atomic_error_rows_and_round_trip():
    from app.m5_import import workbook
    from openpyxl import load_workbook
    from io import BytesIO
    import secrets
    clients,_=context();a=clients['admin'];r=clients['reception']
    x={'code':'XL-'+secrets.token_hex(4),'name':'Chỉ số Excel giả lập','abbreviation':'FAKE','group_name':'other','result_type':'number','unit':'đv giả lập','decimals':1,'print_order':1,'active':True,'choices':[],'references':[{'sex':'chung','age_from':None,'age_to':None,'lower_value':'1','upper_value':'2','normal_value':''}]}
    raw=workbook([x]);upload=lambda b,preview:{'files':{'file':('fake.xlsx',b)},'data':{'preview':preview}}
    assert r.post('/api/lab/catalog-import',**upload(raw,'false')).status_code==403
    with db() as c:before=c.execute('SELECT COUNT(*) FROM lab_tests').fetchone()[0]
    preview=a.post('/api/lab/catalog-import',**upload(raw,'true')).json();assert preview['count']==1
    with db() as c:assert c.execute('SELECT COUNT(*) FROM lab_tests').fetchone()[0]==before
    w=load_workbook(BytesIO(raw));w['ThamChieu'].append(['không có','','','','','','']);b=BytesIO();w.save(b)
    bad=a.post('/api/lab/catalog-import',**upload(b.getvalue(),'true'));assert bad.status_code==422 and bad.json()['detail']['errors'][0]['row']==3
    with db() as c:assert c.execute('SELECT COUNT(*) FROM lab_tests').fetchone()[0]==before
    w['ChiSo'].cell(1,1).value='Sai tên cột';b=BytesIO();w.save(b)
    bad=a.post('/api/lab/catalog-import',**upload(b.getvalue(),'true'));assert bad.status_code==422 and 'Mã chỉ số' in bad.text
    args=upload(raw,'false');args['data']['fingerprint']=preview['fingerprint']
    assert a.post('/api/lab/catalog-import',**args).status_code==200
    export=a.get('/api/lab/catalog-file');assert export.status_code==200
    from app.m5_import import parse
    assert any(row['test']['code']==x['code'] and len(row['test']['references'])==1 for row in parse(export.content))
    assert a.get('/api/lab/catalog-file?template=true').status_code==200


def test_m5_invalid_numbers_ranges_and_source_contract():
    import pytest
    from app.m5 import number,TestInput
    for value in ('NaN','Infinity','1e-999999999','1e99','không phải số'):
        with pytest.raises(ValueError):number(value)
    assert str(number('-2,5'))=='-2.5'
    with pytest.raises(ValueError):TestInput(code='FAKE',name='Giả lập',group_name='other',references=[{'sex':'Nam','age_from':0,'age_to':72,'lower_value':'1'},{'sex':'Nam','age_from':72,'lower_value':'2'}])


def test_m5_closed_correction_rounding_snapshot_audit_and_print():
    from tests.m5_revision_cases import check_closed_correction
    clients,ids=context();check_closed_correction(clients,ids,db,1)


def test_m5_cancelled_visit_blocks_all_result_writes():
    from tests.m5_revision_cases import check_cancelled_writes
    clients,ids=context();check_cancelled_writes(clients,ids,db,1)


def test_m5_import_requires_issued_preview_of_exact_file():
    from tests.m5_revision_cases import check_preview_gate
    clients,_=context();check_preview_gate(clients)
