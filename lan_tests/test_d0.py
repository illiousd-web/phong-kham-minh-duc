from .conftest import db,IDS,SERVICE
from tests.d0_cases import check_d0

def test_d0_postgresql_source_import_rules_and_links(clients):check_d0(clients,IDS,db,SERVICE)

def test_d0_postgresql_prescription_and_lab_snapshots(clients):
    from tests.d0_cases import check_standard_snapshots
    check_standard_snapshots(clients,IDS,db,SERVICE)

def test_d0_populated_catalogs_survive_encrypted_restore(clients,tmp_path):
    import secrets,psycopg,json
    from psycopg import sql
    from urllib.parse import urlsplit,urlunsplit
    from .conftest import URL
    from scripts.backup_lan import backup,restore
    from app.d0_migration import TABLES
    from app.d0_source_migration import TABLES as SOURCE_TABLES
    TABLES=TABLES+SOURCE_TABLES
    check_d0(clients,IDS,db,SERVICE)
    key=tmp_path/'fake.key';key.write_bytes(secrets.token_bytes(32));name='d0_restore_'+secrets.token_hex(6);target=urlunsplit(urlsplit(URL)._replace(path='/'+name))
    def contents(connection):return {table:sorted(json.dumps(dict(zip([d.name for d in cur.description],row)),sort_keys=True,default=str) for row in cur) for table in TABLES for cur in [connection.execute('SELECT * FROM '+table)]}
    with psycopg.connect(URL,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(URL) as c:before=contents(c)
        path=backup(tmp_path/'backups',key);restore(path,key,target,tmp_path/'attachments')
        with psycopg.connect(target) as c:assert contents(c)==before
    finally:
        with psycopg.connect(URL,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
