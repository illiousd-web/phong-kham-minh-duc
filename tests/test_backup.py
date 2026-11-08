"""Backup/verification tests with synthetic database and attachment only."""
import sqlite3
import zipfile
from pathlib import Path
from scripts import backup_demo
import pytest

def test_backup_integrity_and_no_overwrite(tmp_path,monkeypatch):
    original=tmp_path/'source.sqlite3'
    con=sqlite3.connect(original)
    con.execute('CREATE TABLE example(id INTEGER PRIMARY KEY, note TEXT)')
    con.execute('INSERT INTO example(note) VALUES(?)',('Dữ liệu giả lập',))
    con.commit();con.close()
    upload=tmp_path/'uploads';upload.mkdir()
    (upload/'sample.txt').write_text('kết quả mô phỏng',encoding='utf8')
    monkeypatch.setattr(backup_demo,'DB',original)
    monkeypatch.setattr(backup_demo,'UPLOADS',upload)
    monkeypatch.setattr(backup_demo,'BACKUPS',tmp_path)
    out=tmp_path/'backup.zip'
    produced=backup_demo.create(out)
    assert produced==out
    result=backup_demo.verify(out)
    assert result['verified'] is True and result['files']==2
    with pytest.raises(RuntimeError,match='tồn tại'):
        backup_demo.create(out)
    with zipfile.ZipFile(out) as z:
        assert z.read('attachments/sample.txt').decode()=='kết quả mô phỏng'
        raw=z.read('database.sqlite3')
    restored=tmp_path/'restore.sqlite3';restored.write_bytes(raw)
    c=sqlite3.connect(restored)
    assert c.execute('SELECT note FROM example').fetchone()[0]=='Dữ liệu giả lập'
    c.close()
