"""Actual PostgreSQL 016 upgrade/downgrade with legacy stock and immutability."""
from pathlib import Path
import secrets

import psycopg
import pytest

from app.database import PGConnection, record_factory
from app.s2b_migration import migrate_s2b
from tests.test_s2b_migration import legacy, old_snapshot
from .test_v050_migration import create_db, drop_db

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_016_up_down_legacy_and_immutable():
    name = 's2b_migration_' + secrets.token_hex(5)
    url = create_db(name)
    try:
        with psycopg.connect(url, row_factory=record_factory) as raw:
            raw.execute((ROOT/'schema.postgresql.sql').read_text())
            c = PGConnection(raw)
            legacy(c)
            before = old_snapshot(c)
            migrate_s2b(c, postgres=True)
            migrate_s2b(c, postgres=True)
            assert old_snapshot(c) == before
            assert tuple(raw.execute('SELECT quantity,unit_cost,vat_rate,receipt_id FROM stock_lots').fetchone().values()) == (19, None, None, None)
            migrate_s2b(c, postgres=True, down=True)
            migrate_s2b(c, postgres=True, down=True)
            assert old_snapshot(c) == before
            migrate_s2b(c, postgres=True)
            raw.execute("INSERT INTO stock_receipts(document_no,created_by,created_at) VALUES('PN-2026-0001',1,'2026-11-15')")
            raw.execute("INSERT INTO stock_issues(document_no,reason,purpose,created_by,created_at) VALUES('PX-2026-0001','internal','Giả lập',1,'2026-11-15')")
            for table in ('stock_receipts', 'stock_issues', 'stock_movements'):
                for statement in (f'UPDATE {table} SET id=id', f'DELETE FROM {table}', f'TRUNCATE {table} CASCADE'):
                    with pytest.raises(psycopg.errors.CheckViolation):
                        with raw.transaction():
                            raw.execute(statement)
            with pytest.raises(ValueError, match='Chưa quay lui S2b'):
                migrate_s2b(c, postgres=True, down=True)
    finally:
        drop_db(name)
