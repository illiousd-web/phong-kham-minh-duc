"""Cashier and administrator actions for financial closure."""
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .domain import invoice
from .financial_state import ensure_financial_open


class SettlementReason(BaseModel):
    reason: str = Field(max_length=500)


def financial_status(c, visit_id):
    row = c.execute('''SELECT id,kind,created_at,waived_amount FROM active_visit_settlements
        WHERE visit_id=?''', (visit_id,)).fetchone()
    return dict(row) if row else None


def close_visit(c, visit_id, user, audit, now, reason=None):
    visit = c.execute('SELECT status FROM visits WHERE id=?', (visit_id,)).fetchone()
    if not visit:
        raise HTTPException(404, 'Không tìm thấy lượt khám')
    ensure_financial_open(c, visit_id)
    if visit['status'] != 'completed':
        raise HTTPException(409, 'Bác sĩ chưa khóa phiếu')
    bill = invoice(c, visit_id)
    if bill['unpriced_count']:
        raise HTTPException(409, 'Còn khoản chưa có giá')
    if bill['refund_due']:
        amount = f"{bill['refund_due']:,}".replace(',', '.')
        raise HTTPException(409, f'Còn phải hoàn {amount} đồng')
    if reason is None and bill['due']:
        amount = f"{bill['due']:,}".replace(',', '.')
        raise HTTPException(409, f'Còn phải thu {amount} đồng')
    if reason is not None and c.execute('SELECT 1 FROM payments WHERE visit_id=? AND created_by=?',
                                       (visit_id, user['id'])).fetchone():
        raise HTTPException(403, 'Người đã thu tiền lượt này không được duyệt miễn thu')

    previous = c.execute('SELECT id FROM visit_settlements WHERE visit_id=? ORDER BY id DESC LIMIT 1',
                         (visit_id,)).fetchone()
    kind = 'du_thu' if reason is None else 'mien_thu'
    waived = bill['due'] if reason is not None else 0
    approved = user['id'] if reason is not None else None
    stamp = now()
    c.execute('''INSERT INTO visit_settlements(visit_id,previous_settlement_id,actor_id,created_at,
                 charged,paid,due,refund_due,kind,waived_amount,reason,approved_by)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
              (visit_id, previous['id'] if previous else None, user['id'], stamp,
               bill['charged'], bill['paid'], bill['due'], bill['refund_due'], kind, waived, reason, approved))
    settlement_id = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    event = 'visit_settlement_waived' if reason is not None else 'visit_settled'
    audit(c, user, event, 'visit', visit_id, reason or '')
    return {'id': settlement_id, 'kind': kind, 'waived_amount': waived, 'created_at': stamp}


def install_settlements(app, db, principal, require, audit, now):
    @app.post('/api/visits/{visit_id}/settle')
    def settle(visit_id: int, user=Depends(principal)):
        require(user, 'cashier', 'admin')
        with db(True) as c:
            return close_visit(c, visit_id, user, audit, now)

    @app.post('/api/visits/{visit_id}/settlement-waiver')
    def waive(visit_id: int, data: SettlementReason, user=Depends(principal)):
        require(user, 'admin')
        reason = data.reason.strip()
        if len(reason) < 10:
            raise HTTPException(422, 'Lý do miễn thu cần ít nhất 10 ký tự')
        with db(True) as c:
            return close_visit(c, visit_id, user, audit, now, reason)

    @app.post('/api/visits/{visit_id}/settlement-reopen')
    def reopen(visit_id: int, data: SettlementReason, user=Depends(principal)):
        require(user, 'admin')
        reason = data.reason.strip()
        if not reason:
            raise HTTPException(422, 'Cần nhập lý do mở lại')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM visits WHERE id=?', (visit_id,)).fetchone():
                raise HTTPException(404, 'Không tìm thấy lượt khám')
            active = financial_status(c, visit_id)
            if not active:
                raise HTTPException(409, 'Lượt chưa kết thúc tài chính')
            c.execute('''INSERT INTO visit_settlement_reopens(settlement_id,visit_id,actor_id,created_at,reason)
                         VALUES(?,?,?,?,?)''', (active['id'], visit_id, user['id'], now(), reason))
            audit(c, user, 'visit_settlement_reopened', 'visit', visit_id, reason)
            return {'status': 'reopened', 'settlement_id': active['id']}

    @app.get('/api/financial-settlements')
    def list_financial_settlements(closed: bool = False, offset: int = Query(0, ge=0), user=Depends(principal)):
        require(user, *(['admin'] if closed else ['manager', 'admin']))
        where = 's.id IS NOT NULL' if closed else 's.id IS NULL'
        order = 's.id' if closed else 'v.id'
        with db() as c:
            rows = [dict(row) for row in c.execute('''SELECT v.id AS visit_id,v.created_at,
                p.code AS patient_code,p.full_name AS patient_name
                FROM visits v JOIN patients p ON p.id=v.patient_id
                LEFT JOIN active_visit_settlements s ON s.visit_id=v.id
                WHERE v.status='completed' AND ''' + where + ' ORDER BY ' + order + ' DESC LIMIT 51 OFFSET ?', (offset,))]
        return {'items': rows[:50], 'has_more': len(rows) > 50}
