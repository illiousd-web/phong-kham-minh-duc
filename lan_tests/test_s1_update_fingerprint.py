"""Updating a definer/ACL must cause the existing database rollback path to run."""
import secrets
import psycopg
from psycopg import sql
from scripts.install_db import fingerprint
from .conftest import URL


def test_update_fingerprint_detects_function_body_security_and_acl():
    name='s1_fake_fingerprint_'+secrets.token_hex(5)
    fn=sql.Identifier(name)
    table=sql.Identifier(name+'_table')
    try:
        with psycopg.connect(URL,autocommit=True) as c:
            c.execute(sql.SQL('CREATE FUNCTION {}() RETURNS integer LANGUAGE sql AS $$ SELECT 1 $$').format(fn))
            before=fingerprint(URL)
            c.execute(sql.SQL('CREATE OR REPLACE FUNCTION {}() RETURNS integer LANGUAGE sql AS $$ SELECT 2 $$').format(fn))
            body=fingerprint(URL)
            assert body != before, 'Đổi nội dung hàm phải khôi phục CSDL khi cập nhật thất bại'
            c.execute(sql.SQL('ALTER FUNCTION {}() SECURITY DEFINER').format(fn))
            elevated=fingerprint(URL)
            assert elevated != body
            c.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION {}() FROM PUBLIC').format(fn))
            assert fingerprint(URL) != elevated
            assert fingerprint(URL) == fingerprint(URL), 'Chỉ đọc phải ổn định'
            c.execute(sql.SQL('CREATE TABLE {}(n integer)').format(table))
            before_table=fingerprint(URL)
            c.execute(sql.SQL('GRANT SELECT ON {} TO PUBLIC').format(table))
            table_granted=fingerprint(URL)
            assert table_granted != before_table
            c.execute(sql.SQL('GRANT UPDATE(n) ON {} TO PUBLIC').format(table))
            assert fingerprint(URL) != table_granted
    finally:
        with psycopg.connect(URL,autocommit=True) as c:
            c.execute(sql.SQL('DROP FUNCTION IF EXISTS {}()').format(fn))
            c.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(table))
