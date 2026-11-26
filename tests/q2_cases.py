"""Q2: quyền phải còn hiệu lực lúc ghi, kể cả khi đã xác thực trước khi bị thu hồi.

Dùng chung cho SQLite (tests/) và PostgreSQL (lan_tests/). Chỉ dữ liệu giả lập.
Phiên đã xác thực được mô phỏng bằng dependency override của `principal`, trả đúng bản sao
vai đọc trước giao dịch. Thay đổi quyền đã cam kết qua API quản trị trước lần gọi ghi.
"""
from contextlib import contextmanager
import secrets

DENIED = 'Không có quyền thực hiện chức năng'


def checked(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def new_account(admin, roles):
    username = 'q2_' + secrets.token_hex(5)
    uid = checked(admin.post('/api/accounts', json={'username': username, 'full_name': 'Nhân viên Q2 giả lập',
                                                    'password': secrets.token_urlsafe(18), 'roles': roles}), 201)['id']
    return {'id': uid, 'username': username, 'name': 'Nhân viên Q2 giả lập', 'roles': sorted(roles), 'token_hash': '0' * 64}


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
    cashier = new_account(admin, ['cashier'])
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
    other_admin = new_account(admin, ['admin'])
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
    with authenticated_before_change(other_admin):
        checked(anon.post(f'/api/visits/{reopened}/settlement-reopen', json={'reason': 'Mở lại hợp lệ giả lập'}))
        checked(anon.put(f"/api/accounts/{target['id']}", json={'full_name': 'Tên hợp lệ giả lập'}))
    assert count(db, 'SELECT COUNT(*) FROM visit_settlement_reopens WHERE visit_id=?', reopened) == 1
