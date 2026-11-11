"""PR16 regression cases; every patient/document/escort below is synthetic."""
import io
import json
import secrets

from docx import Document
import pymupdf


def check_patch_preserves_administrative_and_private_audit(clients, ids, db, service_id):
    r, d = clients['reception'], clients['doctor']
    number = '000'+str(secrets.randbelow(10**9)).zfill(9)
    patient = r.post('/api/patients', json={
        'full_name': 'Người giả lập kiểm PATCH', 'date_of_birth': '1990-01-01', 'sex': 'Nữ',
        'phone': '0900000000', 'document_type': 'identity', 'document_number': number,
        'ethnicity_code': '01', 'province_code': '06', 'commune_code': '11311067',
        'address_detail': 'Nhà giả lập', 'occupation': 'Nghề cũ giả lập', 'workplace': 'Nơi giả lập'})
    assert patient.status_code == 201, patient.text
    pid = patient.json()['id']; url = f'/api/patients/{pid}/administrative'
    visit = r.post('/api/visits', json={'patient_id': pid, 'doctor_id': ids['doctor'], 'service_id': service_id})
    assert visit.status_code == 201, visit.text
    vid = visit.json()['id']
    child = {'version': 0, 'weight_kg': 22, 'escort_name': 'Người đưa trẻ giả lập',
             'escort_relationship': 'Mẹ giả lập', 'escort_phone': '0900000000'}
    assert d.put(f'/api/visits/{vid}/child-details', json=child).status_code == 200
    with db() as c:
        before = dict(c.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone())
        escort = dict(c.execute('SELECT * FROM visits WHERE id=?', (vid,)).fetchone())
    for client in (clients['admin'], d, clients['manager']):
        assert client.patch(url, json={'occupation': 'Không được sửa'}).status_code == 403
    assert r.patch(url, json={}).status_code == 422
    assert r.put(url, json={'occupation': 'Không được xóa ngầm'}).status_code == 422
    assert r.patch(url, json={'occupation': 'Nghề mới giả lập'}).status_code == 200
    with db() as c:
        after = dict(c.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone())
        assert after == dict(before, occupation='Nghề mới giả lập')
        assert dict(c.execute('SELECT * FROM visits WHERE id=?', (vid,)).fetchone()) == escort
        log = json.loads(c.execute("SELECT details FROM audit_log WHERE event='patient_administrative_updated' AND object_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()[0])
        assert log == {'fields': ['occupation'], 'changes': {'occupation': {'old': before['occupation'], 'new': after['occupation']}}}
    new_number = '000000000000' if number != '000000000000' else '000000000001'
    assert r.patch(url, json={'document_number': new_number}).status_code == 200
    with db() as c:
        raw = c.execute("SELECT details FROM audit_log WHERE event='patient_administrative_updated' AND object_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()[0]
        assert json.loads(raw) == {'fields': ['citizen_id', 'document_number'], 'changes': {}}
        assert number not in raw and new_number not in raw
    assert r.patch(url, json={'document_type': 'passport', 'document_number': 'AB123'}).status_code == 422
    assert r.patch(url, json={'document_type': 'passport', 'document_number': 'AB1234'}).status_code == 200
    with db() as c:
        row = dict(c.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone())
        from app.administrative import AdministrativeFields
        complete = {k: row[k] for k in AdministrativeFields.model_fields}
    assert r.put(url, json=complete).status_code == 200
    # Names and codes form one declared catalog choice; safe changes retain old/new.
    assert r.patch(url, json={'ethnicity_code': '02', 'province_code': '01', 'commune_code': None, 'commune': None}).status_code == 200
    with db() as c:
        event = json.loads(c.execute("SELECT details FROM audit_log WHERE event='patient_administrative_updated' AND object_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()[0])
        assert event['changes']['ethnicity'] == {'old': 'Kinh', 'new': 'Tày'}
        assert event['changes']['province']['old'] == 'Tỉnh Ninh Bình'
        assert event['changes']['commune'] == {'old': 'Xã Cát Thành', 'new': None}
    # Existing legacy aliases/whitespace are not silently normalized by an unrelated PATCH.
    with db(True) as c:
        c.execute('UPDATE patients SET citizen_id=?, document_type=NULL, document_number=NULL, occupation=? WHERE id=?', ('AB12', ' Nghề cũ giả lập ', pid))
    assert r.patch(url, json={'workplace': 'Nơi mới giả lập'}).status_code == 200
    with db() as c:
        row = c.execute('SELECT citizen_id,document_type,document_number,occupation FROM patients WHERE id=?', (pid,)).fetchone()
        assert tuple(row[k] for k in ('citizen_id', 'document_type', 'document_number', 'occupation')) == ('AB12', None, None, ' Nghề cũ giả lập ')
    assert clients['admin'].get(f'/api/patients/{pid}').json()['citizen_id'] == '••••'
    matches = r.get('/api/patients', params={'q': 'AB12'}).json()
    assert next(x for x in matches if x['id'] == pid)['citizen_id'] == '••••'
    assert r.patch(url, json={'workplace': None}).status_code == 200
    with db() as c:
        assert c.execute('SELECT workplace FROM patients WHERE id=?', (pid,)).fetchone()[0] is None


def check_structured_address_print_position(clients, ids, db, service_id):
    r, d = clients['reception'], clients['doctor']
    res = r.post('/api/patients', json={'full_name': 'Người giả lập địa chỉ cấu trúc',
        'date_of_birth': '1990-01-01', 'sex': 'Nam', 'phone': '0900000000', 'address': '',
        'address_detail': 'Nhà giả lập', 'province_code': '06', 'commune_code': '11311067', 'occupation': 'Nghề giả lập địa chỉ'})
    assert res.status_code == 201, res.text
    pid = res.json()['id']
    visit = r.post('/api/visits', json={'patient_id': pid, 'doctor_id': ids['doctor'], 'service_id': service_id})
    assert visit.status_code == 201, visit.text
    vid = visit.json()['id']
    assert d.put(f'/api/visits/{vid}/clinical', json={'version': 0, 'diagnosis': 'Chẩn đoán giả lập'}).status_code == 200
    with db(True) as c:
        c.execute("INSERT INTO medicines(name,base_unit,controlled) VALUES('Thuốc giả lập địa chỉ','viên',0)")
        medicine = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    rx = d.post('/api/prescriptions', json={'visit_id': vid, 'items': [{'medicine_id': medicine, 'quantity': 1, 'directions': 'Chỉ kiểm thử'}], 'instructions': 'Giả lập'})
    assert rx.status_code == 201, rx.text
    address = 'Nhà giả lập, Xã Cát Thành, Tỉnh Ninh Bình'
    for kind, obj, client in [('intake', vid, r), ('rx', rx.json()['id'], d)]:
        for fmt in ('docx', 'pdf'):
            response = client.get(f'/api/forms/{kind}/{obj}?fmt={fmt}')
            assert response.status_code == 200, response.text
            if fmt == 'docx':
                doc = Document(io.BytesIO(response.content))
                if kind == 'intake':
                    assert doc.tables[0].cell(3, 0).text == 'Địa chỉ liên hệ: '+address
                    assert any('Nghề giả lập địa chỉ' in row.cells[0].text for row in doc.tables[0].rows)
                    assert not any('Nghề giả lập địa chỉ' in p.text for p in doc.paragraphs)
                else:
                    paragraphs = [p.text for p in doc.paragraphs]
                    address_at = next(i for i, x in enumerate(paragraphs) if x.startswith('Nơi thường trú / tạm trú / ở hiện tại:'))
                    assert paragraphs[address_at] == 'Nơi thường trú / tạm trú / ở hiện tại: '+address
                    metadata_at = next(i for i, x in enumerate(paragraphs) if x.startswith('Nghề nghiệp:'))
                    diagnosis_at = next(i for i, x in enumerate(paragraphs) if x.startswith('Chẩn đoán:'))
                    assert address_at < metadata_at < diagnosis_at
            else:
                with pymupdf.open(stream=response.content, filetype='pdf') as pdf:
                    text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
                assert 'Địa chỉ: '+address in text
                assert 'Địa chỉ: —' not in text
                if kind == 'rx': assert text.index(address) < text.index('Danh sách thuốc')
