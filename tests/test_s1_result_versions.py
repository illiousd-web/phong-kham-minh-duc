import secrets
from tests.test_administrative import context


def test_text_result_versions_and_approved_cancellation():
    from tests.s1_result_cases import check_text_versions
    c,ids=context();check_text_versions(c,ids)


def test_result_requires_version_and_preserves_legacy_migration(tmp_path):
    import sqlite3,json
    from app.order_result_migration import migrate_result_versions
    conn=sqlite3.connect(tmp_path/'old.sqlite');conn.row_factory=sqlite3.Row
    conn.executescript('''CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);
      CREATE TABLE users(id INTEGER PRIMARY KEY);
      CREATE TABLE orders(id INTEGER PRIMARY KEY,result_text TEXT,result_by INTEGER,created_at TEXT,status TEXT,approved_by INTEGER,approved_at TEXT);
      INSERT INTO users VALUES(1);
      INSERT INTO orders VALUES(1,'Kết quả cũ giả lập',1,'2026-01-01','approved',1,'2026-01-02');''')
    migrate_result_versions(conn);migrate_result_versions(conn)
    assert conn.execute('SELECT result_text FROM orders').fetchone()[0]=='Kết quả cũ giả lập'
    row=conn.execute('SELECT * FROM order_result_versions').fetchone()
    assert row['version']==1 and json.loads(row['snapshot'])['result_text']=='Kết quả cũ giả lập'
    from app.main import ResultInput
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):ResultInput(result_text='Thiếu phiên bản')
