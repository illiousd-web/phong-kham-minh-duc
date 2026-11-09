"""Lệnh đếm hàng chờ chạy định kỳ không được giữ phiên sống: sau 20 phút không thao tác phiên vẫn hết hạn."""
import hashlib
from datetime import datetime, timedelta, timezone

from .conftest import client_for, db


def _last_seen(client):
    digest = hashlib.sha256(client.cookies['__Host-clinic'].encode()).hexdigest()
    with db() as c:
        return c.execute('SELECT last_seen FROM sessions WHERE token_hash=?', (digest,)).fetchone()[0], digest


def _shift(digest, minutes):
    """Lùi mốc thao tác cuối: mô phỏng thời gian trôi mà người dùng không thao tác."""
    with db(True) as c:
        old = datetime.fromisoformat(c.execute('SELECT last_seen FROM sessions WHERE token_hash=?', (digest,)).fetchone()[0])
        c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', ((old - timedelta(minutes=minutes)).isoformat(timespec='seconds'), digest))


def test_only_count_polling_for_21_minutes_still_expires():
    for role in ('reception', 'doctor'):
        client = client_for(role)
        try:
            before, digest = _last_seen(client)
            with db() as c:
                audit_before = c.execute("SELECT COUNT(*) FROM audit_log WHERE details LIKE ?",('GET /api/queue-counts%',)).fetchone()[0]
            # Mỗi vòng = 1 phút chỉ có lệnh đếm (giao diện hỏi mỗi 60 giây).
            for minute in range(1, 22):
                _shift(digest, 1)
                shifted, _ = _last_seen(client)
                response = client.get('/api/queue-counts')
                after, _ = _last_seen(client)
                assert after == shifted, 'lệnh đếm không được gia hạn phiên'
                if minute < 20:
                    assert response.status_code == 200, (minute, response.text)
                    assert set(response.json()) == {'reception' if role == 'reception' else 'doctor'}
                else:
                    assert response.status_code == 401, (minute, response.text)
            assert client.get('/api/me').status_code == 401
            with db() as c:
                assert c.execute("SELECT COUNT(*) FROM audit_log WHERE details LIKE ?",('GET /api/queue-counts%',)).fetchone()[0] == audit_before
        finally:
            client.close()


def test_real_activity_still_extends_session():
    client = client_for('doctor')
    try:
        _, digest = _last_seen(client)
        _shift(digest, 15)
        stale, _ = _last_seen(client)
        with db() as c:
            logged = c.execute("SELECT COUNT(*) FROM audit_log WHERE details LIKE ?", ('GET /api/visits %',)).fetchone()[0]
        assert client.get('/api/visits').status_code == 200
        fresh, _ = _last_seen(client)
        with db() as c:  # thao tác thật vẫn ghi nhật ký truy cập như cũ
            assert c.execute("SELECT COUNT(*) FROM audit_log WHERE details LIKE ?", ('GET /api/visits %',)).fetchone()[0] == logged + 1
        assert datetime.fromisoformat(fresh) > datetime.fromisoformat(stale) + timedelta(minutes=14)
        assert datetime.fromisoformat(fresh) <= datetime.now(timezone.utc)
    finally:
        client.close()
