"""Financial self-review through the normal review and reporting endpoints."""
from contextlib import closing
from datetime import datetime, timedelta
from io import BytesIO
import json
from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from app import self_review
from app.auth import CSRF_COOKIE
from app.database import db
from app.self_review import MANAGER_REQUIRED, RECENT_MANAGER_CHANGE, REASON_REQUIRED
from app.s2e_reports import in_period, revenue_report
from tests.test_s2e_settlements import (
    REASON, checked, clients as clients, key, payment, propose_medication_return,
    propose_price_change, visit as visit,
)

SELF_REASON = 'Đã kiểm chứng từ và đối soát số tiền'


@pytest.fixture
def manager_setup(clients):
    accounts = checked(clients['admin'].get('/api/accounts'))
    names = {'thungan', 'duoc', 'test_cashier', 'test_pharmacy'}
    actors = {a['username']: a for a in accounts if a['username'] in names}
    cashier = actors.get('thungan') or actors['test_cashier']
    pharmacy = actors.get('duoc') or actors['test_pharmacy']
    added = []
    deactivated = []
    removed_roles = []

    def configure(actor, second):
        others = [a for a in accounts if a['id'] != actor['id'] and 'manager' in a['roles']]
        active = [a['id'] for a in others if a['active']]
        with db(True) as c:
            if 'manager' not in actor['roles']:
                c.execute("INSERT INTO user_roles(user_id,role) VALUES(?,'manager')", (actor['id'],))
                added.append(actor['id'])
            if second:
                for user_id in active[1:]:
                    c.execute('UPDATE users SET active=0 WHERE id=?', (user_id,))
                    deactivated.append(user_id)
            else:
                for account in others:
                    c.execute("DELETE FROM user_roles WHERE user_id=? AND role='manager'", (account['id'],))
                    removed_roles.append(account['id'])
        return active[0] if second else None

    yield cashier, pharmacy, configure
    with db(True) as c:
        for user_id in added:
            c.execute("DELETE FROM user_roles WHERE user_id=? AND role='manager'", (user_id,))
        for user_id in removed_roles:
            c.execute("INSERT INTO user_roles(user_id,role) VALUES(?,'manager')", (user_id,))
        for user_id in deactivated:
            c.execute('UPDATE users SET active=1 WHERE id=?', (user_id,))


def submit_request(clients, visit, kind):
    cashier, manager, doctor, pharmacy = (
        clients[role] for role in ('cashier', 'manager', 'doctor', 'pharmacy'))
    if kind == 'return':
        request = propose_medication_return(doctor, pharmacy, manager, visit)[-1]
        return '/api/medication-returns', request, 1000
    if kind == 'price':
        with db(True) as c:
            c.execute("INSERT INTO charges(visit_id,label,created_at) VALUES(?,'Dịch vụ thử','2026-01-01')", (visit,))
            charge = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        return '/api/manual-price-requests', propose_price_change(cashier, charge)[-1], 6000
    payload = {'visit_id': visit, 'kind': kind, 'amount': 500, 'reason': REASON}
    if kind == 'refund':
        paid = checked(cashier.post('/api/payments', json=payment(visit, 150500, prepayment=True)), 201)
        payload['payment_id'] = paid['id']
    return '/api/adjustments', checked(cashier.post('/api/adjustments', json=payload), 201)['id'], 500


@pytest.mark.parametrize(('kind', 'label'), [
    ('discount', 'Giảm phí'), ('refund', 'Hoàn tiền'), ('price', 'Sửa giá'), ('return', 'Trả thuốc'),
])
@pytest.mark.parametrize('scenario', ['approve-after-admin-lock', 'approve-as-sole', 'reject-as-sole'])
def test_financial_self_review(clients, visit, manager_setup, kind, label, scenario):
    approve = scenario != 'reject-as-sole'
    endpoint, request, amount = submit_request(clients, visit, kind)
    cashier, pharmacy, configure = manager_setup
    user, actor = (pharmacy, clients['pharmacy']) if kind == 'return' else (cashier, clients['cashier'])
    other = configure(user, second=scenario == 'approve-after-admin-lock')
    path = f'{endpoint}/{request}/review'

    def eligible():
        return next(row['can_self_review'] for row in checked(actor.get(endpoint)) if row['id'] == request)

    if other is not None:
        assert not eligible()
        checked(actor.post(path, json={'approve': True, 'reason': SELF_REASON}), 403)
        checked(clients['admin'].put(f'/api/accounts/{other}', json={'active': False}))
        try:
            assert eligible()
            checked(actor.post(path, json={'approve': True}), 422, REASON_REQUIRED)
            checked(actor.post(path, json={'approve': True, 'reason': '   quá ngắn  '}), 422, REASON_REQUIRED)
            assert checked(actor.post(path, json={'approve': True, 'reason': SELF_REASON}))['status'] == 'approved'
        finally:
            checked(clients['admin'].put(f'/api/accounts/{other}', json={'active': True}))
    else:
        assert eligible()
        checked(actor.post(path, json={'approve': approve}), 422, REASON_REQUIRED)
        response = actor.post(path, json={'approve': approve, 'reason': 'ả' * 501})
        assert response.status_code == 422
        assert [(err['loc'], err['type']) for err in response.json()['detail']] == [
            (['body', 'reason'], 'string_too_long')]
        result = checked(actor.post(path, json={'approve': approve, 'reason': '  '+SELF_REASON+'  '}))
        assert result['status'] == ('approved' if approve else 'rejected')

    with db() as c:
        audit = c.execute("""SELECT user_id,details,created_at FROM audit_log WHERE event='self_review'
            AND object_type=? AND object_id=?""", (kind, request)).fetchall()
        assert len(audit) == 1 and audit[0]['user_id'] == user['id']
        assert json.loads(audit[0]['details']) == {
            'decision': 'approve' if approve else 'reject', 'reason': SELF_REASON,
        }
    from app.s2e_reports import day
    stamp = day(audit[0]['created_at'])
    params = {'date_from': stamp, 'date_to': stamp}
    report = checked(actor.get('/api/reports/corrections', params=params))
    assert any(row['type'] == label and row['amount'] == amount and row['actor'] == user['full_name']
               and row['reason'] == SELF_REASON and row['decision'] == ('Duyệt' if approve else 'Từ chối')
               for row in report['self_reviews'])
    response = actor.get('/api/reports/corrections/export', params=params)
    assert response.status_code == 200
    with BytesIO(response.content) as data:
        book = load_workbook(data, read_only=True)
        assert any(row[0] == label and row[1] == amount and row[4] == SELF_REASON
                   for row in book['Tự duyệt'].values)
        book.close()


@pytest.mark.parametrize('kind', ['discount', 'refund', 'price', 'return'])
@pytest.mark.parametrize('change', ['lock', 'remove-manager'])
def test_self_review_after_own_manager_change(clients, visit, manager_setup, monkeypatch, kind, change):
    admin = clients['admin']
    role = 'pharmacy' if kind == 'return' else 'cashier'
    username, password = 'selfreview_' + key()[:16], 'Gia-lap-' + key()
    roles = ['admin', 'manager', role]
    uid = checked(admin.post('/api/accounts', json={
        'username': username, 'password': password, 'full_name': 'Quản lý kiêm nhiệm giả lập',
        'roles': roles,
    }), 201)['id']
    _, _, configure = manager_setup
    other = configure({'id': uid, 'roles': roles}, second=True)
    account_path = f'/api/accounts/{other}'
    original = next(row for row in checked(admin.get('/api/accounts')) if row['id'] == other)
    headers = {name: admin.headers[name] for name in ('Origin', 'X-Clinic-Request') if name in admin.headers}
    host = '192.168.10.20' if 'Origin' in headers else '127.0.0.1'
    try:
        with closing(TestClient(admin.app, base_url=str(admin.base_url), client=(host, 1234),
                                headers=headers)) as actor:
            login = checked(actor.post('/api/login', json={'username': username, 'password': password}))
            if 'access_token' in login:
                actor.headers['Authorization'] = 'Bearer ' + login['access_token']
            else:
                actor.headers['X-CSRF-Token'] = actor.cookies[CSRF_COOKIE]
            endpoint, request_id, _ = submit_request({**clients, role: actor}, visit, kind)
            review_path = f'{endpoint}/{request_id}/review'
            remaining_roles = [role for role in original['roles'] if role != 'manager'] or ['cashier']
            update = {'active': False} if change == 'lock' else {'roles': remaining_roles}
            checked(actor.put(account_path, json=update))
            with db() as c:
                audit = c.execute("""SELECT created_at,details FROM audit_log
                    WHERE event='account_updated' AND object_type='user' AND object_id=? AND user_id=?""",
                                  (other, uid)).fetchall()
            assert len(audit) == 1
            details = json.loads(audit[0]['details'])
            assert details['old'] == {'active': True, 'roles': original['roles']}
            assert details['new'] == {
                'active': change != 'lock',
                'roles': original['roles'] if change == 'lock' else sorted(remaining_roles),
            }
            own = next(row for row in checked(actor.get(endpoint)) if row['id'] == request_id)
            assert not own['can_self_review']
            for approve in (True, False):
                checked(actor.post(review_path, json={'approve': approve, 'reason': SELF_REASON}),
                        403, RECENT_MANAGER_CHANGE)
            # Move only the cooldown clock. The account event remains append-only.
            expiry = datetime.fromisoformat(audit[0]['created_at']) + timedelta(days=7)
            almost_expired = expiry - timedelta(seconds=1)
            with monkeypatch.context() as clock:
                clock.setattr(self_review, 'datetime', SimpleNamespace(now=lambda tz: almost_expired))
                checked(actor.post(review_path, json={'approve': True, 'reason': SELF_REASON}),
                        403, RECENT_MANAGER_CHANGE)
                clock.setattr(self_review, 'datetime', SimpleNamespace(now=lambda tz: expiry))
                own = next(row for row in checked(actor.get(endpoint)) if row['id'] == request_id)
                assert own['can_self_review']
                assert checked(actor.post(review_path, json={'approve': True, 'reason': SELF_REASON}))['status'] == 'approved'
    finally:
        checked(admin.put(account_path, json={'active': True, 'roles': original['roles']}))
        checked(admin.put(f'/api/accounts/{uid}', json={'active': False}))


@pytest.mark.parametrize(('kind', 'table'), [
    ('discount', 'adjustments'), ('price', 'manual_price_requests'), ('return', 'medication_returns'),
])
@pytest.mark.parametrize('revocation', [{'active': False}, {'roles': ['cashier']}], ids=['locked', 'role-removed'])
def test_financial_review_rechecks_manager_after_authentication(clients, visit, monkeypatch, kind, table, revocation):
    from app import main

    admin, reviewer = clients['admin'], clients['manager']
    user = checked(reviewer.get('/api/me'))
    endpoint, request_id, _ = submit_request(clients, visit, kind)
    review_path = f'{endpoint}/{request_id}/review'
    account_path = f"/api/accounts/{user['id']}"

    def revoke_after_auth(request: Request):
        principal = main.principal(request, request.headers.get('Authorization'))
        if request.url.path == review_path:
            assert principal['id'] == user['id'] and 'manager' in principal['roles']
            checked(admin.put(account_path, json=revocation))
        return principal

    try:
        with monkeypatch.context() as auth:
            auth.setitem(main.app.dependency_overrides, main.principal, revoke_after_auth)
            checked(reviewer.post(review_path, json={'approve': True}), 403, MANAGER_REQUIRED)
        with db() as c:
            row = c.execute(f'SELECT status,reviewed_by FROM {table} WHERE id=?', (request_id,)).fetchone()
            assert row['status'] == 'pending' and row['reviewed_by'] is None
    finally:
        checked(admin.put(account_path, json={'active': True, 'roles': user['roles']}))


def test_controlled_return_cannot_be_self_reviewed(clients, visit, manager_setup):
    endpoint, request, _ = submit_request(clients, visit, 'return')
    _, pharmacy, configure = manager_setup
    configure(pharmacy, second=False)
    with db(True) as c:
        c.execute("""UPDATE medicines SET controlled=1 WHERE id IN (
            SELECT di.medicine_id FROM dispensation_items di
            JOIN medication_return_items ri ON ri.dispensation_item_id=di.id WHERE ri.return_id=?)""", (request,))
    actor = clients['pharmacy']
    row = next(row for row in checked(actor.get(endpoint)) if row['id'] == request)
    assert not row['can_self_review']
    for approve in (True, False):
        checked(actor.post(f'{endpoint}/{request}/review', json={'approve': approve, 'reason': SELF_REASON}),
                403, 'Thuốc kiểm soát đặc biệt không được tự duyệt')


def test_waiver_sql_matches_previous_period_filter(clients, visit):
    from tests.test_s2e_settlements import complete_visit
    complete_visit(clients['doctor'], visit)
    with db(True) as c:
        admin = c.execute('SELECT id FROM users WHERE username IN (?,?)', ('quantri', 'test_admin')).fetchone()[0]
        previous = None
        for stamp in ('2026-03-31T16:59:59+00:00', '2026-03-31T17:00:00+00:00',
                      '2026-04-30T16:59:59+00:00', '2026-04-30T17:00:00+00:00'):
            if previous is not None:
                c.execute('INSERT INTO visit_settlement_reopens VALUES(?,?,?,?,?)',
                          (previous, visit, admin, stamp, REASON))
            c.execute("""INSERT INTO visit_settlements(visit_id,previous_settlement_id,actor_id,created_at,
                charged,paid,due,refund_due,kind,waived_amount,reason,approved_by)
                VALUES(?,?,?,?,150000,0,150000,0,'mien_thu',150000,?,?)""",
                      (visit, previous, admin, stamp, REASON, admin))
            previous = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        waivers = c.execute("""SELECT w.waived_amount,w.created_at,s.id IS NOT NULL AS active
            FROM visit_settlements w LEFT JOIN active_visit_settlements s ON s.id=w.id
            WHERE w.kind='mien_thu'""").fetchall()
        for start, end in (('2026-03-01', '2026-03-31'), ('2026-04-01', '2026-04-30'),
                           ('2026-05-01', '2026-05-31'), ('2026-01-01', '2026-12-31')):
            old = [row for row in waivers if in_period(row['created_at'], start, end)]
            totals = revenue_report(c, start, end)['totals']
            assert (totals['waived_amount'], totals['waived_visits'], totals['waiver_approval_count']) == (
                sum(row['waived_amount'] for row in old if row['active']),
                sum(1 for row in old if row['active']), len(old))
