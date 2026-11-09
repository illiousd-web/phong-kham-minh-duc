"""PostgreSQL owner migration and guarded rollback; never touch deployed data."""
from pathlib import Path
import secrets

import psycopg
import pytest
from psycopg import sql

from app.database import PGConnection, record_factory
from app.migrations import migrate_v050
from app.manual_price_migration import migrate_manual_prices
from .test_v050_migration import create_db, drop_db, old_data
from .conftest import SOURCE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy_pg():
    name = 'c3_migration_' + secrets.token_hex(5)
    url = create_db(name)
    try:
        with psycopg.connect(url, row_factory=record_factory) as c:
            c.execute((ROOT / 'tests/fixtures/v042_schema_pg.sql').read_text())
            old_data(c, True)
            migrate_v050(PGConnection(c), postgres=True)
        yield url
    finally:
        drop_db(name)


def snapshots(c):
    return {t: [dict(r) for r in c.execute('SELECT * FROM ' + t + ' ORDER BY 1')] for t in (
        'charges', 'orders', 'order_authorizations', 'payments', 'charge_sources', 'patients', 'visits', 'audit_log')}


def test_pg_migration_up_down_idempotent_preserves_all_old_values(legacy_pg):
    with psycopg.connect(legacy_pg, row_factory=record_factory) as c:
        before = snapshots(c)
        migrate_manual_prices(PGConnection(c), postgres=True)
        migrate_manual_prices(PGConnection(c), postgres=True)
        assert snapshots(c) == before
        assert [r[0] for r in c.execute('SELECT amount FROM effective_charges ORDER BY id')] == [150000, 25000]
        assert c.execute('SELECT count(*) FROM service_catalog WHERE price_at_collection<>0').fetchone()[0] == 0
        migrate_manual_prices(PGConnection(c), postgres=True, down=True)
        migrate_manual_prices(PGConnection(c), postgres=True, down=True)
        assert snapshots(c) == before
        assert not c.execute('SELECT 1 FROM schema_migrations WHERE version=4').fetchone()
        assert not c.execute("SELECT 1 FROM information_schema.columns WHERE table_name='service_catalog' AND column_name='price_at_collection'").fetchone()
        migrate_manual_prices(PGConnection(c), postgres=True)
        assert snapshots(c) == before


@pytest.mark.parametrize('data', ['flag', 'null', 'history', 'category'])
def test_pg_rollback_refuses_data_and_preserves_every_row(legacy_pg, data):
    with psycopg.connect(legacy_pg, row_factory=record_factory) as c:
        migrate_manual_prices(PGConnection(c), postgres=True)
        if data == 'flag':
            c.execute('UPDATE service_catalog SET price_at_collection=1 WHERE id=1')
        elif data == 'null':
            c.execute('UPDATE charges SET amount=NULL WHERE id=1')
        elif data == 'history':
            c.execute("INSERT INTO manual_charge_prices VALUES(1,100000,'Nội dung giả lập',1,'2026-11-09','fake-history')")
        else:
            c.execute("UPDATE service_categories SET category='procedure' WHERE service_id=2")
        before = snapshots(c)
        with pytest.raises(ValueError, match='Không thể quay lui'):
            with c.transaction():
                migrate_manual_prices(PGConnection(c), postgres=True, down=True)
        assert snapshots(c) == before
        assert c.execute('SELECT 1 FROM schema_migrations WHERE version=4').fetchone()


def test_pg_failed_upgrade_is_atomic(legacy_pg, monkeypatch):
    original = PGConnection.execute
    def fail(self, statement, params=()):
        if statement == 'INSERT INTO schema_migrations(version) VALUES(4)':
            raise RuntimeError('Ép lỗi cuối migration')
        return original(self, statement, params)
    with psycopg.connect(legacy_pg, row_factory=record_factory) as c:
        before = snapshots(c)
        monkeypatch.setattr(PGConnection, 'execute', fail)
        with pytest.raises(RuntimeError):
            with c.transaction():
                migrate_manual_prices(PGConnection(c), postgres=True)
        assert snapshots(c) == before
        assert not c.execute("SELECT 1 FROM information_schema.tables WHERE table_name='manual_charge_prices'").fetchone()
        assert c.execute('SELECT amount FROM effective_charges ORDER BY id LIMIT 1').fetchone()[0] == 150000


def test_pg_runtime_cannot_rewrite_initial_manual_price(legacy_pg):
    role = 'c3_app_' + secrets.token_hex(5)
    try:
        with psycopg.connect(SOURCE, autocommit=True) as c:
            c.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
        with psycopg.connect(legacy_pg, row_factory=record_factory) as c:
            migrate_manual_prices(PGConnection(c), postgres=True)
            grants = (ROOT / 'deploy/postgresql-roles.sql').read_text().replace('clinic_app', role).replace('DATABASE minhduc', 'DATABASE ' + c.info.dbname)
            c.execute(grants)
            c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            for statement in ('UPDATE manual_charge_prices SET amount=1', 'DELETE FROM manual_charge_prices', 'TRUNCATE manual_charge_prices'):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with c.transaction():
                        c.execute(statement)
    finally:
        with psycopg.connect(legacy_pg, autocommit=True) as c:
            c.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
        with psycopg.connect(SOURCE, autocommit=True) as c:
            c.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
