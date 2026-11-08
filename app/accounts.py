"""Admin account lifecycle and self-service password changes (no demo dependency)."""
import secrets
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import verify

Role = Literal['admin','manager','reception','doctor','technician','nurse','pharmacy','cashier']


class AccountInput(BaseModel):
    username: str = Field(pattern=r'^[a-z][a-z0-9_.-]{1,39}$')
    full_name: str = Field(min_length=2, max_length=180)
    password: str = Field(min_length=12, max_length=250)
    roles: list[Role] = Field(min_length=1, max_length=8)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=250)
    new_password: str = Field(min_length=12, max_length=250)


class ResetInput(BaseModel):
    password: str = Field(min_length=12, max_length=250)


class AccountUpdate(BaseModel):
    active: bool
    roles: list[Role] = Field(min_length=1, max_length=8)


def create_account(c, data, pw_hash):
    if c.execute('SELECT 1 FROM users WHERE username=?', (data.username,)).fetchone():
        raise HTTPException(409, 'Tài khoản đã tồn tại')
    salt = secrets.token_hex(16)
    c.execute('INSERT INTO users(username,full_name,salt,password_hash) VALUES(?,?,?,?)',
              (data.username,data.full_name,salt,pw_hash(data.password,salt)))
    uid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    for role in sorted(set(data.roles)):
        c.execute('INSERT INTO user_roles(user_id,role) VALUES(?,?)', (uid,role))
    return uid


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
        with db(True) as c:
            uid = create_account(c, data, pw_hash)
            audit(c,u,'account_created','user',uid)
        return {'id':uid}

    @app.put('/api/accounts/{uid}')
    def update_account(uid: int, data: AccountUpdate, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                raise HTTPException(404, 'Không có tài khoản')
            if not data.active or 'admin' not in data.roles:
                others = c.execute("SELECT COUNT(*) FROM users u JOIN user_roles r ON r.user_id=u.id WHERE u.active=1 AND r.role='admin' AND u.id<>?", (uid,)).fetchone()[0]
                current_admin = c.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role='admin'", (uid,)).fetchone()
                if current_admin and not others:
                    raise HTTPException(409, 'Phải giữ ít nhất một quản trị viên hoạt động')
            c.execute('UPDATE users SET active=? WHERE id=?', (int(data.active),uid))
            c.execute('DELETE FROM user_roles WHERE user_id=?', (uid,))
            for role in sorted(set(data.roles)):
                c.execute('INSERT INTO user_roles VALUES(?,?)', (uid,role))
            c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
            audit(c,u,'account_updated','user',uid,','.join(sorted(set(data.roles)))+'; active='+str(data.active))
        return {'ok':True}

    @app.post('/api/accounts/{uid}/password')
    def reset_password(uid: int, data: ResetInput, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                raise HTTPException(404, 'Không có tài khoản')
            salt = secrets.token_hex(16)
            c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt,pw_hash(data.password,salt),uid))
            c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
            audit(c,u,'password_reset','user',uid)
        return {'ok':True}

    @app.post('/api/password')
    def change_password(data: PasswordInput, u=Depends(principal)):
        with db(True) as c:
            user = c.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone()
            if not verify(data.current_password, user['salt'], user['password_hash']):
                raise HTTPException(403, 'Mật khẩu hiện tại không đúng')
            if data.current_password == data.new_password:
                raise HTTPException(422, 'Mật khẩu mới phải khác mật khẩu hiện tại')
            salt = secrets.token_hex(16)
            c.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt,pw_hash(data.new_password,salt),u['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?', (u['id'],))
            audit(c,u,'password_changed','user',u['id'])
        return {'ok':True,'login_required':True}
