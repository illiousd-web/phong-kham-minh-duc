"""Shared SQLite/PostgreSQL safety checks, synthetic records only."""
import json

from app.doctor_workspace import doctor_queue


def check_m0(clients, ids, db):
    reception, doctor, other = (clients[k] for k in ('reception', 'doctor', 'doctor2'))
    pid = reception.post('/api/patients', json={'full_name': 'Đặng Thị M0 giả lập', 'sex': 'Nữ',
        'date_of_birth': '1990-01-01', 'phone': '0901234567'}).json()['id']
    with db(True) as c:
        c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
                  (pid, ids['doctor'], ids['reception'], '2026-11-09T17:00:00+00:00'))
        vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    path = f'/api/patients/{pid}/allergies'
    for role in ('doctor2', 'cashier', 'pharmacy', 'manager', 'admin', 'technician'):
        assert clients[role].put(path, json={'allergies': 'Sai quyền'}).status_code == 403
    for actor, value in ((reception, 'Không dị ứng'), (doctor, 'Thuốc A: ' + 'a' * 1900), (doctor, None)):
        assert actor.put(path, json={'allergies': value}).status_code == 200
    with db() as c:
        logs = [json.loads(r[0]) for r in c.execute("SELECT details FROM audit_log WHERE event='patient_allergies_updated' AND object_id=? ORDER BY id", (pid,))]
        assert logs == [{'old': None, 'new': 'Không dị ứng'}, {'old': 'Không dị ứng', 'new': 'Thuốc A: ' + 'a' * 1900}, {'old': 'Thuốc A: ' + 'a' * 1900, 'new': None}]
        assert not doctor_queue(c, ids['doctor'], '09/11/2026', 'dang thi m0')['visits']
        rows = doctor_queue(c, ids['doctor'], '10/11/2026', 'DANG THI M0')['visits']
        assert vid in [r['id'] for r in rows] and rows[-1]['daily_number'] >= 1
    close = f'/api/visits/{vid}/close-abandoned'
    for role in ('doctor2', 'cashier', 'pharmacy', 'manager', 'admin', 'technician'):
        assert clients[role].post(close, json={'reason': 'Tạo nhầm'}).status_code == 403
    assert reception.post(close, json={'reason': 'Khác', 'note': '  '}).status_code == 422
    assert reception.post(close, json={}).status_code == 422
    before = doctor.get('/api/queue-counts').json()['doctor']
    assert doctor.post(close, json={'reason': 'Người bệnh bỏ về'}).status_code == 200
    assert doctor.get('/api/queue-counts').json()['doctor'] == before - 1
    assert vid not in [r['id'] for r in doctor.get('/api/visits').json()]
    assert reception.post(close, json={'reason': 'Tạo nhầm'}).status_code == 409
    with db() as c:
        assert not doctor_queue(c, ids['doctor'], '10/11/2026', 'dang thi m0')['visits']
        assert c.execute('SELECT reason FROM visit_cancellations WHERE visit_id=?', (vid,)).fetchone()[0] == 'Người bệnh bỏ về'
        assert c.execute("SELECT 1 FROM audit_log WHERE event='visit_cancelled' AND object_id=?", (vid,)).fetchone()
    # Every financial footprint blocks, including zero / NULL / already-voided fees.
    for amount in (0, None, 123):
        with db(True) as c:
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (pid, ids['doctor'], ids['reception'], '2026-11-10T00:00:00+00:00'))
            blocked = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,'M0',?,?)", (blocked, amount, '2026-11-10'))
        response = reception.post(f'/api/visits/{blocked}/close-abandoned', json={'reason': 'Tạo nhầm'})
        assert response.status_code == 409 and 'hủy/hoàn' in response.json()['detail']
    for table in ('payments', 'dispensations'):
        with db(True) as c:
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (pid, ids['doctor'], ids['reception'], '2026-11-10T00:00:00+00:00'))
            blocked = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            if table == 'payments':
                c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(?,1,'cash',?,'2026-11-10',?)", (blocked, ids['cashier'], 'm0-' + str(blocked)))
            else:
                c.execute("INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,instructions,created_at) VALUES(?,?,'M0','','2026-11-10')", (blocked, ids['doctor']))
                rx = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute("INSERT INTO dispensations(prescription_id,visit_id,dispensed_by,dispensed_at) VALUES(?,?,?,'2026-11-10')", (rx, blocked, ids['pharmacy']))
        assert doctor.post(f'/api/visits/{blocked}/close-abandoned', json={'reason': 'Tạo nhầm'}).status_code == 409
    assert other.get(f'/api/visits/{vid}/patient-history').status_code == 403
    assert reception.get(f'/api/visits/{vid}/payment-status').status_code == 403
    assert doctor.get(f'/api/visits/{vid}/payment-status').status_code == 200

    with db(True) as c:
        c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (pid, ids['doctor'], ids['reception'], '2026-11-10T00:00:00+00:00'))
        reception_vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    before = reception.get('/api/queue-counts').json()['reception']
    assert reception.post(f'/api/visits/{reception_vid}/close-abandoned', json={'reason': 'Khác', 'note': 'Ghi chú giả lập M0'}).status_code == 200
    assert reception.get('/api/queue-counts').json()['reception'] == before - 1
    with db() as c:
        assert c.execute('SELECT reason FROM visit_cancellations WHERE visit_id=?', (reception_vid,)).fetchone()[0] == 'Khác: Ghi chú giả lập M0'
