"""A contended username lock must not mutate password-attempt counters."""
import hashlib
import time
import psycopg
from .conftest import URL, db, client_for, PASSWORDS


def test_same_username_lock_is_503_without_incrementing_attempts():
    username = 'test_reception'
    key = hashlib.sha256(username.casefold().encode()).hexdigest()
    with db('access') as c:
        c.execute('INSERT INTO login_attempts(key,failures,locked_until) VALUES(?,2,?) ON CONFLICT(key) DO UPDATE SET failures=2,locked_until=excluded.locked_until', (key,''))
    client = client_for()
    client.raise_server_exceptions = False
    # Set the transport flag as well (Starlette stores it on the transport).
    client._transport.raise_server_exceptions = False
    try:
        with psycopg.connect(URL) as holder:
            holder.execute('SELECT pg_advisory_xact_lock(%s)', (-int(key[:15],16)-1,))
            start = time.monotonic()
            r = client.post('/api/login',json={'username':username,'password':PASSWORDS['reception']})
            assert r.status_code == 503, r.text
            assert r.json()['detail'] == 'Đang xử lý đăng nhập, thử lại'
            assert r.headers['Retry-After'] == '1'
            assert time.monotonic()-start < 2
        with db() as c:
            attempt = dict(c.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone())
            assert attempt['failures']==2 and attempt['locked_until']==''
    finally:
        client.close()
        with db('access') as c: c.execute('DELETE FROM login_attempts WHERE key=?',(key,))
