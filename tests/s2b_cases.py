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
        'invoice_date': '2026-11-15', 'unit_cost': cost, 'vat_rate': 5, 'request_key': secrets.token_hex(8)}), 201)


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
    issued = checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 2, 'purpose': 'Xuất nội bộ giả lập', 'recipient': 'Bộ phận giả lập', 'request_key': secrets.token_hex(8)}), 201)
    doc = checked(owner.get('/api/stock/documents/issues/' + str(issued['id'])))
    assert [(i['unit_cost'], i['quantity']) for i in doc['items']] == [(2700, 2)]
    assert doc['total_amount'] == 5400
    # Explicit expired disposal is separate and cannot select a quarantined lot.
    lots = checked(owner.get('/api/stock'))
    expired = next(l for l in lots if l['medicine_id'] == mid and l['expiry_date'] == '2020-01-01')
    disposed = checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 1,
        'purpose': 'Hủy hết hạn giả lập', 'reason': 'expired_disposal', 'lot_id': expired['id'], 'request_key': secrets.token_hex(8)}), 201)
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
        response = actor.post('/api/stock/receipts', json={'medicine_id': 1, 'quantity': 1, 'lot_number': 'SAI-QUYEN', 'expiry_date': '2029-01-01', 'unit_cost': 1, 'request_key': secrets.token_hex(8)})
        assert response.status_code == 403
    # Admin sees money but keeps the original pharmacy-only stock mutation boundary.
    admin_doc = checked(clients['admin'].get('/api/stock/documents/receipts/' + str(first['id'])))
    assert admin_doc['items'][0]['unit_cost'] == 1300
    assert clients['admin'].post('/api/stock/issues', json={'medicine_id': 1, 'quantity': 1, 'request_key': secrets.token_hex(8)}).status_code == 403
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
    issue = checked(owner.post('/api/stock/issues', json={'medicine_id': mid, 'quantity': 2, 'purpose': 'Xuất lô cũ giả lập', 'request_key': secrets.token_hex(8)}), 201)
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
        'lot_number': 'CHUA-GIA-' + secrets.token_hex(4), 'quantity': 2, 'expiry_date': '2029-01-01', 'request_key': secrets.token_hex(8)}), 201)
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
        'reason': reason, 'lot_id': lid, 'purpose': 'Kiểm chi phí xuất giả lập', 'request_key': secrets.token_hex(8)}), 201)
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


def stock_totals(db, mid):
    """Tồn, số phiếu nhập/xuất và số dòng biến động của một mặt hàng giả lập."""
    with db() as c:
        quantity = c.execute('SELECT COALESCE(SUM(quantity),0) FROM stock_lots WHERE medicine_id=?', (mid,)).fetchone()[0]
        moves = c.execute('''SELECT COUNT(*) AS n,COUNT(DISTINCT m.receipt_id) AS receipts,COUNT(DISTINCT m.issue_id) AS issues FROM stock_movements m
            JOIN stock_lots l ON l.id=m.stock_lot_id WHERE l.medicine_id=?''', (mid,)).fetchone()
        return quantity, (moves[0], moves[1], moves[2])


def check_resent_documents_are_not_duplicated(clients, db, owner_factory):
    """T4: gửi lại cùng mã thao tác sau mất phản hồi không nhập/xuất lần hai."""
    owner = owner_factory()
    mid = med(clients)
    receipt = {'medicine_id': mid, 'quantity': 10, 'lot_number': 'T4-' + secrets.token_hex(6), 'expiry_date': '2029-01-01',
               'supplier': 'Nhà cung cấp giả lập', 'invoice_no': 'HĐ-T4', 'invoice_date': '2026-11-15',
               'unit_cost': 1300, 'vat_rate': 5, 'request_key': secrets.token_hex(12)}
    first = checked(owner.post('/api/stock/receipts', json=receipt), 201)
    again = checked(owner.post('/api/stock/receipts', json=receipt), 201)
    assert (again['id'], again['document_no'], again['stock_lot_id']) == (first['id'], first['document_no'], first['stock_lot_id'])
    assert again['status'] == 'already_recorded' and again['quantity_added'] == 10
    assert stock_totals(db, mid) == (10, (1, 1, 0))
    lot = next(r for r in checked(owner.get('/api/stock')) if r['id'] == first['stock_lot_id'])
    assert lot['quantity'] == 10 and lot['inventory_value'] == 13000

    # Cùng mã nhưng khác nội dung, khác người gửi: từ chối, không ghi thêm gì.
    for actor, changed in ((owner, {'quantity': 11}), (owner, {'unit_cost': 1400}), (owner, {'vat_rate': None}),
                           (owner, {'invoice_no': 'HĐ-KHÁC'}), (owner, {'lot_number': 'T4-KHAC-' + secrets.token_hex(4)}),
                           (owner, {'supplier': 'Nhà cung cấp khác'}), (owner, {'invoice_date': '2026-11-16'}),
                           (owner, {'expiry_date': '2030-01-01'}), (owner, {'medicine_id': med(clients)}),
                           (clients['pharmacy'], {'unit_cost': None, 'vat_rate': None})):
        response = actor.post('/api/stock/receipts', json={**receipt, **changed})
        assert response.status_code == 409, (changed, response.text)
        assert response.json()['detail'] == 'Mã thao tác đã dùng cho phiếu kho khác nội dung; tải lại trang và lập phiếu mới'
    assert stock_totals(db, mid) == (10, (1, 1, 0))

    issue = {'medicine_id': mid, 'quantity': 3, 'purpose': 'Xuất nội bộ giả lập T4', 'recipient': 'Bộ phận giả lập',
             'request_key': secrets.token_hex(12)}
    issued = checked(owner.post('/api/stock/issues', json=issue), 201)
    again = checked(owner.post('/api/stock/issues', json=issue), 201)
    assert (again['id'], again['document_no'], again['lots']) == (issued['id'], issued['document_no'], issued['lots'])
    assert again['status'] == 'already_recorded'
    assert stock_totals(db, mid) == (7, (2, 1, 1))
    for changed in ({'quantity': 4}, {'purpose': 'Mục đích khác giả lập'}, {'reason': 'supplier_return'}, {'recipient': ''}):
        response = owner.post('/api/stock/issues', json={**issue, **changed})
        assert response.status_code == 409, (changed, response.text)
    assert stock_totals(db, mid) == (7, (2, 1, 1))
    # Mã của phiếu nhập không làm phiếu xuất bị coi là gửi lại, và ngược lại.
    fresh = checked(owner.post('/api/stock/issues', json={**issue, 'request_key': receipt['request_key']}), 201)
    assert fresh['id'] != issued['id'] and fresh.get('status') != 'already_recorded'
    assert stock_totals(db, mid) == (4, (3, 1, 2))

    # Hai máy gửi cùng một phiếu cùng lúc (bấm lại khi lần đầu chưa trả lời): chỉ một phiếu.
    barrier = threading.Barrier(2)
    resend = {**receipt, 'lot_number': 'T4-DONG-THOI-' + secrets.token_hex(4), 'request_key': secrets.token_hex(12)}
    def save(_):
        actor = owner_factory()
        barrier.wait(timeout=10)
        return checked(actor.post('/api/stock/receipts', json=resend), 201)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, (1, 2)))
    assert results[0]['id'] == results[1]['id']
    assert sorted(r.get('status', 'recorded') for r in results) == ['already_recorded', 'recorded']
    assert stock_totals(db, mid) == (14, (4, 2, 2))
    with db() as c:
        assert c.execute('SELECT COUNT(*) FROM stock_receipts WHERE request_key=?', (resend['request_key'],)).fetchone()[0] == 1

    # Phiếu xuất gửi đồng thời; người khác gửi nguyên nội dung vẫn bị từ chối.
    concurrent_issue = {**issue, 'quantity': 2, 'request_key': secrets.token_hex(12)}
    barrier = threading.Barrier(2)
    def save_issue(_):
        actor = owner_factory()
        barrier.wait(timeout=10)
        return checked(actor.post('/api/stock/issues', json=concurrent_issue), 201)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save_issue, (1, 2)))
    assert results[0]['id'] == results[1]['id']
    assert sorted(r['status'] for r in results) == ['already_recorded', 'demo_issued']
    assert clients['pharmacy'].post('/api/stock/issues', json=concurrent_issue).status_code == 409
    assert stock_totals(db, mid) == (12, (5, 2, 3))
    with db(True) as c:
        c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(?,?,?,?)',
                  (mid, 'T4-HET-HAN-' + secrets.token_hex(4), '2000-01-01', 2))
        expired_lot = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    disposal = {**issue, 'reason': 'expired_disposal', 'lot_id': expired_lot, 'quantity': 2,
                'request_key': secrets.token_hex(12)}
    disposed = checked(owner.post('/api/stock/issues', json=disposal), 201)
    replay = checked(owner.post('/api/stock/issues', json=disposal), 201)
    assert replay['id'] == disposed['id'] and replay['lots'] == disposed['lots']
    assert replay['status'] == 'already_recorded'

    # Giả lập đồng hồ tiến đến sau hạn; giữ nguyên lô và phiếu đã ghi.
    from unittest.mock import patch
    from datetime import date
    class LaterDate(date):
        @classmethod
        def today(cls):
            return cls(2030, 1, 2)
    with patch('app.stock.date', LaterDate):
        replay = checked(owner.post('/api/stock/receipts', json=receipt), 201)
        assert replay['id'] == first['id'] and replay['status'] == 'already_recorded'
        assert owner.post('/api/stock/receipts', json={**receipt, 'request_key': secrets.token_hex(12)}).status_code == 422
    owner.close()


def check_missing_request_key_rejected(clients, owner):
    mid = med(clients)
    receipt = {'medicine_id': mid, 'quantity': 1, 'lot_number': 'T4-THIEU-' + secrets.token_hex(4), 'expiry_date': '2029-01-01'}
    issue = {'medicine_id': mid, 'quantity': 1, 'purpose': 'Thiếu mã thao tác'}
    for path, body in (('/api/stock/receipts', receipt), ('/api/stock/issues', issue)):
        for key in (None, 'ngan'):
            payload = body if key is None else {**body, 'request_key': key}
            assert owner.post(path, json=payload).status_code == 422, (path, key)
