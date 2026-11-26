"""Q2: quyền phải còn hiệu lực lúc ghi, kể cả khi đã xác thực trước khi bị thu hồi.

Dùng chung cho SQLite (tests/) và PostgreSQL (lan_tests/). Chỉ dữ liệu giả lập.
Phiên đã xác thực được mô phỏng bằng dependency override của `principal`, trả đúng bản sao
vai đọc trước giao dịch. Trạng thái mới được lưu trước khi kiểm tra giao dịch ghi.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import secrets

DENIED = 'Không có quyền thực hiện chức năng'
INVALID_SESSION = 'Hết hạn phiên hoặc không hợp lệ'
REASON = 'Lý do kiểm thử Q2 giả lập'


def checked(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def account_input(roles):
    return {'username': 'q2_' + secrets.token_hex(5), 'full_name': 'Nhân viên Q2 giả lập',
            'password': secrets.token_urlsafe(18), 'roles': roles}


def new_account(admin, roles):
    body = account_input(roles)
    uid = checked(admin.post('/api/accounts', json=body), 201)['id']
    return {'id': uid, 'username': body['username'], 'name': body['full_name'], 'roles': sorted(roles)}


def open_test_session(db, user):
    from app.database import PGConnection

    token_hash = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=8)).isoformat()
    with db(True) as c:
        if isinstance(c, PGConnection):
            c.execute('INSERT INTO sessions(token_hash,user_id,expires_at,last_seen) VALUES(?,?,?,?)',
                      (token_hash, user['id'], expires, now.isoformat()))
        else:
            c.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',
                      (token_hash, user['id'], expires))
    return dict(user, token_hash=token_hash)


@contextmanager
def authenticated_before_change(snapshot):
    """Yêu cầu đã qua bước xác thực với vai cũ; giao dịch ghi bắt đầu sau khi quyền đổi."""
    from app.main import app, principal
    app.dependency_overrides[principal] = lambda: dict(snapshot, roles=list(snapshot['roles']))
    try:
        yield
    finally:
        app.dependency_overrides.pop(principal, None)


def owing_visit(clients, db, doctor_id, service_id, completed=False):
    pid = checked(clients['reception'].post('/api/patients', json={
        'full_name': 'Người bệnh Q2 giả lập', 'date_of_birth': '1990-01-01', 'sex': 'Nữ', 'phone': '0900000021'}), 201)['id']
    vid = checked(clients['reception'].post('/api/visits', json={
        'patient_id': pid, 'doctor_id': doctor_id, 'service_id': service_id}), 201)['id']
    if completed:
        with db(True) as c:
            c.execute("UPDATE visits SET status='completed' WHERE id=?", (vid,))
    return vid


def count(db, sql, *args):
    with db() as c:
        return c.execute(sql, args).fetchone()[0]


def set_account(admin, user, **change):
    checked(admin.put(f"/api/accounts/{user['id']}", json=change))


def check_write_rechecks_current_roles(clients, anon, db, doctor_id, service_id):
    admin = clients['admin']

    # 1. Thu tiền: bỏ vai thu ngân, rồi khóa tài khoản (vẫn giữ vai) — cả hai đều 403, không có phiếu thu.
    cashier = open_test_session(db, new_account(admin, ['cashier']))
    vid = owing_visit(clients, db, doctor_id, service_id)
    payment = {'visit_id': vid, 'amount': 1000, 'method': 'cash'}
    for change in ({'roles': ['reception']}, {'roles': ['cashier'], 'active': False}):
        set_account(admin, cashier, **change)
        with authenticated_before_change(cashier):
            response = anon.post('/api/payments', json={**payment, 'idempotency_key': secrets.token_hex(12)})
        assert response.status_code == 403 and response.json()['detail'] == DENIED, (change, response.text)
        assert count(db, 'SELECT COUNT(*) FROM payments WHERE visit_id=?', vid) == 0
    # Đối chứng: quyền còn hiệu lực thì cùng đường gọi vẫn thu được.
    set_account(admin, cashier, roles=['cashier'], active=True)
    cashier = open_test_session(db, cashier)
    with authenticated_before_change(cashier):
        checked(anon.post('/api/payments', json={**payment, 'idempotency_key': secrets.token_hex(12)}), 201)
    assert count(db, 'SELECT COUNT(*) FROM payments WHERE visit_id=?', vid) == 1

    # 2. Kết thúc tài chính (thu ngân): vai đã bị bỏ thì không kết thúc được.
    settled = owing_visit(clients, db, doctor_id, service_id, completed=True)
    due = checked(clients['cashier'].get(f'/api/visits/{settled}/settlement'))['billing']['due']
    checked(clients['cashier'].post('/api/payments', json={'visit_id': settled, 'amount': due, 'method': 'cash',
                                                           'idempotency_key': secrets.token_hex(12)}), 201)
    set_account(admin, cashier, roles=['reception'])
    with authenticated_before_change(cashier):
        response = anon.post(f'/api/visits/{settled}/settle')
    assert response.status_code == 403, response.text
    assert count(db, 'SELECT COUNT(*) FROM visit_settlements WHERE visit_id=?', settled) == 0

    # 3–5. Miễn thu, mở lại, sửa tài khoản: quản trị đã bị bỏ vai hoặc bị khóa.
    other_admin = open_test_session(db, new_account(admin, ['admin']))
    waived = owing_visit(clients, db, doctor_id, service_id, completed=True)
    reopened = owing_visit(clients, db, doctor_id, service_id, completed=True)
    checked(admin.post(f'/api/visits/{reopened}/settlement-waiver', json={'reason': 'Miễn thu giả lập Q2 có lý do'}))
    target = new_account(admin, ['reception'])
    before_target = count(db, "SELECT COUNT(*) FROM user_roles WHERE user_id=? AND role='reception'", target['id'])
    for change in ({'roles': ['reception']}, {'roles': ['admin'], 'active': False}):
        set_account(admin, other_admin, **change)
        with authenticated_before_change(other_admin):
            waiver = anon.post(f'/api/visits/{waived}/settlement-waiver', json={'reason': 'Miễn thu sau khi mất quyền'})
            reopen = anon.post(f'/api/visits/{reopened}/settlement-reopen', json={'reason': 'Mở lại sau khi mất quyền'})
            account = anon.put(f"/api/accounts/{target['id']}", json={'roles': ['admin'], 'full_name': 'Đổi tên trái phép'})
        for response in (waiver, reopen, account):
            assert response.status_code == 403 and response.json()['detail'] == DENIED, (change, response.text)
        assert count(db, 'SELECT COUNT(*) FROM visit_settlements WHERE visit_id=?', waived) == 0
        assert count(db, 'SELECT COUNT(*) FROM visit_settlement_reopens WHERE visit_id=?', reopened) == 0
        assert count(db, "SELECT COUNT(*) FROM user_roles WHERE user_id=? AND role='admin'", target['id']) == 0
        assert count(db, "SELECT COUNT(*) FROM user_roles WHERE user_id=? AND role='reception'", target['id']) == before_target
        assert count(db, 'SELECT COUNT(*) FROM users WHERE id=? AND full_name=?', target['id'], 'Đổi tên trái phép') == 0
    # Đối chứng: quản trị còn quyền thì cùng đường gọi vẫn ghi được.
    set_account(admin, other_admin, roles=['admin'], active=True)
    other_admin = open_test_session(db, other_admin)
    try:
        with authenticated_before_change(other_admin):
            checked(anon.post(f'/api/visits/{reopened}/settlement-reopen', json={'reason': 'Mở lại hợp lệ giả lập'}))
            checked(anon.put(f"/api/accounts/{target['id']}", json={'full_name': 'Tên hợp lệ giả lập'}))
        assert count(db, 'SELECT COUNT(*) FROM visit_settlement_reopens WHERE visit_id=?', reopened) == 1
    finally:
        set_account(admin, other_admin, active=False)


def read_state(db, queries):
    with db() as c:
        return [[dict(row) for row in c.execute(sql, params)] for sql, *params in queries]


def check_denied_write(db, actor, send, queries, status=403, detail=DENIED):
    queries = [*queries, ('SELECT COUNT(*) FROM audit_log WHERE user_id=?', actor['id'])]
    before = read_state(db, queries)
    try:
        with authenticated_before_change(actor):
            response = send()
        assert response.status_code == status, response.text
        assert response.json()['detail'] == detail
        assert read_state(db, queries) == before
    finally:
        with db(True) as c:
            c.execute('UPDATE users SET active=0 WHERE id=?', (actor['id'],))
            c.execute('DELETE FROM sessions WHERE user_id=?', (actor['id'],))


def remove_role(db, user, role):
    # Giữ nguyên phiên giả lập để kiểm riêng điều kiện còn quyền.
    with db(True) as c:
        assert c.execute('DELETE FROM user_roles WHERE user_id=? AND role=?', (user['id'], role)).rowcount == 1


def check_account_write_after_restriction(admin, anon, db, operation, restriction):
    actor = open_test_session(db, new_account(admin, ['admin', 'reception']))
    target = open_test_session(db, new_account(admin, ['reception']))
    if restriction == 'role':
        remove_role(db, actor, 'admin')
    else:
        # Giữ vai và phiên giả lập để kiểm riêng trạng thái hoạt động.
        with db(True) as c:
            c.execute('UPDATE users SET active=0 WHERE id=?', (actor['id'],))

    if operation == 'create':
        path, body = '/api/accounts', account_input(['reception'])
    else:
        path, body = f"/api/accounts/{target['id']}/password", {'password': secrets.token_urlsafe(18)}
    check_denied_write(db, actor, lambda: anon.post(path, json=body), [
        ('SELECT COUNT(*) FROM users',),
        ('SELECT COUNT(*) FROM user_roles',),
        ('SELECT salt,password_hash FROM users WHERE id=?', target['id']),
        ('SELECT token_hash FROM sessions WHERE user_id=? ORDER BY token_hash', target['id']),
    ])


def check_write_after_session_revoked(clients, anon, db, doctor_id, service_id, revocation):
    cashier = open_test_session(db, new_account(clients['admin'], ['cashier']))
    vid = owing_visit(clients, db, doctor_id, service_id)
    if revocation == 'logout':
        with authenticated_before_change(cashier):
            checked(anon.post('/api/logout'))
    else:
        checked(clients['admin'].post(f"/api/accounts/{cashier['id']}/password",
                                      json={'password': secrets.token_urlsafe(18)}))
    assert count(db, 'SELECT COUNT(*) FROM sessions WHERE token_hash=?', cashier['token_hash']) == 0
    # Một phiên mới của cùng người dùng không làm phiên đã xóa có hiệu lực trở lại.
    open_test_session(db, cashier)
    body = {'visit_id': vid, 'amount': 1000, 'method': 'cash', 'idempotency_key': secrets.token_hex(12)}
    check_denied_write(db, cashier, lambda: anon.post('/api/payments', json=body),
                       [('SELECT COUNT(*) FROM payments WHERE visit_id=?', vid)], 401, INVALID_SESSION)


VISIT_WRITE_CASES = ('reprice', 'reverse', 'cancel', 'cancel-controlled', 'manual-price')
CATALOG_WRITE_CASES = ('medicine-price', 'medicine-price-controlled', 'service-create', 'service-update')
STOCK_WRITE_CASES = ('lot-cost', 'receipt', 'receipt-cost', 'issue')


def check_visit_write_after_role_removed(clients, anon, db, doctor_id, service_id, operation):
    admin = clients['admin']
    tag = secrets.token_hex(6)
    if operation == 'manual-price':
        service_id = checked(admin.post('/api/catalog/services', json={
            'name': 'Dịch vụ nhập tay Q2 ' + tag, 'price': None, 'price_at_collection': True,
        }), 201)['id']
    vid = owing_visit(clients, db, doctor_id, service_id)
    cid = count(db, 'SELECT id FROM charges WHERE visit_id=?', vid)
    body = {'reason': REASON}
    if operation == 'reprice':
        path = f'/api/charges/{cid}/reprice'
        body.update(amount=10000, request_key=tag)
        queries = [('SELECT amount FROM effective_charges WHERE id=?', cid),
                   ('SELECT COUNT(*) FROM charge_price_history WHERE charge_id=?', cid)]
        role, extra_roles = 'manager', []
    elif operation == 'reverse':
        with db(True) as c:
            c.execute("""INSERT INTO adjustments(visit_id,kind,amount,reason,status,proposed_by,proposed_at)
                         VALUES(?,'discount',1000,?,'approved',?,?)""",
                      (vid, REASON, doctor_id, datetime.now(timezone.utc).isoformat()))
            aid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        path = f'/api/adjustments/{aid}/reverse'
        queries = [('SELECT COUNT(*) FROM adjustment_reversals WHERE adjustment_id=?', aid)]
        role, extra_roles = 'manager', []
    elif operation == 'manual-price':
        path = f'/api/charges/{cid}/manual-price'
        body = {'amount': 10000, 'description': REASON, 'request_key': tag}
        queries = [('SELECT amount FROM effective_charges WHERE id=?', cid),
                   ('SELECT COUNT(*) FROM manual_charge_prices WHERE charge_id=?', cid)]
        role, extra_roles = 'cashier', []
    else:
        path = f'/api/visits/{vid}/cancel'
        queries = [('SELECT status,version FROM visits WHERE id=?', vid),
                   ('SELECT COUNT(*) FROM visit_cancellations WHERE visit_id=?', vid),
                   ('SELECT COUNT(*) FROM charge_voids WHERE charge_id=?', cid)]
        role, extra_roles = 'manager', []
        if operation == 'cancel-controlled':
            with db(True) as c:
                c.execute('INSERT INTO medicines(name,base_unit,controlled) VALUES(?,?,1)', ('Thuốc Q2 ' + tag, 'viên'))
                mid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute('INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,created_at) VALUES(?,?,?,?)',
                          (vid, doctor_id, 'Thuốc giả lập', datetime.now(timezone.utc).isoformat()))
                rx = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute('INSERT INTO prescription_items(prescription_id,medicine_id,quantity) VALUES(?,?,1)', (rx, mid))
            queries.append(('SELECT status FROM prescriptions WHERE id=?', rx))
            role, extra_roles = 'controlled_reviewer', ['manager']
    actor = open_test_session(db, new_account(admin, [role, *extra_roles]))
    remove_role(db, actor, role)
    detail = 'Thiếu quyền đối soát lượt có thuốc kiểm soát' if extra_roles else DENIED
    check_denied_write(db, actor, lambda: anon.post(path, json=body), queries, detail=detail)


def check_catalog_write_after_role_removed(admin, anon, db, operation):
    tag = secrets.token_hex(6)
    body = {'name': 'Dịch vụ Q2 ' + tag, 'price': 12000}
    role, extra_roles, detail = 'manager', [], DENIED
    if operation == 'service-create':
        path, method = '/api/catalog/services', anon.post
        queries = [('SELECT COUNT(*) FROM service_catalog WHERE name=?', body['name']),
                   ('SELECT COUNT(*) FROM service_categories',)]
    elif operation == 'service-update':
        sid = checked(admin.post('/api/catalog/services', json=body), 201)['id']
        path, method = f'/api/catalog/services/{sid}', anon.put
        body['price'] = 14000
        queries = [('SELECT * FROM service_catalog WHERE id=?', sid),
                   ('SELECT * FROM service_categories WHERE service_id=?', sid)]
    else:
        controlled = operation == 'medicine-price-controlled'
        with db(True) as c:
            c.execute('INSERT INTO medicines(name,base_unit,controlled) VALUES(?,?,?)', ('Thuốc Q2 ' + tag, 'viên', int(controlled)))
            mid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        if controlled:
            role, extra_roles = 'controlled_reviewer', ['manager']
            detail = 'Giá thuốc kiểm soát cần quyền riêng và lý do'
        path, method = f'/api/medicines/{mid}/price', anon.put
        body = {'unit_price': 12000, 'reason': REASON}
        queries = [('SELECT * FROM medicine_prices WHERE medicine_id=?', mid)]
    actor = open_test_session(db, new_account(admin, [role, *extra_roles]))
    remove_role(db, actor, role)
    check_denied_write(db, actor, lambda: method(path, json=body), queries, detail=detail)


def check_stock_write_after_role_removed(admin, anon, db, operation):
    tag = secrets.token_hex(6)
    expiry = (date.today() + timedelta(days=90)).isoformat()
    mid = checked(admin.post('/api/catalog/medicines', json={'name': 'Thuốc kho Q2 ' + tag, 'base_unit': 'viên'}), 201)['id']
    with db(True) as c:
        c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(?,?,?,10)', (mid, tag, expiry))
        lid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    role, extra_roles, detail = 'pharmacy', [], DENIED
    if operation == 'lot-cost':
        role = 'stock_owner'
        method, path = anon.put, f'/api/stock/lots/{lid}/cost'
        body = {'unit_cost': 5000, 'reason': REASON}
    elif operation == 'issue':
        method, path = anon.post, '/api/stock/issues'
        body = {'medicine_id': mid, 'quantity': 1}
    else:
        method, path = anon.post, '/api/stock/receipts'
        body = {'medicine_id': mid, 'quantity': 1, 'lot_number': 'PN-' + tag, 'expiry_date': expiry}
        if operation == 'receipt-cost':
            body['unit_cost'] = 5000
            role, extra_roles = 'stock_owner', ['pharmacy']
            detail = 'Cần quyền Chủ kho thuốc để nhập giá'
    actor = open_test_session(db, new_account(admin, [role, *extra_roles]))
    remove_role(db, actor, role)
    check_denied_write(db, actor, lambda: method(path, json=body), [
        ('SELECT * FROM stock_lots WHERE medicine_id=? ORDER BY id', mid),
        ('SELECT COUNT(*) FROM stock_movements WHERE created_by=?', actor['id']),
        ('SELECT COUNT(*) FROM stock_receipts WHERE created_by=?', actor['id']),
        ('SELECT COUNT(*) FROM stock_issues WHERE created_by=?', actor['id']),
        ('SELECT * FROM stock_document_sequences ORDER BY kind,year',),
    ], detail=detail)


def check_manager_review_after_session_invalid(clients, anon, db, doctor_id, service_id, revocation):
    """Rà lại #66: cửa duyệt giảm phí của quản lý cũng phải kiểm phiên lúc ghi (bị xóa hoặc đã hết hạn)."""
    manager = open_test_session(db, new_account(clients['admin'], ['manager']))
    vid = owing_visit(clients, db, doctor_id, service_id)
    adj = checked(clients['cashier'].post('/api/adjustments', json={
        'visit_id': vid, 'kind': 'discount', 'amount': 1000, 'reason': REASON}), 201)['id']
    with db(True) as c:
        if revocation == 'deleted':
            c.execute('DELETE FROM sessions WHERE token_hash=?', (manager['token_hash'],))
        else:
            past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            c.execute('UPDATE sessions SET expires_at=? WHERE token_hash=?', (past, manager['token_hash']))
    check_denied_write(db, manager, lambda: anon.post(f'/api/adjustments/{adj}/review', json={'approve': True}),
                       [('SELECT status,reviewed_by FROM adjustments WHERE id=?', adj)], 401, INVALID_SESSION)
