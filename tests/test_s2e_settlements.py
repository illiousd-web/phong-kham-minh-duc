"""Financial settlement contract. The LAN suite runs the same cases on PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
import secrets
import sqlite3

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from app import database
from app.domain import invoice
from app.labels import local_day

REASON = 'Quyết định miễn thu cho lượt giả lập'
REOPEN = 'Đối soát lại'
CLOSED = 'Lượt đã kết thúc tài chính'


def key():
    return secrets.token_hex(16)


def checked(response, status=200, detail=None):
    assert response.status_code == status, response.text
    if detail:
        assert response.json()['detail'] == detail
    return response.json()


def record_clinical(doctor, visit):
    return checked(doctor.put(f'/api/visits/{visit}/clinical',
                              json={'version': 0, 'diagnosis': 'Chẩn đoán giả lập'}))['version']


def complete_visit(doctor, visit, version=None):
    if version is None:
        version = record_clinical(doctor, visit)
    return checked(doctor.post(f'/api/visits/{visit}/complete', json={'version': version}))


def payment(visit, amount, **extra):
    return {'visit_id': visit, 'amount': amount, 'method': 'cash', 'idempotency_key': key(), **extra}


def test_settle_records_an_immutable_invoice_and_rejects_concurrent_duplicate(clients, visit):
    prefix = f'/api/visits/{visit}'
    cashier = clients['cashier']
    completed = complete_visit(clients['doctor'], visit)
    record = payment(visit, 150000)
    paid = checked(cashier.post('/api/payments', json=record), 201)
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda actor: actor.post(prefix+'/settle'),
                                 [cashier, clients['admin']]))
    assert sorted(result.status_code for result in attempts) == [200, 409]
    denied = next(r for r in attempts if r.status_code == 409)
    assert denied.json()['detail'] == CLOSED
    closure = next(r.json() for r in attempts if r.status_code == 200)
    assert closure['kind'] == 'du_thu' and closure['waived_amount'] == 0
    state = checked(cashier.get(prefix+'/settlement'))
    assert state['financial_settlement'] == closure
    assert state['clinical_status'] == 'completed' and state['version'] == completed['version']
    assert checked(cashier.post('/api/payments', json=record), 201)['id'] == paid['id']
    assert visit not in {row['visit_id'] for row in checked(cashier.get('/api/dues'))}
    with database.db() as c:
        row = dict(c.execute('SELECT * FROM visit_settlements WHERE visit_id=?', (visit,)).fetchone())
        assert (row['charged'], row['paid'], row['due'], row['refund_due']) == (150000, 150000, 0, 0)
        assert row['approved_by'] is None and row['reason'] is None
        event = c.execute("SELECT user_id FROM audit_log WHERE event='visit_settled' AND object_id=?", (visit,)).fetchall()
        assert [item['user_id'] for item in event] == [row['actor_id']]


@pytest.mark.parametrize(('state', 'message'), [
    ('clinical', 'Bác sĩ chưa khóa phiếu'),
    ('due', 'Còn phải thu 150.000 đồng'),
    ('refund', 'Còn phải hoàn 10.000 đồng'),
    ('unpriced', 'Còn khoản chưa có giá'),
])
def test_settlement_preconditions(clients, visit, state, message):
    prefix = f'/api/visits/{visit}'
    cashier, admin = clients['cashier'], clients['admin']
    if state == 'refund':
        checked(cashier.post('/api/payments', json=payment(visit, 160000, prepayment=True)), 201)
    if state == 'unpriced':
        with database.db(True) as c:
            c.execute("INSERT INTO charges(visit_id,label,created_at) VALUES(?,'Khoản giả lập chưa giá',?)",
                      (visit, '2026-10-15T00:00:00+00:00'))
    if state != 'clinical':
        complete_visit(clients['doctor'], visit)
    checked(cashier.post(prefix+'/settle'), 409, message)
    if state != 'due':
        checked(admin.post(prefix+'/settlement-waiver', json={'reason': REASON}), 409, message)


def test_waiver_requires_admin_and_an_independent_approver(clients, visit):
    prefix = f'/api/visits/{visit}'
    cashier, admin = clients['cashier'], clients['admin']
    complete_visit(clients['doctor'], visit)
    for actor in (cashier, clients['manager']):
        for endpoint in ('settlement-waiver', 'settlement-reopen'):
            checked(actor.post(prefix+'/'+endpoint, json={'reason': REASON}), 403)
    checked(admin.post(prefix+'/settlement-waiver', json={'reason': '   ngắn  '}), 422,
            'Lý do miễn thu cần ít nhất 10 ký tự')

    username, password = 's2e3a_'+key(), 'Gia-lap-'+key()
    account = checked(admin.post('/api/accounts', json={'username': username, 'password': password,
                      'full_name': 'Quản trị kiêm thu ngân giả lập', 'roles': ['admin', 'cashier']}), 201)
    with TestClient(cashier.app, base_url=str(cashier.base_url), client=('127.0.0.1', 1234)) as both:
        if 'Origin' in cashier.headers:
            both.headers['Origin'] = cashier.headers['Origin']
        both.headers['X-Clinic-Request'] = '1'
        user = checked(both.post('/api/login', json={'username': username, 'password': password}))
        if 'access_token' in user:
            both.headers['Authorization'] = 'Bearer '+user['access_token']
        else:
            both.headers['X-CSRF-Token'] = both.cookies['__Host-clinic-csrf']
        checked(both.post('/api/payments', json=payment(visit, 30000)), 201)
        checked(both.post(prefix+'/settlement-waiver', json={'reason': REASON}), 403,
                'Người đã thu tiền lượt này không được duyệt miễn thu')
    result = checked(admin.post(prefix+'/settlement-waiver', json={'reason': '  '+REASON+'  '}))
    assert (result['kind'], result['waived_amount']) == ('mien_thu', 120000)
    with database.db() as c:
        row = dict(c.execute('SELECT * FROM visit_settlements WHERE id=?', (result['id'],)).fetchone())
        assert row['reason'] == REASON
        assert row['actor_id'] == row['approved_by'] != account['id']
        assert (row['charged'], row['paid'], row['due'], row['refund_due']) == (150000, 30000, 120000, 0)
        assert invoice(c, visit)['due'] == 120000



def test_fully_paid_waiver_rejected_and_not_reported(clients, visit):
    cashier, admin, manager = (clients[name] for name in ('cashier', 'admin', 'manager'))
    complete_visit(clients['doctor'], visit)
    checked(cashier.post('/api/payments', json=payment(visit, 150000)), 201)
    with database.db() as c:
        day = local_day(c.execute('SELECT created_at FROM visits WHERE id=?', (visit,)).fetchone()[0])[:10]
    params = {'date_from': day, 'date_to': day}
    before = checked(manager.get('/api/reports/revenue', params=params))['totals']
    checked(admin.post(f'/api/visits/{visit}/settlement-waiver', json={'reason': REASON}), 409,
            'Lượt khám đã thu đủ, không có khoản để miễn thu. Dùng Kết thúc thường.')
    with database.db() as c:
        assert c.execute('SELECT COUNT(*) FROM visit_settlements WHERE visit_id=?', (visit,)).fetchone()[0] == 0
    after = checked(manager.get('/api/reports/revenue', params=params))['totals']
    for field in ('waived_amount', 'waived_visits', 'waiver_approval_count'):
        assert after[field] == before[field]


def test_waiver_with_fifty_thousand_due(clients, visit):
    complete_visit(clients['doctor'], visit)
    checked(clients['cashier'].post('/api/payments', json=payment(visit, 100000)), 201)
    result = checked(clients['admin'].post(f'/api/visits/{visit}/settlement-waiver', json={'reason': REASON}))
    assert (result['kind'], result['waived_amount']) == ('mien_thu', 50000)


def test_fully_paid_pending_refund_blocks_closure(clients, visit):
    cashier = clients['cashier']
    complete_visit(clients['doctor'], visit)
    pay_id = checked(cashier.post('/api/payments', json=payment(visit, 150000)), 201)['id']
    checked(cashier.post('/api/adjustments', json={'visit_id': visit, 'kind': 'refund',
            'payment_id': pay_id, 'amount': 10000, 'reason': REASON}), 201)
    response = cashier.post(f'/api/visits/{visit}/settle')
    assert response.status_code == 409
    assert 'hoàn tiền 10.000 đ' in response.json()['detail']
    with database.db() as c:
        assert c.execute('SELECT COUNT(*) FROM visit_settlements WHERE visit_id=?', (visit,)).fetchone()[0] == 0


def test_concurrent_request_and_closure_cannot_both_succeed(clients, visit):
    cashier, admin = clients['cashier'], clients['admin']
    complete_visit(clients['doctor'], visit)
    pay_id = checked(cashier.post('/api/payments', json=payment(visit, 150000)), 201)['id']
    proposal = {'visit_id': visit, 'kind': 'refund', 'payment_id': pay_id,
                'amount': 10000, 'reason': REASON}
    with ThreadPoolExecutor(max_workers=2) as pool:
        request = pool.submit(cashier.post, '/api/adjustments', json=proposal)
        closure = pool.submit(admin.post, f'/api/visits/{visit}/settle')
        statuses = (request.result().status_code, closure.result().status_code)
    assert statuses in ((201, 409), (409, 200))
    with database.db() as c:
        pending = c.execute("SELECT COUNT(*) FROM adjustments WHERE visit_id=? AND status='pending'", (visit,)).fetchone()[0]
        closed = c.execute('SELECT COUNT(*) FROM visit_settlements WHERE visit_id=?', (visit,)).fetchone()[0]
        assert (pending, closed) in ((1, 0), (0, 1))


@pytest.mark.parametrize('approve', [True, False])
def test_resolved_request_allows_closure(clients, visit, approve):
    cashier, manager = clients['cashier'], clients['manager']
    request = checked(cashier.post('/api/adjustments', json={'visit_id': visit, 'kind': 'discount',
                      'amount': 10000, 'reason': REASON}), 201)['id']
    checked(manager.post(f'/api/adjustments/{request}/review', json={'approve': approve}))
    complete_visit(clients['doctor'], visit)
    checked(cashier.post('/api/payments', json=payment(visit, 140000 if approve else 150000)), 201)
    checked(cashier.post(f'/api/visits/{visit}/settle'))

def test_reopen_restores_queue_and_allows_new_payment_and_a_second_closure(clients, visit):
    prefix = f'/api/visits/{visit}'
    cashier, admin, manager = (clients[name] for name in ('cashier','admin','manager'))
    # An old visit belongs to the queues even after it has been fully paid.
    with database.db(True) as c:
        c.execute("UPDATE visits SET created_at='2026-01-01T00:00:00+00:00' WHERE id=?", (visit,))
    completed = complete_visit(clients['doctor'], visit)
    checked(cashier.post('/api/payments', json=payment(visit, 50000)), 201)
    first = checked(admin.post(prefix+'/settlement-waiver', json={'reason': REASON}))
    assert visit not in {row['visit_id'] for row in checked(manager.get('/api/financial-settlements'))['items']}
    assert visit in {row['visit_id'] for row in checked(admin.get('/api/financial-settlements?closed=true'))['items']}
    checked(manager.get('/api/financial-settlements?closed=true'), 403)
    checked(clients['reception'].get('/api/financial-settlements'), 403)
    checked(admin.post(prefix+'/settlement-reopen', json={'reason': '  '}), 422, 'Cần nhập lý do mở lại')
    reopened = checked(admin.post(prefix+'/settlement-reopen', json={'reason': REOPEN}))
    assert reopened['settlement_id'] == first['id']
    checked(admin.post(prefix+'/settlement-reopen', json={'reason': REOPEN}), 409, 'Lượt chưa kết thúc tài chính')
    assert visit in {row['visit_id'] for row in checked(manager.get('/api/financial-settlements'))['items']}
    checked(cashier.post('/api/payments', json=payment(visit, 100000)), 201)
    row = next(row for row in checked(cashier.get('/api/dues')) if row['visit_id'] == visit)
    assert row['financial_pending'] == 1 and row['charged'] == row['paid']
    second = checked(admin.post(prefix+'/settle'))
    assert second['id'] != first['id']
    assert checked(admin.get(prefix+'/settlement'))['version'] == completed['version']
    with database.db() as c:
        rows = c.execute('SELECT * FROM visit_settlements WHERE visit_id=? ORDER BY id', (visit,)).fetchall()
        assert [(r['kind'], r['waived_amount'], r['previous_settlement_id']) for r in rows] == [
            ('mien_thu', 100000, None), ('du_thu', 0, first['id'])]
        row = c.execute('SELECT * FROM visit_settlement_reopens WHERE settlement_id=?', (first['id'],)).fetchone()
        assert row['reason'] == REOPEN and row['actor_id'] == rows[0]['actor_id']
        events = c.execute("SELECT event FROM audit_log WHERE object_type='visit' AND object_id=? ORDER BY id",
                           (visit,)).fetchall()
        assert [r['event'] for r in events if r['event'].startswith('visit_settle')] == [
            'visit_settlement_waived', 'visit_settlement_reopened', 'visit_settled']


def test_waiver_is_reported_without_becoming_payment(clients, visit):
    prefix = f'/api/visits/{visit}'
    cashier, admin, manager = (clients[name] for name in ('cashier','admin','manager'))
    complete_visit(clients['doctor'], visit)
    checked(cashier.post('/api/payments', json=payment(visit, 20000)), 201)
    with database.db() as c:
        day = local_day(c.execute('SELECT created_at FROM visits WHERE id=?', (visit,)).fetchone()[0])[:10]
    params = {'date_from': day, 'date_to': day}
    report = '/api/reports/revenue'
    before = checked(manager.get(report, params=params))
    assert visit in {row['visit_id'] for row in before['unpaid_visits']}
    closed = checked(admin.post(prefix+'/settlement-waiver', json={'reason': REASON}))
    assert local_day(closed['created_at'])[:10] == day
    after = checked(manager.get(report, params=params))
    assert after['totals']['paid'] == before['totals']['paid']
    assert after['totals']['revenue'] == before['totals']['revenue']
    assert after['totals']['known_due'] == before['totals']['known_due'] - 130000
    assert after['totals']['waived_amount'] == before['totals']['waived_amount'] + 130000
    assert after['totals']['waived_visits'] == before['totals']['waived_visits'] + 1
    assert after['totals']['waiver_approval_count'] == before['totals']['waiver_approval_count'] + 1
    assert visit not in {row['visit_id'] for row in after['unpaid_visits']}
    response = admin.get(report+'/export', params=params)
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content), read_only=True)
    rows = list(book['Tổng kỳ'].values)
    columns = rows[-2]
    assert rows[-1][columns.index('Miễn thu đã duyệt')] == after['totals']['waived_amount']
    assert rows[-1][columns.index('Số lượt miễn thu')] == after['totals']['waived_visits']
    assert rows[-1][columns.index('Số lần duyệt miễn thu (kể cả đã mở lại)')] == after['totals']['waiver_approval_count']
    book.close()
    checked(admin.post(prefix+'/settlement-reopen', json={'reason': REOPEN}))
    reopened = checked(manager.get(report, params=params))
    assert reopened['totals']['waived_amount'] == before['totals']['waived_amount'] == after['totals']['waived_amount'] - 130000
    assert reopened['totals']['waived_visits'] == before['totals']['waived_visits']
    assert reopened['totals']['waiver_approval_count'] == after['totals']['waiver_approval_count']
    assert reopened['totals']['known_due'] == before['totals']['known_due']
    checked(cashier.post('/api/payments', json=payment(visit, 10000)), 201)
    checked(admin.post(prefix+'/settlement-waiver', json={'reason': REASON}))
    waived_again = checked(manager.get(report, params=params))['totals']
    assert waived_again['waived_amount'] == before['totals']['waived_amount'] + 120000
    assert waived_again['waived_visits'] == before['totals']['waived_visits'] + 1
    assert waived_again['waiver_approval_count'] == before['totals']['waiver_approval_count'] + 2


def test_overview_excludes_active_waiver_and_restores_outstanding_after_reopen(clients, visit):
    prefix = f'/api/visits/{visit}'
    cashier, admin, manager = (clients[name] for name in ('cashier', 'admin', 'manager'))
    complete_visit(clients['doctor'], visit)
    checked(cashier.post('/api/payments', json=payment(visit, 20000)), 201)
    before = checked(manager.get('/api/overview'))
    checked(admin.post(prefix+'/settlement-waiver', json={'reason': REASON}))
    after = checked(manager.get('/api/overview'))
    assert (after['charged'], after['paid'], after['unpriced_count']) == (
        before['charged'], before['paid'], before['unpriced_count'])
    assert after['known_outstanding'] == before['known_outstanding'] - 130000
    assert after['outstanding'] == (None if before['unpriced_count'] else after['known_outstanding'])
    checked(admin.post(prefix+'/settlement-reopen', json={'reason': REOPEN}))
    reopened = checked(manager.get('/api/overview'))
    assert reopened['known_outstanding'] == before['known_outstanding']
    assert reopened['outstanding'] == before['outstanding']


def propose_price_change(cashier, manual_charge):
    price = {'amount': 5000, 'description': 'Thủ thuật giả lập', 'request_key': key()}
    checked(cashier.post(f'/api/charges/{manual_charge}/manual-price', json=price))
    change = {**price, 'amount': 6000, 'request_key': key(), 'reason': REASON}
    price_request = checked(cashier.post(f'/api/charges/{manual_charge}/manual-price-requests', json=change), 201)['id']
    return price, change, price_request


def propose_medication_return(doctor, pharmacy, manager, visit):
    med = checked(manager.post('/api/catalog/medicines', json={'name': 'Thuốc giả lập '+key(), 'base_unit': 'viên'}), 201)['id']
    checked(manager.put(f'/api/medicines/{med}/price', json={'unit_price': 1000}))
    checked(pharmacy.post('/api/stock/receipts', json={'medicine_id': med, 'lot_number': key(),
                    'expiry_date': '2099-12-31', 'quantity': 3, 'request_key': key()}), 201)
    version = record_clinical(doctor, visit)
    rx = checked(doctor.post('/api/prescriptions', json={'visit_id': visit,
                 'items': [{'medicine_id': med, 'quantity': 2}]}), 201)['id']
    disp = checked(pharmacy.post(f'/api/prescriptions/{rx}/dispense'), 201)
    return_input = {'request_key': key(), 'reason': REASON,
                    'items': [{'dispensation_item_id': disp['lots'][0]['id'], 'quantity': 1}]}
    return_path = f"/api/dispensations/{disp['dispensation_id']}/returns"
    pending_return = checked(pharmacy.post(return_path, json=return_input), 201)['id']
    return version, rx, return_path, return_input, pending_return


@pytest.mark.parametrize(('kind', 'label', 'total'), [
    ('discount', 'giảm phí 500 đ', 150000),
    ('refund', 'hoàn tiền 1.000 đ', 150000),
    ('price', 'sửa giá 6.000 đ', 155000),
    ('return', 'trả thuốc 1.000 đ', 152000),
])
def test_each_pending_request_blocks_closure(clients, visit, kind, label, total):
    cashier, admin, manager, doctor, pharmacy = (
        clients[role] for role in ('cashier', 'admin', 'manager', 'doctor', 'pharmacy'))
    version = None
    if kind == 'price':
        with database.db(True) as c:
            c.execute("INSERT INTO charges(visit_id,label,created_at) VALUES(?,'Phí nhập tay giả lập',?)",
                      (visit, '2026-10-15T00:00:00+00:00'))
            charge = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        _, _, request_id = propose_price_change(cashier, charge)
        table, actor_col, time_col = 'manual_price_requests', 'proposed_by', 'proposed_at'
        review = f'/api/manual-price-requests/{request_id}/review'
    elif kind == 'return':
        version, _, _, _, request_id = propose_medication_return(doctor, pharmacy, manager, visit)
        table, actor_col, time_col = 'medication_returns', 'requested_by', 'created_at'
        review = f'/api/medication-returns/{request_id}/review'

    complete_visit(doctor, visit, version)
    pay_id = checked(cashier.post('/api/payments', json=payment(visit, total)), 201)['id']
    if kind in ('discount', 'refund'):
        payload = {'visit_id': visit, 'kind': kind, 'amount': 500, 'reason': REASON}
        if kind == 'refund':
            payload.update(payment_id=pay_id, amount=1000)
        request_id = checked(cashier.post('/api/adjustments', json=payload), 201)['id']
        table, actor_col, time_col = 'adjustments', 'proposed_by', 'proposed_at'
        review = f'/api/adjustments/{request_id}/review'

    with database.db() as c:
        row = c.execute(
            f'SELECT u.full_name,r.{time_col} FROM {table} r JOIN users u ON u.id=r.{actor_col} WHERE r.id=?',
            (request_id,)).fetchone()
    proposer, timestamp = row[0], row[1]
    vietnam_time = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00')).astimezone(
        timezone(timedelta(hours=7))).strftime('%d/%m/%Y %H:%M')
    expected = f'Chưa kết thúc được: còn 1 đề nghị {label} ({proposer}, {vietnam_time}) chờ duyệt.'
    prefix = f'/api/visits/{visit}'
    checked(cashier.post(prefix+'/settle'), 409, expected)
    checked(admin.post(prefix+'/settlement-waiver', json={'reason': REASON}), 409, expected)
    checked(manager.post(review, json={'approve': False}))
    checked(cashier.post(prefix+'/settle'))


def test_closed_visit_blocks_all_financial_writes(clients, visit):
    doctor, cashier, pharmacy, manager = (clients[r] for r in ('doctor','cashier','pharmacy','manager'))
    prefix = f'/api/visits/{visit}'
    discount = {'visit_id': visit, 'kind': 'discount', 'amount': 500, 'reason': REASON}
    approved = checked(cashier.post('/api/adjustments', json=discount), 201)['id']
    checked(manager.post(f'/api/adjustments/{approved}/review', json={'approve': True}))
    pending_discount = checked(cashier.post('/api/adjustments', json=discount), 201)['id']
    pay_id = checked(cashier.post('/api/payments', json=payment(visit, 10000)), 201)['id']
    refund = {'visit_id': visit, 'kind': 'refund', 'payment_id': pay_id, 'amount': 1000, 'reason': REASON}
    pending_refund = checked(cashier.post('/api/adjustments', json=refund), 201)['id']

    with database.db(True) as c:
        visit_row = c.execute('SELECT * FROM visits WHERE id=?', (visit,)).fetchone()
        doctor_id, stamp = visit_row['doctor_id'], visit_row['created_at']
        fixed_charge = c.execute('SELECT id FROM charges WHERE visit_id=?', (visit,)).fetchone()[0]
        c.execute("INSERT INTO charges(visit_id,label,created_at) VALUES(?,'Phí nhập tay giả lập',?)", (visit, stamp))
        manual_charge = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("""INSERT INTO orders(visit_id,category,name,status,requested_by,created_at)
                     VALUES(?,'lab','Chỉ định thử chặn duyệt','cancelled',?,?)""", (visit, doctor_id, stamp))
        order = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO order_cancel_requests(order_id,reason,requested_by,requested_at) VALUES(?,?,?,?)',
                  (order, REASON, doctor_id, stamp))
        cancel = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    price, change, price_request = propose_price_change(cashier, manual_charge)
    version, rx, return_path, return_input, pending_return = propose_medication_return(
        doctor, pharmacy, manager, visit)
    complete_visit(doctor, visit, version)
    checked(cashier.post('/api/payments', json=payment(visit, 146500)), 201)
    for endpoint, actor in (('settle', cashier), ('settlement-waiver', clients['admin'])):
        response = actor.post(prefix+'/'+endpoint, json={'reason': REASON} if endpoint != 'settle' else None)
        assert response.status_code == 409
        assert 'còn 4 đề nghị' in response.json()['detail']
        for detail in ('giảm phí 500 đ', 'hoàn tiền 1.000 đ', 'sửa giá 6.000 đ', 'trả thuốc 1.000 đ'):
            assert detail in response.json()['detail']
    for path, label in ((f'/api/adjustments/{pending_discount}/review', 'giảm phí'),
                        (f'/api/adjustments/{pending_refund}/review', 'hoàn tiền'),
                        (f'/api/manual-price-requests/{price_request}/review', 'sửa giá'),
                        (f'/api/medication-returns/{pending_return}/review', 'trả thuốc')):
        response = cashier.post(prefix+'/settle')
        assert response.status_code == 409 and label in response.json()['detail']
        checked(manager.post(path, json={'approve': False}))
    checked(cashier.post(prefix+'/settle'))

    writes = [
        (cashier, '/api/payments', payment(visit, 1)),
        (cashier, '/api/payments', payment(visit, 1, prepayment=True)),
        (cashier, '/api/adjustments', discount),
        (cashier, '/api/adjustments', refund),
        (manager, f'/api/adjustments/{approved}/reverse', {'reason': REASON}),
        (manager, f'/api/charges/{fixed_charge}/reprice', {'amount': 1, 'request_key': key(), 'reason': REASON}),
        (cashier, f'/api/charges/{manual_charge}/manual-price', {**price, 'request_key': key()}),
        (cashier, f'/api/charges/{manual_charge}/manual-price-requests', {**change, 'request_key': key()}),
        (doctor, '/api/orders', {'visit_id': visit, 'category': 'lab', 'request_key': key()}),
        (doctor, f'/api/orders/{order}/authorize', None),
        (manager, f'/api/orders/cancellation-requests/{cancel}/review', {'approve': True}),
        (manager, prefix+'/cancel', {'reason': REASON}),
        (pharmacy, f'/api/prescriptions/{rx}/dispense', None),
        (pharmacy, return_path, {**return_input, 'request_key': key()}),
    ]
    for actor, path, data in writes:
        response = actor.post(path, json=data)
        assert response.status_code == 409, (path, response.text)
        assert response.json()['detail'] == CLOSED, (path, response.text)


def test_sqlite_upgrade_19_to_20_preserves_existing_data(monkeypatch, tmp_path):
    from app import main, s2e_settlement_migration, stock_request_key_migration
    migrate = s2e_settlement_migration.migrate_settlements
    stock_keys = stock_request_key_migration.migrate_stock_request_keys
    path = tmp_path/'v19.sqlite3'
    monkeypatch.setattr(main, 'DB', path)
    monkeypatch.setattr(database, 'DB', path)
    monkeypatch.setattr(s2e_settlement_migration, 'migrate_settlements', lambda c: None)
    # Bản v19 thật chưa có migration 021 (mã thao tác phiếu kho, T4).
    monkeypatch.setattr(stock_request_key_migration, 'migrate_stock_request_keys', lambda c: None)
    main.init_db()
    monkeypatch.setattr(s2e_settlement_migration, 'migrate_settlements', migrate)
    monkeypatch.setattr(stock_request_key_migration, 'migrate_stock_request_keys', stock_keys)
    with database.db(True) as c:
        assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 19
        c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES('VA19','Bệnh nhân giả lập','Nam','2026-01-01')")
        c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at,status) VALUES(1,3,3,'2026-01-01','completed')")
        c.execute("""INSERT INTO visits(patient_id,doctor_id,created_by,created_at)
                     SELECT 1,id,3,'2026-01-01' FROM users WHERE username='bs_noi'""")
        c.execute("INSERT INTO prescription_settings(key,value) VALUES('require_primary_icd10','false') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(1,'Khám',1000,'2026-01-01')")
        c.execute("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                     VALUES(1,700,'cash',9,'2026-01-01','v19-payment')""")
        before = snapshot(c)
    main.init_db()
    main.init_db()
    with database.db(True) as c:
        assert snapshot(c) == before
        assert c.execute('SELECT 1 FROM schema_migrations WHERE version=20').fetchone()
        assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 21
        assert not c.execute('SELECT * FROM visit_settlements').fetchall()
        c.execute("""INSERT INTO visit_settlements(visit_id,actor_id,created_at,charged,paid,due,refund_due,kind,waived_amount,reason,approved_by)
                     VALUES(1,1,'2026-01-02',1000,700,300,0,'mien_thu',300,?,1)""", (REASON,))
        c.execute("INSERT INTO visit_settlement_reopens VALUES(1,1,1,'2026-01-03',?)", (REOPEN,))
        for statement in (
            "UPDATE visit_settlements SET waived_amount=500",
            "DELETE FROM visit_settlements",
            "INSERT OR REPLACE INTO visit_settlements SELECT * FROM visit_settlements",
            "UPDATE visit_settlement_reopens SET reason='Lý do khác'",
            "DELETE FROM visit_settlement_reopens",
            "INSERT OR REPLACE INTO visit_settlement_reopens SELECT * FROM visit_settlement_reopens",
        ):
            with pytest.raises(sqlite3.IntegrityError, match='lịch sử kết thúc lượt'):
                c.execute(statement)
        assert [row[0] for row in c.execute('SELECT visit_id FROM legacy_completed_visits')] == [1]
        for statement in (
            'INSERT INTO legacy_completed_visits VALUES(2)',
            'UPDATE legacy_completed_visits SET visit_id=2',
            'DELETE FROM legacy_completed_visits',
        ):
            with pytest.raises(sqlite3.IntegrityError, match='Không thể ghi danh sách lượt cũ'):
                c.execute(statement)

    with ExitStack() as stack:
        actors = {}
        for role, username in (('cashier', 'thungan'), ('doctor', 'bs_noi'), ('manager', 'quanly'), ('admin', 'quantri')):
            actor = stack.enter_context(TestClient(main.app))
            login = checked(actor.post('/api/login', json={'username': username, 'password': os.environ['DEMO_PASSWORD']}))
            actor.headers['Authorization'] = 'Bearer '+login['access_token']
            actors[role] = actor
        cashier, manager = actors['cashier'], actors['manager']
        legacy = checked(cashier.get('/api/visits/1/settlement'))
        assert legacy['billing']['due'] == 300
        assert legacy['financial_legacy'] and legacy['financial_settlement'] is None
        assert checked(cashier.get('/api/dues'))[0]['financial_pending'] == 0
        checked(cashier.post('/api/visits/1/settle'), 409, 'Lượt cũ không cần kết thúc tài chính')
        checked(actors['admin'].post('/api/visits/1/settlement-waiver', json={'reason': REASON}), 409,
                'Lượt cũ không cần kết thúc tài chính')
        assert not checked(manager.get('/api/financial-settlements'))['items']
        report = checked(manager.get('/api/reports/revenue', params={'date_from':'2026-01-01', 'date_to':'2026-01-01'}))
        assert [(row['visit_id'], row['known_due']) for row in report['unpaid_visits']] == [(1, 300)]
        before = checked(manager.get('/api/overview'))
        assert before['outstanding'] == 300
        checked(cashier.post('/api/payments', json=payment(1, 300)), 201)
        assert checked(cashier.get('/api/dues')) == []
        complete_visit(actors['doctor'], 2)
        assert [row['visit_id'] for row in checked(manager.get('/api/financial-settlements'))['items']] == [2]
        pending = checked(cashier.get('/api/dues'))
        assert [(row['visit_id'], row['financial_pending']) for row in pending] == [(2, 1)]
        assert not checked(cashier.get('/api/visits/2/settlement'))['financial_legacy']
        assert checked(cashier.post('/api/visits/2/settle'))['kind'] == 'du_thu'


def snapshot(c):
    return {table: [dict(row) for row in c.execute('SELECT * FROM '+table+' ORDER BY id')]
            for table in ('patients','visits','charges','payments','adjustments','stock_lots','audit_log')}


@pytest.fixture
def clients():
    names = {'cashier':'thungan', 'admin':'quantri', 'manager':'quanly', 'reception':'letan',
             'doctor':'bs_noi', 'pharmacy':'duoc'}
    from app.main import app
    actors = {}
    for role, name in names.items():
        client = TestClient(app)
        login = checked(client.post('/api/login', json={'username': name, 'password': os.environ['DEMO_PASSWORD']}))
        client.headers['Authorization'] = 'Bearer '+login['access_token']
        actors[role] = client
    yield actors
    for client in actors.values():
        client.close()


@pytest.fixture
def visit(clients):
    reception = clients['reception']
    staff = checked(reception.get('/api/staff'))
    doctor_id = next(user['id'] for user in staff if user['username'] == 'bs_noi')
    patient = checked(reception.post('/api/patients', json={'full_name': 'Bệnh nhân giả lập tài chính '+key(),
                      'sex': 'Nữ', 'date_of_birth': '1990-01-01', 'phone': '0900000011'}), 201)
    return checked(reception.post('/api/visits', json={'patient_id': patient['id'],
                   'service_id': 1, 'doctor_id': doctor_id}), 201)['id']
