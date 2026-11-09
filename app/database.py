"""One transaction boundary for demo SQLite and LAN PostgreSQL.

LAN writes take a transaction-scoped advisory lock BEFORE any business reads.
This deliberately serializes clinic writes across workers (including backup),
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
ID_TABLES=set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\(\s*id\b',
    (ROOT/'schema.postgresql.sql').read_text()+(ROOT/'migrations/003_v050.sql').read_text(),re.I))
_pool = None


class Record(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def record_factory(cursor):
    names = [col.name for col in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values))


class PGConnection:
    """Small SQL dialect boundary; all values stay bound parameters."""
    def __init__(self, connection):
        self.connection = connection
        self.last_id = None

    def execute(self, sql, params=()):
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
        if write:
            from .storage import require_space
            require_space(DATA)
        with pool().connection() as con:
            with con.transaction():
                con.execute("SET LOCAL statement_timeout = '30s'")
                con.execute("SET LOCAL lock_timeout = '15s'")
                if write:
                    con.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_ID,))
                else:
                    con.execute('SET TRANSACTION READ ONLY')
                yield PGConnection(con)
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
        con.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_ID,))
        con.execute((ROOT / 'schema.postgresql.sql').read_text())
        from .migrations import migrate_v050
        migrate_v050(PGConnection(con),postgres=True)
