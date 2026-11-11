from tests.test_administrative import context
from app.main import db
from tests.m6_cases import check_m6


def test_m6_clinical_prescription_end_to_end():
    clients,ids=context();check_m6(clients,ids,db,1)


def test_m6_quantity_and_legacy_address():
    from app.m6 import quantity,components
    from app.forms import format_patient_address
    assert quantity('0,5','2','7')=='7'
    assert quantity('1/2 viên','2','7')==''
    assert components('A + B')==['A','B']
    assert format_patient_address({'address':'Nhà giả lập','commune':'Xã giả lập','province':'Tỉnh giả lập'})=='Nhà giả lập, Xã giả lập, Tỉnh giả lập'


def test_m6_excel_preview_errors_atomic_and_example_rows():
    import io
    from openpyxl import Workbook
    clients,_=context();a=clients['admin'];r=clients['reception']
    from app.m6_import import HEADERS
    def book(rows,headers=HEADERS):
        w=Workbook();s=w.active;s.title='DanhMucThuoc';s.append(list(headers))
        for row in rows:s.append(row)
        b=io.BytesIO();w.save(b);return b.getvalue()
    fake=[1,'Mặt hàng giả lập Excel','Hoạt chất giả lập','10 mg','Viên giả lập','Uống','viên','ĐK-GIA-LAP','Nhà sản xuất giả lập','Chỉ kiểm thử']
    upload=lambda raw,preview='true':{'files':{'file':('thuoc-gia-lap.xlsx',raw)},'data':{'preview':preview}}
    raw=book([fake,[2,'VÍ DỤ bỏ qua','','','','','','','','']])
    assert r.post('/api/drugs/import',**upload(raw)).status_code==403
    with db() as c:before=c.execute('SELECT COUNT(*) FROM drugs').fetchone()[0]
    result=a.post('/api/drugs/import',**upload(raw));assert result.status_code==200,result.text
    assert result.json()['count']==1
    with db() as c:assert c.execute('SELECT COUNT(*) FROM drugs').fetchone()[0]==before
    bad=book([fake,[3,'','','','','','','','','']])
    result=a.post('/api/drugs/import',**upload(bad,'false'));assert result.status_code==422 and result.json()['detail']['errors'][0]['row']==3
    with db() as c:assert c.execute('SELECT COUNT(*) FROM drugs').fetchone()[0]==before
    missing=book([],HEADERS[:-1]);result=a.post('/api/drugs/import',**upload(missing));assert result.status_code==422 and 'Ghi chú' in result.text
    result=a.post('/api/drugs/import',**upload(raw,'false'));assert result.status_code==200 and result.json()['added']==1


def test_m6_migration_additive_idempotent(tmp_path):
    import sqlite3
    from app.m6_migration import migrate_m6,TABLES
    c=sqlite3.connect(tmp_path/'legacy.sqlite');c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)');c.execute('INSERT INTO schema_migrations VALUES(7)')
    for table in ('users','visits'):
        c.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY,content TEXT)');c.execute('INSERT INTO '+table+' VALUES(1,?)',('Giữ nguyên giả lập',))
    migrate_m6(c);migrate_m6(c)
    assert c.execute('SELECT * FROM visits').fetchall()==[(1,'Giữ nguyên giả lập')]
    assert c.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()==[(7,),(8,)]
    for table in TABLES:assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    c.close()
