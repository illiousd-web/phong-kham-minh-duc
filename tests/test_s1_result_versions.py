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
    assert row['legacy_time_unknown']==1
    assert row['created_at']=='2026-01-01'
    from app.order_result_versions import save_version
    save_version(conn,{'id':1},type('Input',(),{'version':1,'result_text':'Kết quả mới giả lập'})(),{'id':1},'2026-02-01')
    assert conn.execute('SELECT legacy_time_unknown FROM order_result_versions WHERE version=2').fetchone()[0]==0
    assert row['version']==1 and json.loads(row['snapshot'])['result_text']=='Kết quả cũ giả lập'
    from app.main import ResultInput
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):ResultInput(result_text='Thiếu phiên bản')


def test_legacy_result_time_display_uses_unknown_message():
    import re,subprocess,json
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/'app/static/app.js').read_text()
    helper=re.search(r'function s1ResultTime\(x\)\{[^\n]+\}',source).group()
    script="function showDay(x){return 'TIME:'+x;}\n"+helper+"\nconsole.log(JSON.stringify([s1ResultTime({legacy_time_unknown:1,created_at:'old'}),s1ResultTime({legacy_time_unknown:0,created_at:'new'})]));"
    output=json.loads(subprocess.check_output(['node','-e',script],text=True))
    assert output==['Kết quả nhập trước nâng cấp – không rõ thời điểm gửi','TIME:new']
    assert '${s1ResultTime(x)}' in source


def test_existing_v14_adds_time_provenance_without_changing_snapshot(tmp_path):
    import sqlite3
    from app.order_result_migration import migrate_result_versions
    c=sqlite3.connect(tmp_path/'v14.sqlite');c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE schema_migrations(version INTEGER); INSERT INTO schema_migrations VALUES(14);
        CREATE TABLE order_result_versions(id INTEGER PRIMARY KEY,created_at TEXT,snapshot TEXT);
        INSERT INTO order_result_versions VALUES(1,'2026-01-01','{"synthetic":true}');""")
    migrate_result_versions(c);migrate_result_versions(c)
    assert dict(c.execute('SELECT * FROM order_result_versions').fetchone())=={'id':1,'created_at':'2026-01-01','snapshot':'{"synthetic":true}','legacy_time_unknown':1}
    c.execute("INSERT INTO order_result_versions(id,created_at) VALUES(2,'2026-02-01')")
    assert c.execute('SELECT legacy_time_unknown FROM order_result_versions WHERE id=2').fetchone()[0]==0
