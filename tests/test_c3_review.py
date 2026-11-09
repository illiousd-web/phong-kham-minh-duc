"""Sửa theo rà soát PR #11 (mục 1–7). Chỉ dữ liệu giả lập."""
import io
import json
import secrets
import zipfile

import pymupdf
import pytest
from openpyxl import Workbook

from app.database import db
from app.price_import import HEADERS
from tests.test_workflows import client, token, prepare_visit
from tests.test_price_import import upload
from tests.test_manual_prices import manual_service, order, line, price, payment, receipt_title, billing

OLD = '2025-01-01T03:00:00+00:00'


@pytest.fixture(scope='module')
def actors():
    return {u: token(u) for u in ('quanly', 'thungan', 'bs_noi', 'quantri', 'letan')}


def make_old(vid):
    with db(True) as c:
        c.execute('UPDATE visits SET created_at=? WHERE id=?', (OLD, vid))


def newer_settled_visits(count=160):
    """Chèn thêm nhiều lượt cũ hơn hôm nay, đã thu đủ, để lượt cần kiểm bị đẩy ra ngoài '100 lượt mới nhất'."""
    pid, _ = prepare_visit()
    with db(True) as c:
        for i in range(count):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (pid, 1, 1, OLD))
            vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)', (vid, 'Khám giả lập', 1000, OLD))
            c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(?,?,'cash',1,?,?)",
                      (vid, 1000, OLD, 'filler-' + secrets.token_hex(8)))


def due_ids(actors):
    r = client.get('/api/dues', headers=actors['thungan'])
    assert r.status_code == 200, r.text
    return {d['visit_id']: d for d in r.json()}


# ---------- Mục 1 ----------
def test_dues_keeps_every_owing_unpriced_refund_and_today_visit(actors):
    _, owing = prepare_visit()                       # còn nợ 150.000 đ, không có khoản chưa có giá
    _, unpriced = prepare_visit()
    oid = order(actors, unpriced, manual_service(actors))
    _, refund = prepare_visit()
    with db(True) as c:                              # đã thu nhiều hơn phải thu: cần hoàn tiền
        c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(?,?,'cash',1,?,?)",
                  (refund, 200000, OLD, 'refund-' + secrets.token_hex(8)))
    for vid in (owing, unpriced, refund):
        make_old(vid)
    newer_settled_visits(160)
    dues = due_ids(actors)
    assert owing in dues and dues[owing]['charged'] - dues[owing]['paid'] == 150000 and dues[owing]['unpriced_count'] == 0
    assert unpriced in dues and dues[unpriced]['unpriced_count'] == 1
    assert refund in dues and dues[refund]['paid'] > dues[refund]['charged']
    with db() as c:
        newer = c.execute('SELECT COUNT(*) FROM visits WHERE id>?', (owing,)).fetchone()[0]
    assert newer > 150
    # Lượt cũ đã thu đủ, không phải hôm nay: không có trong hàng chờ.
    with db() as c:
        settled_old = c.execute('SELECT MAX(id) FROM visits WHERE created_at=?', (OLD,)).fetchone()[0]
    assert settled_old not in dues
    # Nhập giá nhưng chưa thu: vẫn hiện; thu đủ mới hết.
    assert price(actors, line(actors, unpriced, oid)['id'], amount=80000).status_code == 200
    dues = due_ids(actors)
    assert unpriced in dues and dues[unpriced]['unpriced_count'] == 0 and dues[unpriced]['charged'] - dues[unpriced]['paid'] == 230000
    assert payment(actors, unpriced, 230000).status_code == 201
    assert unpriced not in due_ids(actors)
    # Lượt tạo hôm nay vẫn hiện dù đã thu đủ.
    _, today = prepare_visit()
    assert payment(actors, today, 150000).status_code == 201
    assert today in due_ids(actors)
    # Số đếm thu ngân: mọi lượt còn nợ hoặc còn khoản chưa có giá, kể cả lượt cũ.
    dues = due_ids(actors).values()
    assert client.get('/api/queue-counts', headers=actors['thungan']).json()['cashier'] == sum(
        d['charged'] > d['paid'] or d['unpriced_count'] > 0 for d in dues)


# ---------- Mục 2 ----------
@pytest.mark.parametrize('reason', ['        ', '\t \n  ', 'a  b  c  d', '   ngắn    '])
def test_reason_whitespace_normalized_before_length_check(actors, reason):
    _, vid = prepare_visit()
    oid = order(actors, vid, manual_service(actors))
    cid = line(actors, vid, oid)['id']
    assert price(actors, cid).status_code == 200
    r = client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['thungan'], json={
        'amount': 130000, 'description': 'Thủ thuật sửa giả lập', 'reason': reason, 'request_key': secrets.token_hex(12)})
    assert r.status_code == 422, r.text


def test_reason_and_description_stored_normalized(actors):
    _, vid = prepare_visit()
    oid = order(actors, vid, manual_service(actors))
    cid = line(actors, vid, oid)['id']
    assert price(actors, cid, description='   ').status_code == 422
    assert price(actors, cid, description='  Tiêm \t  bắp   ').status_code == 200
    assert line(actors, vid, oid)['description'] == 'Tiêm bắp'
    r = client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['thungan'], json={
        'amount': 130000, 'description': ' Tiêm   tĩnh mạch ', 'reason': '  Đối   soát\n lại   giá  ', 'request_key': secrets.token_hex(12)})
    assert r.status_code == 201, r.text
    stored = next(x for x in client.get('/api/manual-price-requests', headers=actors['thungan']).json() if x['id'] == r.json()['id'])
    assert stored['reason'] == 'Đối soát lại giá' and stored['description'] == 'Tiêm tĩnh mạch'


# ---------- Mục 3 ----------
def test_receipt_kind_stored_at_collection_and_print_ignores_caller(actors):
    settings = client.get('/api/ui-settings', headers=actors['thungan']).json()
    assert settings['advance_payment'] is False     # thu tạm phải chạy khi công tắc Ứng trước đang TẮT
    report_before = client.get('/api/reports/manual-prices', headers=actors['quanly']).json()['payments']
    _, vid = prepare_visit()
    oid = order(actors, vid, manual_service(actors))
    temp = payment(actors, vid, 40000)
    assert temp.status_code == 201 and temp.json()['kind'] == 'provisional'
    assert price(actors, line(actors, vid, oid)['id'], amount=60000).status_code == 200
    # In lại sau khi đã đủ giá: vẫn là PHIẾU THU TẠM; tham số cố ý sai không đổi được loại.
    for query in ('', '?provisional=false', '?provisional=0', '?kind=regular'):
        assert receipt_title(actors, temp.json()['id'], query) == 'PHIẾU THU TẠM'
    regular = payment(actors, vid, 170000)
    assert regular.status_code == 201 and regular.json()['kind'] == 'regular'
    for query in ('', '?provisional=true', '?provisional=1'):
        assert receipt_title(actors, regular.json()['id'], query) == 'PHIẾU THU'
    _, other = prepare_visit()
    advance = payment(actors, other, 30000, advance=True)
    assert advance.status_code == 201 and advance.json()['kind'] == 'advance'
    assert receipt_title(actors, advance.json()['id'], '?provisional=true') == 'PHIẾU THU TIỀN ỨNG TRƯỚC'
    kinds = {p['id']: p['kind'] for p in client.get('/api/payments', headers=actors['thungan']).json()}
    assert kinds[temp.json()['id']] == 'provisional' and kinds[regular.json()['id']] == 'regular' and kinds[advance.json()['id']] == 'advance'
    with db() as c:
        assert c.execute('SELECT is_advance FROM payments WHERE id=?', (temp.json()['id'],)).fetchone()[0] == 0
        assert c.execute('SELECT is_advance FROM payments WHERE id=?', (advance.json()['id'],)).fetchone()[0] == 1
    # Báo cáo ngày tách rõ ba loại.
    after = client.get('/api/reports/manual-prices', headers=actors['quanly']).json()['payments']
    assert after['provisional']['total'] - report_before['provisional']['total'] == 40000
    assert after['regular']['total'] - report_before['regular']['total'] == 170000
    assert after['advance']['total'] - report_before['advance']['total'] == 30000
    assert after['provisional']['count'] - report_before['provisional']['count'] == 1


# ---------- Mục 4 ----------
def test_provisional_cap_needs_confirmation(actors):
    _, vid = prepare_visit()                         # khoản đã có giá: 150.000 đ -> trần 3 lần = 450.000 đ
    order(actors, vid, manual_service(actors))
    assert payment(actors, vid, 400000).status_code == 201
    over = payment(actors, vid, 100000)              # cộng dồn 500.000 đ > 450.000 đ
    assert over.status_code == 409 and 'vượt trần' in over.json()['detail']
    assert payment(actors, vid, 50000).status_code == 201          # cộng dồn đúng 450.000 đ: không vượt
    assert payment(actors, vid, 100000, confirm=True).status_code == 201
    # Trần 5.000.000 đ khi 3 lần khoản đã có giá còn lớn hơn.
    big = client.post('/api/catalog/services', headers=actors['quanly'], json={
        'name': 'Khám giá cao giả lập ' + secrets.token_hex(4), 'price': 3_000_000, 'category': 'consultation'}).json()['id']
    r = actors['letan']
    patient = client.post('/api/patients', headers=r, json={'full_name': 'Người bệnh trần giả lập', 'date_of_birth': '1990-01-01', 'sex': 'Nam', 'phone': '0900000012'}).json()['id']
    doctor = next(s['id'] for s in client.get('/api/staff', headers=r).json() if s['username'] == 'bs_noi')
    visit = client.post('/api/visits', headers=r, json={'patient_id': patient, 'doctor_id': doctor, 'service_id': big}).json()['id']
    order(actors, visit, manual_service(actors))
    assert payment(actors, visit, 5_000_001).status_code == 409
    assert payment(actors, visit, 5_000_000).status_code == 201
    assert payment(actors, visit, 1, confirm=True).status_code == 201
    # Thu thường (không còn khoản chưa có giá) không áp trần thu tạm.
    assert billing(actors, visit)['payment_status'] == 'unpriced'


# ---------- Mục 5 ----------
def test_import_logs_every_added_service(actors):
    tag = secrets.token_hex(4).upper()
    w = Workbook()
    w.active.append(['Hướng dẫn nhập dữ liệu giả lập'])
    w.active.append(HEADERS)
    w.active.append(['ADD' + tag, 'Dịch vụ thêm mới A ' + tag, 'Xét nghiệm', 35000])
    w.active.append([None, 'Dịch vụ thêm mới B ' + tag, 'Thủ thuật', None])
    out = io.BytesIO(); w.save(out); content = out.getvalue()
    manager = actors['quanly']
    preview = upload(manager, content).json()
    assert preview['can_confirm'], preview
    assert upload(manager, content, preview['preview_id']).json()['added'] == 2
    logs = [json.loads(a['details']) for a in client.get('/api/audit?limit=200', headers=actors['quantri']).json()
            if a['event'] == 'service_added_from_import']
    mine = sorted((x for x in logs if tag in x['name']), key=lambda x: x['row'])
    assert [(x['row'], x['group'], x['category'], x['price'], x['price_at_collection']) for x in mine] == [
        (3, 'Xét nghiệm', 'lab', 35000, False), (4, 'Thủ thuật', 'procedure', None, True)]
    assert mine[0]['code'] == 'ADD' + tag and mine[1]['code'].startswith('DV')
    assert all(x['import_id'] == preview['preview_id'] for x in mine)
    codes = {s['name']: s['code'] for s in client.get('/api/catalog', headers=manager).json()['services']}
    assert mine[1]['code'] == codes['Dịch vụ thêm mới B ' + tag]


# ---------- Mục 6 ----------
def test_manual_price_requests_paginated_and_counted(actors):
    created = []
    for _ in range(3):
        _, vid = prepare_visit()
        oid = order(actors, vid, manual_service(actors))
        cid = line(actors, vid, oid)['id']
        assert price(actors, cid).status_code == 200
        r = client.post(f'/api/charges/{cid}/manual-price-requests', headers=actors['thungan'], json={
            'amount': 125000, 'description': 'Thủ thuật sửa giả lập', 'reason': 'Đối soát lại giá giả lập', 'request_key': secrets.token_hex(12)})
        created.append(r.json()['id'])
    m = actors['quanly']
    first = client.get('/api/manual-price-requests?status=pending&limit=2', headers=m).json()
    second = client.get('/api/manual-price-requests?status=pending&limit=2&offset=2', headers=m).json()
    assert len(first) == 2 and first[0]['id'] > first[1]['id'] and not {x['id'] for x in first} & {x['id'] for x in second}
    count = client.get('/api/manual-price-requests/count?status=pending', headers=m).json()['count']
    with db() as c:
        assert count == c.execute("SELECT COUNT(*) FROM manual_price_requests WHERE status='pending'").fetchone()[0]
    assert set(created) <= {x['id'] for x in client.get('/api/manual-price-requests?status=pending&limit=200', headers=m).json()}
    for bad in ('limit=0', 'limit=201', 'offset=-1', 'status=khac'):
        assert client.get('/api/manual-price-requests?' + bad, headers=m).status_code == 422
    assert client.get('/api/manual-price-requests/count', headers=actors['letan']).status_code == 403
    assert client.get('/api/manual-price-requests', headers=actors['thungan']).status_code == 200


def test_manager_queue_count_uses_count_not_list(actors, monkeypatch):
    """Số đếm quản lý gọi /count (COUNT), không gọi danh sách đề nghị sửa giá."""
    from app.main import app
    route = next(r for r in app.routes if getattr(r, 'path', None) == '/api/manual-price-requests' and 'GET' in r.methods)
    called = []
    original = route.endpoint
    try:
        route.endpoint = lambda *a, **k: called.append(1) or original(*a, **k)
        counts = client.get('/api/queue-counts', headers=actors['quanly']).json()
    finally:
        route.endpoint = original
    assert 'manager' in counts and not called


# ---------- Mục 7 ----------
def two_sheet_workbook(price_cell, reference_cell='=1+1'):
    w = Workbook()
    data = w.active
    data.title = 'BANG_GIA'
    data.append([*HEADERS, 'Phân nhóm (tham khảo)'])
    tag = secrets.token_hex(4).upper()
    data.append(['F' + tag, 'Dịch vụ công thức ' + tag, 'Xét nghiệm', price_cell, reference_cell])
    notes = w.create_sheet('CAN_XEM_LAI')
    notes.append(['Ghi chú', '=SUM(1,2)'])
    out = io.BytesIO(); w.save(out)
    return out.getvalue()


def corrupt_sheet(content, sheet_xml):
    source = zipfile.ZipFile(io.BytesIO(content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as target:
        for item in source.infolist():
            data = source.read(item.filename)
            target.writestr(item, b'<<khong phai XML>>' if item.filename == sheet_xml else data)
    return out.getvalue()


def test_formula_check_only_bang_gia_data_columns_other_sheet_not_read(actors):
    manager = actors['quanly']
    # Công thức ở cột tham khảo và ở trang CAN_XEM_LAI: không kiểm, không đọc.
    ok = upload(manager, two_sheet_workbook(45000)).json()
    assert ok['can_confirm'], ok
    # Trang CAN_XEM_LAI hỏng hẳn vẫn nhập được: chứng tỏ trang đó không được đọc.
    content = two_sheet_workbook(45000)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        assert 'xl/worksheets/sheet2.xml' in z.namelist()
    broken = upload(manager, corrupt_sheet(content, 'xl/worksheets/sheet2.xml')).json()
    assert broken['can_confirm'], broken
    # Công thức trong cột dữ liệu của BANG_GIA: từ chối dòng đó.
    bad = upload(manager, two_sheet_workbook('=40000+5000')).json()
    assert not bad['can_confirm'] and any('công thức' in e for r in bad['rows'] for e in r['errors'])
