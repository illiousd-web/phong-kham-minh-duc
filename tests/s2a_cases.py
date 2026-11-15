"""Shared S2a contracts, using invented identities and images generated in memory."""
import hashlib
import json
import secrets
from io import BytesIO

from PIL import Image, ImageDraw

PROFILE = {'name': 'Phòng khám giả lập S2a', 'governing_body': 'Đơn vị giả lập',
           'address': 'Địa chỉ kiểm thử S2a', 'phone': '0000000000', 'email': 's2a@example.invalid'}


def signature_image(fmt='PNG', size=(160, 60)):
    image = Image.new('RGB', size, 'white')
    ImageDraw.Draw(image).line([(10, 45), (50, 12), (80, 40), (145, 20)], fill='black', width=2)
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def draft_prescription(clients, visit):
    assert clients['doctor'].put(f'/api/visits/{visit}/clinical', json={'version': 0, 'diagnosis': 'Chẩn đoán giả lập S2a'}).status_code == 200
    medicine = clients['manager'].post('/api/catalog/medicines', json={'name': 'Thuốc giả lập S2a '+secrets.token_hex(5), 'base_unit': 'viên'})
    assert medicine.status_code == 201, medicine.text
    rx = clients['doctor'].post('/api/prescriptions', json={'visit_id': visit, 'items': [
        {'medicine_id': medicine.json()['id'], 'quantity': 1, 'directions': 'Chỉ kiểm thử'}]})
    assert rx.status_code == 201, rx.text
    return rx.json()['id']


def check_pharmacy_allergies(clients, ids, service):
    r, d, p = clients['reception'], clients['doctor'], clients['pharmacy']
    patient = r.post('/api/patients', json={'full_name': 'Người bệnh giả lập S2a', 'sex': 'Nữ', 'date_of_birth': '1990-01-01', 'phone': '0000000000'}).json()['id']
    visit = r.post('/api/visits', json={'patient_id': patient, 'doctor_id': ids['doctor'], 'service_id': service}).json()['id']
    rx = draft_prescription(clients, visit)
    path = f'/api/prescriptions?visit_id={visit}&status=draft&limit=1'
    assert p.get(path).json()[0]['patient_allergies'] is None
    allergy = 'Thuốc giả lập <A> & B: nổi mẩn'
    assert r.put(f'/api/patients/{patient}/allergies', json={'allergies': allergy}).status_code == 200
    result = p.get(path).json()[0]
    assert result['patient_allergies'] == allergy and result['id'] == rx
    assert 'patient_allergies' not in d.get(path).json()[0]
    assert clients['doctor2'].get(path).json() == []
    for role in ('reception', 'cashier', 'manager', 'admin', 'technician', 'nurse'):
        assert clients[role].get(path).status_code == 403
    assert p.get(f'/api/patients/{patient}').status_code == 403
    assert p.put(f'/api/patients/{patient}/allergies', json={'allergies': 'Thay đổi trái quyền'}).status_code == 403
    assert r.get(f'/api/patients/{patient}').json()['allergies'] == allergy
    assert clients['cashier'].get(f'/api/patients/{patient}').status_code == 403
    assert all('patient_allergies' not in row for row in clients['cashier'].get('/api/dues').json())


def check_profile_and_signatures(clients, ids, db):
    admin = clients['admin']
    path = f'/api/users/{ids["doctor"]}/signature'
    profile_before = admin.get('/api/clinic-profile').json()
    try:
        assert admin.put('/api/clinic-profile', json=PROFILE).json() == PROFILE
        assert admin.get('/api/clinic-profile').json() == PROFILE
        assert admin.put('/api/clinic-profile', json={**PROFILE, 'unexpected': True}).status_code == 422
        assert admin.put('/api/clinic-profile', json={**PROFILE, 'name': 'x'*251}).status_code == 422
        assert clients['doctor'].get(path).status_code == 404
        payload = signature_image()
        for role in ('reception', 'cashier', 'manager', 'doctor', 'doctor2', 'technician', 'pharmacy', 'nurse'):
            client = clients[role]
            assert client.get('/api/clinic-profile').status_code == 403
            assert client.put('/api/clinic-profile', json=PROFILE).status_code == 403
            assert client.put(path, files={'file': ('fake.png', payload, 'image/png')}).status_code == 403
            if role != 'doctor':
                assert client.get(path).status_code == 403
                assert client.get('/api/users/99999999/signature').status_code == 403
        corrupt_png = bytearray(payload)
        chunk = corrupt_png.index(b'IDAT')
        corrupt_png[chunk+4+int.from_bytes(corrupt_png[chunk-4:chunk], 'big')] ^= 1
        for bad in (b'<svg/>', b'not an image', payload[:30], bytes(corrupt_png), signature_image('GIF'), signature_image(size=(2001, 2000))):
            assert admin.put(path, files={'file': ('fake.png', bad, 'image/png')}).status_code == 422
        assert admin.put(path, files={'file': ('fake.png', payload + bytes(300*1024), 'image/png')}).status_code == 413
        assert admin.put('/api/users/99999999/signature', files={'file': ('fake.png', payload, 'image/png')}).status_code == 404
        with db() as c:
            initial = c.execute("SELECT COUNT(*) FROM audit_log WHERE event='user_signature_changed' AND object_id=?", (ids['doctor'],)).fetchone()[0]
        for image, mime in ((payload + bytes(300*1024-len(payload)), 'image/png'), (signature_image('JPEG'), 'image/jpeg')):
            uploaded = admin.put(path, files={'file': ('untrusted.txt', image, 'application/octet-stream')})
            assert uploaded.status_code == 200, uploaded.text
            assert uploaded.json()['uploaded_by'] == ids['admin']
            for role in ('admin', 'doctor'):
                response = clients[role].get(path)
                assert response.status_code == 200 and response.content == image
                assert response.headers['content-type'] == mime
                assert response.headers['cache-control'] == 'no-store'
                assert response.headers['x-content-type-options'] == 'nosniff'
        assert admin.get('/api/users/signatures').status_code == 404
        with db() as c:
            entries = c.execute("SELECT details,user_id FROM audit_log WHERE event='user_signature_changed' AND object_id=? ORDER BY id", (ids['doctor'],)).fetchall()
            assert len(entries) == initial + 2
            assert entries[-1]['user_id'] == ids['admin']
            assert json.loads(entries[-1]['details'])['new_sha256'] == hashlib.sha256(image).hexdigest()
            assert json.loads(entries[-1]['details'])['old_sha256']
            profile_audit = c.execute("SELECT details FROM audit_log WHERE event='clinic_profile_changed' ORDER BY id DESC LIMIT 1").fetchone()
            assert json.loads(profile_audit[0])['new'] == PROFILE
    finally:
        assert admin.put('/api/clinic-profile', json=profile_before).status_code == 200
        with db(True) as c:
            c.execute('DELETE FROM user_signatures WHERE user_id=?', (ids['doctor'],))
