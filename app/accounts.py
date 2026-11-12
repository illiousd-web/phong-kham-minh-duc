"""Admin account lifecycle and self-service password changes (no demo dependency)."""
import secrets
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import verify

Role = Literal['admin','manager','reception','doctor','technician','nurse','pharmacy','cashier','controlled_prescriber','controlled_pharmacy','controlled_reviewer']


class AccountInput(BaseModel):
    username: str = Field(pattern=r'^[a-z][a-z0-9_.-]{1,39}$')
    full_name: str = Field(min_length=2, max_length=180)
    password: str = Field(min_length=12, max_length=250)
    roles: list[Role] = Field(min_length=1, max_length=11)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=250)
    new_password: str = Field(min_length=12, max_length=250)


class ResetInput(BaseModel):
    password: str = Field(min_length=12, max_length=250)


class AccountUpdate(BaseModel):
    """Chỉ đổi trường được gửi. Không gửi roles thì giữ nguyên quyền (ví dụ chỉ khóa/mở)."""
    active: bool | None = None
    roles: list[Role] | None = Field(default=None, min_length=1, max_length=11)
    full_name: str | None = Field(default=None, min_length=2, max_length=180)


def create_account(c, data, pw_hash, prepared=None):
    if c.execute('SELECT 1 FROM users WHERE username=?', (data.username,)).fetchone():
        raise HTTPException(409, 'Tài khoản đã tồn tại')
    salt, hashed = prepared if prepared else password_digest(data.password, pw_hash)
    c.execute('INSERT INTO users(username,full_name,salt,password_hash) VALUES(?,?,?,?)',
              (data.username,data.full_name,salt,hashed))
    uid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    for role in sorted(set(data.roles)):
        c.execute('INSERT INTO user_roles(user_id,role) VALUES(?,?)', (uid,role))
    return uid


def password_digest(password, pw_hash):
    salt = secrets.token_hex(16)
    return salt, pw_hash(password, salt)


def install_accounts(app, db, principal, require, audit, pw_hash, now):
    @app.get('/api/accounts')
    def accounts(u=Depends(principal)):
        require(u, 'admin')
        with db() as c:
            result = [dict(r) for r in c.execute('SELECT id,username,full_name,active FROM users ORDER BY id')]
            for item in result:
                item['roles'] = [r[0] for r in c.execute('SELECT role FROM user_roles WHERE user_id=? ORDER BY role', (item['id'],))]
            return result

    @app.post('/api/accounts', status_code=201)
    def add_account(data: AccountInput, u=Depends(principal)):
        require(u, 'admin')
        prepared = password_digest(data.password, pw_hash)
        with db(True) as c:
            uid = create_account(c, data, pw_hash, prepared)
            audit(c,u,'account_created','user',uid)
        return {'id':uid}

    @app.put('/api/accounts/{uid}')
    def update_account(uid: int, data: AccountUpdate, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            row = c.execute('SELECT active FROM users WHERE id=?', (uid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Không có tài khoản')
            if data.active is None and data.roles is None and data.full_name is None:
                raise HTTPException(422, 'Không có thay đổi nào')
            old_roles = {r[0] for r in c.execute('SELECT role FROM user_roles WHERE user_id=?', (uid,))}
            roles = set(data.roles) if data.roles is not None else old_roles
            active = data.active if data.active is not None else bool(row['active'])
            if (not active or 'admin' not in roles) and 'admin' in old_roles:
                others = c.execute("SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id=u.id WHERE u.active=1 AND r.role='admin' AND u.id<>?", (uid,)).fetchone()[0]
                if not others:
                    raise HTTPException(409, 'Phải giữ ít nhất một quản trị viên hoạt động')
            changes = []
            if data.full_name is not None:
                c.execute('UPDATE users SET full_name=? WHERE id=?', (data.full_name.strip(), uid))
                changes.append('full_name')
            if data.active is not None:
                c.execute('UPDATE users SET active=? WHERE id=?', (int(active), uid))
                changes.append('active='+str(active))
            if data.roles is not None and roles != old_roles:
                c.execute('DELETE FROM user_roles WHERE user_id=?', (uid,))
                for role in sorted(roles):
                    c.execute('INSERT INTO user_roles VALUES(?,?)', (uid,role))
                changes.append('roles='+','.join(sorted(roles)))
            # Đổi quyền hoặc khóa: thu hồi mọi phiên của người đó.
            if roles != old_roles or not active:
                c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
            audit(c,u,'account_updated','user',uid,'; '.join(changes) or 'không đổi')
        return {'ok':True}

    @app.post('/api/accounts/{uid}/password')
    def reset_password(uid: int, data: ResetInput, u=Depends(principal)):
        require(u, 'admin')
        salt, hashed = password_digest(data.password, pw_hash)
        with db(True) as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                raise HTTPException(404, 'Không có tài khoản')
            c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt,hashed,uid))
            c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
            audit(c,u,'password_reset','user',uid)
        return {'ok':True}

    @app.post('/api/password')
    def change_password(data: PasswordInput, u=Depends(principal)):
        with db() as c:
            candidate = c.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone()
        if not verify(data.current_password, candidate['salt'], candidate['password_hash']):
            raise HTTPException(403, 'Mật khẩu hiện tại không đúng')
        if data.current_password == data.new_password:
            raise HTTPException(422, 'Mật khẩu mới phải khác mật khẩu hiện tại')
        salt, hashed = password_digest(data.new_password, pw_hash)
        with db(True) as c:
            user = c.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone()
            if candidate['password_hash'] != user['password_hash'] or candidate['salt'] != user['salt']:
                raise HTTPException(409, 'Mật khẩu vừa thay đổi; đăng nhập lại')
            c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt,hashed,u['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?', (u['id'],))
            audit(c,u,'password_changed','user',u['id'])
        return {'ok':True,'login_required':True}
