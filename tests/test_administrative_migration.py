"""Upgrade a populated pre-L1 SQLite database, including legacy document strings."""
import sqlite3
from pathlib import Path

from app.administrative_migration import migrate_administrative
from app.m0_migration import migrate_m0
from tests.test_manual_price_migration import legacy
from app.manual_price_migration import migrate_sqlite_manual_prices


def test_l12_sqlite_upgrade_preserves_every_legacy_column(tmp_path):
    path=tmp_path/'old.sqlite3'
    legacy(path);migrate_sqlite_manual_prices(path)
    with sqlite3.connect(path) as c:
        migrate_m0(c)
        # Old synthetic documents may contain letters; opening/printing must not validate/backfill them.
        c.execute("UPDATE patients SET citizen_id='LEGACY-GIA-LAP',address='Địa chỉ cũ giả lập'")
        tables=('patients','visits','users','payments','charges','clinical_revisions')
        before={t:(list(c.execute('SELECT * FROM '+t).description),c.execute('SELECT * FROM '+t).fetchall()) for t in tables}
        migrate_administrative(c);migrate_administrative(c)
        for t,(columns,rows) in before.items():
            assert c.execute('SELECT '+','.join(x[0] for x in columns)+' FROM '+t).fetchall()==rows
        assert c.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=6').fetchone()[0]==1
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
