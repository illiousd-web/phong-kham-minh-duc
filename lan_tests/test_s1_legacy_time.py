"""Adding time provenance must not modify frozen version-14 evidence."""
import secrets
from urllib.parse import urlsplit,urlunsplit
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from .conftest import SOURCE
from app.database import PGConnection
from app.order_result_migration import migrate_result_versions


def test_existing_v14_time_column_keeps_frozen_rows_and_guard():
    name='s1_time_'+secrets.token_hex(5)
    target=urlunsplit(urlsplit(SOURCE)._replace(path='/'+name))
    with psycopg.connect(SOURCE,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(target,row_factory=dict_row) as raw:
            raw.execute('''CREATE TABLE schema_migrations(version INTEGER); INSERT INTO schema_migrations VALUES(14);
                CREATE TABLE order_result_versions(id INTEGER PRIMARY KEY,created_at TEXT,snapshot TEXT);
                INSERT INTO order_result_versions VALUES(1,'2026-01-01','{"synthetic":true}');
                CREATE FUNCTION frozen_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'frozen' USING ERRCODE='23514'; END $$;
                CREATE TRIGGER frozen BEFORE UPDATE OR DELETE ON order_result_versions FOR EACH ROW EXECUTE FUNCTION frozen_guard();''')
            before=raw.execute("SELECT pg_get_functiondef('frozen_guard()'::regprocedure) AS body").fetchone()['body']
            migrate_result_versions(PGConnection(raw),postgres=True)
            migrate_result_versions(PGConnection(raw),postgres=True)
            assert raw.execute('SELECT * FROM order_result_versions').fetchone()=={'id':1,'created_at':'2026-01-01','snapshot':'{"synthetic":true}','legacy_time_unknown':1}
            raw.execute("INSERT INTO order_result_versions(id,created_at) VALUES(2,'2026-02-01')")
            assert raw.execute('SELECT legacy_time_unknown FROM order_result_versions WHERE id=2').fetchone()['legacy_time_unknown']==0
            assert raw.execute("SELECT pg_get_functiondef('frozen_guard()'::regprocedure) AS body").fetchone()['body']==before
            with pytest.raises(psycopg.errors.CheckViolation),raw.transaction():
                raw.execute('UPDATE order_result_versions SET legacy_time_unknown=0 WHERE id=1')
    finally:
        with psycopg.connect(SOURCE,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
