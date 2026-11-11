"""Only the two owner-approved public workbooks and invented patient records."""
import csv
import io
import sqlite3

import pytest

from app.patient_catalog import (DATA, parse_geography, parse_ethnicities, bundled_catalog,
    search_catalog, migrate_public_catalog)

GEO='Danh-muc-Phuong-xa_moi_34-tinh-thanh-sau-sat-nhap.xlsx'
ETHNIC='Danh_sach_54_dan_toc_Viet_Nam_2026.xlsx'


def test_exact_public_source_counts_and_reproducible_csv():
    gx=parse_geography((DATA/GEO).read_bytes(),GEO,bundled=True)
    gc=parse_geography((DATA/'tinh_xa.csv').read_bytes(),'tinh_xa.csv',bundled=True)
    assert gx==gc
    provinces=[r for r in gc if r[0]=='province'];communes=[r for r in gc if r[0]=='commune']
    assert len(provinces)==34 and len({r[1] for r in provinces})==34
    assert len(communes)==3321 and len({r[1] for r in communes})==3321
    assert all(r[6]=='mã thuế TMS' and r[7] is None for r in communes)
    assert {r[2] for r in communes if r[3]=='06'} >= {'Phường Nam Định','Xã Cát Thành'}
    assert next(r for r in communes if r[2]=='Xã Cát Thành' and r[3]=='06')[5]=='Huyện Trực Ninh'
    ex=parse_ethnicities((DATA/ETHNIC).read_bytes(),ETHNIC,bundled=True)
    ec=parse_ethnicities((DATA/'dan_toc.csv').read_bytes(),'dan_toc.csv',bundled=True)
    assert ex==ec
    assert [r[1] for r in ec[:-2]]==[f'{i:02d}' for i in range(1,55)]
    assert {r[1] for r in ec[-2:]}=={'FOREIGN','UNKNOWN'}
    for name,parser in [('tinh_xa.csv',parse_geography),('dan_toc.csv',parse_ethnicities)]:
        rows=list(csv.reader(io.StringIO((DATA/name).read_text(encoding='utf-8'))));rows.pop()
        out=io.StringIO();csv.writer(out).writerows(rows)
        with pytest.raises(ValueError,match='34 tỉnh|54 dân tộc'):
            parser(out.getvalue().encode(),name,bundled=True)


def check_public_lookup(clients):
    r=clients['reception']
    for query,name in [('cat thanh','Xã Cát Thành'),('phuong nam dinh','Phường Nam Định')]:
        rows=r.get('/api/patient-catalog',params={'kind':'commune','province_code':'06','q':query}).json()
        assert any(x['name']==name and x['parent_code']=='06' for x in rows)
    for query,name in [('viet','Kinh'),('tho','Tày')]:
        rows=r.get('/api/patient-catalog',params={'kind':'ethnicity','q':query}).json()
        assert name in [x['name'] for x in rows]
    kinh=r.get('/api/patient-catalog',params={'kind':'ethnicity','q':'viet'}).json()[0]
    assert kinh['code']=='01' and kinh['aliases']=='Việt'
    assert r.get('/api/patient-catalog',params={'kind':'commune'}).json()==[]
    assert len(r.get('/api/patient-catalog',params={'kind':'commune','province_code':'01','limit':100}).json())<=30
    assert not any(x['kind']=='commune' for x in r.get('/api/patient-catalog').json())
    for ec in ('FOREIGN','UNKNOWN','01',None):
        response=r.post('/api/patients',json={'full_name':'Người giả lập dân tộc','date_of_birth':'1990-01-01','sex':'Nam','phone':'0900000000','ethnicity_code':ec})
        assert response.status_code==201,response.text
        saved=r.get('/api/patients/'+str(response.json()['id'])).json()
        assert saved['ethnicity_code']==ec
        assert saved['ethnicity']=={'FOREIGN':'Người nước ngoài','UNKNOWN':'Không rõ','01':'Kinh',None:None}[ec]
    assert clients['admin'].put('/api/ui-settings',json={'default_province_code':'06'}).status_code==200
    assert clients['admin'].get('/api/ui-settings').json()['default_province_code']=='06'
    assert clients['reception'].put('/api/ui-settings',json={'default_province_code':'01'}).status_code==403
    assert clients['admin'].put('/api/ui-settings',json={'default_province_code':'99'}).status_code==422
    assert clients['admin'].put('/api/ui-settings',json={'default_province_code':None}).status_code==200


def test_public_lookup_and_explicit_ethnicity_codes():
    from tests.test_administrative import context
    clients,_=context()
    from app.ui_settings import settings_path
    from app.main import FILES
    path=settings_path(FILES);old=path.read_bytes() if path.exists() else None
    try:check_public_lookup(clients)
    finally:
        if old is None:path.unlink(missing_ok=True)
        else:path.write_bytes(old)


def test_public_migration_never_guesses_legacy_ethnicity(tmp_path):
    from tests.test_manual_price_migration import legacy
    from app.manual_price_migration import migrate_sqlite_manual_prices
    from app.m0_migration import migrate_m0
    from app.administrative_migration import migrate_administrative
    file=tmp_path/'old.sqlite3';legacy(file);migrate_sqlite_manual_prices(file)
    with sqlite3.connect(file) as c:
        c.row_factory=sqlite3.Row
        migrate_m0(c);migrate_administrative(c)
        c.execute("UPDATE patients SET ethnicity='Kinh',province='Địa chỉ tỉnh cũ giả lập',commune='Xã cũ giả lập'")
        before=dict(c.execute('SELECT * FROM patients WHERE id=1').fetchone())
        migrate_public_catalog(c);migrate_public_catalog(c)
        p=dict(c.execute('SELECT * FROM patients WHERE id=1').fetchone())
        assert all(p[k]==v for k,v in before.items())
        assert p['ethnicity_code'] is None and p['province_code'] is None and p['commune_code'] is None
        assert c.execute('SELECT COUNT(*) FROM patient_catalog WHERE active=1').fetchone()[0]==3411
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='patient_catalog_seeded'").fetchone()[0]==1
