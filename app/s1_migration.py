"""S1a: immutable PostgreSQL evidence, applied by schema owner only."""
from pathlib import Path


def migrate_s1(c):
    installed = c.execute('SELECT 1 FROM schema_migrations WHERE version=12').fetchone()
    # Execute as one owner transaction: no partly installed protection.
    source = (Path(__file__).resolve().parents[1]/'migrations/012_s1_immutable.sql').read_text(encoding='utf-8')
    if installed:
        # Refresh guards on already installed S1a databases, without recreating triggers.
        source = source.split('CREATE TRIGGER', 1)[0]
    c.connection.execute(source)
    if not installed:
        c.execute('INSERT INTO schema_migrations(version) VALUES(12)')
