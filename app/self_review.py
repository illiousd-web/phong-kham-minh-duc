"""Eligibility and audit for self-review of financial requests."""
import json

from fastapi import HTTPException
from pydantic import BaseModel


class FinancialReview(BaseModel):
    approve: bool
    reason: str | None = None


REASON_REQUIRED = 'Tự duyệt cần ghi lý do (ít nhất 10 ký tự)'
CONTROLLED_RETURN_ITEMS = '''SELECT 1 FROM medication_return_items ri
    JOIN dispensation_items di ON di.id=ri.dispensation_item_id
    JOIN medicines m ON m.id=di.medicine_id
    WHERE ri.return_id={return_id} AND m.controlled=1'''


def sole_manager(c, user):
    return 'manager' in user['roles'] and not c.execute('''SELECT 1 FROM users u
        JOIN user_roles ur ON ur.user_id=u.id
        WHERE u.active=1 AND ur.role='manager' AND u.id<>? LIMIT 1''', (user['id'],)).fetchone()


def mark_self_review(c, user, rows, proposer):
    eligible = sole_manager(c, user)
    for row in rows:
        row['can_self_review'] = (
            eligible and row['status'] == 'pending' and row[proposer] == user['id']
            and not row.get('has_controlled_items', False)
        )
    return rows


def self_review_reason(c, user, proposer, data, forbidden, *, controlled=False):
    if proposer != user['id']:
        return None
    if controlled:
        raise HTTPException(403, 'Thuốc kiểm soát đặc biệt không được tự duyệt')
    if not sole_manager(c, user):
        raise HTTPException(403, forbidden)
    reason = (data.reason or '').strip()
    if len(reason) < 10:
        raise HTTPException(422, REASON_REQUIRED)
    return reason


def audit_self_review(audit, c, user, kind, request_id, approve, reason):
    if reason is not None:
        details = json.dumps({
            'decision': 'approve' if approve else 'reject', 'reason': reason,
        }, ensure_ascii=False)
        audit(c, user, 'self_review', kind, request_id, details, details_limit=len(details))
