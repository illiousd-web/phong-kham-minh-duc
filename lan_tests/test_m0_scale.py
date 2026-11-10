"""Migration on the existing C5 generator's full 22,000 visits, no reduced cohort."""
import hashlib
import secrets
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from .conftest import SOURCE
from app.database import PGConnection, record_factory
from app.m0_migration import migrate_m0
from scripts.tao_du_lieu_gia import generate, CONFIRM
from scripts.do_hieu_nang import measure
from app.doctor_workspace import doctor_queue


def fingerprint(c):
    result = {}
    for table in ('patients', 'visits', 'charges', 'payments', 'stock_lots'):
        digest = hashlib.sha256()
        for row in c.execute(sql.SQL('SELECT (to_jsonb(t)-\'allergies\')::text FROM {} t ORDER BY id').format(sql.Identifier(table))):
            digest.update(row[0].encode('utf-8'))
        result[table] = digest.hexdigest()
    return result


def test_m0_migration_preserves_full_c5_data_and_queue(tmp_path):
    name = 'clinic_perf_test_' + secrets.token_hex(6)
    source = urlunsplit(urlsplit(SOURCE)._replace(path='/postgres'))
    url = urlunsplit(urlsplit(SOURCE)._replace(path='/' + name))
    try:
        manifest = generate(source, name, tmp_path / name, CONFIRM, attachments=0)
        with psycopg.connect(url, row_factory=record_factory) as con:
            before = fingerprint(con)
            migrate_m0(PGConnection(con)); migrate_m0(PGConnection(con))
            assert fingerprint(con) == before
            assert con.execute('SELECT COUNT(*) FROM visits').fetchone()[0] == 22000
            assert con.execute('SELECT COUNT(*) FROM patients WHERE allergies IS NULL').fetchone()[0] == 20000
            result = measure('M0 C5 truy vấn hàng chờ', lambda: doctor_queue(PGConnection(con), manifest['roles']['doctor'], manifest['today']))
            assert result['passed'], result
    finally:
        with psycopg.connect(SOURCE, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
