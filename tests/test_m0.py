import sqlite3
from tests.test_workflows import client, token
from app.main import db
from app.m0_migration import migrate_m0
from tests.m0_cases import check_m0


class RoleClient:
    def __init__(self, name): self.headers = token(name)
    def get(self, path, **kw): return client.get(path, headers=self.headers, **kw)
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
