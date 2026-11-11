"""L1/L2 scenarios shared by SQLite and PostgreSQL; all records are invented."""
import io
import json
import secrets
from datetime import datetime, timedelta

from docx import Document


def check_administrative(clients, ids, db, service_id):
    r, d, a = (clients[k] for k in ('reception', 'doctor', 'admin'))
    from app.practitioners import COLUMNS
    prior=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==ids['doctor'])
    prior={key:prior[key] for key in COLUMNS}
    base = {'full_name': 'Hồ sơ hành chính giả lập '+secrets.token_hex(3), 'date_of_birth': '1990-01-01', 'sex': 'Nữ', 'phone': '0900000000'}
    number = '000'+str(secrets.randbelow(10**9)).zfill(9)  # synthetic document, never a real record
    for invalid in ('0'*11, '0'*13, '0'*11+'A'):
        res = r.post('/api/patients', json=dict(base, document_type='identity', document_number=invalid))
        assert res.status_code == 422, res.text
    for body in ({'document_type': 'identity'}, {'document_type': 'passport'}, {'document_type': 'none', 'document_number': number}):
        assert r.post('/api/patients', json=dict(base, **body)).status_code == 422
    payload = dict(base, document_type='identity', document_number=number,
                   ethnicity='Kinh', occupation='Nghề giả lập', workplace='Nơi học giả lập',
                   province='Tỉnh Ninh Bình', commune='Xã Cát Thành', address_detail='Số nhà giả lập', address='Địa chỉ cũ giả lập')
    first = r.post('/api/patients', json=payload); assert first.status_code == 201, first.text
    pid = first.json()['id']
    second = r.post('/api/patients', json=payload); assert second.status_code == 201, second.text
    assert second.json()['warnings']
    assert clients['manager'].get(f'/api/patients/{pid}').status_code == 403
    assert clients['doctor2'].get(f'/api/patients/{pid}').status_code == 403
    for role in ('reception', 'admin'):
        rows = clients[role].get('/api/patients', params={'q': number}).json()
        matches = [x for x in rows if x['id'] in (pid, second.json()['id'])]
        assert len(matches) == 2
        assert all(x['document_number'] == '••••'+number[-4:] and x['citizen_id'] == '••••'+number[-4:] for x in matches)
    assert pid not in [x['id'] for x in r.get('/api/patients', params={'q': number[1:]}).json()]
    assert a.get(f'/api/patients/{pid}').json()['document_number'] == '••••'+number[-4:]
    assert r.get(f'/api/patients/{pid}').json()['document_number'] == number
    v = r.post('/api/visits', json={'patient_id': pid, 'doctor_id': ids['doctor'], 'service_id': service_id})
    assert v.status_code == 201, v.text
    vid = v.json()['id']
    assert d.get(f'/api/patients/{pid}').json()['document_number'] == number
    assert d.post(f'/api/visits/{vid}/nurses',json={'nurse_id':ids['nurse']}).status_code==201
    nurse=clients['nurse']
    assert 'document_number' not in nurse.get(f'/api/patients/{pid}').json()
    assert 'citizen_id' not in nurse.get(f'/api/patients/{pid}').json()
    nrows=nurse.get('/api/patients',params={'q':number}).json()
    assert next(x for x in nrows if x['id']==pid)['document_number']=='••••'+number[-4:]
    with db() as c:
        events = [dict(x) for x in c.execute("SELECT * FROM audit_log WHERE event='patient_document_viewed' AND object_id=?", (pid,))]
        assert {e['user_id'] for e in events} == {ids['doctor'], ids['reception']}
        assert all(number not in x['details'] for x in events)
    assert d.patch(f'/api/patients/{pid}/administrative', json=payload).status_code == 403
    assert a.patch(f'/api/patients/{pid}/administrative', json=payload).status_code == 403
    changed = r.patch(f'/api/patients/{pid}/administrative', json={k: v for k,v in payload.items() if k not in base and k!='address'})
    assert changed.status_code == 200 and changed.json()['warnings']
    # Metadata cannot be changed by doctors, reception, manager, or self-service account routes.
    practitioner = {'printed_name': 'Nguyễn Giả Lập', 'printed_title': 'BSCKI',
                    'practice_license': 'GP-GIA-LAP', 'practice_scopes': ['Nội'],
                    'certificate_provider': 'Nhà cung cấp giả lập', 'certificate_serial': 'SERI-GIA-LAP', 'certificate_expiry': '01/01/2000'}
    for role in ('reception', 'doctor', 'manager', 'technician'):
        assert clients[role].put(f'/api/practitioners/{ids["doctor"]}', json=practitioner).status_code == 403
        assert clients[role].get('/api/practitioners').status_code == 403
    assert a.put(f'/api/practitioners/{ids["doctor"]}', json=practitioner).status_code == 200
    assert next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==ids['doctor'])['certificate_warning']
    with db() as c:
        old_name = c.execute('SELECT full_name FROM users WHERE id=?', (ids['doctor'],)).fetchone()[0]
        from app.practitioners import has_scope
        assert has_scope(c, ids['doctor'], 'Nội') and not has_scope(c, ids['doctor'], 'Xét nghiệm')
        log = c.execute("SELECT details FROM audit_log WHERE event='practitioner_updated' AND object_id=? ORDER BY id DESC LIMIT 1", (ids['doctor'],)).fetchone()[0]
        assert json.loads(log)['new'] == dict(practitioner,certificate_expiry='2000-01-01')
        assert 'old' in json.loads(log)
    assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Giả lập','follow_up':'01/01/2027'}).status_code==200
    # Both document routes and the legacy PDF routes must draw the same display name.
    for path in (f'/api/forms/visit/{vid}?fmt=docx', f'/api/visits/{vid}/forms/clinical?format=docx',
                 f'/api/forms/followup/{vid}?fmt=docx',f'/api/visits/{vid}/forms/followup?format=docx'):
        res = d.get(path); assert res.status_code == 200, res.text
        doc = Document(io.BytesIO(res.content))
        text = '\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(cell.text for t in doc.tables for row in t.rows for cell in row.cells)
        assert 'BSCKI Nguyễn Giả Lập' in text and 'Nghề giả lập' in text and 'Địa chỉ cũ giả lập' in text, (path,text)
        assert number not in text
    import pymupdf
    for path in (f'/api/forms/visit/{vid}',f'/api/visits/{vid}/forms/clinical',f'/api/print/clinical/{vid}',f'/api/print/follow_up/{vid}'):
        res=d.get(path);assert res.status_code==200,res.text
        with pymupdf.open(stream=res.content,filetype='pdf') as pdf:
            assert 'BSCKI Nguyễn Giả Lập' in ''.join(page.get_text() for page in pdf)
    # Empty metadata falls back to account name; restore to keep other suites independent.
    assert a.put(f'/api/practitioners/{ids["doctor"]}', json={}).status_code == 200
    from app.practitioners import printed_name
    with db() as c: assert printed_name(c, ids['doctor']) == old_name
    a.put(f'/api/practitioners/{ids["doctor"]}',json=prior)


def check_catalog(clients, db):
    from app.patient_catalog import GEO_HEADERS, ETHNIC_HEADERS, bundled_catalog, apply_catalog
    import csv as csv_module
    a,r=clients['admin'],clients['reception']
    def content(headers,rows):
        buf=io.StringIO();w=csv_module.writer(buf);w.writerow(headers);w.writerows(rows);return buf.getvalue().encode()
    geography=content(GEO_HEADERS,[['99','Tỉnh giả lập','99001','Xã cùng tên giả lập','Huyện cũ giả lập'],['98','Tỉnh khác giả lập','98001','Xã cùng tên giả lập','Huyện cũ khác']])
    upload=lambda raw,kind='geography': {'data':{'kind':kind},'files':{'file':('gia-lap.csv',raw,'text/csv')}}
    assert r.post('/api/patient-catalog/import',**upload(geography)).status_code==403
    try:
        response=a.post('/api/patient-catalog/import',**upload(geography));assert response.status_code==200,response.text
        assert response.json()['inactive']>=3355
        # Equal commune names in different provinces are valid and resolve by both codes.
        for province,commune in [('99','99001'),('98','98001')]:
            p=r.post('/api/patients',json={'full_name':'Người giả lập danh mục','date_of_birth':'1990-01-01','sex':'Nam','phone':'0900000000','province_code':province,'commune_code':commune})
            assert p.status_code==201,p.text
        before=a.get('/api/patient-catalog',params={'kind':'province'}).json()
        missing=content(GEO_HEADERS[:-1],[['99','Tỉnh giả lập','99001','Xã cùng tên giả lập']])
        res=a.post('/api/patient-catalog/import',**upload(missing))
        assert res.status_code==422 and 'Tên Quận huyện TMS (cũ)' in res.json()['detail']
        duplicate=content(GEO_HEADERS,[['99','Tỉnh giả lập','99001','Xã một',''],['99','Tỉnh giả lập','99001','Xã hai','']])
        res=a.post('/api/patient-catalog/import',**upload(duplicate));assert res.status_code==422 and 'Dòng 3' in res.json()['detail']
        assert a.get('/api/patient-catalog',params={'kind':'province'}).json()==before
        # Update by code and deactivate a removed, referenced commune. Patient snapshots do not change.
        kept_pid=p.json()['id']
        changed=content(GEO_HEADERS,[['99','Tỉnh giả lập đổi tên','99001','Xã mới giả lập','Huyện cũ giả lập']])
        assert a.post('/api/patient-catalog/import',**upload(changed)).status_code==200
        kept=r.get(f'/api/patients/{kept_pid}').json()
        assert kept['province']=='Tỉnh khác giả lập' and kept['commune']=='Xã cùng tên giả lập'
        with db() as c:
            assert c.execute("SELECT active FROM patient_catalog WHERE kind='commune' AND code='98001'").fetchone()[0]==0
        assert a.get('/api/patient-catalog',params={'kind':'commune','province_code':'98'}).json()==[]
        body={k:kept[k] for k in ('province','commune','province_code','commune_code','ethnicity','ethnicity_code')}
        assert r.patch(f'/api/patients/{kept_pid}/administrative',json=body).status_code==200
        assert r.post('/api/patients',json={'full_name':'Người mới giả lập','date_of_birth':'1990-01-01','sex':'Nam','phone':'0900000000','province_code':'98','commune_code':'98001'}).status_code==422
        moved=content(GEO_HEADERS,[['99','Tỉnh giả lập đổi tên','98001','Xã được chuyển giả lập','Huyện cũ khác']])
        assert a.post('/api/patient-catalog/import',**upload(moved)).status_code==200
        assert r.patch(f'/api/patients/{kept_pid}/administrative',json=body).status_code==200
        assert r.get(f'/api/patients/{kept_pid}').json()['province']=='Tỉnh khác giả lập'

        # Workbook headers are located by name, ignoring surrounding spaces.
        from openpyxl import Workbook
        book=Workbook();sheet=book.active;sheet.append(['Ghi chú công khai']);sheet.append([]);sheet.append([' '+h+' ' for h in reversed(GEO_HEADERS)])
        sheet.append(list(reversed(['99','Tỉnh giả lập','99001','Xã giả lập','Huyện cũ giả lập'])))
        buf=io.BytesIO();book.save(buf)
        res=a.post('/api/patient-catalog/import',data={'kind':'geography'},files={'file':('gia-lap.xlsx',buf.getvalue())});assert res.status_code==200,res.text
        ethnic=content(ETHNIC_HEADERS,[['01','Dân tộc giả lập','Tên khác giả lập']])
        assert a.post('/api/patient-catalog/import',**upload(ethnic,'ethnicity')).status_code==200
        assert a.get('/api/patient-catalog',params={'kind':'ethnicity','q':'ten khac gia lap'}).json()[0]['code']=='01'
        # Original public catalogs remain available to restore the removed items.
        assert a.post('/api/patient-catalog/import').status_code==200
        assert len(a.get('/api/patient-catalog',params={'kind':'province'}).json())==34
        assert any(x['event']=='patient_catalog_imported' for x in a.get('/api/audit?limit=30').json())
    finally:
        with db(True) as c:apply_catalog(c,bundled_catalog(),('province','commune','ethnicity'))


def check_child(clients, ids, db, service_id):
    from app.labels import VN_TZ
    from app.administrative import months_old
    now=datetime(2026,11,10,16,59,59,tzinfo=__import__('datetime').timezone.utc)
    assert months_old('2020-11-11',now)==71
    assert months_old('2020-11-11',now+timedelta(seconds=1))==72
    assert months_old('2020-02-29',datetime(2026,2,28,0,tzinfo=VN_TZ))==71
    from unittest.mock import patch
    fixed = datetime(2026,11,10,12,tzinfo=VN_TZ)
    r,d=clients['reception'],clients['doctor']
    # Patch only the shared age clock, including the real prescribing API call.
    with patch('app.administrative.datetime') as clock:
        clock.now.return_value=fixed
        for birth, child in [('2020-11-11',True),('2020-11-10',False)]:
            p=r.post('/api/patients',json={'full_name':'Trẻ giả lập ranh giới','date_of_birth':birth,'sex':'Nữ','phone':'0900000000'}).json()['id']
            vid=r.post('/api/visits',json={'patient_id':p,'doctor_id':ids['doctor'],'service_id':service_id}).json()['id']
            assert d.get(f'/api/visits/{vid}').json()['age_months']==(71 if child else 72)
            assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập'}).status_code==200
            # structured items for both demo and LAN
            with db() as c: medicine=c.execute('SELECT id FROM medicines WHERE controlled=0 AND active=1 ORDER BY id LIMIT 1').fetchone()[0]
            rx={'visit_id':vid,'items':[{'medicine_id':medicine,'quantity':1,'directions':'Giả lập'}]}
            if child:
                assert d.post('/api/prescriptions',json=rx).status_code==422
                child_data={'version':1,'weight_kg':12.5}
                assert r.put(f'/api/visits/{vid}/child-details',json=child_data).status_code==403
                assert d.put(f'/api/visits/{vid}/child-details',json=child_data).status_code==200
                assert d.post('/api/prescriptions',json=rx).status_code==422
                child_data.update(version=2,weight_kg=None,escort_name='Người giả lập',escort_relationship='Mẹ',escort_phone='0900000000')
                assert d.put(f'/api/visits/{vid}/child-details',json=child_data).status_code==200
                assert d.post('/api/prescriptions',json=rx).status_code==422
                child_data.update(version=3,weight_kg=12.5)
                assert d.put(f'/api/visits/{vid}/child-details',json=child_data).status_code==200
            res=d.post('/api/prescriptions',json=rx)
            assert res.status_code==201,res.text


def check_scopes(clients, ids, db, service_id):
    r,d,a,t=(clients[k] for k in ('reception','doctor','admin','technician'))
    p=r.post('/api/patients',json={'full_name':'Giả lập phạm vi','date_of_birth':'1990-01-01','sex':'Nam','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':p,'doctor_id':ids['doctor'],'service_id':service_id}).json()['id']
    from app.ui_settings import settings_path
    from app.main import FILES
    settings_file=settings_path(FILES)
    previous=settings_file.read_bytes() if settings_file.exists() else None
    from app.practitioners import COLUMNS
    prior=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==ids['doctor'])
    prior={key:prior[key] for key in COLUMNS}
    a.put(f'/api/practitioners/{ids["doctor"]}',json={})
    category_services={}
    with db(True) as c:
        for category in ('lab','ultrasound','xray','ecg'):
            c.execute('INSERT INTO service_catalog(name,price) VALUES(?,?)',('Dịch vụ giả lập '+category,1000))
            sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(sid,category))
            category_services[category]=sid
    try:
        assert a.get('/api/ui-settings').json()['block_practitioner_scope'] is False
        a.put(f'/api/practitioners/{ids["doctor"]}',json={'printed_name':'Người duyệt giả lập','printed_title':'ThS.BS'})
        for category in ('lab','ultrasound','xray','ecg'):
            o=d.post('/api/orders',json={'visit_id':vid,'category':category,'name':'Dịch vụ giả lập','service_id':category_services[category],'request_key':secrets.token_hex(16)})
            assert o.status_code==201,o.text
            oid=o.json()['id']
            assert t.put(f'/api/orders/{oid}/result',json={'result_text':'Kết luận: Giả lập'}).status_code==200
            res=d.post(f'/api/orders/{oid}/approve');assert res.status_code==200,res.text
            assert bool(res.json()['warnings'])==(category!='ecg')
            for path in (f'/api/forms/{category}/{oid}?fmt=docx',f'/api/orders/{oid}/forms/result?format=docx'):
                output=d.get(path);assert output.status_code==200,output.text
                doc=Document(io.BytesIO(output.content))
                text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
                assert 'ThS.BS Người duyệt giả lập' in text
        with db() as c:
            assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='practitioner_scope_warning' AND object_id IN (SELECT id FROM orders WHERE visit_id=?)",(vid,)).fetchone()[0]==3
        assert a.put('/api/ui-settings',json={'block_practitioner_scope':True}).status_code==200
        oid=d.post('/api/orders',json={'visit_id':vid,'category':'lab','name':'Xét nghiệm giả lập','service_id':category_services['lab'],'request_key':secrets.token_hex(16)}).json()['id']
        assert t.put(f'/api/orders/{oid}/result',json={'result_text':'Kết luận: Giả lập'}).status_code==200
        assert d.post(f'/api/orders/{oid}/approve').status_code==422
        assert a.put(f'/api/practitioners/{ids["doctor"]}',json={'practice_scopes':['Xét nghiệm','Chẩn đoán hình ảnh']}).status_code==200
        assert d.post(f'/api/orders/{oid}/approve').json()['warnings']==[]
    finally:
        a.put('/api/ui-settings',json={'block_practitioner_scope':False})
        a.put(f'/api/practitioners/{ids["doctor"]}',json=prior)
        if previous is None:settings_file.unlink(missing_ok=True)
        else:settings_file.write_bytes(previous)
