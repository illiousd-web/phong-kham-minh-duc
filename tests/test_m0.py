import sqlite3
from tests.test_workflows import client, token
from app.main import db
from app.m0_migration import migrate_m0
from tests.m0_cases import check_m0


class RoleClient:
    def __init__(self, name): self.headers = token(name)
    def get(self, path, **kw): return client.get(path, headers=self.headers, **kw)
    def patch(self, path, **kw): return client.patch(path, headers=self.headers, **kw)
    def put(self, path, **kw): return client.put(path, headers=self.headers, **kw)
    def post(self, path, **kw): return client.post(path, headers=self.headers, **kw)


def test_m0_permissions_audit_closing_and_daily_queue():
    names = dict(reception='letan', doctor='bs_noi', doctor2='bs_san', cashier='thungan', pharmacy='duoc', manager='quanly', admin='quantri', technician='kythuat')
    clients = {k: RoleClient(v) for k, v in names.items()}
    with db() as c:
        ids = {k: c.execute('SELECT id FROM users WHERE username=?', (v,)).fetchone()[0] for k, v in names.items()}
    check_m0(clients, ids, db)


def test_m0_sqlite_upgrade_preserves_existing_data_and_is_idempotent(tmp_path):
    c = sqlite3.connect(tmp_path / 'old.sqlite3')
    c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
    c.execute('CREATE TABLE patients(id INTEGER PRIMARY KEY,full_name TEXT)')
    c.executemany('INSERT INTO patients VALUES(?,?)', [(i, 'Giả lập '+str(i)) for i in range(22000)])
    before = c.execute('SELECT * FROM patients ORDER BY id').fetchall()
    migrate_m0(c); migrate_m0(c)
    assert c.execute('SELECT id,full_name FROM patients ORDER BY id').fetchall() == before
    assert c.execute('SELECT COUNT(*) FROM patients WHERE allergies IS NULL').fetchone()[0] == 22000
    c.close()


def test_historical_doctor_cannot_edit_allergies():
    from tests.test_workflows import prepare_visit
    pid, vid = prepare_visit()
    d = RoleClient('bs_noi')
    v = d.get(f'/api/visits/{vid}').json()
    assert d.put(f'/api/visits/{vid}/clinical', json={'version': v['version'], 'diagnosis': 'Giả lập'}).status_code == 200
    v = d.get(f'/api/visits/{vid}').json()
    assert d.post(f'/api/visits/{vid}/complete', json={'version': v['version']}).status_code == 200
    assert d.put(f'/api/patients/{pid}/allergies', json={'allergies': 'Thuốc A'}).status_code == 403
    assert RoleClient('letan').put(f'/api/patients/{pid}/allergies', json={'allergies': 'Thuốc A'}).status_code == 200


def test_300_history_visits_have_constant_query_count_and_are_fast(monkeypatch):
    import time
    import statistics
    from tests.test_workflows import prepare_visit
    pid, vid = prepare_visit()
    with db(True) as c:
        doctor = c.execute('SELECT doctor_id FROM visits WHERE id=?',(vid,)).fetchone()[0]
        for _ in range(300):
            c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at,status) VALUES(?,?,?,'2020-01-01T00:00:00+00:00','completed')",(pid,doctor,doctor))
    original = sqlite3.connect
    statements = []
    def traced(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', traced)
    d = RoleClient('bs_noi')
    timings = []
    for _ in range(6):
        statements.clear()
        started = time.perf_counter()
        response = d.get(f'/api/visits/{vid}/patient-history')
        timings.append(time.perf_counter()-started)
        assert response.status_code == 200 and len(response.json()) == 300
        assert sum('FROM prescriptions WHERE visit_id IN' in q for q in statements) == 1
        assert sum('FROM orders WHERE visit_id IN' in q for q in statements) == 1
    assert statistics.median(timings[1:]) <= 1.5


def test_doctor_queue_date_bounds():
    d = RoleClient('bs_noi')
    for day in ('01/01/2000', '31/12/2100'):
        assert d.get('/api/doctor/queue', params={'day': day}).status_code == 200
    for day in ('31/12/1999', '01/01/2101', '31/12/9999'):
        assert d.get('/api/doctor/queue', params={'day': day}).status_code == 422
