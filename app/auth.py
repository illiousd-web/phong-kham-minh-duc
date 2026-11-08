"""Individual passwords and revocable sessions; secure cookies in LAN mode."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

COOKIE = '__Host-clinic'
CSRF_COOKIE = '__Host-clinic-csrf'
IDLE_MINUTES = 20


def pw_hash(password, salt):
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return 'pbkdf2_sha256$600000$' + digest


def verify(password, salt, stored):
    # Legacy hashes only occur in local demo databases; new/reset passwords use 600k.
    actual = pw_hash(password, salt) if stored.startswith('pbkdf2_sha256$') else hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260_000).hex()
    return hmac.compare_digest(actual, stored)


class Login(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=1, max_length=250)


def install_auth(app, db, lan, now):
    dummy_salt=secrets.token_hex(16)
    dummy_hash=pw_hash(secrets.token_urlsafe(32),dummy_salt)
    def log(c, uid, event):
        c.execute('INSERT INTO audit_log(user_id,event,object_type,created_at) VALUES(?,?,?,?)',
                  (uid, event, 'session', now()))

    @app.post('/api/login')
    def login(data: Login, request: Request, response: Response):
        denied = False
        with db(True) as c:
            instant = datetime.now(timezone.utc)
            key = hashlib.sha256(data.username.casefold().encode()).hexdigest()
            if lan:
                attempt = c.execute('SELECT * FROM login_attempts WHERE key=?', (key,)).fetchone()
                if attempt and attempt['locked_until'] > instant.isoformat():
                    raise HTTPException(429, 'Tạm khóa đăng nhập, thử lại sau 15 phút', headers={'Retry-After': '900'})
            u = c.execute('SELECT * FROM users WHERE username=? AND active=1', (data.username,)).fetchone()
            valid = verify(data.password, u['salt'], u['password_hash']) if u else verify(data.password, dummy_salt, dummy_hash)
            if not u or not valid:
                denied = True
                if lan:
                    failures = (attempt['failures'] if attempt and not attempt['locked_until'] else 0) + 1
                    until = (instant + timedelta(minutes=15)).isoformat() if failures >= 5 else ''
                    c.execute('INSERT INTO login_attempts(key,failures,locked_until) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET failures=excluded.failures,locked_until=excluded.locked_until', (key, failures, until))
                log(c, u['id'] if u else None, 'login_failed')
            else:
                if lan:
                    c.execute('DELETE FROM login_attempts WHERE key=?', (key,))
                c.execute('DELETE FROM sessions WHERE expires_at<=?', (now(),))
                token = secrets.token_urlsafe(48)
                digest = hashlib.sha256(token.encode()).hexdigest()
                expires = (instant + timedelta(hours=8)).isoformat()
                if lan:
                    # Rotate the current browser session on each successful login.
                    previous = request.cookies.get(COOKIE)
                    if previous:
                        c.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(previous.encode()).hexdigest(),))
                    c.execute('INSERT INTO sessions(token_hash,user_id,expires_at,last_seen) VALUES(?,?,?,?)', (digest,u['id'],expires,instant.isoformat()))
                else:
                    c.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)', (digest,u['id'],expires))
                roles = [r[0] for r in c.execute('SELECT role FROM user_roles WHERE user_id=? ORDER BY role', (u['id'],))]
                log(c, u['id'], 'login_succeeded')
                payload = {'user': {'id':u['id'],'username':u['username'],'name':u['full_name'],'roles':roles}}
                if lan:
                    options = dict(secure=True, samesite='strict', max_age=8*3600, path='/')
                    response.set_cookie(COOKIE, token, httponly=True, **options)
                    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False, **options)
                else:
                    payload['access_token'] = token
        # Commit failed-login counters and audit before returning an error.
        if denied:
            raise HTTPException(401, 'Sai tài khoản hoặc mật khẩu')
        return payload

    def principal(request: Request, authorization: Annotated[str | None, Header()] = None):
        token = request.cookies.get(COOKIE) if lan else (authorization[7:] if authorization and authorization.startswith('Bearer ') else None)
        if not token or len(token) < 48 or len(token) > 200:
            raise HTTPException(401, 'Cần đăng nhập')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with db(lan) as c:
            u = c.execute('SELECT users.*,sessions.expires_at' + (',sessions.last_seen' if lan else '') + ' FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires_at>? AND active=1', (digest,now())).fetchone()
            if not u:
                raise HTTPException(401, 'Hết hạn phiên hoặc không hợp lệ')
            if lan:
                if not u['last_seen'] or datetime.fromisoformat(u['last_seen']) < datetime.now(timezone.utc)-timedelta(minutes=IDLE_MINUTES):
                    raise HTTPException(401, 'Phiên hết hạn do không hoạt động')
                c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', (now(),digest))
            roles = [r[0] for r in c.execute('SELECT role FROM user_roles WHERE user_id=? ORDER BY role', (u['id'],))]
            return {'id':u['id'],'username':u['username'],'name':u['full_name'],'roles':roles,'token_hash':digest}

    @app.get('/api/me')
    def me(u=Depends(principal)):
        return {k:v for k,v in u.items() if k != 'token_hash'}

    @app.post('/api/logout')
    def logout(response: Response, u=Depends(principal)):
        with db(True) as c:
            c.execute('DELETE FROM sessions WHERE token_hash=?', (u['token_hash'],))
            log(c, u['id'], 'logout')
        for cookie in (COOKIE, CSRF_COOKIE):
            response.delete_cookie(cookie, path='/', secure=True, httponly=cookie == COOKIE, samesite='strict')
        return {'ok':True}

    return principal
