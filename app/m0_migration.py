"""Version 5: additive nullable allergy history; no patient/visit backfill."""
from pathlib import Path


def migrate_m0(c):
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=5').fetchone():
        return
    c.execute((Path(__file__).resolve().parents[1] / 'migrations/005_patient_allergies.sql').read_text(encoding='utf-8'))
    c.execute('INSERT INTO schema_migrations(version) VALUES(5)')
