"""Practitioner metadata; scope checks warn by default and never grant permissions."""
import json
from datetime import date, datetime

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .labels import parse_day, VN_TZ

SCOPES = ('Nội', 'Ngoại', 'Sản phụ khoa', 'Mắt', 'Tai mũi họng', 'Răng hàm mặt',
          'Da liễu', 'Tâm thần', 'Chẩn đoán hình ảnh', 'Xét nghiệm')
COLUMNS = ('printed_name', 'printed_title', 'practice_license', 'practice_scopes',
           'certificate_provider', 'certificate_serial', 'certificate_expiry')


class PractitionerInput(BaseModel):
    printed_name: str | None = Field(default=None, max_length=180)
    printed_title: str | None = Field(default=None, max_length=80)
    practice_license: str | None = Field(default=None, max_length=100)
    practice_scopes: list[str] = Field(default_factory=list, max_length=10)
    certificate_provider: str | None = Field(default=None, max_length=180)
    certificate_serial: str | None = Field(default=None, max_length=180)
    certificate_expiry: str | None = None

    @field_validator('printed_name', 'printed_title', 'practice_license', 'certificate_provider', 'certificate_serial', mode='before')
    @classmethod
    def trim(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator('certificate_expiry')
    @classmethod
    def expiry(cls, value):
        return parse_day(value)

    @field_validator('practice_scopes')
    @classmethod
    def scopes(cls, value):
        if any(scope not in SCOPES for scope in value):
            raise ValueError('Phạm vi chuyên môn không hợp lệ')
        return sorted(set(value))


def has_scope(c, uid, scope):
    r = c.execute('SELECT practice_scopes FROM users WHERE id=?', (uid,)).fetchone()
    return bool(r and scope in json.loads(r['practice_scopes']))


def printed_name(c, uid):
    if not uid:
        return ''
    r = c.execute('SELECT full_name,printed_name,printed_title FROM users WHERE id=?', (uid,)).fetchone()
    if not r:
        return ''
    return ' '.join(x for x in (r['printed_title'], r['printed_name'] or r['full_name']) if x)


def scope_warning(c, u, category, order_id, now, *, block=False):
    scope = {'lab': 'Xét nghiệm', 'ultrasound': 'Chẩn đoán hình ảnh', 'xray': 'Chẩn đoán hình ảnh'}.get(category)
    if not scope or has_scope(c, u['id'], scope):
        return []
    warning = 'Người duyệt chưa khai phạm vi '+scope+'. Cần kiểm tra hồ sơ người hành nghề.'
    if block:
        raise HTTPException(422, warning)
    c.execute('INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)',
              (u['id'], 'practitioner_scope_warning', 'order', order_id, warning, now()))
    return [warning]


def certificate_warning(value, now=None):
    if not value:
        return None
    today = (now or datetime.now(VN_TZ)).astimezone(VN_TZ).date()
    remaining = (date.fromisoformat(value)-today).days
    if remaining < 30:
        return 'Chứng thư số đã hết hạn' if remaining < 0 else f'Chứng thư số còn {remaining} ngày hết hạn'
    return None


def install_practitioners(app, db, principal, require, now):
    @app.get('/api/practitioners')
    def practitioners(u=Depends(principal)):
        require(u, 'admin')
        with db() as c:
            items = []
            for row in c.execute('SELECT id,full_name,'+','.join(COLUMNS)+' FROM users ORDER BY id'):
                x = dict(row)
                x['practice_scopes'] = json.loads(x['practice_scopes'])
                x['certificate_warning'] = certificate_warning(x['certificate_expiry'])
                items.append(x)
            return {'scopes': SCOPES, 'items': items}

    @app.put('/api/practitioners/{uid}')
    def update_practitioner(uid: int, data: PractitionerInput, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            old = c.execute('SELECT '+','.join(COLUMNS)+' FROM users WHERE id=?', (uid,)).fetchone()
            if not old:
                raise HTTPException(404, 'Không có tài khoản')
            before = dict(old)
            before['practice_scopes'] = json.loads(before['practice_scopes'])
            after = data.model_dump()
            stored = dict(after, practice_scopes=json.dumps(after['practice_scopes'], ensure_ascii=False))
            c.execute('UPDATE users SET '+','.join(k+'=?' for k in stored)+' WHERE id=?', (*stored.values(), uid))
            # Do not truncate old/new practitioner metadata in the audit trail.
            c.execute('INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)',
                      (u['id'], 'practitioner_updated', 'user', uid, json.dumps({'old': before, 'new': after}, ensure_ascii=False), now()))
        return {'ok': True, 'certificate_warning': certificate_warning(after['certificate_expiry'])}
