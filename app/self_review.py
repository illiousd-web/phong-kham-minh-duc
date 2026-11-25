"""Eligibility and audit for self-review of financial requests."""
from datetime import datetime, timedelta, timezone
import json

from fastapi import HTTPException
from pydantic import BaseModel, Field


class FinancialReview(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


REASON_REQUIRED = 'Tự duyệt cần ghi lý do (ít nhất 10 ký tự)'
RECENT_MANAGER_CHANGE = 'Không được tự duyệt: bạn vừa khóa hoặc bỏ quyền quản lý của người khác trong 7 ngày qua.'
MANAGER_REQUIRED = 'Không có quyền thực hiện chức năng'
CONTROLLED_RETURN_ITEMS = '''SELECT 1 FROM medication_return_items ri
    JOIN dispensation_items di ON di.id=ri.dispensation_item_id
    JOIN medicines m ON m.id=di.medicine_id
    WHERE ri.return_id={return_id} AND m.controlled=1'''


def active_account_roles(c, user_id):
    return {row[0] for row in c.execute('''SELECT ur.role FROM users u
        JOIN user_roles ur ON ur.user_id=u.id WHERE u.id=? AND u.active=1''', (user_id,))}


def require_current_manager(c, user_id):
    roles = active_account_roles(c, user_id)
    if 'manager' not in roles:
        raise HTTPException(403, MANAGER_REQUIRED)
    return roles


def recently_restricted_manager(c, user_id):
    # Account audit timestamps are written as UTC ISO text to second precision.
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=7)).isoformat(timespec='seconds')
    for row in c.execute("""SELECT details FROM audit_log
        WHERE event='account_updated' AND object_type='user' AND user_id=? AND object_id<>?
        AND created_at>? AND created_at<=?""", (user_id, user_id, cutoff, now.isoformat(timespec='seconds'))):
        try:
            change = json.loads(row['details'])
            old, new = change['old'], change['new']
            was_manager = 'manager' in old['roles']
            is_manager = 'manager' in new['roles']
            locked = old['active'] is True and new['active'] is False
        except (ValueError, KeyError, TypeError):
            # Older account events have a text summary without before/after state.
            continue
        if (locked and (was_manager or is_manager)) or (was_manager and not is_manager):
            return True
    return False


def self_review_denial(c, user_id, forbidden):
    if recently_restricted_manager(c, user_id):
        return RECENT_MANAGER_CHANGE
    if c.execute('''SELECT 1 FROM users u
        JOIN user_roles ur ON ur.user_id=u.id
        WHERE u.active=1 AND ur.role='manager' AND u.id<>? LIMIT 1''', (user_id,)).fetchone():
        return forbidden
    return None


def sole_manager(c, user):
    user_id = user['id']
    return ('manager' in active_account_roles(c, user_id)
            and self_review_denial(c, user_id, MANAGER_REQUIRED) is None)


def mark_self_review(c, user, rows, proposer):
    eligible = None
    for row in rows:
        candidate = (row['status'] == 'pending' and row[proposer] == user['id']
                     and not row.get('has_controlled_items', False))
        if candidate and eligible is None:
            eligible = sole_manager(c, user)
        row['can_self_review'] = candidate and eligible
    return rows


def self_review_reason(c, user, proposer, data, forbidden, *, controlled=False):
    if proposer != user['id']:
        return None
    if controlled:
        raise HTTPException(403, 'Thuốc kiểm soát đặc biệt không được tự duyệt')
    denial = self_review_denial(c, user['id'], forbidden)
    if denial:
        raise HTTPException(403, denial)
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
