from datetime import datetime, timezone
from scripts import backup_job


def test_catchup_defers_work_hours_but_not_48_hours(monkeypatch):
    # 02:00 UTC = 09:00 Vietnam; ordinary catchup must not interrupt clinic hours.
    now = datetime(2026,11,12,2,tzinfo=timezone.utc)
    recent = {'last_success_utc':'2026-11-11T13:00:00+00:00'}
    stale = {'last_success_utc':'2026-11-10T01:59:59+00:00'}
    assert backup_job.should_defer_catchup(recent, now)
    assert not backup_job.should_defer_catchup(stale, now)
    assert not backup_job.should_defer_catchup({}, now)
    monkeypatch.setenv('CLINIC_WORK_START','10:00')
    assert not backup_job.should_defer_catchup(recent, now)


def test_access_reserve_uses_service_writable_logs(tmp_path,monkeypatch):
    from app import storage
    monkeypatch.setattr(storage,'free_bytes',lambda path:storage.LIMITS.min_free_bytes+2*storage.ACCESS_RESERVE_BYTES)
    storage.prepare_access_reserve(tmp_path)
    reserve=tmp_path/'logs'/'.access-reserve'
    assert reserve.stat().st_size==storage.ACCESS_RESERVE_BYTES
    monkeypatch.setattr(storage,'free_bytes',lambda path:0)
    storage.release_access_reserve(tmp_path)
    assert not reserve.exists()


import json
import pytest


@pytest.mark.parametrize('flag,instant,last,should_run', [
    ('--scheduled','2026-11-12T13:00:00+00:00','2026-11-11T13:00:00+00:00',True),
    ('--daily','2026-11-12T13:00:00+00:00','2026-11-11T13:00:00+00:00',True),
    ('--catchup','2026-11-12T02:00:00+00:00','2026-11-11T13:00:00+00:00',False),
    ('--catchup','2026-11-12T02:00:00+00:00','2026-11-10T01:59:59+00:00',True)])
def test_daily_and_catchup_use_distinct_scheduling_policy(tmp_path,monkeypatch,flag,instant,last,should_run):
    from scripts import backup_lan
    state=tmp_path/'state.json'
    state.write_text(json.dumps({'last_success_utc':last}))
    monkeypatch.setenv('CLINIC_WORK_START','07:00')
    monkeypatch.setenv('CLINIC_WORK_END','21:00')
    monkeypatch.setattr(backup_job,'now_utc',lambda:datetime.fromisoformat(instant))
    monkeypatch.setattr(backup_job,'space_required',lambda directory:0)
    calls=[]
    def started(*args,**kw):
        calls.append(True)
        # Stop before any actual pg_dump/files/retention; test the decision only.
        raise RuntimeError('Dừng sao lưu giả lập sau khi xác nhận đã chạy')
    monkeypatch.setattr(backup_lan,'backup',started)
    result=backup_job.main([flag,'--key',str(tmp_path/'fake.key'),'--directory',str(tmp_path/'backups'),'--state',str(state)])
    assert bool(calls) == should_run
    assert result == (1 if should_run else 0)


def test_installer_and_updater_share_verified_backup_task_migration():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'deploy/windows'
    for file in ('CaiDat.ps1','CapNhat.ps1'):
        assert 'Set-MinhDucBackupTasks -Paths $P' in (root/file).read_text(encoding='utf-8-sig')
    source=(root/'MinhDuc.Install.psm1').read_text(encoding='utf-8-sig')
    assert 'function Set-MinhDucBackupTasks' in source
    assert 'function Restore-MinhDucBackupTasks' in source
    assert 'function Test-MinhDucBackupTasks' in source
