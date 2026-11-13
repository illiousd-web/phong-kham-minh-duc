"""S1 regressions: MVCC reads remain available under storage/backup pressure."""
import time
from app import storage
from app.database import db
from scripts.backup_lan import maintenance_lock
from lan_tests.conftest import URL, client_for


def test_full_disk_reads_login_and_writes(clients, visit, monkeypatch):
    monkeypatch.setattr(storage, 'free_bytes', lambda path: 0)
    r = clients['reception']
    assert r.get('/api/patients').status_code == 200
    assert clients['doctor'].get(f'/api/visits/{visit}').status_code == 200
    assert r.get(f'/api/visits/{visit}/forms/reception?format=pdf').status_code == 200
    with db() as c:
        assert c.execute("SELECT 1 FROM audit_log WHERE event='demo_form_exported' AND object_id=?", (str(visit),)).fetchone()
    fresh = client_for('reception')
    assert fresh.get('/api/me').status_code == 200
    fresh.close()
    response = r.post('/api/patients', json={'full_name': 'Giả lập đầy ổ S1', 'sex': 'Nam', 'date_of_birth': '1990-01-01', 'phone': '0900000000'})
    assert response.status_code == 507, response.text


def test_backup_lock_does_not_block_reads(clients):
    with maintenance_lock(URL):
        start = time.monotonic()
        response = clients['reception'].get('/api/patients')
        assert response.status_code == 200, response.text
        assert time.monotonic() - start < 1
        start = time.monotonic()
        response = clients['reception'].post('/api/patients', json={'full_name': 'Giả lập khóa S1', 'sex': 'Nam', 'date_of_birth': '1990-01-01', 'phone': '0900000000'})
        assert response.status_code == 503, response.text
        assert 'Đang sao lưu' in response.text
        assert time.monotonic() - start < 2


def test_expired_session_is_not_extended(clients):
    from datetime import datetime, timedelta, timezone
    r = clients['reception']
    import hashlib
    digest = hashlib.sha256(r.cookies['__Host-clinic'].encode()).hexdigest()
    with db(True) as c:
        c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', ((datetime.now(timezone.utc)-timedelta(minutes=21)).isoformat(),digest))
    assert r.get('/api/me').status_code == 401
