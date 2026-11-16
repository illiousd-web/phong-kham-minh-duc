"""Password-confirmed signatures bind the responsible actor to exact print content."""
import hashlib
import hmac
import json
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import verify
from .clinic_profile import read_profile
from .s2c_forms import from_context, from_m6, laboratory

KINDS = Literal['rx', 'order', 'lab', 'clinical_rx', 'lab_report']


class SignInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=250)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


def lab_print_data(c, r, o):
    from .m5 import report_data
    from .d0 import diagnosis_text
    p = report_data(c, r, o)
    p['clinic_profile'] = read_profile(c)
    visit = dict(c.execute('SELECT * FROM visits WHERE id=?', (o['visit_id'],)).fetchone())
    p['diagnosis'] = diagnosis_text(visit)
    successor = c.execute("SELECT id FROM lab_reports WHERE replaces_id=? AND status='approved'", (r['id'],)).fetchone()
    if successor:
        p['superseded_by'] = successor['id']
    return p


def clinical_print_data(c, rx):
    from .m6 import payload
    p = json.loads(rx['snapshot']) if rx['snapshot'] else payload(c, rx)
    p['clinic_profile'] = read_profile(c)
    patient = c.execute('SELECT p.code FROM patients p JOIN visits v ON v.patient_id=p.id WHERE v.id=?', (rx['visit_id'],)).fetchone()
    p['patient']['code'] = patient['code']
    p['print_number'] = rx['local_code'] or f"MD-RX-{rx['id']:06d}"
    if rx['status'] == 'cancelled':
        replacement = c.execute('SELECT id,local_code FROM clinical_prescriptions WHERE replaces_id=? AND locked_at IS NOT NULL ORDER BY id LIMIT 1', (rx['id'],)).fetchone()
        if replacement:
            p['replaced_by_code'] = replacement['local_code'] or '#'+str(replacement['id'])
    return p


def load_document(c, kind, object_id):
    if kind == 'clinical_rx':
        r = c.execute('SELECT * FROM clinical_prescriptions WHERE id=?', (object_id,)).fetchone()
        if not r:
            raise HTTPException(404, 'Không có đơn thuốc')
        models = [from_m6(clinical_print_data(c, r), r['status'])]
        actor, vid, allowed = r['doctor_id'], r['visit_id'], r['status'] != 'cancelled'
    elif kind == 'lab_report':
        from .m5 import GROUPS
        r = c.execute('SELECT * FROM lab_reports WHERE id=?', (object_id,)).fetchone()
        if not r:
            raise HTTPException(404, 'Không có phiếu xét nghiệm')
        o = c.execute('SELECT * FROM orders WHERE id=?', (r['order_id'],)).fetchone()
        p = lab_print_data(c, r, o)
        models = [laboratory(p, g) for g in GROUPS if any(x['group_name'] == g for x in p['items'])]
        actor, vid, allowed = r['approved_by'], o['visit_id'], r['status'] == 'approved' and not p.get('superseded_by')
    else:
        from .main import form_context
        p = form_context(c, kind, object_id)
        r = p.get('rx') if kind == 'rx' else p.get('order')
        models = [from_context(kind, p)]
        actor = r.get('approved_by') if kind == 'lab' else p['visit']['doctor_id']
        vid = p['visit']['id']
        allowed = r['status'] == 'approved' if kind == 'lab' else r['status'] != 'cancelled'
        if kind == 'lab' and c.execute('SELECT 1 FROM lab_reports WHERE order_id=?', (object_id,)).fetchone():
            raise HTTPException(409, 'Ký phiếu theo chỉ số trong Xét nghiệm M5')
    return {'models': models, 'actor': actor, 'visit_id': vid, 'allowed': allowed,
            'content_hash': content_hash(models)}


def content_hash(models):
    encoded = json.dumps(models, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def valid_signature(c, kind, object_id, document=None, *, models=None):
    d = document or load_document(c, kind, object_id)
    if models is not None:
        d = {**d, 'content_hash': content_hash(models)}
    s = c.execute('SELECT * FROM document_signatures WHERE document_kind=? AND document_id=? ORDER BY id DESC LIMIT 1', (kind, object_id)).fetchone()
    if not s or s['invalidated'] or not d['allowed'] or s['signed_by'] != d['actor'] or not hmac.compare_digest(s['content_hash'], d['content_hash']):
        return None
    return {**dict(s), 'image': bytes(s['image'])}


def install_document_signatures(app, db, principal, require, audit, now):
    def authorized(c, kind, oid, u):
        require(u, 'doctor')
        d = load_document(c, kind, oid)
        if d['actor'] != u['id']:
            raise HTTPException(403, 'Chỉ bác sĩ kê đơn / chỉ định hoặc chính người duyệt xét nghiệm được ký phiếu')
        if not d['allowed']:
            raise HTTPException(409, 'Phiếu đã hủy, chưa duyệt hoặc đã được thay thế; không thể ký')
        return d

    @app.get('/api/document-signatures/{kind}/{object_id}')
    def state(kind: KINDS, object_id: int, u=Depends(principal)):
        with db() as c:
            d = authorized(c, kind, object_id, u)
            s = valid_signature(c, kind, object_id, d)
        return {'content_hash': d['content_hash'], 'signed_by': s['signed_by'] if s else None,
                'signed_at': s['signed_at'] if s else None}

    @app.post('/api/document-signatures/{kind}/{object_id}')
    def sign(kind: KINDS, object_id: int, data: SignInput, u=Depends(principal)):
        # Password hashing is deliberately outside the database write/backup lock.
        with db() as c:
            authorized(c, kind, object_id, u)
            account = c.execute('SELECT * FROM users WHERE id=? AND active=1', (u['id'],)).fetchone()
        if not account or not verify(data.password, account['salt'], account['password_hash']):
            with db(True) as c:
                audit(c, u, 'document_sign_failed', kind, object_id, 'Mật khẩu xác nhận không đúng')
            raise HTTPException(403, 'Mật khẩu xác nhận không đúng')
        with db(True) as c:
            current = c.execute('SELECT * FROM users WHERE id=? AND active=1', (u['id'],)).fetchone()
            if not current or current['password_hash'] != account['password_hash'] or current['salt'] != account['salt']:
                raise HTTPException(409, 'Tài khoản vừa thay đổi; đăng nhập lại trước khi ký')
            # PostgreSQL source writers and signer serialize on the visit row.
            from .config import LAN
            d = authorized(c, kind, object_id, u)
            if LAN:
                c.execute('SELECT id FROM visits WHERE id=? FOR UPDATE', (d['visit_id'],))
                d = authorized(c, kind, object_id, u)
            if not hmac.compare_digest(data.content_hash, d['content_hash']):
                raise HTTPException(409, 'Nội dung đã thay đổi; mở lại phiếu trước khi ký')
            image = c.execute('SELECT image FROM user_signatures WHERE user_id=?', (u['id'],)).fetchone()
            if not image:
                raise HTTPException(409, 'Chưa có ảnh chữ ký của tài khoản; liên hệ quản trị tải ảnh lên')
            stamp = now()
            from .s2c_forms import render
            for model in d['models']:
                model['signature'] = {'image': bytes(image['image']), 'signed_at': stamp, 'username': current['username']}
                render(model, 'pdf')
            c.execute('INSERT INTO document_signatures(document_kind,document_id,visit_id,signed_by,signed_at,content_hash,image,username) VALUES(?,?,?,?,?,?,?,?)',
                      (kind, object_id, d['visit_id'], u['id'], stamp, d['content_hash'], bytes(image['image']), current['username']))
            audit(c, u, 'document_signed', kind, object_id, json.dumps({
                'signed_by': u['id'], 'signed_at': stamp, 'content_hash': d['content_hash'],
                'signature_sha256': hashlib.sha256(bytes(image['image'])).hexdigest()}))
        return {'signed_by': u['id'], 'signed_at': stamp, 'content_hash': d['content_hash']}
