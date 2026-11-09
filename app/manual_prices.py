"""Cashier entry, independent review and daily reconciliation of manual prices."""
from datetime import datetime, timedelta, timezone
import json

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .domain import invoice

VN = timezone(timedelta(hours=7))


class ManualPrice(BaseModel):
    amount: int = Field(strict=True, gt=0, le=2_000_000_000)
    description: str = Field(min_length=1, max_length=240)
    request_key: str = Field(min_length=8, max_length=120)

    @field_validator('description')
    @classmethod
    def content_required(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Bắt buộc ghi nội dung dịch vụ cụ thể')
        return value


class ManualPriceChange(ManualPrice):
    reason: str = Field(min_length=8, max_length=500)


class Review(BaseModel):
    approve: bool


def manual_description(c, cid):
    latest = c.execute("SELECT description FROM manual_price_requests WHERE charge_id=? AND status='approved' ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if latest:
        return latest[0]
    first = c.execute('SELECT description FROM manual_charge_prices WHERE charge_id=?', (cid,)).fetchone()
    return first[0] if first else None


def manual_charge(c, cid):
    ch = c.execute('SELECT * FROM effective_charges WHERE id=?', (cid,)).fetchone()
    if not ch:
        raise HTTPException(404, 'Không có khoản phải thu')
    if ch['original_amount'] is not None:
        raise HTTPException(409, 'Khoản này có giá cố định, không phải khoản giá nhập tay')
    if c.execute('SELECT 1 FROM charge_voids WHERE charge_id=?', (cid,)).fetchone():
        raise HTTPException(409, 'Khoản đã hủy, không được nhập hoặc sửa giá')
    return ch


def install_manual_prices(app, db, principal, require, audit, now):
    @app.post('/api/charges/{cid}/manual-price')
    def enter_price(cid: int, data: ManualPrice, u=Depends(principal)):
        require(u, 'cashier', 'manager')
        with db(True) as c:
            old = c.execute('SELECT * FROM manual_charge_prices WHERE request_key=?', (data.request_key,)).fetchone()
            if old:
                if (old['charge_id'], old['amount'], old['description'], old['priced_by']) != (cid, data.amount, data.description, u['id']):
                    raise HTTPException(409, 'Mã thao tác đã dùng với nội dung khác')
                return {'status': 'already_recorded', 'billing': invoice(c, c.execute('SELECT visit_id FROM charges WHERE id=?', (cid,)).fetchone()[0])}
            ch = manual_charge(c, cid)
            if ch['amount'] is not None:
                raise HTTPException(409, 'Khoản đã nhập giá; muốn sửa phải gửi đề nghị để quản lý duyệt')
            c.execute('INSERT INTO manual_charge_prices(charge_id,amount,description,priced_by,priced_at,request_key) VALUES(?,?,?,?,?,?)',
                      (cid, data.amount, data.description, u['id'], now(), data.request_key))
            audit(c, u, 'manual_price_entered', 'charge', cid,
                  json.dumps({'amount': data.amount, 'description': data.description}, ensure_ascii=False))
            return {'status': 'recorded', 'billing': invoice(c, ch['visit_id'])}

    @app.post('/api/charges/{cid}/manual-price-requests', status_code=201)
    def propose(cid: int, data: ManualPriceChange, u=Depends(principal)):
        require(u, 'cashier', 'manager')
        with db(True) as c:
            old = c.execute('SELECT * FROM manual_price_requests WHERE request_key=?', (data.request_key,)).fetchone()
            if old:
                if (old['charge_id'], old['new_amount'], old['description'], old['reason'], old['proposed_by']) != (cid, data.amount, data.description, data.reason, u['id']):
                    raise HTTPException(409, 'Mã thao tác đã dùng với nội dung khác')
                return {'id': old['id'], 'status': old['status']}
            ch = manual_charge(c, cid)
            if ch['amount'] is None:
                raise HTTPException(409, 'Khoản chưa có giá; hãy nhập giá lần đầu')
            if c.execute("SELECT 1 FROM manual_price_requests WHERE charge_id=? AND status='pending'", (cid,)).fetchone():
                raise HTTPException(409, 'Đã có đề nghị sửa giá chờ quản lý duyệt')
            c.execute('''INSERT INTO manual_price_requests(charge_id,previous_amount,previous_description,new_amount,
                description,reason,proposed_by,proposed_at,request_key) VALUES(?,?,?,?,?,?,?,?,?)''',
                      (cid, ch['amount'], manual_description(c, cid), data.amount, data.description, data.reason, u['id'], now(), data.request_key))
            rid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c, u, 'manual_price_change_requested', 'charge', cid,
                  json.dumps({'request_id': rid, 'old_price': ch['amount'], 'new_price': data.amount,
                              'description': data.description}, ensure_ascii=False))
            return {'id': rid, 'status': 'pending'}

    @app.get('/api/manual-price-requests')
    def requests(u=Depends(principal)):
        require(u, 'cashier', 'manager')
        with db() as c:
            sql = '''SELECT r.*,ch.visit_id,ch.label,p.full_name AS patient_name,u.full_name AS proposed_name
                FROM manual_price_requests r JOIN charges ch ON ch.id=r.charge_id JOIN visits v ON v.id=ch.visit_id
                JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=r.proposed_by'''
            args = ()
            if 'manager' not in u['roles']:
                sql += ' WHERE r.proposed_by=?'
                args = (u['id'],)
            return [dict(r) for r in c.execute(sql + ' ORDER BY r.id DESC', args)]

    @app.post('/api/manual-price-requests/{rid}/review')
    def review(rid: int, data: Review, u=Depends(principal)):
        require(u, 'manager')
        with db(True) as c:
            r = c.execute('SELECT * FROM manual_price_requests WHERE id=?', (rid,)).fetchone()
            if not r:
                raise HTTPException(404, 'Không có đề nghị sửa giá')
            if r['status'] != 'pending':
                raise HTTPException(409, 'Đề nghị đã xử lý')
            if r['proposed_by'] == u['id']:
                raise HTTPException(403, 'Không tự duyệt đề nghị sửa giá của mình')
            ch = manual_charge(c, r['charge_id']) if data.approve else c.execute('SELECT * FROM effective_charges WHERE id=?', (r['charge_id'],)).fetchone()
            if data.approve:
                if ch['amount'] != r['previous_amount'] or manual_description(c, r['charge_id']) != r['previous_description']:
                    raise HTTPException(409, 'Giá hoặc nội dung đã thay đổi; cần đề nghị lại')
                c.execute('INSERT INTO charge_pricing(charge_id,amount) VALUES(?,?) ON CONFLICT(charge_id) DO UPDATE SET amount=excluded.amount', (ch['id'], r['new_amount']))
                c.execute('INSERT INTO charge_price_history(charge_id,previous_amount,new_amount,reason,changed_by,created_at,request_key) VALUES(?,?,?,?,?,?,?)',
                          (ch['id'], ch['amount'], r['new_amount'], r['reason'], u['id'], now(), 'manual-review:' + str(rid)))
                invoice(c, ch['visit_id'])  # Rolls back the entire approval if discounts become invalid.
            status = 'approved' if data.approve else 'rejected'
            c.execute('UPDATE manual_price_requests SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?', (status, u['id'], now(), rid))
            audit(c, u, 'manual_price_change_' + status, 'charge', ch['id'],
                  json.dumps({'request_id': rid, 'old_price': r['previous_amount'], 'new_price': r['new_amount'],
                              'description': r['description']}, ensure_ascii=False))
            return {'status': status, 'billing': invoice(c, ch['visit_id'])}

    @app.get('/api/reports/manual-prices')
    def daily(day: str | None = None, u=Depends(principal)):
        require(u, 'manager')
        try:
            start = datetime.strptime(day, '%d/%m/%Y').replace(tzinfo=VN) if day else datetime.now(VN).replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            raise HTTPException(422, 'Ngày báo cáo phải theo dd/mm/yyyy và là ngày có thật')
        begin, end = start.astimezone(timezone.utc).isoformat(timespec='seconds'), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec='seconds')
        with db() as c:
            entries = [dict(r) for r in c.execute('''SELECT mp.charge_id,ch.visit_id,ch.label,p.full_name AS patient_name,
                mp.amount,mp.description,mp.priced_at AS occurred_at,u.full_name AS actor_name,mp.priced_by AS actor_id,
                NULL AS previous_amount,NULL AS reviewer_name,'entry' AS kind,cv.reason AS void_reason
                FROM manual_charge_prices mp JOIN charges ch ON ch.id=mp.charge_id JOIN visits v ON v.id=ch.visit_id
                JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=mp.priced_by
                LEFT JOIN charge_voids cv ON cv.charge_id=ch.id WHERE mp.priced_at>=? AND mp.priced_at<?''', (begin, end))]
            changes = [dict(r) for r in c.execute('''SELECT r.charge_id,ch.visit_id,ch.label,p.full_name AS patient_name,
                r.new_amount AS amount,r.description,r.reviewed_at AS occurred_at,u.full_name AS actor_name,r.proposed_by AS actor_id,
                r.previous_amount,reviewer.full_name AS reviewer_name,'change' AS kind,cv.reason AS void_reason
                FROM manual_price_requests r JOIN charges ch ON ch.id=r.charge_id JOIN visits v ON v.id=ch.visit_id
                JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=r.proposed_by
                JOIN users reviewer ON reviewer.id=r.reviewed_by LEFT JOIN charge_voids cv ON cv.charge_id=ch.id
                WHERE r.status='approved' AND r.reviewed_at>=? AND r.reviewed_at<?''', (begin, end))]
            unpriced = [dict(r) for r in c.execute('''SELECT ch.id AS charge_id,ch.visit_id,ch.label,p.full_name AS patient_name
                FROM effective_charges ch JOIN visits v ON v.id=ch.visit_id JOIN patients p ON p.id=v.patient_id
                WHERE ch.amount IS NULL AND ch.created_at>=? AND ch.created_at<? ORDER BY ch.id''', (begin, end))]
        return {'day': start.strftime('%d/%m/%Y'), 'entries': sorted(entries + changes, key=lambda r: (r['occurred_at'], r['charge_id'])),
                'total_entered': sum(r['amount'] for r in entries), 'adjustment_delta': sum(r['amount'] - r['previous_amount'] for r in changes),
                'unpriced': unpriced}
