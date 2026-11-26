"""H2: báo cáo kho chỉ đọc biến động từ đầu kỳ, kết quả không đổi.

Dùng chung cho SQLite (tests/) và PostgreSQL (lan_tests/). Chỉ dữ liệu giả lập.
reference_stock_report là bản sao nguyên văn của app/stock.py::stock_report trước H2
(main c1712ab), dùng làm đối chứng.
"""
from datetime import datetime, timedelta
import secrets

from fastapi import HTTPException

from app.labels import VN_TZ, local_day
from app.stock import INCOMING, OUTGOING, period
from tests.s2b_cases import checked, med, receive


# ---- Bản cũ (đối chứng) -------------------------------------------------------------------
def reference_stock_report(c, start, end):
    # Reconstruct the opening from current stock and the complete movement ledger.
    # This preserves unrecorded legacy opening balances without inventing receipts.
    rows = {r['id']: dict(r, opening=r['current_stock'], received=0, issued=0, closing=r['current_stock'],
                          cogs_sold=0, cost_internal=0, cost_supplier_return=0, cost_expired=0,
                          returns_revenue=0, revenue=0, gross_profit=0, cost_status='đã có giá')
            for r in c.execute('''SELECT m.id,m.name,m.code,m.base_unit,COALESCE(SUM(l.quantity),0) AS current_stock
                FROM medicines m LEFT JOIN stock_lots l ON l.medicine_id=m.id GROUP BY m.id,m.name,m.code,m.base_unit ORDER BY m.id''')}
    for movement in c.execute('''SELECT s.*,l.medicine_id,i.reason FROM stock_movements s
        JOIN stock_lots l ON l.id=s.stock_lot_id LEFT JOIN stock_issues i ON i.id=s.issue_id ORDER BY s.id'''):
        row = rows[movement['medicine_id']]
        if movement['movement_type'] not in INCOMING | OUTGOING:
            raise HTTPException(409, 'Có loại biến động kho chưa được đối chiếu')
        incoming = movement['movement_type'] in INCOMING
        net = movement['quantity'] * (1 if incoming else -1)
        day = local_day(movement['created_at'])
        if day >= start:
            row['opening'] -= net
        if day > end:
            row['closing'] -= net
        if start <= day <= end:
            row['received' if incoming else 'issued'] += movement['quantity']
            if not incoming:
                cost_key = 'cogs_sold' if movement['movement_type'] == 'rx_dispense' else {
                    'internal': 'cost_internal', 'supplier_return': 'cost_supplier_return',
                    'expired_disposal': 'cost_expired'}[movement['reason'] or 'internal']
                if movement['unit_cost'] is None:
                    row[cost_key] = None
                    row['cost_status'] = 'chưa có giá'
                elif row[cost_key] is not None:
                    row[cost_key] += movement['quantity'] * movement['unit_cost']
                # Legacy rx movements lack a revenue snapshot. Mark it unknown as well.
                if movement['movement_type'] == 'rx_dispense':
                    if movement['revenue_amount'] is None:
                        row['revenue'] = None
                    elif row['revenue'] is not None:
                        row['revenue'] += movement['revenue_amount']
    # dispense_rx inserts one movement and one item per consumed lot, in the same
    # transaction after locking/updating that lot. Their per-lot order is identical,
    # including pre-016 rows. Match the original snapshot, never today's lot cost.
    returns = c.execute("""WITH items AS (
        SELECT di.*,ROW_NUMBER() OVER (PARTITION BY stock_lot_id ORDER BY id) AS ordinal
        FROM dispensation_items di), movements AS (
        SELECT s.*,ROW_NUMBER() OVER (PARTITION BY stock_lot_id ORDER BY id) AS ordinal
        FROM stock_movements s WHERE movement_type='rx_dispense')
        SELECT di.medicine_id,ri.quantity,r.reviewed_at,COALESCE(cr.amount,0) AS credit,
            CASE WHEN s.quantity=di.quantity THEN s.unit_cost ELSE NULL END AS unit_cost
        FROM medication_return_items ri JOIN medication_returns r ON r.id=ri.return_id
        JOIN items di ON di.id=ri.dispensation_item_id
        LEFT JOIN movements s ON s.stock_lot_id=di.stock_lot_id AND s.ordinal=di.ordinal
        LEFT JOIN charge_credits cr ON cr.source_id=ri.id
        WHERE r.status='approved'""")
    for returned in returns:
        if not start <= local_day(returned['reviewed_at']) <= end:
            continue
        row = rows[returned['medicine_id']]
        row['returns_revenue'] += returned['credit']
        if row['revenue'] is not None:
            row['revenue'] -= returned['credit']
        if returned['unit_cost'] is None:
            row['cogs_sold'] = None
            row['cost_status'] = 'chưa có giá'
        elif row['cogs_sold'] is not None:
            row['cogs_sold'] -= returned['quantity'] * returned['unit_cost']
    for row in rows.values():
        row.pop('current_stock')
        row['cost_of_goods'] = row['cogs_sold']  # Compatibility alias: sold cost, net of approved returns.
        row['gross_profit'] = None if row['cogs_sold'] is None or row['revenue'] is None else row['revenue'] - row['cogs_sold']
    return {'date_from': start, 'date_to': end, 'rows': list(rows.values())}


# ---- Kiểm H2 -------------------------------------------------------------------------------
class RowCounter:
    """Đếm số dòng mọi câu SQL trả về cho báo cáo."""
    def __init__(self, c):
        self.c, self.rows = c, 0

    def execute(self, sql, params=()):
        rows = self.c.execute(sql, params).fetchall()
        self.rows += len(rows)
        return rows


def with_clock(path, moment, request):
    from app.main import app
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == path)
    cell = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__))['now']
    original = cell.cell_contents
    try:
        cell.cell_contents = lambda: moment.isoformat()
        return request()
    finally:
        cell.cell_contents = original


def old_history(db, mid, count):
    """Biến động nhiều năm trước: không ảnh hưởng tồn đầu/cuối của kỳ hiện tại."""
    with db(True) as c:
        c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,unit_cost) VALUES(?,?,?,?,?)',
                  (mid, 'H2-CU-' + secrets.token_hex(4), '2029-01-01', count, 900))
        lot = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        user = c.execute('SELECT MIN(id) FROM users').fetchone()[0]
        for i in range(count):
            c.execute("""INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost)
                         VALUES(?,'receipt',1,?,?,900)""", (lot, user, f'2020-01-01T03:{i // 60 % 60:02d}:{i % 60:02d}+00:00'))


def check_stock_report_reads_period_only(clients, visit, db, owner):
    mid = med(clients)
    receive(owner, mid, 10, 1300)
    doctor, pharmacy, manager = clients['doctor'], clients['pharmacy'], clients['manager']
    row = checked(doctor.get(f'/api/visits/{visit}'))
    checked(doctor.put(f'/api/visits/{visit}/clinical', json={'version': row['version'], 'diagnosis': 'Kiểm báo cáo kho H2'}))
    rid = checked(doctor.post('/api/prescriptions', json={'visit_id': visit,
        'items': [{'medicine_id': mid, 'quantity': 4, 'directions': 'Không điều trị thật'}]}), 201)['id']
    disp = checked(pharmacy.post(f'/api/prescriptions/{rid}/dispense'), 201)
    ret = checked(pharmacy.post(f'/api/dispensations/{disp["dispensation_id"]}/returns', json={
        'reason': 'Trả thuốc giả lập H2', 'request_key': secrets.token_hex(16),
        'items': [{'dispensation_item_id': disp['lots'][0]['id'], 'quantity': 2}]}), 201)
    # Trả được duyệt ở kỳ sau kỳ cấp: phải ghép đúng lần cấp gốc ở kỳ trước.
    returned_at = datetime.now(VN_TZ) + timedelta(days=40)
    with_clock('/api/medication-returns/{rid}/review', returned_at,
               lambda: checked(manager.post(f'/api/medication-returns/{ret["id"]}/review', json={'approve': True})))
    old_history(db, mid, 30)
    today = datetime.now(VN_TZ).date()
    later = returned_at.date()
    periods = [period(), (today.isoformat(), today.isoformat()), (later.isoformat(), later.isoformat()),
               (today.isoformat(), later.isoformat()), ('2020-01-01', '2020-01-01'), ('2019-12-31', '2020-01-02'),
               ('2000-01-01', '2100-12-31'), ((today + timedelta(days=1)).isoformat(), (later - timedelta(days=1)).isoformat())]
    from app.stock import stock_report
    with db() as c:
        for start, end in periods:
            assert stock_report(c, start, end) == reference_stock_report(c, start, end), (start, end)


        mine = next(r for r in stock_report(c, later.isoformat(), later.isoformat())['rows'] if r['id'] == mid)
        assert (mine['returns_revenue'], mine['cogs_sold']) == (10000, -2600)  # trả 2/4 viên, giá vốn lô 1.300.
        before = RowCounter(c)
        stock_report(before, *period())
    # Thêm 300 biến động cũ: số dòng đọc cho kỳ hiện tại không đổi (trước H2: đọc toàn sổ biến động).
    old_history(db, mid, 300)
    with db() as c:
        after = RowCounter(c)
        stock_report(after, *period())
        assert after.rows == before.rows, (before.rows, after.rows)
        for start, end in periods:
            assert stock_report(c, start, end) == reference_stock_report(c, start, end), (start, end)


def check_utc_evening_and_missing_cost(clients, db):
    """17:00–23:59 UTC thuộc ngày hôm sau tại Việt Nam; lô chưa có giá vốn."""
    mid = med(clients)
    with db(True) as c:
        c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,unit_cost) VALUES(?,?,?,?,NULL)',
                  (mid, 'H2-KHONG-GIA-' + secrets.token_hex(4), '2030-01-01', 7))
        lot = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        user = c.execute('SELECT MIN(id) FROM users').fetchone()[0]
        for kind, quantity, stamp in (('receipt', 10, '2031-03-09T17:00:00+00:00'),
                                      ('issue', 3, '2031-03-09T23:59:59+00:00')):
            c.execute('''INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost)
                         VALUES(?,?,?,?,?,NULL)''', (lot, kind, quantity, user, stamp))
    from app.stock import stock_report
    with db() as c:
        for start, end in (('2031-03-09', '2031-03-09'), ('2031-03-10', '2031-03-10'),
                           ('2031-03-09', '2031-03-10')):
            assert stock_report(c, start, end) == reference_stock_report(c, start, end)
        row = next(r for r in stock_report(c, '2031-03-10', '2031-03-10')['rows'] if r['id'] == mid)
        assert (row['opening'], row['received'], row['issued'], row['closing']) == (0, 10, 3, 7)
        assert row['cost_internal'] is None and row['cost_status'] == 'chưa có giá'
