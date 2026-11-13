"""One transaction boundary for demo SQLite and LAN PostgreSQL.

LAN writes take a transaction-scoped advisory lock BEFORE any business reads.
This deliberately serializes clinic writes across workers (excluding catalog imports),
while readers use MVCC. Never bypass this boundary in application write paths.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
from .config import DATABASE_URL, LAN, DATA
from .resources import LIMITS

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv('CLINIC_DB_PATH', str(ROOT / 'data' / 'minh_duc_demo.sqlite3'))).resolve()
LOCK_ID = 764209431
BACKUP_LOCK_ID = 764209432
CATALOG_LOCK_ID = 764209433
ID_TABLES=set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\(\s*id\b',
    (ROOT/'schema.postgresql.sql').read_text(encoding='utf-8')+(ROOT/'migrations/003_v050.sql').read_text(encoding='utf-8')+(ROOT/'migrations/004_manual_prices.sql').read_text(encoding='utf-8'),re.I))
ID_TABLES.update(('catalog_imports','tech_catalog_pl02'))
ID_TABLES.update(('lab_tests','lab_reference_ranges','lab_reports','lab_results'))
ID_TABLES.update(('drugs','clinical_prescriptions','clinical_prescription_items','prescription_outbox'))
_pool = None


class Record(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def record_factory(cursor):
    names = [col.name for col in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values))


class PGConnection:
    """Small SQL dialect boundary; all values stay bound parameters."""
    def __init__(self, connection, operational=False):
        self.connection = connection
        self.last_id = None
        self.operational = operational

    def execute(self, sql, params=()):
        if self.operational and not re.match(r'\s*(SELECT\b|(?:INSERT INTO|UPDATE|DELETE FROM)\s+(?:sessions|login_attempts|audit_log)\b)', sql, re.I):
            raise RuntimeError('Giao dịch truy cập không được sửa dữ liệu nghiệp vụ')
        if sql == 'SELECT last_insert_rowid()':
            return SavedID(self.last_id)
        sql = sql.replace("date('now','+90 days')", "to_char(CURRENT_DATE + 90, 'YYYY-MM-DD')")
        # Existing SQL has no question marks in string literals. Percent signs in
        # LIKE patterns are parameters; psycopg sees only placeholders here.
        sql = sql.replace('?', '%s')
        match = re.match(r'\s*INSERT INTO\s+(\w+)', sql, re.I)
        has_id = match and match[1] in ID_TABLES
        if has_id:
            sql += ' RETURNING id'
        cur = self.connection.execute(sql, params)
        if has_id:
            self.last_id = cur.fetchone()['id']
        return cur

    def executemany(self, sql, params):
        for item in params:
            self.execute(sql, item)


class SavedID:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)


def pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(DATABASE_URL, min_size=LIMITS.pool_min, max_size=LIMITS.pool_max, timeout=5,
                               max_idle=60, max_lifetime=1800, num_workers=1,
                               kwargs={'row_factory': record_factory, 'connect_timeout': 5}, open=True)
    return _pool


@contextmanager
def db(write=False):
    if LAN:
        operational = write == 'access'
        if write and not operational:
            from .storage import require_space
            require_space(DATA)
        with pool().connection() as con:
            with con.transaction():
                con.execute("SET LOCAL statement_timeout = '30s'")
                if write and not operational:
                    from fastapi import HTTPException
                    import time
                    # Hold a shared backup gate throughout the transaction, including
                    # commit and attachment writes. Backup takes the exclusive gate.
                    if not con.execute('SELECT pg_try_advisory_xact_lock_shared(%s)', (BACKUP_LOCK_ID,)).fetchone()[0]:
                        raise HTTPException(503, 'Đang sao lưu, thử lại sau 1 giây', headers={'Retry-After': '1'})
                    # Catalog changes are atomic under MVCC, independent of clinical
                    # writes. They still share the backup gate and their own writer lock.
                    key = CATALOG_LOCK_ID if write == 'catalog' else LOCK_ID
                    deadline = time.monotonic() + 5
                    while not con.execute('SELECT pg_try_advisory_xact_lock(%s)', (key,)).fetchone()[0]:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise HTTPException(503, 'Hệ thống đang bận, vui lòng thử lại', headers={'Retry-After': '1'})
                        time.sleep(min(.025, remaining))
                elif operational:
                    from .storage import release_access_reserve
                    release_access_reserve(DATA)
                else:
                    con.execute('SET TRANSACTION READ ONLY')
                yield PGConnection(con, operational=operational)
        return
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=10000')
    try:
        if write:
            con.execute('BEGIN IMMEDIATE')
        yield con
        if write:
            con.commit()
    except Exception:
        if write:
            con.rollback()
        raise
    finally:
        con.close()


def migrate():
    """Explicit operator action in LAN; never DDL on web process startup."""
    if not LAN:
        return
    import psycopg
    with psycopg.connect(DATABASE_URL,row_factory=record_factory) as con:
        con.execute('SELECT pg_advisory_xact_lock(%s)', (BACKUP_LOCK_ID,))
        con.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_ID,))
        con.execute((ROOT / 'schema.postgresql.sql').read_text(encoding='utf-8'))
        from .migrations import migrate_v050
        migrate_v050(PGConnection(con),postgres=True)
        from .manual_price_migration import migrate_manual_prices
        migrate_manual_prices(PGConnection(con),postgres=True)

        from .m0_migration import migrate_m0
        migrate_m0(PGConnection(con))
        from .administrative_migration import migrate_administrative
        migrate_administrative(PGConnection(con))
        from .patient_catalog import migrate_public_catalog
        migrate_public_catalog(PGConnection(con))

        from .m6_migration import migrate_m6
        migrate_m6(PGConnection(con), postgres=True)
        from .m5_migration import migrate_m5
        migrate_m5(PGConnection(con), postgres=True)
        from .d0_migration import migrate_d0
        migrate_d0(PGConnection(con), postgres=True)
        from .d0_source_migration import migrate_source_catalogs
        migrate_source_catalogs(PGConnection(con), postgres=True)

        from .s1_migration import migrate_s1
        migrate_s1(PGConnection(con))
