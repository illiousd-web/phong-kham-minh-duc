"""Migration 016 preserves legacy balances and NULL costs, with guarded rollback."""
import sqlite3
from pathlib import Path

import pytest

from app.s2b_migration import migrate_s2b

ROOT = Path(__file__).resolve().parents[1]


def legacy(c):
    c.execute("INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(1,'s2b_old','Giả lập cũ','00','FAKE')")
    c.execute("INSERT INTO medicines(id,name,base_unit) VALUES(1,'Thuốc cũ giả lập','viên')")
    c.execute("INSERT INTO stock_lots(id,medicine_id,lot_number,expiry_date,quantity) VALUES(1,1,'LOT-CU','2029-01-01',19)")
    c.execute("INSERT INTO stock_movements(id,stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(1,1,'receipt',20,1,'2026-01-01')")
    c.execute("INSERT INTO stock_movements(id,stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(2,1,'issue',1,1,'2026-01-02')")


def old_snapshot(c):
    return {table: [tuple(r.values()) if isinstance(r, dict) else tuple(r) for r in c.execute('SELECT '+columns+' FROM '+table+' ORDER BY id')]
            for table, columns in [('medicines', 'id,name,base_unit,controlled'),
                ('stock_lots', 'id,medicine_id,lot_number,expiry_date,quantity,quarantined'),
                ('stock_movements', 'id,stock_lot_id,movement_type,quantity,created_by,created_at')]}


def test_sqlite_016_up_down_preserves_stock_and_unknown_prices(tmp_path):
    with sqlite3.connect(tmp_path/'old.db') as c:
        c.executescript((ROOT/'schema.sql').read_text())
        c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
        legacy(c)
        before = old_snapshot(c)
        migrate_s2b(c)
        migrate_s2b(c)
        assert old_snapshot(c) == before
        assert c.execute('SELECT quantity,unit_cost,vat_rate,receipt_id FROM stock_lots').fetchall() == [(19, None, None, None)]
        assert c.execute('SELECT quantity,unit_cost FROM stock_movements ORDER BY id').fetchall() == [(20, None), (1, None)]
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        migrate_s2b(c, down=True)
        migrate_s2b(c, down=True)
        assert old_snapshot(c) == before
        assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=16').fetchone()
        migrate_s2b(c)
        assert old_snapshot(c) == before


@pytest.mark.parametrize('kind', ['cost', 'minimum', 'receipt', 'issue', 'role'])
def test_sqlite_016_down_refuses_new_data(tmp_path, kind):
    with sqlite3.connect(tmp_path/'new.db') as c:
        c.executescript((ROOT/'schema.sql').read_text())
        c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
        legacy(c)
        migrate_s2b(c)
        statement = {'cost': 'UPDATE stock_lots SET unit_cost=0', 'minimum': 'UPDATE medicines SET min_stock=0',
            'receipt': "INSERT INTO stock_receipts(document_no,created_by,created_at) VALUES('PN-2026-0001',1,'2026-11-15')",
            'issue': "INSERT INTO stock_issues(document_no,reason,purpose,created_by,created_at) VALUES('PX-2026-0001','internal','Giả lập',1,'2026-11-15')",
            'role': "INSERT INTO user_roles VALUES(1,'stock_owner')"}[kind]
        c.execute(statement)
        with pytest.raises(ValueError, match='Chưa quay lui S2b'):
            migrate_s2b(c, down=True)
        assert c.execute('SELECT 1 FROM schema_migrations WHERE version=16').fetchone()


def test_sqlite_016_failed_upgrade_is_atomic(tmp_path):
    path = tmp_path/'failed.db'
    with sqlite3.connect(path) as c:
        c.executescript((ROOT/'schema.sql').read_text())
        c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
        legacy(c)
        c.execute('CREATE TABLE stock_issues(fake TEXT)')
    with pytest.raises(sqlite3.OperationalError), sqlite3.connect(path) as c:
        c.execute('BEGIN IMMEDIATE')
        migrate_s2b(c)
    with sqlite3.connect(path) as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='stock_receipts'").fetchone()
        assert c.execute('SELECT quantity FROM stock_lots').fetchone()[0] == 19


def test_sqlite_016_documents_and_snapshots_immutable(tmp_path):
    with sqlite3.connect(tmp_path/'immutable.db') as c:
        c.executescript((ROOT/'schema.sql').read_text())
        c.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)')
        legacy(c)
        migrate_s2b(c)
        c.execute("INSERT INTO stock_receipts(document_no,created_by,created_at) VALUES('PN-2026-0001',1,'2026-11-15')")
        c.execute("INSERT INTO stock_issues(document_no,reason,purpose,created_by,created_at) VALUES('PX-2026-0001','internal','Giả lập',1,'2026-11-15')")
        for table in ('stock_receipts', 'stock_issues', 'stock_movements'):
            for statement in (f'UPDATE {table} SET id=id', f'DELETE FROM {table}'):
                with pytest.raises(sqlite3.IntegrityError):
                    c.execute(statement)
