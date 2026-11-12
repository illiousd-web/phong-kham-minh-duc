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
