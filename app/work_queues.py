"""Điều kiện SQL dùng chung cho hàng chờ và COUNT; lịch sử đọc riêng."""
OPEN_VISITS = "v.status NOT IN ('completed','cancelled')"
ACTIVE_ORDERS = "o.status IN ('requested','ordered','pending_review')"


def visit_scope(u):
    # Giữ thứ tự ưu tiên vai trò của /api/visits, kể cả người kiêm nhiệm.
    roles=set(u['roles'])
    if roles & {'manager','admin'}:
        return '', []
    if 'doctor' in roles:
        return 'v.doctor_id=?', [u['id']]
    if 'technician' in roles:
        return 'EXISTS(SELECT 1 FROM orders o WHERE o.visit_id=v.id)', []
    if roles & {'reception','cashier','pharmacy'}:
        return '', []
    return 'EXISTS(SELECT 1 FROM visit_nurses n WHERE n.visit_id=v.id AND n.nurse_id=? AND n.active=1)', [u['id']]


def visit_predicate(u, history=False):
    scope,args=visit_scope(u)
    status="v.status IN ('completed','cancelled')" if history else OPEN_VISITS
    return status+(' AND '+scope if scope else ''),args


def approval_predicate(alias, history=False):
    return alias+('.status<>\'pending\'' if history else ".status='pending'")


def history_limit(history):
    return ' LIMIT 100' if history else ''
