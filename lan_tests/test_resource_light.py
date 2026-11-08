from dataclasses import replace
from pathlib import Path
import os
import secrets
import shutil
import pytest
from .conftest import db


def order(clients,visit):
    return clients['doctor'].post('/api/orders',json={'visit_id':visit,'category':'lab','name':'Tệp giả lập tài nguyên'}).json()['id']


def test_low_disk_refuses_upload_without_changing_record(clients,visit,monkeypatch):
    from app import storage
    oid=order(clients,visit)
    monkeypatch.setattr(storage,'free_bytes',lambda path:0)
    response=clients['technician'].post(f'/api/orders/{oid}/attachment',files={'file':('fake.pdf',b'%PDF-1.5\nFAKE','application/pdf')})
    assert response.status_code==507,response.text
    with db() as c:assert c.execute('SELECT file_key FROM orders WHERE id=?',(oid,)).fetchone()[0] is None


def test_replaced_upload_removed_only_after_commit_and_rollback_keeps_old(clients,visit,monkeypatch):
    from app import main
    oid=order(clients,visit)
    tech=clients['technician']
    def upload():return tech.post(f'/api/orders/{oid}/attachment',files={'file':('fake.pdf',b'%PDF-1.5\nFAKE','application/pdf')})
    assert upload().status_code==200
    with db() as c:first=c.execute('SELECT file_key FROM orders WHERE id=?',(oid,)).fetchone()[0]
    assert upload().status_code==200
    with db() as c:second=c.execute('SELECT file_key FROM orders WHERE id=?',(oid,)).fetchone()[0]
    assert not (main.FILES/first).exists() and (main.FILES/second).exists()
    before=set(main.FILES.iterdir())
    def fail(*args,**kwargs):raise RuntimeError('synthetic transaction failure')
    monkeypatch.setattr(main,'audit',fail)
    with pytest.raises(RuntimeError):upload()
    assert set(main.FILES.iterdir())==before
    with db() as c:assert c.execute('SELECT file_key FROM orders WHERE id=?',(oid,)).fetchone()[0]==second


def test_backup_stream_has_no_plain_tar_and_offsite_failure_preserves_old(tmp_path,monkeypatch):
    from scripts import backup_lan as backup
    key=tmp_path/'backup.key';key.write_bytes(secrets.token_bytes(32))
    directory=tmp_path/'local';offsite=tmp_path/'offsite';offsite.mkdir()
    monkeypatch.setenv('CLINIC_BACKUP_KEEP','2')
    monkeypatch.delenv('CLINIC_BACKUP_OFFSITE_DIR',raising=False)
    original=backup.encrypt_archive
    def checked(members,target,key):
        assert not (target.parent/'payload.tar').exists()
        assert not (target.parent/'attachments').exists() or not any((target.parent/'attachments').iterdir())
        original(members,target,key)
    monkeypatch.setattr(backup,'encrypt_archive',checked)
    first=backup.backup(directory,key)
    for n in ('older1','older2'):shutil.copyfile(first,directory/f'minhduc-{n}.mdbackup')
    before=set(directory.glob('*.mdbackup'))
    monkeypatch.setenv('CLINIC_BACKUP_OFFSITE_DIR',str(tmp_path/'not-mounted'))
    with pytest.raises(ValueError,match='not available'):backup.backup(directory,key)
    assert before.issubset(set(directory.glob('*.mdbackup')))
    monkeypatch.setenv('CLINIC_BACKUP_OFFSITE_DIR',str(offsite))
    new=backup.backup(directory,key)
    assert backup.checksum(new)==backup.checksum(offsite/new.name)
    assert len(list(directory.glob('*.mdbackup')))==2


def test_backup_budget_and_required_offsite_fail_without_pruning(tmp_path,monkeypatch):
    from scripts import backup_lan as backup
    key=tmp_path/'key';key.write_bytes(secrets.token_bytes(32))
    monkeypatch.setenv('CLINIC_REQUIRE_OFFSITE','1');monkeypatch.delenv('CLINIC_BACKUP_OFFSITE_DIR',raising=False)
    with pytest.raises(ValueError,match='off-server'):backup.backup(tmp_path/'local',key)
    monkeypatch.setenv('CLINIC_REQUIRE_OFFSITE','0')
    monkeypatch.setattr(backup,'LIMITS',replace(backup.LIMITS,backup_total_bytes=1))
    with pytest.raises(backup.StorageLimitError):backup.backup(tmp_path/'local',key)
    assert not list((tmp_path/'local').glob('*.mdbackup'))
