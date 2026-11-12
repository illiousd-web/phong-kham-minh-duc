"""S1a: immutable PostgreSQL evidence, applied by schema owner only."""
from pathlib import Path


def migrate_s1(c):
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=12').fetchone():
        return
    # Execute as one owner transaction: no partly installed protection.
    c.connection.execute((Path(__file__).resolve().parents[1]/'migrations/012_s1_immutable.sql').read_text())
    c.execute('INSERT INTO schema_migrations(version) VALUES(12)')
