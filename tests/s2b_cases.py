"""S2b contracts shared by SQLite and real PostgreSQL; synthetic values only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
import json
import secrets
import threading

from openpyxl import load_workbook
from pypdf import PdfReader

from app.labels import VN_TZ
from app.stock import MONEY_FIELDS


def checked(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def med(clients):
    mid = checked(clients['manager'].post('/api/catalog/medicines', json={
        'name': 'Thuốc S2b giả lập ' + secrets.token_hex(5), 'base_unit': 'viên'}), 201)['id']
    checked(clients['manager'].put(f'/api/medicines/{mid}/price', json={'unit_price': 5000}))
    return mid


def receive(owner, mid, qty=10, cost=1300, lot=None, expiry='2029-01-01'):
    return checked(owner.post('/api/stock/receipts', json={
        'medicine_id': mid, 'quantity': qty, 'lot_number': lot or 'S2B-' + secrets.token_hex(6),
        'expiry_date': expiry, 'supplier': 'Nhà cung cấp giả lập', 'invoice_no': 'HĐ-GIẢ-LẬP',
        'invoice_date': '2026-11-15', 'unit_cost': cost, 'vat_rate': 5}), 201)


def assert_private(data):
    if isinstance(data, dict):
        assert not MONEY_FIELDS.intersection(data), data
        for value in data.values():
            assert_private(value)
    elif isinstance(data, list):
        for value in data:
            assert_private(value)


def check_cost_and_report(clients, ids, visit, db, owner):
    mid = med(clients)
    first = receive(owner, mid, 3, 1300, expiry='2028-01-01')
    second = receive(owner, mid, 9, 2700, expiry='2029-01-01')
    # Neither quarantined nor expired lots may become FEFO candidates.
    with db(True) as c:
        c.execute('''INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,quarantined,unit_cost)
            VALUES(?,?,?,?,?,?)''', (mid, 'CACH-LY-' + secrets.token_hex(4), '2028-01-01', 8, 1, 1))
        c.execute('''INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,quarantined,unit_cost)
            VALUES(?,?,?,?,?,?)''', (mid, 'HET-HAN-' + secrets.token_hex(4), '2020-01-01', 6, 0, 2))
    visit_row = checked(clients['doctor'].get(f'/api/visits/{visit}'))
    checked(clients['doctor'].put(f'/api/visits/{visit}/clinical', json={'version': visit_row['version'], 'diagnosis': 'Chẩn đoán giả lập S2b'}))
    rid = checked(clients['doctor'].post('/api/prescriptions', json={'visit_id': visit, 'items': [
        {'medicine_id': mid, 'quantity': 7, 'directions': 'Không điều trị thật'}]}), 201)['id']
    disp = checked(clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense'), 201)
    assert [(x['stock_lot_id'], x['quantity']) for x in disp['lots']] == [(first['stock_lot_id'], 3), (second['stock_lot_id'], 4)]
    with db() as c:
        moves = c.execute("SELECT s.unit_cost,s.quantity FROM stock_movements s JOIN stock_lots l ON l.id=s.stock_lot_id WHERE l.medicine_id=? AND movement_type='rx_dispense' ORDER BY s.id", (mid,)).fetchall()
        assert [(r[0], r[1]) for r in moves] == [(1300, 3), (2700, 4)]
    report = checked(owner.get('/api/reports/stock'))
    row = next(r for r in report['rows'] if r['id'] == mid)
    assert row['cost_of_goods'] == 3*1300 + 4*2700
    assert row['revenue'] == 7*5000
    assert row['gross_profit'] == 7*5000 - (3*1300 + 4*2700)
    for item in report['rows']:
        assert item['opening'] + item['received'] - item['issued'] == item['closing'], item
    assert (row['opening'], row['received'], row['issued'], row['closing']) == (14, 12, 7, 19)
    issued = checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 2, 'purpose': 'Xuất nội bộ giả lập', 'recipient': 'Bộ phận giả lập'}), 201)
    doc = checked(owner.get('/api/stock/documents/issues/' + str(issued['id'])))
    assert [(i['unit_cost'], i['quantity']) for i in doc['items']] == [(2700, 2)]
    assert doc['total_amount'] == 5400
    # Explicit expired disposal is separate and cannot select a quarantined lot.
    lots = checked(owner.get('/api/stock'))
    expired = next(l for l in lots if l['medicine_id'] == mid and l['expiry_date'] == '2020-01-01')
    disposed = checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 1,
        'purpose': 'Hủy hết hạn giả lập', 'reason': 'expired_disposal', 'lot_id': expired['id']}), 201)
    assert disposed['lots'] == [{'lot_id': expired['id'], 'quantity': 1}]
    return mid, first, issued, disp


def check_concurrent_receipts(clients, owner_factory):
    mid = med(clients)
    barrier = threading.Barrier(2)
    def save(index):
        actor = owner_factory()
        barrier.wait(timeout=10)
        return receive(actor, mid, 2, 1300, lot='DONG-THOI-' + secrets.token_hex(5))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, (1, 2)))
    assert len({r['document_no'] for r in results}) == 2
    assert all(r['document_no'].startswith('PN-' + str(datetime.now(VN_TZ).year) + '-') for r in results)


def check_permissions(clients, owner, first, issued, disp):
    endpoints = ['/api/stock', '/api/stock/summary', '/api/medicines', '/api/catalog',
                 '/api/stock/documents/receipts', '/api/stock/documents/issues',
                 '/api/reports/stock', '/api/reports/stock?quarter=4&year=2026',
                 '/api/reports/stock?date_from=2026-01-01&date_to=2029-12-31',
                 f'/api/stock/documents/receipts/{first["id"]}', f'/api/stock/documents/issues/{issued["id"]}',
                 '/api/dispensations', f'/api/dispensations/{disp["dispensation_id"]}/items']
    for role in ('pharmacy', 'manager', 'doctor'):
        actor = clients[role]
        for path in endpoints:
            response = actor.get(path)
            assert response.status_code in (200, 403), (role, path, response.text)
            assert_private(response.json())
        for path in ('/api/stock/export.xlsx', '/api/reports/stock/export?fmt=xlsx'):
            response = actor.get(path)
            if response.status_code == 403:
                continue
            assert response.status_code == 200, response.text
            sheet = load_workbook(BytesIO(response.content)).active
            headers = [cell.value for cell in sheet[1]]
            assert not {'Giá nhập', 'Giá trị tồn', 'Giá vốn xuất', 'Giá vốn bán', 'Xuất nội bộ', 'Trả NCC', 'Hủy hết hạn', 'Lãi gộp'}.intersection(headers)
        for path in (f'/api/stock/documents/receipts/{first["id"]}/print', f'/api/stock/documents/issues/{issued["id"]}/print', '/api/reports/stock/export?fmt=pdf'):
            response = actor.get(path)
            if response.status_code == 403:
                continue
            assert response.status_code == 200, response.text
            text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
            for forbidden in ('Đơn giá', 'Thành tiền', 'Tổng số tiền', 'Giá vốn', 'Lãi gộp'):
                assert forbidden not in text
        assert actor.put(f'/api/stock/lots/{first["stock_lot_id"]}/cost', json={'unit_cost': 1, 'reason': 'Sai quyền'}).status_code == 403
        assert actor.put('/api/medicines/1/min-stock', json={'min_stock': 1}).status_code == 403
        response = actor.post('/api/stock/receipts', json={'medicine_id': 1, 'quantity': 1, 'lot_number': 'SAI-QUYEN', 'expiry_date': '2029-01-01', 'unit_cost': 1})
        assert response.status_code == 403
    # Admin sees money but keeps the original pharmacy-only stock mutation boundary.
    admin_doc = checked(clients['admin'].get('/api/stock/documents/receipts/' + str(first['id'])))
    assert admin_doc['items'][0]['unit_cost'] == 1300
    assert clients['admin'].post('/api/stock/issues', json={'medicine_id': 1, 'quantity': 1}).status_code == 403
    privileged = checked(owner.get('/api/stock/documents/receipts/' + str(first['id'])))
    assert privileged['items'][0]['unit_cost'] == 1300
    assert privileged['total_amount'] == 4095  # 3 x 1300 + VAT 5%.
    profile = checked(clients['admin'].get('/api/clinic-profile'))
    checked(clients['admin'].put('/api/clinic-profile', json={**profile, 'name': 'Đơn vị giả lập S2b', 'address': 'Địa chỉ giả lập S2b'}))
    try:
        for kind, ident, label in [('receipts', first['id'], '01 - VT'), ('issues', issued['id'], '02 - VT')]:
            response = owner.get(f'/api/stock/documents/{kind}/{ident}/print')
            assert response.status_code == 200, response.text
            pdf = PdfReader(BytesIO(response.content))
            text = '\n'.join(page.extract_text() for page in pdf.pages)
            assert label in text and 'Số lô' in text and 'Hạn dùng' in text
            assert 'Nợ: 1561' not in text and 'Có: 331' not in text
            assert 'Tổng số tiền' in text and 'đồng' in text
            assert 'Đơn vị giả lập S2b' in text and 'Địa chỉ giả lập S2b' in text
    finally:
        checked(clients['admin'].put('/api/clinic-profile', json=profile))


def check_legacy_cost(clients, db, owner):
    mid = med(clients)
    with db(True) as c:
        c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(?,?,?,?)',
                  (mid, 'CU-' + secrets.token_hex(5), '2029-01-01', 17))
        lid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    row = next(x for x in checked(owner.get('/api/stock')) if x['id'] == lid)
    assert row['unit_cost'] is None and row['inventory_value'] is None and row['cost_status'] == 'chưa có giá'
    issue = checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 2, 'purpose': 'Xuất lô cũ giả lập'}), 201)
    assert checked(owner.get(f'/api/stock/documents/issues/{issue["id"]}'))['total_amount'] is None
    checked(owner.put(f'/api/stock/lots/{lid}/cost', json={'unit_cost': 1600, 'reason': 'Theo chứng từ giả lập'}))
    assert owner.put(f'/api/stock/lots/{lid}/cost', json={'unit_cost': 1700, 'reason': 'Không được sửa'}).status_code == 409
    with db() as c:
        audit = c.execute("SELECT details FROM audit_log WHERE event='stock_legacy_cost_added' AND object_id=?", (str(lid),)).fetchone()
        assert json.loads(audit['details']) == {'old': None, 'new': 1600, 'reason': 'Theo chứng từ giả lập'}
    # Supplementing current cost cannot rewrite history.
    assert checked(owner.get(f'/api/stock/documents/issues/{issue["id"]}'))['total_amount'] is None
    row = next(x for x in checked(owner.get('/api/reports/stock'))['rows'] if x['id'] == mid)
    assert row['cost_internal'] is None and row['cost_status'] == 'chưa có giá'
    # S2b correction: unknown internal cost does not affect profit on medicine sales.
    assert row['cogs_sold'] == row['cost_of_goods'] == row['gross_profit'] == 0
    checked(owner.put(f'/api/medicines/{mid}/min-stock', json={'min_stock': 16}))
    assert any(x['medicine_id'] == mid for x in checked(owner.get('/api/stock?stock_filter=below_minimum')))
    checked(owner.put(f'/api/medicines/{mid}/min-stock', json={'min_stock': None}))
    assert not any(x['medicine_id'] == mid for x in checked(owner.get('/api/stock?stock_filter=below_minimum')))
    unpriced_mid = med(clients)
    unpriced = checked(clients['pharmacy'].post('/api/stock/receipts', json={'medicine_id': unpriced_mid,
        'lot_number': 'CHUA-GIA-' + secrets.token_hex(4), 'quantity': 2, 'expiry_date': '2029-01-01'}), 201)
    checked(owner.put(f'/api/stock/lots/{unpriced["stock_lot_id"]}/cost', json={'unit_cost': 1800, 'reason': 'Bổ sung từ chứng từ giả lập'}))
    saved = checked(owner.get(f'/api/stock/documents/receipts/{unpriced["id"]}'))
    assert saved['total_amount'] is None and saved['items'][0]['unit_cost'] is None



def owner_sessions(clients):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import LAN, ORIGIN
    password = secrets.token_urlsafe(24)
    username = 'stock_' + secrets.token_hex(5)
    checked(clients['admin'].post('/api/accounts', json={'username': username, 'full_name': 'Chủ kho giả lập',
        'password': password, 'roles': ['pharmacy', 'stock_owner']}), 201)
    def make():
        actor = TestClient(app, base_url=ORIGIN if LAN else 'http://testserver', client=('127.0.0.1', 3210))
        if LAN:
            actor.headers.update({'Origin': ORIGIN, 'X-Clinic-Request': '1'})
        result = checked(actor.post('/api/login', json={'username': username, 'password': password}))
        if LAN:
            actor.headers['X-CSRF-Token'] = actor.cookies['__Host-clinic-csrf']
        else:
            actor.headers['Authorization'] = 'Bearer ' + result['access_token']
        return actor
    make.username = username
    make.password = password
    return make


def check_report_period_boundaries(clients, db, owner):
    mid = med(clients)
    with db(True) as c:
        c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,unit_cost) VALUES(?,?,?,?,?)',
                  (mid, 'MOC-GIO-' + secrets.token_hex(5), '2029-01-01', 57, 3000))
        lid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        actor = c.execute('SELECT created_by FROM stock_receipts ORDER BY id LIMIT 1').fetchone()[0]
        for kind, qty, stamp in [('receipt', 10, '2026-01-01T23:30:00+00:00'), ('issue', 3, '2026-01-02T18:30:00+00:00')]:
            c.execute('INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost) VALUES(?,?,?,?,?,?)',
                      (lid, kind, qty, actor, stamp, 3000))
    for query, expected in [('date_from=2026-01-02&date_to=2026-01-02', (50, 10, 0, 60)),
                            ('date_from=2026-01-03&date_to=2026-01-03', (60, 0, 3, 57)),
                            ('month=2026-01', (50, 10, 3, 57)), ('quarter=1&year=2026', (50, 10, 3, 57))]:
        report = checked(owner.get('/api/reports/stock?' + query))
        row = next(r for r in report['rows'] if r['id'] == mid)
        assert tuple(row[key] for key in ('opening', 'received', 'issued', 'closing')) == expected
        for item in report['rows']:
            assert item['opening'] + item['received'] - item['issued'] == item['closing']
    for query in ('month=2026-13', 'quarter=5', 'date_from=2026-02-01&date_to=2026-01-01', 'date_from=2026-01-01'):
        assert owner.get('/api/reports/stock?' + query).status_code == 422


def report_row(owner, mid, query=''):
    report = checked(owner.get('/api/reports/stock' + query))
    for row in report['rows']:
        assert row['opening'] + row['received'] - row['issued'] == row['closing'], row
    return next(row for row in report['rows'] if row['id'] == mid)


def check_issue_profit(clients, db, owner, reason):
    mid = med(clients)
    receipt = receive(owner, mid, 20, 2000)
    if reason == 'expired_disposal':
        # Synthetic expired stock, outside the receiving workflow's expiry guard.
        with db(True) as c:
            c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,unit_cost) VALUES(?,?,?,?,?)',
                      (mid, 'HUY-' + secrets.token_hex(4), '2020-01-01', 20, 2000))
            lid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    else:
        lid = receipt['stock_lot_id']
    checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 10,
        'reason': reason, 'lot_id': lid, 'purpose': 'Kiểm chi phí xuất giả lập'}), 201)
    row = report_row(owner, mid)
    key = {'internal': 'cost_internal', 'supplier_return': 'cost_supplier_return',
           'expired_disposal': 'cost_expired'}[reason]
    assert row[key] == 20000
    assert all(row[k] == 0 for k in ('cost_internal', 'cost_supplier_return', 'cost_expired') if k != key)
    assert row['revenue'] == row['cogs_sold'] == row['cost_of_goods'] == row['gross_profit'] == 0
    check_report_exports(owner, row)


def check_report_exports(owner, row):
    response = owner.get('/api/reports/stock/export?fmt=xlsx')
    assert response.status_code == 200, response.text
    values = list(load_workbook(BytesIO(response.content)).active.values)
    headers = values[0]
    exported = next(dict(zip(headers, values)) for values in values[1:] if values[0] == row['name'])
    for key, label in [('cogs_sold', 'Giá vốn bán'), ('cost_internal', 'Xuất nội bộ'),
                       ('cost_supplier_return', 'Trả NCC'), ('cost_expired', 'Hủy hết hạn'),
                       ('returns_revenue', 'Trả lại (giảm doanh thu)'), ('revenue', 'Doanh thu thuần'),
                       ('gross_profit', 'Lãi gộp')]:
        assert exported[label] == row[key]
    response = owner.get('/api/reports/stock/export?fmt=pdf')
    assert response.status_code == 200, response.text
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    # PDF paragraphs may wrap their headings to fit the additional columns.
    compact = ' '.join(text.split())
    for label in ('Giá vốn bán', 'Xuất nội bộ', 'Trả NCC', 'Hủy hết hạn', 'Trả lại (giảm doanh thu)', 'Doanh thu thuần'):
        assert label in compact
    report = checked(owner.get('/api/reports/stock'))['rows']
    expected = None if any(r['gross_profit'] is None for r in report) else sum(r['gross_profit'] for r in report)
    assert checked(owner.get('/api/stock/summary'))['gross_profit'] == expected


def check_return_profit(clients, visit, db, owner, half, approval_next_day=False):
    mid = med(clients)
    # Two different original lot costs: full 20,000; half (1 + 4 units) 10,000.
    receive(owner, mid, 2, 1000, expiry='2028-01-01')
    receive(owner, mid, 8, 2250, expiry='2029-01-01')
    visit_row = checked(clients['doctor'].get(f'/api/visits/{visit}'))
    checked(clients['doctor'].put(f'/api/visits/{visit}/clinical', json={
        'version': visit_row['version'], 'diagnosis': 'Kiểm trả thuốc giả lập'}))
    rid = checked(clients['doctor'].post('/api/prescriptions', json={'visit_id': visit,
        'items': [{'medicine_id': mid, 'quantity': 10, 'directions': 'Không điều trị thật'}]}), 201)['id']
    disp = checked(clients['pharmacy'].post(f'/api/prescriptions/{rid}/dispense'), 201)
    row = report_row(owner, mid)
    assert (row['revenue'], row['cogs_sold'], row['gross_profit']) == (50000, 20000, 30000)
    return_items = [{'dispensation_item_id': it['id'], 'quantity': it['quantity'] // (2 if half else 1)} for it in disp['lots']]
    ret = checked(clients['pharmacy'].post(f'/api/dispensations/{disp["dispensation_id"]}/returns', json={
        'reason': 'Trả thuốc giả lập', 'request_key': secrets.token_hex(16), 'items': return_items}), 201)
    # Pending returns neither reduce revenue nor reverse COGS.
    assert report_row(owner, mid) == row
    sale_day = datetime.now(VN_TZ).date()
    approved_at = datetime.now(VN_TZ) + timedelta(days=int(approval_next_day))
    from app.main import app
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/api/medication-returns/{rid}/review')
    clock_cell = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__))['now']
    # Inject only the return workflow's clock, leaving authentication on real time.
    original_clock = clock_cell.cell_contents
    try:
        clock_cell.cell_contents = lambda: approved_at.isoformat()
        checked(clients['manager'].post(f'/api/medication-returns/{ret["id"]}/review', json={'approve': True}))
    finally:
        clock_cell.cell_contents = original_clock
    credit, cost = (25000, 10000) if half else (50000, 20000)
    query = '?date_from=' + sale_day.isoformat() + '&date_to=' + approved_at.date().isoformat()
    row = report_row(owner, mid, query)
    assert (row['returns_revenue'], row['revenue'], row['cogs_sold'], row['gross_profit']) == (credit, 50000-credit, 20000-cost, 30000-credit+cost)
    assert row['cost_internal'] == row['cost_supplier_return'] == row['cost_expired'] == 0
    assert row['received'] == 10 + (5 if half else 10)
    with db() as c:
        assert c.execute('SELECT SUM(quantity) FROM stock_lots WHERE medicine_id=? AND quarantined=1', (mid,)).fetchone()[0] == (5 if half else 10)
    if approval_next_day:
        # Approval date (Vietnam), rather than request, sale, or credit timestamp.
        same_day = report_row(owner, mid, '?date_from=' + sale_day.isoformat() + '&date_to=' + sale_day.isoformat())
        assert (same_day['returns_revenue'], same_day['revenue'], same_day['cogs_sold'], same_day['gross_profit']) == (0, 50000, 20000, 30000)
        next_day = report_row(owner, mid, '?date_from=' + approved_at.date().isoformat() + '&date_to=' + approved_at.date().isoformat())
        assert (next_day['returns_revenue'], next_day['revenue'], next_day['cogs_sold'], next_day['gross_profit']) == (credit, -credit, -cost, cost-credit)
    else:
        check_report_exports(owner, row)


def call_with_clock(path, moment, request):
    """Chạy một API ghi với đồng hồ nghiệp vụ của đúng API đó (xác thực vẫn dùng giờ thật)."""
    from app.main import app
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == path)
    cell = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__))['now']
    original = cell.cell_contents
    try:
        cell.cell_contents = lambda: moment.isoformat()
        return request()
    finally:
        cell.cell_contents = original


def check_reprice_revenue_periods(clients, visit, db, owner):
    """T2: doanh thu kho theo giá hiệu lực sau sửa giá; kỳ cấp, kỳ sửa giá, kỳ trả khác nhau."""
    mid = med(clients)  # giá bán 5.000/viên
    receive(owner, mid, 4, 1000)
    doctor, pharmacy, manager, cashier = clients['doctor'], clients['pharmacy'], clients['manager'], clients['cashier']
    row = checked(doctor.get(f'/api/visits/{visit}'))
    checked(doctor.put(f'/api/visits/{visit}/clinical', json={'version': row['version'], 'diagnosis': 'Kiểm sửa giá thuốc giả lập'}))
    rid = checked(doctor.post('/api/prescriptions', json={'visit_id': visit,
        'items': [{'medicine_id': mid, 'quantity': 4, 'directions': 'Không điều trị thật'}]}), 201)['id']
    disp = checked(pharmacy.post(f'/api/prescriptions/{rid}/dispense'), 201)
    item = disp['lots'][0]
    with db() as c:
        charge = c.execute("SELECT charge_id FROM charge_sources WHERE source_type='dispense_item' AND source_id=?", (item['id'],)).fetchone()[0]
    sale = datetime.now(VN_TZ)
    repriced_at, returned_at = sale + timedelta(days=1), sale + timedelta(days=2)
    checked(call_with_clock('/api/charges/{cid}/reprice', repriced_at, lambda: manager.post(f'/api/charges/{charge}/reprice', json={
        'amount': 12000, 'reason': 'Sửa tổng tiền thuốc giả lập', 'request_key': secrets.token_hex(12)})))
    # Giảm phí chung của lượt không được phân bổ vào doanh thu thuốc.
    discount = checked(cashier.post('/api/adjustments', json={'visit_id': visit, 'kind': 'discount', 'amount': 1000,
                                                              'reason': 'Giảm phí chung giả lập'}), 201)['id']
    checked(manager.post(f'/api/adjustments/{discount}/review', json={'approve': True}))
    ret = checked(pharmacy.post(f'/api/dispensations/{disp["dispensation_id"]}/returns', json={
        'reason': 'Trả thuốc giả lập', 'request_key': secrets.token_hex(16),
        'items': [{'dispensation_item_id': item['id'], 'quantity': 2}]}), 201)
    checked(call_with_clock('/api/medication-returns/{rid}/review', returned_at,
                            lambda: manager.post(f'/api/medication-returns/{ret["id"]}/review', json={'approve': True})))
    line = next(x for x in checked(manager.get(f'/api/charges/{visit}')) if x['id'] == charge)
    assert line['amount'] == 6000  # 12.000 sau sửa giá trừ 6.000 tiền trả 2/4 viên.

    def day(moment, until=None):
        r = report_row(owner, mid, '?date_from=' + moment.date().isoformat() + '&date_to=' + (until or moment).date().isoformat())
        return r['revenue'], r['returns_revenue'], r['cogs_sold'], r['gross_profit']
    assert day(sale) == (20000, 0, 4000, 16000)
    assert day(repriced_at) == (-8000, 0, 0, -8000)
    assert day(returned_at) == (-6000, 6000, -2000, -4000)
    whole = day(sale, returned_at)
    assert whole == (line['amount'], 6000, 2000, 4000)
    assert sum(x[0] for x in (day(sale), day(repriced_at), day(returned_at))) == whole[0]


def check_reprice_twice_and_return_all(clients, visit, db, owner):
    """Hai lần sửa giá, ba lần trả hết: cộng kỳ bằng dòng thuốc trên hóa đơn."""
    mid = med(clients)
    receive(owner, mid, 4, 1000)
    doctor, pharmacy, manager = clients['doctor'], clients['pharmacy'], clients['manager']
    row = checked(doctor.get(f'/api/visits/{visit}'))
    checked(doctor.put(f'/api/visits/{visit}/clinical', json={'version': row['version'], 'diagnosis': 'Giả lập'}))
    rx = checked(doctor.post('/api/prescriptions', json={'visit_id': visit,
        'items': [{'medicine_id': mid, 'quantity': 4, 'directions': 'Giả lập'}]}), 201)
    disp = checked(pharmacy.post(f'/api/prescriptions/{rx["id"]}/dispense'), 201)
    item = disp['lots'][0]['id']
    with db() as c:
        charge = c.execute("SELECT charge_id FROM charge_sources WHERE source_type='dispense_item' AND source_id=?", (item,)).fetchone()[0]
    sale = datetime.now(VN_TZ)
    for offset, price in ((1, 16000), (2, 12000)):
        checked(call_with_clock('/api/charges/{cid}/reprice', sale + timedelta(days=offset),
            lambda: manager.post(f'/api/charges/{charge}/reprice', json={
                'amount': price, 'reason': 'Sửa giá giả lập', 'request_key': secrets.token_hex(12)})))
    for offset, quantity in ((3, 1), (4, 1), (5, 2)):
        ret = checked(pharmacy.post(f'/api/dispensations/{disp["dispensation_id"]}/returns', json={
            'reason': 'Trả thuốc giả lập', 'request_key': secrets.token_hex(16),
            'items': [{'dispensation_item_id': item, 'quantity': quantity}]}), 201)
        checked(call_with_clock('/api/medication-returns/{rid}/review', sale + timedelta(days=offset),
            lambda: manager.post(f'/api/medication-returns/{ret["id"]}/review', json={'approve': True})))
    line = next(x for x in checked(manager.get(f'/api/charges/{visit}')) if x['id'] == charge)
    amounts = []
    for offset in range(6):
        day = (sale + timedelta(days=offset)).date().isoformat()
        amounts.append(report_row(owner, mid, f'?date_from={day}&date_to={day}')['revenue'])
    assert amounts == [20000, -4000, -4000, -3000, -3000, -6000]
    assert sum(amounts) == line['amount'] == 0
    end = (sale + timedelta(days=5)).date().isoformat()
    assert report_row(owner, mid, f'?date_from={sale.date().isoformat()}&date_to={end}')['revenue'] == line['amount']
