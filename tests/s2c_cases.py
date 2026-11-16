"""Synthetic signing scenarios shared by SQLite and PostgreSQL."""
from io import BytesIO
import secrets
from zipfile import ZipFile

from PIL import Image, ImageDraw
from pypdf import PdfReader


def signature_image(color='blue'):
    image = Image.new('RGB', (150, 50), 'white')
    draw = ImageDraw.Draw(image)
    draw.line([(5, 40), (35, 8), (55, 36), (105, 15), (145, 25)], fill=color, width=4)
    out = BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def new_visit(clients, ids, service, dob='1990-01-01'):
    p = clients['reception'].post('/api/patients', json={'full_name': 'Người bệnh giả lập S2c '+secrets.token_hex(4),
        'date_of_birth': dob, 'sex': 'Nữ', 'phone': '0000000000', 'address': 'Địa chỉ giả lập'})
    assert p.status_code == 201, p.text
    v = clients['reception'].post('/api/visits', json={'patient_id': p.json()['id'], 'doctor_id': ids['doctor'], 'service_id': service})
    assert v.status_code == 201, v.text
    vid = v.json()['id']
    assert clients['doctor'].put(f'/api/visits/{vid}/clinical', json={'version': 0, 'diagnosis': 'Chẩn đoán giả lập S2c'}).status_code == 200
    return vid


def document(clients, ids, db, service, kind, dob='1990-01-01'):
    vid = new_visit(clients, ids, service, dob)
    d, t, a = clients['doctor'], clients['technician'], clients['admin']
    if kind == 'rx':
        suffix=secrets.token_hex(4)
        with db(True) as c:
            c.execute('INSERT INTO medicines(name,base_unit,code) VALUES(?,?,?)',('Thuốc giả lập S2c '+suffix,'viên','S2C-'+suffix))
            mid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        r = d.post('/api/prescriptions', json={'visit_id': vid, 'items':[{'medicine_id':mid,'quantity':2,'directions':'Liều giả lập'}], 'instructions': 'Lời dặn giả lập'})
        assert r.status_code == 201, r.text
        oid = r.json()['id']
        # This fixture has no inventory; keep it out of later pharmacy catalog choices.
        with db(True) as c:
            c.execute('UPDATE medicines SET active=0 WHERE id=?',(mid,))
        return vid, oid, f'/api/forms/rx/{oid}', f'/api/forms/rx/{oid}?fmt=docx'
    if kind == 'clinical_rx':
        r = d.post('/api/clinical-prescriptions', json={'visit_id': vid, 'items': [
            {'name': 'Thuốc giả lập S2c', 'ingredient': 'Chất giả lập S2c', 'strength': '5 mg', 'unit': 'viên',
             'dose': '1', 'frequency': '1', 'route': 'Uống', 'timing': 'sau ăn', 'days': '2'}]})
        assert r.status_code == 201, r.text
        oid = r.json()['id']
        return vid, oid, f'/api/clinical-prescriptions/{oid}/form', f'/api/clinical-prescriptions/{oid}/form?fmt=docx'
    sid = None
    if kind == 'lab_report':
        suffix = secrets.token_hex(4)
        test = a.post('/api/lab/catalog', json={'code': 'S2C-'+suffix, 'name': 'Chỉ số giả lập S2c', 'group_name': 'hematology',
            'unit': 'g/L', 'result_type': 'number', 'decimals': 1, 'references': [{'sex': 'chung', 'lower_value': '10', 'upper_value': '20'}]})
        assert test.status_code == 201, test.text
        tid = test.json()['id']
        with db(True) as c:
            c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)', ('XN giả lập S2c '+suffix, 10000, 'S2C-'+suffix))
            sid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)', (sid, 'lab'))
        assert a.put(f'/api/lab/services/{sid}', json={'test_ids': [tid]}).status_code == 200
    if sid is None:
        suffix=secrets.token_hex(4)
        with db(True) as c:
            c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)',('Glucose giả lập '+suffix,10000,'S2C-'+suffix))
            sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(sid,'lab'))
    args = {'service_id': sid, 'request_key': secrets.token_hex(16)}
    r = d.post('/api/orders', json={'visit_id': vid, 'category': 'lab', **args})
    assert r.status_code == 201, r.text
    oid = r.json()['id']
    if kind == 'lab_report':
        opened = t.post(f'/api/lab/orders/{oid}/reports')
        assert opened.status_code == 201, opened.text
        rid = opened.json()['id']
        path = f'/api/lab/reports/{rid}'
        assert t.put(path, json={'version': 0, 'sample_at': '2026-11-16T08:00:00+07:00', 'result_at': '2026-11-16T09:00:00+07:00',
            'items': [{'test_id': tid, 'value': '25'}]}).status_code == 200
        assert t.post(path+'/submit', json={'version': 1}).status_code == 200
        assert d.post(path+'/approve', json={'version': 2}).status_code == 200
        return vid, rid, path+'/form?group=hematology', path+'/form?group=hematology&fmt=docx'
    if kind == 'lab':
        assert t.put(f'/api/orders/{oid}/result', json={'version': 0, 'result_text': 'Glucose | 8 | mmol/L | 3.9 – 6.4 | H'}).status_code == 200
        assert d.post(f'/api/orders/{oid}/approve').status_code == 200
    return vid, oid, f'/api/forms/{kind}/{oid}', f'/api/forms/{kind}/{oid}?fmt=docx'


def image_count(response):
    assert response.status_code == 200, response.text[:500] if response.status_code != 200 else ''
    pdf = PdfReader(BytesIO(response.content))
    assert len(pdf.pages) == 1
    assert abs(float(pdf.pages[0].mediabox.width)-595.276) < 1
    return len(pdf.pages[0].images)


def check_signing(clients, ids, db, service, password, kind):
    d, a = clients['doctor'], clients['admin']
    own, other = signature_image('blue'), signature_image('red')
    for key, image in [('doctor', own), ('doctor2', other)]:
        assert a.put(f'/api/users/{ids[key]}/signature', files={'file': ('fake.png', image, 'image/png')}).status_code == 200
    vid, oid, url, word_url = document(clients, ids, db, service, kind)
    endpoint = f'/api/document-signatures/{kind}/{oid}'
    assert image_count(d.get(url)) == 1  # Only the public clinic logo, never a signature.
    state = d.get(endpoint)
    assert state.status_code == 200, state.text
    body = {'password': password, 'content_hash': state.json()['content_hash']}
    assert d.post(endpoint, json={**body, 'password': 'Sai mật khẩu giả lập'}).status_code == 403
    assert d.post(endpoint, json={**body, 'signed_by': ids['doctor2']}).status_code == 422
    for role in ('doctor2', 'technician', 'admin', 'reception', 'pharmacy'):
        assert clients[role].post(endpoint, json=body).status_code == 403
    assert image_count(d.get(url)) == 1
    signed = d.post(endpoint, json=body)
    assert signed.status_code == 200, signed.text
    assert signed.json()['signed_by'] == ids['doctor']
    assert image_count(d.get(url)) == 2
    aliases={'rx':f'/api/prescriptions/{oid}/forms/prescription','order':f'/api/orders/{oid}/forms/order','lab':f'/api/orders/{oid}/forms/result'}
    if kind in aliases:
        assert image_count(d.get(aliases[kind]))==2
    with ZipFile(BytesIO(d.get(word_url).content)) as archive:
        media = [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert own in media and other not in media
    pdf = PdfReader(BytesIO(d.get(url).content))
    text = pdf.pages[0].extract_text()
    assert 'Ký lúc ' in text and ' bởi tài khoản ' in text
    with db() as c:
        evidence = c.execute('SELECT * FROM document_signatures WHERE document_kind=? AND document_id=? ORDER BY id DESC LIMIT 1', (kind, oid)).fetchone()
        assert evidence['signed_by'] == ids['doctor'] and len(evidence['content_hash']) == 64
        assert c.execute("SELECT 1 FROM audit_log WHERE event='document_signed' AND object_type=? AND object_id=?", (kind, oid)).fetchone()
    # Operational versions and statuses do not alter print content or revoke a signature.
    with db(True) as c:
        c.execute('UPDATE visits SET version=version+1 WHERE id=?',(vid,))
    assert image_count(d.get(url))==2
    # Replacing an account's current signature never substitutes it into an earlier signed form.
    assert a.put(f'/api/users/{ids["doctor"]}/signature', files={'file': ('new.png', other, 'image/png')}).status_code == 200
    with ZipFile(BytesIO(d.get(word_url).content)) as archive:
        assert own in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
    # A clinical correction invalidates all prints for the encounter, permanently, even after revert.
    with db(True) as c:
        prior = c.execute('SELECT diagnosis FROM visits WHERE id=?', (vid,)).fetchone()[0]
        c.execute('UPDATE visits SET diagnosis=? WHERE id=?', ('Đã sửa nội dung giả lập', vid))
    assert image_count(d.get(url)) == 1
    with db(True) as c:
        c.execute('UPDATE visits SET diagnosis=? WHERE id=?', (prior, vid))
    assert image_count(d.get(url)) == 1
    # Fresh confirmation is required; every new signature adds its own audit entry.
    again = d.get(endpoint).json()
    assert d.post(endpoint, json={'password': password, 'content_hash': again['content_hash']}).status_code == 200
    assert image_count(d.get(url)) == 2
    with db() as c:
        assert c.execute('SELECT COUNT(*) FROM document_signatures WHERE document_kind=? AND document_id=?', (kind, oid)).fetchone()[0] == 2

    if kind in ('rx','clinical_rx'):
        if kind=='rx':
            # Mirror the existing warehouse workflow status without mutating stock or money.
            with db(True) as c:
                c.execute("UPDATE prescriptions SET status='dispensed' WHERE id=?",(oid,))
            assert image_count(d.get(url))==2
        current=d.get(f'/api/visits/{vid}').json()
        closed=d.post(f'/api/visits/{vid}/complete',json={'version':current['version']})
        assert closed.status_code==200,closed.text
        assert image_count(d.get(url))==2


def check_scoped_signature(clients, ids, db, service, password):
    d, a = clients['doctor'], clients['admin']
    image = signature_image()
    assert a.put(f'/api/users/{ids["doctor"]}/signature', files={'file': ('fake.png', image, 'image/png')}).status_code == 200
    vid, rid, url, _ = document(clients, ids, db, service, 'rx')
    endpoint = f'/api/document-signatures/rx/{rid}'
    state = d.get(endpoint).json()
    assert d.post(endpoint, json={'password': password, 'content_hash': state['content_hash']}).status_code == 200
    suffix = secrets.token_hex(6)
    test = a.post('/api/lab/catalog', json={'code': 'S2C-SCOPE-'+suffix, 'name': 'XN giả lập',
        'group_name': 'hematology', 'unit': 'g/L', 'result_type': 'number', 'decimals': 1})
    assert test.status_code == 201, test.text
    tid = test.json()['id']
    with db(True) as c:
        c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)', ('XN giả lập '+suffix, 10000, 'S2C-SCOPE-'+suffix))
        service_id = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)', (service_id, 'lab'))
    assert a.put(f'/api/lab/services/{service_id}', json={'test_ids': [tid]}).status_code == 200
    order = d.post('/api/orders', json={'visit_id': vid, 'category': 'lab', 'service_id': service_id, 'request_key': secrets.token_hex(16)})
    assert order.status_code == 201, order.text
    opened = clients['technician'].post(f"/api/lab/orders/{order.json()['id']}/reports")
    assert opened.status_code == 201, opened.text
    report = opened.json()['id']
    for version, value in ((0, '1'), (1, '2')):
        edited = clients['technician'].put(f'/api/lab/reports/{report}', json={
            'version': version, 'sample_at': '2026-11-16T08:00:00+07:00', 'result_at': '2026-11-16T09:00:00+07:00',
            'items': [{'test_id': tid, 'value': value}]})
        assert edited.status_code == 200, edited.text
    assert image_count(d.get(url)) == 2
    with db(True) as c:
        row = c.execute("SELECT id FROM document_signatures WHERE document_kind='rx' AND document_id=? ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
        sid = row['id']
        c.execute("UPDATE prescriptions SET instructions='Sửa đơn giả lập' WHERE id=?", (rid,))
    assert image_count(d.get(url)) == 1
    return sid


def check_order_invalidation_scope(clients, ids, db, service):
    vid = new_visit(clients, ids, service)
    with db(True) as c:
        pairs = []
        for index in (1, 2):
            c.execute("INSERT INTO orders(visit_id,category,name,requested_by,created_at) VALUES(?,'lab',?,?,'2026-01-01')", (vid, f'XN giả lập {index}', ids['doctor']))
            oid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO lab_reports(order_id,created_at) VALUES(?,'2026-01-01')", (oid,))
            report = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            ids_for_order = []
            for kind, document_id in (('order', oid), ('lab', oid), ('lab_report', report)):
                c.execute('INSERT INTO document_signatures(document_kind,document_id,visit_id,signed_by,signed_at,content_hash,image,username) VALUES(?,?,?,?,?,?,?,?)',
                          (kind, document_id, vid, ids['doctor'], '2026-01-01', '0'*64, signature_image(), 'fake'))
                ids_for_order.append(c.execute('SELECT id FROM document_signatures WHERE document_kind=? AND document_id=? AND visit_id=? ORDER BY id DESC LIMIT 1', (kind, document_id, vid)).fetchone()[0])
            pairs.append((oid, ids_for_order))
        c.execute("UPDATE orders SET name='Đã sửa' WHERE id=?", (pairs[0][0],))
        for index, (_, records) in enumerate(pairs):
            for sid in records:
                assert c.execute('SELECT invalidated FROM document_signatures WHERE id=?', (sid,)).fetchone()[0] == (1 if index == 0 else 0)
