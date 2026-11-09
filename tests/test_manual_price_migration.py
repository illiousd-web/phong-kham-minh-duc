"""SQLite migration up/down, old-row preservation and atomic failure recovery."""
from pathlib import Path
import sqlite3

import pytest

from app.migrations import migrate_v050
from app.manual_price_migration import migrate_sqlite_manual_prices

ROOT = Path(__file__).resolve().parents[1]


def legacy(path):
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        c.executescript((ROOT / 'schema.sql').read_text())
        migrate_v050(c)
        c.execute("INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(1,'fake','Nhân viên giả lập','00','fake')")
        c.execute("INSERT INTO patients(id,full_name,sex,created_at) VALUES(1,'Người bệnh giả lập','Nữ','2026-11-09')")
        c.execute("INSERT INTO visits(id,patient_id,doctor_id,created_by,created_at) VALUES(1,1,1,1,'2026-11-09')")
        c.execute("INSERT INTO service_catalog(id,name,price,code) VALUES(1,'Khám giả lập',150000,'OLD01')")
        c.execute("INSERT INTO service_categories VALUES(1,'consultation')")
        c.execute("INSERT INTO charges(id,visit_id,label,amount,created_at) VALUES(1,1,'Khoản cũ',150000,'2026-11-09')")
        c.execute("INSERT INTO orders(id,visit_id,category,name,requested_by,created_at,proposed_price,service_id) VALUES(1,1,'lab','Chỉ định cũ',1,'2026-11-09',150000,1)")
        c.execute("INSERT INTO order_authorizations VALUES(1,1,150000,1,'2026-11-09')")
        c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(1,50000,'cash',1,'2026-11-09','fake-payment')")
        c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key,is_advance) VALUES(1,20000,'cash',1,'2026-11-09','fake-advance',1)")
        c.execute("INSERT INTO charge_sources VALUES(1,'order',1)")
        c.execute("CREATE INDEX c3_legacy_index ON charges(visit_id)")
        c.execute("CREATE TRIGGER c3_legacy_trigger BEFORE UPDATE ON charges BEGIN SELECT 1; END")
        c.commit()


LEGACY_PAYMENT = 'id,visit_id,amount,method,created_by,created_at,external_ref,idempotency_key,is_advance'


def snapshot(path):
    """Giá trị của mọi cột CŨ (cột payments.kind mới của v4 so riêng)."""
    with sqlite3.connect(path) as c:
        return {table: c.execute('SELECT ' + (LEGACY_PAYMENT if table == 'payments' else '*') + ' FROM ' + table + ' ORDER BY 1').fetchall() for table in (
            'users','patients','visits','charges','orders','payments','order_authorizations','charge_sources','service_categories')}


def test_sqlite_upgrade_and_down_preserve_every_legacy_value_and_fk(tmp_path):
    path = tmp_path / 'legacy.db'; legacy(path); before = snapshot(path)
    migrate_sqlite_manual_prices(path); migrate_sqlite_manual_prices(path)
    assert snapshot(path) == before
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT price_at_collection FROM service_catalog').fetchone()[0] == 0
        # Dữ liệu cũ giữ nguyên ý nghĩa: is_advance=1 là ứng trước, còn lại là thu thường.
        assert c.execute('SELECT idempotency_key,kind FROM payments ORDER BY id').fetchall() == [('fake-payment', 'regular'), ('fake-advance', 'advance')]
        assert c.execute('SELECT amount FROM effective_charges').fetchone()[0] == 150000
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'c3_legacy_%'")} == {'c3_legacy_index', 'c3_legacy_trigger'}
    migrate_sqlite_manual_prices(path, down=True); migrate_sqlite_manual_prices(path, down=True)
    assert snapshot(path) == before
    with sqlite3.connect(path) as c:
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=4').fetchone()
        assert 'price_at_collection' not in [r[1] for r in c.execute('PRAGMA table_info(service_catalog)')]
        assert 'kind' not in [r[1] for r in c.execute('PRAGMA table_info(payments)')]
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_charges_visit'").fetchone()
        assert next(r[3] for r in c.execute('PRAGMA table_info(charges)') if r[1] == 'amount') == 1
    migrate_sqlite_manual_prices(path)
    assert snapshot(path) == before


@pytest.mark.parametrize('new_data', ['flag', 'null', 'history', 'category', 'provisional'])
def test_sqlite_down_refuses_new_data_without_loss(tmp_path, new_data):
    path = tmp_path / 'legacy.db'; legacy(path); migrate_sqlite_manual_prices(path)
    with sqlite3.connect(path) as c:
        if new_data == 'flag':
            c.execute('UPDATE service_catalog SET price_at_collection=1')
        elif new_data == 'null':
            c.execute('UPDATE charges SET amount=NULL')
        elif new_data == 'history':
            c.execute("INSERT INTO manual_charge_prices VALUES(1,200000,'Nội dung giả lập',1,'2026-11-09','new-fake')")
        elif new_data == 'provisional':
            c.execute("UPDATE payments SET kind='provisional' WHERE idempotency_key='fake-payment'")
        else:
            c.execute("UPDATE service_categories SET category='procedure'")
    before = snapshot(path)
    with pytest.raises(ValueError, match='Không thể quay lui'):
        migrate_sqlite_manual_prices(path, down=True)
    assert snapshot(path) == before
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT 1 FROM schema_migrations WHERE version=4').fetchone()


def test_sqlite_failed_upgrade_rolls_back_schema_and_rows(tmp_path, monkeypatch):
    from app import manual_price_migration as migration
    path = tmp_path / 'legacy.db'; legacy(path); before = snapshot(path)
    real = migration.rebuild_sqlite
    def fail_after_first(c, table, *args, **kwargs):
        real(c, table, *args, **kwargs)
        if table == 'orders':
            raise RuntimeError('Ép lỗi sau khi đã sửa hai bảng')
    monkeypatch.setattr(migration, 'rebuild_sqlite', fail_after_first)
    with pytest.raises(RuntimeError):
        migration.migrate_sqlite_manual_prices(path)
    assert snapshot(path) == before
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT amount FROM effective_charges').fetchone()[0] == 150000
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'c3_new_%'").fetchone()
