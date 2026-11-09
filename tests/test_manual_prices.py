"""C3: manual prices, provisional collections and independent review, fake data only."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import secrets
from datetime import datetime

import pymupdf
import pytest

from app.database import db
from app.manual_prices import VN
from tests.test_workflows import client, token, prepare_visit
from tests.test_price_import import workbook, upload


@pytest.fixture(scope='module')
def actors():
    return {u: token(u) for u in ('quanly', 'thungan', 'bs_noi', 'dieuduong', 'quantri', 'letan', 'kythuat', 'duoc', 'bs_san')}


def manual_service(actors, category='procedure'):
    tag = secrets.token_hex(6)
    r = client.post('/api/catalog/services', headers=actors['quanly'], json={
        'code': 'MAN' + tag, 'name': 'Dịch vụ giá nhập tay giả lập ' + tag,
        'category': category, 'price': None, 'price_at_collection': True})
    assert r.status_code == 201, r.text
    return r.json()['id']


def order(actors, vid, sid, category='procedure', who='bs_noi', draft=False):
    r = client.post('/api/orders', headers=actors[who], json={
        'visit_id': vid, 'service_id': sid, 'category': category, 'defer_approval': draft, 'request_key': secrets.token_hex(12)})
    assert r.status_code == 201, r.text
    return r.json()['id']


def line(actors, vid, oid):
    r = client.get(f'/api/charges/{vid}', headers=actors['thungan'])
    assert r.status_code == 200, r.text
    return next(x for x in r.json() if x['source_type'] == 'order' and x['source_id'] == oid)


def billing(actors, vid):
    return client.get(f'/api/visits/{vid}/settlement', headers=actors['thungan']).json()


def price(actors, cid, amount=120000, description='Thủ thuật giả lập cụ thể', who='thungan', key=None):
    return client.post(f'/api/charges/{cid}/manual-price', headers=actors[who], json={
        'amount': amount, 'description': description, 'request_key': key or secrets.token_hex(12)})


def payment(actors, vid, amount, advance=False, confirm=False):
    """advance=True chỉ dùng cho chức năng Nhận tiền ứng trước; thu tạm do máy chủ tự xác định."""
    return client.post('/api/payments', headers=actors['thungan'], json={
        'visit_id': vid, 'amount': amount, 'method': 'cash', 'prepayment': advance,
        'confirm_over_limit': confirm, 'idempotency_key': secrets.token_hex(12)})


def receipt_title(actors, pid, query=''):
    r = client.get(f'/api/print/receipt/{pid}{query}', headers=actors['thungan'])
    assert r.status_code == 200, r.text
    with pymupdf.open(stream=r.content, filetype='pdf') as pdf:
        text = ''.join(p.get_text() for p in pdf)
    for title in ('PHIẾU THU TIỀN ỨNG TRƯỚC', 'PHIẾU THU TẠM', 'PHIẾU THU'):
        if title in text:
            return title


def test_import_blank_is_manual_zero_stays_zero_and_second_import_unchanged(actors):
    tag = secrets.token_hex(6)
    data = workbook([('BLANK' + tag, 'Giá trống ' + tag, 'Thủ thuật', None),
                     ('ZERO' + tag, 'Giá không ' + tag, 'Thủ thuật', 0)])
    p = upload(actors['quanly'], data).json()
    assert p['can_confirm'] and [r['price_at_collection'] for r in p['rows']] == [True, False]
    assert upload(actors['quanly'], data, p['preview_id']).status_code == 200
    again = upload(actors['quanly'], data).json()
    assert all(r['status'] == 'KHÔNG ĐỔI' for r in again['rows'])
    _, vid = prepare_visit()
    sid = next(s['id'] for s in client.get('/api/catalog', headers=actors['quanly']).json()['services'] if s['code'] == 'ZERO' + tag)
    oid = order(actors, vid, sid)
    assert line(actors, vid, oid)['amount'] == 0
    assert not line(actors, vid, oid)['price_at_collection']


def test_blank_codes_match_normalized_name_and_group_on_reimport(actors):
    tag = secrets.token_hex(6)
    original = workbook([('', 'Tên giá trống ' + tag, 'Thủ thuật', None)])
    p = upload(actors['quanly'], original).json()
    assert upload(actors['quanly'], original, p['preview_id']).status_code == 200
    modified = workbook([('', '  TÊN   GIÁ TRỐNG  ' + tag.upper(), '  THỦ   THUẬT ', None)])
    p = upload(actors['quanly'], modified).json()
    assert p['can_confirm'] and p['rows'][0]['status'] == 'KHÔNG ĐỔI'


def test_clinic_workbook_reference_columns_and_named_notes_sheet(actors):
    from openpyxl import Workbook
    w = Workbook(); s = w.active; s.title = 'BANG_GIA'
    s.append(['Mã dịch vụ','Tên dịch vụ','Nhóm','Giá (đồng)','Phân nhóm (tham khảo)','Dòng trong tệp gốc'])
    s.append(['NOTE01','Dịch vụ giả lập có ghi chú','Thủ thuật',None,'Nhóm tham khảo',289])
    notes = w.create_sheet('CAN_XEM_LAI'); notes.append(['Không nhập trang ghi chú này'])
    w.active = 1
    out = io.BytesIO(); w.save(out)
    result = upload(actors['quanly'], out.getvalue())
    assert result.status_code == 200, result.text
    assert result.json()['can_confirm'] and result.json()['rows'][0]['code'] == 'NOTE01'


def test_unpriced_collection_receipt_and_complete_payment(actors):
    _, vid = prepare_visit()
    sid = manual_service(actors)
    oid = order(actors, vid, sid)
    ch = line(actors, vid, oid)
    assert ch['amount'] is None and ch['price_at_collection']
    state = billing(actors, vid)
    assert state['payment_status'] == 'unpriced' and state['billing']['due'] is None
    # Còn khoản chưa có giá: máy chủ tự lưu là THU TẠM (không qua cờ ứng trước).
    paid = payment(actors, vid, 50000)
    assert paid.status_code == 201, paid.text
    assert paid.json()['kind'] == 'provisional'
    assert receipt_title(actors, paid.json()['id']) == 'PHIẾU THU TẠM'
    assert price(actors, ch['id']).status_code == 200
    doctor_order = next(o for o in client.get('/api/orders', headers=actors['bs_noi']).json() if o['id'] == oid)
    assert doctor_order['proposed_price'] is None and doctor_order['unpriced'] == 0
    state = billing(actors, vid)
    assert state['billing']['due'] == 220000 and state['payment_status'] == 'due'
    final = payment(actors, vid, 220000)
    assert final.status_code == 201 and final.json()['kind'] == 'regular'
    assert billing(actors, vid)['payment_status'] == 'settled'
    assert receipt_title(actors, final.json()['id']) == 'PHIẾU THU'
    assert line(actors, vid, oid)['amount'] == 120000


def test_unpriced_only_visit_remains_in_cashier_queue_even_if_known_balance_zero(actors):
    sid = manual_service(actors, 'consultation')
    r = actors['letan']
    patient = client.post('/api/patients', headers=r, json={'full_name': 'Người bệnh C3 giả lập', 'date_of_birth': '1990-01-01', 'sex': 'Nữ', 'phone': '0900000011'}).json()['id']
    doctor = next(s['id'] for s in client.get('/api/staff', headers=r).json() if s['username'] == 'bs_noi')
    vid = client.post('/api/visits', headers=r, json={'patient_id': patient, 'doctor_id': doctor, 'service_id': sid}).json()['id']
    state = billing(actors, vid)
    assert state['billing']['charged'] == 0 and state['billing']['unpriced_count'] == 1
    assert state['payment_status'] == 'unpriced' and state['billing']['due'] is None
    overview = client.get('/api/overview', headers=actors['quanly']).json()
    assert overview['unpriced_count'] > 0 and overview['outstanding'] is None
    dues = client.get('/api/dues', headers=actors['thungan']).json()
    assert next(d for d in dues if d['visit_id'] == vid)['unpriced_count'] == 1
    assert client.get('/api/queue-counts', headers=actors['thungan']).json()['cashier'] == sum(d['charged'] > d['paid'] or d['unpriced_count'] > 0 for d in dues)
    # Chưa có khoản nào có giá: 3 × 0 = 0 nên thu tạm nào cũng vượt trần, phải xác nhận.
    refused = payment(actors, vid, 50000)
    assert refused.status_code == 409 and 'vượt trần' in refused.json()['detail']
    confirmed = payment(actors, vid, 50000, confirm=True)
    assert confirmed.status_code == 201 and confirmed.json()['kind'] == 'provisional'
    assert billing(actors, vid)['payment_status'] == 'unpriced'


@pytest.mark.parametrize('amount,description', [(0, 'Nội dung'), (-1, 'Nội dung'), (1.5, 'Nội dung'), ('100', 'Nội dung'), (True, 'Nội dung'), (100, ''), (100, '   ')])
def test_price_requires_positive_integer_and_content(actors, amount, description):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors)); cid = line(actors, vid, oid)['id']
    assert price(actors, cid, amount, description).status_code == 422
    assert line(actors, vid, oid)['amount'] is None


@pytest.mark.parametrize('who', ['letan', 'bs_noi', 'bs_san', 'dieuduong', 'kythuat', 'duoc', 'quantri'])
def test_manual_price_roles_rejected_at_api(actors, who):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors)); cid = line(actors, vid, oid)['id']
    assert price(actors, cid, who=who).status_code == 403
    assert client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors[who], json={'amount': 100000, 'description': 'Nội dung', 'reason': 'Lý do điều chỉnh giá', 'request_key': secrets.token_hex(12)}).status_code == 403


def test_price_is_once_only_idempotent_audited_and_changes_need_review(actors):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors)); cid = line(actors, vid, oid)['id']
    req = secrets.token_hex(12)
    assert price(actors, cid, key=req).status_code == 200
    assert price(actors, cid, key=req).json()['status'] == 'already_recorded'
    assert price(actors, cid, amount=150000, key=req).status_code == 409
    assert price(actors, cid, amount=150000).status_code == 409
    assert client.post(f'/api/charges/{cid}/reprice', headers=actors['quanly'], json={'amount': 150000, 'reason': 'Sửa không qua đề nghị', 'request_key': secrets.token_hex(12)}).status_code == 409
    body = {'amount': 160000, 'description': 'Thủ thuật đã đối soát', 'reason': 'Điều chỉnh theo thực hiện', 'request_key': secrets.token_hex(12)}
    r = client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['thungan'], json=body)
    assert r.status_code == 201, r.text
    assert line(actors, vid, oid)['amount'] == 120000
    rid = r.json()['id']
    assert client.post(f'/api/manual-price-requests/{rid}/review', headers=actors['thungan'], json={'approve': True}).status_code == 403
    approved = client.post(f'/api/manual-price-requests/{rid}/review', headers=actors['quanly'], json={'approve': True})
    assert approved.status_code == 200, approved.text
    assert line(actors, vid, oid)['amount'] == 160000
    assert line(actors, vid, oid)['description'] == 'Thủ thuật đã đối soát'
    assert client.post(f'/api/manual-price-requests/{rid}/review', headers=actors['quanly'], json={'approve': True}).status_code == 409
    with db() as c:
        logs = [dict(x) for x in c.execute("SELECT * FROM audit_log WHERE object_type='charge' AND object_id=? AND event='manual_price_entered'", (cid,))]
    assert len(logs) == 1 and logs[0]['user_id']
    assert json.loads(logs[0]['details']) == {'amount': 120000, 'description': 'Thủ thuật giả lập cụ thể'}


def test_manager_enters_but_cannot_approve_own_change_and_can_reject(actors):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors)); cid = line(actors, vid, oid)['id']
    assert price(actors, cid, who='quanly').status_code == 200
    body = {'amount': 90000, 'description': 'Nội dung sửa', 'reason': 'Lý do sửa giá cần duyệt', 'request_key': secrets.token_hex(12)}
    rid = client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['quanly'], json=body).json()['id']
    assert client.post(f'/api/manual-price-requests/{rid}/review', headers=actors['quanly'], json={'approve': True}).status_code == 403
    body['request_key'] = secrets.token_hex(12)
    assert client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['thungan'], json=body).status_code == 409


def test_assigned_nurse_orders_and_cannot_read_billing(actors):
    _, vid = prepare_visit(); sid = manual_service(actors)
    body = {'visit_id': vid, 'service_id': sid, 'category': 'procedure', 'request_key': secrets.token_hex(12)}
    assert client.post('/api/orders', headers=actors['dieuduong'], json=body).status_code == 403
    nurse = client.get('/api/me', headers=actors['dieuduong']).json()['id']
    assert client.post(f'/api/visits/{vid}/nurses', headers=actors['bs_noi'], json={'nurse_id': nurse}).status_code == 201
    oid = order(actors, vid, sid, who='dieuduong')
    assert line(actors, vid, oid)['amount'] is None
    assert client.get(f'/api/charges/{vid}', headers=actors['dieuduong']).status_code == 403
    assert client.get(f'/api/charges/{vid}', headers=actors['letan']).status_code == 403
    assert billing(actors, vid)['payment_status'] == 'unpriced'


def test_manual_prices_daily_report_has_all_entries_adjustments_and_actor(actors):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors)); cid = line(actors, vid, oid)['id']
    day = datetime.now(VN).strftime('%d/%m/%Y')
    before = client.get('/api/reports/manual-prices', headers=actors['quanly'], params={'day': day}).json()
    assert price(actors, cid, amount=170000, description='Tên thủ thuật trên báo cáo').status_code == 200
    body = {'amount': 180000, 'description': 'Nội dung đã duyệt', 'reason': 'Đối chiếu lại giá thực hiện', 'request_key': secrets.token_hex(12)}
    rid = client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['thungan'], json=body).json()['id']
    assert client.post(f'/api/manual-price-requests/{rid}/review', headers=actors['quanly'], json={'approve': True}).status_code == 200
    report = client.get('/api/reports/manual-prices', headers=actors['quanly'], params={'day': day}).json()
    entries = [x for x in report['entries'] if x['charge_id'] == cid]
    assert [e['amount'] for e in entries] == [170000, 180000]
    assert all(e['actor_name'] for e in entries) and entries[1]['reviewer_name']
    assert report['total_entered'] - before['total_entered'] == 170000
    assert report['adjustment_delta'] - before['adjustment_delta'] == 10000
    assert client.get('/api/reports/manual-prices', headers=actors['thungan']).status_code == 403
    assert client.get('/api/reports/manual-prices?day=31/02/2026', headers=actors['quanly']).status_code == 422


def test_concurrent_price_entry_records_exactly_one_price(actors):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors)); cid = line(actors, vid, oid)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda amount: price(actors, cid, amount=amount), (110000, 130000)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert line(actors, vid, oid)['amount'] in (110000, 130000)


def test_old_manual_order_snapshot_survives_catalog_becoming_fixed(actors):
    _, vid = prepare_visit(); sid = manual_service(actors)
    draft = order(actors, vid, sid, draft=True)
    current = next(s for s in client.get('/api/catalog', headers=actors['quanly']).json()['services'] if s['id'] == sid)
    changed = client.put(f'/api/catalog/services/{sid}', headers=actors['quanly'], json={
        'code': current['code'], 'name': current['name'], 'category': 'procedure', 'price': 70000, 'price_at_collection': False})
    assert changed.status_code == 200, changed.text
    assert client.post(f'/api/orders/{draft}/authorize', headers=actors['bs_noi']).json()['charge_amount'] is None
    assert line(actors, vid, draft)['amount'] is None
    new_order = order(actors, vid, sid)
    assert line(actors, vid, new_order)['amount'] == 70000


def test_report_day_uses_vietnam_midnight(actors):
    _, vid = prepare_visit(); sid = manual_service(actors)
    first, second = order(actors, vid, sid), order(actors, vid, sid)
    ids = [line(actors, vid, first)['id'], line(actors, vid, second)['id']]
    for cid in ids:
        assert price(actors, cid).status_code == 200
    with db(True) as c:
        c.execute("UPDATE manual_charge_prices SET priced_at='2099-01-01T16:59:59+00:00' WHERE charge_id=?", (ids[0],))
        c.execute("UPDATE manual_charge_prices SET priced_at='2099-01-01T17:00:00+00:00' WHERE charge_id=?", (ids[1],))
    one = client.get('/api/reports/manual-prices?day=01/01/2099', headers=actors['quanly']).json()
    two = client.get('/api/reports/manual-prices?day=02/01/2099', headers=actors['quanly']).json()
    assert [e['charge_id'] for e in one['entries']] == ids[:1]
    assert [e['charge_id'] for e in two['entries']] == ids[1:]


def test_unpriced_visit_older_than_latest_hundred_still_appears(actors):
    _, vid = prepare_visit(); oid = order(actors, vid, manual_service(actors))
    assert line(actors, vid, oid)['amount'] is None
    newer = []
    with db(True) as c:
        v = c.execute('SELECT * FROM visits WHERE id=?', (vid,)).fetchone()
        for _ in range(101):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (v['patient_id'], v['doctor_id'], v['created_by'], v['created_at']))
            newer.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
    try:
        dues = client.get('/api/dues', headers=actors['thungan']).json()
        assert next(d for d in dues if d['visit_id'] == vid)['unpriced_count'] == 1
        assert client.get('/api/queue-counts', headers=actors['thungan']).json()['cashier'] == sum(d['charged'] > d['paid'] or d['unpriced_count'] > 0 for d in dues)
    finally:
        with db(True) as c:
            for item in newer:
                c.execute('DELETE FROM visits WHERE id=?', (item,))


def test_daily_report_does_not_truncate_after_hundred_entries(actors):
    _, vid = prepare_visit()
    uid = client.get('/api/me', headers=actors['thungan']).json()['id']
    with db(True) as c:
        for n in range(101):
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,NULL,'2099-12-12T03:00:00+00:00')", (vid, 'Khoản giả lập ' + str(n)))
            cid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO manual_charge_prices VALUES(?,?,?,?,'2099-12-12T03:00:00+00:00',?)", (cid, 1111, 'Nội dung giả lập ' + str(n), uid, secrets.token_hex(12)))
    result = client.get('/api/reports/manual-prices?day=12/12/2099', headers=actors['quanly']).json()
    assert len(result['entries']) == 101
    assert result['total_entered'] == 101 * 1111
