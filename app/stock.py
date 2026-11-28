"""Lot cost snapshots and warehouse documents, within the existing write boundary."""
import calendar
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .clinic_profile import read_profile
from .labels import VN_TZ, local_day
from .resources import export_slot
from .self_review import require_current_roles

MONEY_FIELDS = frozenset(('unit_cost', 'vat_rate', 'inventory_value', 'cost_of_goods', 'gross_profit',
                          'total_amount', 'vat_amount', 'cost_status', 'unknown_cost_lots',
                          'cogs_sold', 'cost_internal', 'cost_supplier_return', 'cost_expired'))
INCOMING = frozenset(('receipt', 'controlled_receipt', 'patient_return_quarantine'))
OUTGOING = frozenset(('issue', 'rx_dispense'))


def can_view_money(user):
    return bool({'admin', 'stock_owner'}.intersection(user['roles']))


def visible(data, user):
    """All stock representations are built from the same server-side projection."""
    if isinstance(data, list):
        return [visible(x, user) for x in data]
    if isinstance(data, dict):
        return {k: visible(v, user) for k, v in data.items() if can_view_money(user) or k not in MONEY_FIELDS}
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, int) and abs(data) > 9_007_199_254_740_991:
        # JSON numbers above this bound lose whole đồng in JavaScript.
        return str(data)
    return data


def number(c, kind, stamp):
    year = datetime.fromisoformat(stamp).astimezone(VN_TZ).year
    c.execute('''INSERT INTO stock_document_sequences(kind,year,last_number) VALUES(?,?,1)
        ON CONFLICT(kind,year) DO UPDATE SET last_number=stock_document_sequences.last_number+1''', (kind, year))
    value = c.execute('SELECT last_number FROM stock_document_sequences WHERE kind=? AND year=?', (kind, year)).fetchone()[0]
    return f'{kind}-{year}-{value:04d}'


MAX_LOT_QUANTITY = 2_147_483_647  # trần INTEGER PostgreSQL


def amount(quantity, unit_cost, vat_rate=0):
    if unit_cost is None:
        return None
    return int((Decimal(quantity) * unit_cost * (1 + Decimal(str(vat_rate or 0)) / 100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class StockReceipt(BaseModel):
    medicine_id: int = Field(gt=0)
    lot_number: str = Field(min_length=2, max_length=80)
    expiry_date: date
    quantity: int = Field(gt=0, le=10_000_000)
    supplier: str = Field(default='', max_length=250)
    invoice_no: str = Field(default='', max_length=100)
    invoice_date: date | None = None
    unit_cost: int | None = Field(default=None, ge=0, le=2_000_000_000)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    # Mã thao tác: một lần lập phiếu trên giao diện; gửi lại sau mất phản hồi dùng lại mã này.
    request_key: str = Field(min_length=8, max_length=120)

class StockIssue(BaseModel):
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10_000_000)
    purpose: str = Field(default='Sử dụng nội bộ mô phỏng', min_length=5, max_length=200)
    reason: Literal['internal', 'supplier_return', 'expired_disposal'] = 'internal'
    recipient: str = Field(default='', max_length=250)
    lot_id: int | None = Field(default=None, gt=0)
    request_key: str = Field(min_length=8, max_length=120)


REUSED_KEY = 'Mã thao tác đã dùng cho phiếu kho khác nội dung; tải lại trang và lập phiếu mới'


def same_vat(stored, sent):
    if (stored is None) != (sent is None):
        return False
    return stored is None or Decimal(str(stored)) == sent


def replayed_receipt(c, data, user):
    """Phiếu nhập đã lưu với cùng mã thao tác: cùng nội dung trả lại phiếu cũ, khác nội dung trả 409."""
    old = c.execute('SELECT * FROM stock_receipts WHERE request_key=?', (data.request_key,)).fetchone()
    if not old:
        return None
    moves = c.execute('''SELECT m.stock_lot_id,m.quantity,m.unit_cost,m.vat_rate,l.medicine_id,l.lot_number,l.expiry_date
        FROM stock_movements m JOIN stock_lots l ON l.id=m.stock_lot_id WHERE m.receipt_id=? ORDER BY m.id''', (old['id'],)).fetchall()
    invoice_date = data.invoice_date.isoformat() if data.invoice_date else None
    same = (old['created_by'] == user['id'] and len(moves) == 1 and old['supplier'] == data.supplier
            and old['invoice_no'] == data.invoice_no and old['invoice_date'] == invoice_date)
    if same:
        move = moves[0]
        same = (move['medicine_id'] == data.medicine_id and move['lot_number'] == data.lot_number
                and move['expiry_date'] == data.expiry_date.isoformat() and move['quantity'] == data.quantity
                and move['unit_cost'] == data.unit_cost and same_vat(move['vat_rate'], data.vat_rate))
    if not same:
        raise HTTPException(409, REUSED_KEY)
    return {'id': old['id'], 'document_no': old['document_no'], 'stock_lot_id': moves[0]['stock_lot_id'],
            'quantity_added': moves[0]['quantity'], 'status': 'already_recorded'}


def replayed_issue(c, data, user):
    """Phiếu xuất đã lưu với cùng mã thao tác: không trừ tồn lần hai."""
    old = c.execute('SELECT * FROM stock_issues WHERE request_key=?', (data.request_key,)).fetchone()
    if not old:
        return None
    moves = c.execute('''SELECT m.stock_lot_id,m.quantity,l.medicine_id FROM stock_movements m
        JOIN stock_lots l ON l.id=m.stock_lot_id WHERE m.issue_id=? ORDER BY m.id''', (old['id'],)).fetchall()
    same = (old['created_by'] == user['id'] and old['reason'] == data.reason and old['purpose'] == data.purpose
            and old['recipient'] == data.recipient and bool(moves)
            and all(m['medicine_id'] == data.medicine_id for m in moves)
            and sum(m['quantity'] for m in moves) == data.quantity)
    # Chỉ hủy hết hạn xuất đúng lô được chọn; các lý do khác chọn lô theo hạn dùng (FEFO).
    if same and data.reason == 'expired_disposal':
        same = all(m['stock_lot_id'] == data.lot_id for m in moves)
    if not same:
        raise HTTPException(409, REUSED_KEY)
    return {'id': old['id'], 'document_no': old['document_no'], 'medicine_id': data.medicine_id, 'quantity': data.quantity,
            'lots': [{'lot_id': m['stock_lot_id'], 'quantity': m['quantity']} for m in moves], 'status': 'already_recorded'}


class LotCost(BaseModel):
    unit_cost: int = Field(ge=0, le=2_000_000_000)
    reason: str = Field(min_length=5, max_length=500)


class MinimumStock(BaseModel):
    min_stock: int | None = Field(default=None, ge=0, le=10_000_000)


def stock_rows(c, stock_filter=''):
    today = datetime.now(VN_TZ).date()
    rows = [dict(r) for r in c.execute('''SELECT l.*,m.name,m.code,m.base_unit,m.controlled,m.min_stock,p.unit_price AS sale_price,
        (SELECT COALESCE(SUM(s.quantity),0) FROM stock_lots s WHERE s.medicine_id=m.id AND s.quarantined=0 AND s.expiry_date>=?) AS available
        FROM stock_lots l JOIN medicines m ON m.id=l.medicine_id
        LEFT JOIN medicine_prices p ON p.medicine_id=m.id ORDER BY m.id,l.expiry_date,l.id''', (today.isoformat(),))]
    for row in rows:
        row['expiring'] = row['quantity'] > 0 and 0 <= (date.fromisoformat(row['expiry_date']) - today).days <= 60
        row['below_minimum'] = row['min_stock'] is not None and row['available'] < row['min_stock']
        row['inventory_value'] = None if row['unit_cost'] is None else row['quantity'] * row['unit_cost']
        row['cost_status'] = 'chưa có giá' if row['unit_cost'] is None else 'đã có giá'
    if stock_filter == 'expiring':
        rows = [r for r in rows if r['expiring']]
    if stock_filter == 'below_minimum':
        rows = [r for r in rows if r['below_minimum']]
    return rows


def period(month=None, quarter=None, year=None, date_from=None, date_to=None):
    today = datetime.now(VN_TZ).date()
    try:
        if date_from is not None or date_to is not None:
            if date_from is None or date_to is None:
                raise ValueError
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        elif quarter is not None:
            if quarter not in (1, 2, 3, 4):
                raise ValueError
            y, m = year or today.year, 3 * quarter - 2
            start, end = date(y, m, 1), date(y, m + 2, calendar.monthrange(y, m + 2)[1])
        else:
            y, m = (map(int, month.split('-')) if month else (today.year, today.month))
            start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        if start > end:
            raise ValueError
        return start.isoformat(), end.isoformat()
    except (ValueError, TypeError):
        raise HTTPException(422, 'Kỳ báo cáo không hợp lệ; chọn tháng, quý hoặc đủ từ ngày–đến ngày') from None


def text_bounds(column, start=None, end=None):
    """Điều kiện SQL lọc sơ bộ theo chuỗi thời gian, rộng hơn kỳ một ngày mỗi bên (H2).

    Mọi thời điểm có ngày Việt Nam trong kỳ (UTC, có múi giờ khác, không múi giờ, chỉ ngày) đều
    qua điều kiện; local_day vẫn quyết định chính xác ở Python.
    """
    clauses, args = [], []
    if start is not None and date.fromisoformat(start) > date.min:
        clauses.append(column + '>=?')
        args.append((date.fromisoformat(start) - timedelta(days=1)).isoformat())
    if end is not None and date.fromisoformat(end) < date.max - timedelta(days=1):
        clauses.append(column + '<?')
        args.append((date.fromisoformat(end) + timedelta(days=2)).isoformat())
    return ' AND '.join(clauses) or '1=1', args


def stock_report(c, start, end):
    # Reconstruct the opening from current stock and the movements since the period start.
    # This preserves unrecorded legacy opening balances without inventing receipts.
    rows = {r['id']: dict(r, opening=r['current_stock'], received=0, issued=0, closing=r['current_stock'],
                          cogs_sold=0, cost_internal=0, cost_supplier_return=0, cost_expired=0,
                          returns_revenue=0, revenue=0, gross_profit=0, cost_status='đã có giá')
            for r in c.execute('''SELECT m.id,m.name,m.code,m.base_unit,COALESCE(SUM(l.quantity),0) AS current_stock
                FROM medicines m LEFT JOIN stock_lots l ON l.medicine_id=m.id GROUP BY m.id,m.name,m.code,m.base_unit ORDER BY m.id''')}
    # Biến động trước đầu kỳ không đóng góp vào công thức tồn đầu/cuối dưới đây (H2): chỉ đọc từ
    # ngày trước đầu kỳ (bao trọn mọi múi giờ của ngày đầu kỳ) và dùng chỉ mục created_at sẵn có.
    # local_day vẫn quyết định chính xác ngày của từng biến động.
    since, since_args = text_bounds('s.created_at', start)
    for movement in c.execute('''SELECT s.*,l.medicine_id,i.reason FROM stock_movements s
        JOIN stock_lots l ON l.id=s.stock_lot_id LEFT JOIN stock_issues i ON i.id=s.issue_id
        WHERE ''' + since + ' ORDER BY s.id', since_args):
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
    # Sửa giá dòng tiền thuốc (T2): ghi phần chênh vào kỳ sửa giá, như tiền trả được ghi vào kỳ duyệt trả.
    # Kỳ cấp giữ doanh thu lúc cấp; cộng các kỳ bằng giá hiệu lực của dòng trừ tiền trả, đúng một lần.
    # Giá vốn giữ theo lô lúc xuất. Giảm phí chung của lượt không phân bổ vào đây.
    for change in c.execute("""SELECT di.medicine_id,h.previous_amount,h.new_amount,h.created_at
        FROM charge_price_history h JOIN charge_sources cs ON cs.charge_id=h.charge_id AND cs.source_type='dispense_item'
        JOIN dispensation_items di ON di.id=cs.source_id"""):
        if not start <= local_day(change['created_at']) <= end:
            continue
        row = rows[change['medicine_id']]
        if row['revenue'] is not None:
            row['revenue'] += change['new_amount'] - change['previous_amount']
    # dispense_rx inserts one movement and one item per consumed lot, in the same
    # transaction after locking/updating that lot. Their per-lot order is identical,
    # including pre-016 rows. Match the original snapshot, never today's lot cost.
    # Chỉ ghép các lô có trả được duyệt quanh kỳ; thứ tự cấp trong lô vẫn đánh số trên toàn bộ
    # dòng của chính lô đó nên vẫn khớp lần cấp gốc, kể cả khi cấp ở kỳ trước.
    reviewed, reviewed_args = text_bounds('r.reviewed_at', start, end)
    returns = c.execute("""WITH picked AS (
        SELECT ri.id AS return_item_id,ri.quantity,ri.dispensation_item_id,r.reviewed_at
        FROM medication_return_items ri JOIN medication_returns r ON r.id=ri.return_id
        WHERE r.status='approved' AND """ + reviewed + """),
        lots AS (SELECT DISTINCT d.stock_lot_id FROM picked p JOIN dispensation_items d ON d.id=p.dispensation_item_id),
        items AS (
        SELECT di.*,ROW_NUMBER() OVER (PARTITION BY stock_lot_id ORDER BY id) AS ordinal
        FROM dispensation_items di WHERE di.stock_lot_id IN (SELECT stock_lot_id FROM lots)), movements AS (
        SELECT s.*,ROW_NUMBER() OVER (PARTITION BY stock_lot_id ORDER BY id) AS ordinal
        FROM stock_movements s WHERE movement_type='rx_dispense' AND s.stock_lot_id IN (SELECT stock_lot_id FROM lots))
        SELECT di.medicine_id,p.quantity,p.reviewed_at,COALESCE(cr.amount,0) AS credit,
            CASE WHEN s.quantity=di.quantity THEN s.unit_cost ELSE NULL END AS unit_cost
        FROM picked p JOIN items di ON di.id=p.dispensation_item_id
        LEFT JOIN movements s ON s.stock_lot_id=di.stock_lot_id AND s.ordinal=di.ordinal
        LEFT JOIN charge_credits cr ON cr.source_id=p.return_item_id""", reviewed_args)
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


def document(c, kind, document_id):
    table, key = ('stock_receipts', 'receipt_id') if kind == 'receipts' else ('stock_issues', 'issue_id')
    row = c.execute(f'SELECT d.*,u.full_name AS creator FROM {table} d JOIN users u ON u.id=d.created_by WHERE d.id=?', (document_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Không có phiếu kho')
    result = dict(row)
    result['items'] = [dict(r) for r in c.execute(f'''SELECT s.id,s.quantity,s.unit_cost,s.vat_rate,l.lot_number,l.expiry_date,m.name,m.code,m.base_unit
        FROM stock_movements s JOIN stock_lots l ON l.id=s.stock_lot_id JOIN medicines m ON m.id=l.medicine_id WHERE s.{key}=? ORDER BY s.id''', (document_id,))]
    for item in result['items']:
        item['total_amount'] = amount(item['quantity'], item['unit_cost'], item['vat_rate'] if kind == 'receipts' else 0)
    result['total_amount'] = None if any(i['total_amount'] is None for i in result['items']) else sum(i['total_amount'] for i in result['items'])
    return result


def install_stock(app, db, principal, require, audit, now):
    def view(u):
        require(u, 'pharmacy', 'manager', 'admin', 'stock_owner')

    @app.get('/api/stock')
    def stock(u=Depends(principal), stock_filter: Literal['', 'expiring', 'below_minimum'] = ''):
        view(u)
        with db() as c:
            return visible(stock_rows(c, stock_filter), u)

    @app.get('/api/medicines')
    def medicines(u=Depends(principal)):
        view(u)
        with db() as c:
            return [dict(r) for r in c.execute('SELECT id,name,base_unit,controlled,min_stock FROM medicines ORDER BY id')]

    @app.put('/api/medicines/{mid}/min-stock')
    def minimum(mid: int, data: MinimumStock, u=Depends(principal)):
        require(u, 'admin', 'stock_owner')
        with db(True) as c:
            if c.execute('UPDATE medicines SET min_stock=? WHERE id=?', (data.min_stock, mid)).rowcount != 1:
                raise HTTPException(404, 'Không có thuốc/vật tư')
            audit(c, u, 'stock_minimum_changed', 'medicine', mid, str(data.min_stock))
        return {'id': mid, 'min_stock': data.min_stock}

    @app.put('/api/stock/lots/{lid}/cost')
    def supplement(lid: int, data: LotCost, u=Depends(principal)):
        require(u, 'admin', 'stock_owner')
        with db(True) as c:
            require_current_roles(c, u, 'admin', 'stock_owner')
            old = c.execute('SELECT unit_cost FROM stock_lots WHERE id=?', (lid,)).fetchone()
            if not old:
                raise HTTPException(404, 'Không có lô')
            if old['unit_cost'] is not None:
                raise HTTPException(409, 'Chỉ bổ sung giá cho lô chưa có giá')
            c.execute('UPDATE stock_lots SET unit_cost=? WHERE id=? AND unit_cost IS NULL', (data.unit_cost, lid))
            audit(c, u, 'stock_legacy_cost_added', 'stock_lot', lid,
                  json.dumps({'old': None, 'new': data.unit_cost, 'reason': data.reason}, ensure_ascii=False))
        return {'id': lid, 'unit_cost': data.unit_cost}

    @app.post('/api/stock/receipts', status_code=201)
    def receipt(data: StockReceipt, u=Depends(principal)):
        require(u, 'pharmacy')
        has_cost = data.unit_cost is not None or data.vat_rate is not None
        if has_cost and not can_view_money(u):
            raise HTTPException(403, 'Cần quyền Chủ kho thuốc để nhập giá')
        with db(True) as c:
            current = require_current_roles(c, u, 'pharmacy')
            if has_cost and not can_view_money(dict(u, roles=current)):
                raise HTTPException(403, 'Cần quyền Chủ kho thuốc để nhập giá')
            replay = replayed_receipt(c, data, u)
            if replay:
                return replay
            if data.expiry_date < date.today():
                raise HTTPException(422, 'Không nhận thuốc đã hết hạn')
            med = c.execute('SELECT * FROM medicines WHERE id=?', (data.medicine_id,)).fetchone()
            if not med:
                raise HTTPException(404, 'Không tìm thấy mặt hàng')
            if med['controlled']:
                raise HTTPException(403, 'Thuốc kiểm soát dùng quy trình nhập riêng')
            old = c.execute('SELECT * FROM stock_lots WHERE medicine_id=? AND lot_number=?', (data.medicine_id, data.lot_number)).fetchone()
            if old and (old['expiry_date'] != data.expiry_date.isoformat() or old['quarantined'] or
                        old['unit_cost'] != data.unit_cost or Decimal(str(old['vat_rate'] or 0)) != (data.vat_rate or 0)):
                raise HTTPException(409, 'Lô đã có hạn dùng, giá khác hoặc đang cách ly; nhập số lô riêng')
            # Tồn lô cộng dồn không được vượt trần INTEGER của PostgreSQL (rà soát 25/11/2026, T5).
            if old and old['quantity'] + data.quantity > MAX_LOT_QUANTITY:
                raise HTTPException(409, f'Tồn lô sau khi nhập vượt giới hạn {MAX_LOT_QUANTITY:,} đơn vị; nhập số lô riêng'.replace(',', '.'))
            stamp = now()
            docno = number(c, 'PN', stamp)
            c.execute('''INSERT INTO stock_receipts(document_no,supplier,invoice_no,invoice_date,created_by,created_at,request_key)
                VALUES(?,?,?,?,?,?,?)''', (docno, data.supplier, data.invoice_no, data.invoice_date.isoformat() if data.invoice_date else None,
                                           u['id'], stamp, data.request_key))
            rid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            if old:
                lid = old['id']
                c.execute('UPDATE stock_lots SET quantity=quantity+? WHERE id=?', (data.quantity, lid))
            else:
                c.execute('''INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,unit_cost,vat_rate,receipt_id)
                    VALUES(?,?,?,?,?,?,?)''', (data.medicine_id, data.lot_number, data.expiry_date.isoformat(), data.quantity, data.unit_cost,
                                              float(data.vat_rate) if data.vat_rate is not None else None, rid))
                lid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('''INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost,vat_rate,receipt_id)
                VALUES(?,?,?,?,?,?,?,?)''', (lid, 'receipt', data.quantity, u['id'], stamp, data.unit_cost,
                                           float(data.vat_rate) if data.vat_rate is not None else None, rid))
            audit(c, u, 'stock_received_demo', 'stock_lot', lid, docno)
            return {'id': rid, 'document_no': docno, 'stock_lot_id': lid, 'quantity_added': data.quantity}

    @app.post('/api/stock/issues', status_code=201)
    def issue(data: StockIssue, u=Depends(principal)):
        require(u, 'pharmacy')
        with db(True) as c:
            require_current_roles(c, u, 'pharmacy')
            replay = replayed_issue(c, data, u)
            if replay:
                return replay
            med = c.execute('SELECT * FROM medicines WHERE id=?', (data.medicine_id,)).fetchone()
            if not med:
                raise HTTPException(404, 'Không có thuốc/vật tư')
            if med['controlled']:
                raise HTTPException(403, 'Chưa triển khai xuất thuốc phải kiểm soát đặc biệt')
            if data.reason == 'expired_disposal':
                if not data.lot_id:
                    raise HTTPException(422, 'Hủy hết hạn phải chọn rõ lô đã hết hạn')
                # Separate disposal route; dispensing/internal FEFO remains unchanged.
                lots = c.execute('''SELECT id,quantity,unit_cost FROM stock_lots WHERE id=? AND medicine_id=?
                    AND quarantined=0 AND expiry_date<? AND quantity>0''', (data.lot_id, data.medicine_id, date.today().isoformat())).fetchall()
            else:
                lots = c.execute('''SELECT id,quantity,unit_cost FROM stock_lots WHERE medicine_id=? AND quarantined=0
                    AND expiry_date>=? AND quantity>0 ORDER BY expiry_date,id''', (data.medicine_id, date.today().isoformat())).fetchall()
            if sum(l['quantity'] for l in lots) < data.quantity:
                raise HTTPException(409, 'Không đủ tồn khả dụng hoặc lô không phù hợp')
            stamp = now()
            docno = number(c, 'PX', stamp)
            c.execute('INSERT INTO stock_issues(document_no,reason,purpose,recipient,created_by,created_at,request_key) VALUES(?,?,?,?,?,?,?)',
                      (docno, data.reason, data.purpose, data.recipient, u['id'], stamp, data.request_key))
            iid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            remaining, used = data.quantity, []
            for lot in lots:
                if not remaining:
                    break
                take = min(remaining, lot['quantity'])
                remaining -= take
                if c.execute('UPDATE stock_lots SET quantity=quantity-? WHERE id=? AND quantity>=?', (take, lot['id'], take)).rowcount != 1:
                    raise HTTPException(409, 'Tồn kho đã thay đổi; hãy tải lại')
                c.execute('''INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at,unit_cost,issue_id)
                    VALUES(?,?,?,?,?,?,?)''', (lot['id'], 'issue', take, u['id'], stamp, lot['unit_cost'], iid))
                used.append({'lot_id': lot['id'], 'quantity': take})
            audit(c, u, 'stock_issued_demo', 'medicine', data.medicine_id, docno + ': ' + data.purpose)
            return {'id': iid, 'document_no': docno, 'medicine_id': data.medicine_id, 'quantity': data.quantity, 'lots': used, 'status': 'demo_issued'}

    @app.get('/api/stock/summary')
    def summary(u=Depends(principal)):
        view(u)
        with db() as c:
            rows = stock_rows(c)
            report = stock_report(c, *period())['rows']
            low = c.execute('''SELECT COUNT(*) FROM medicines m WHERE m.min_stock IS NOT NULL AND
                (SELECT COALESCE(SUM(l.quantity),0) FROM stock_lots l WHERE l.medicine_id=m.id AND l.quarantined=0 AND l.expiry_date>=?)<m.min_stock''',
                            (datetime.now(VN_TZ).date().isoformat(),)).fetchone()[0]
            unknown = sum(1 for r in rows if r['quantity'] and r['unit_cost'] is None)
            return visible({'expiring_lots': sum(r['expiring'] for r in rows), 'below_minimum': low,
                            'inventory_value': None if unknown else sum(r['inventory_value'] or 0 for r in rows),
                            'unknown_cost_lots': unknown,
                            'gross_profit': None if any(r['gross_profit'] is None for r in report) else sum(r['gross_profit'] for r in report)}, u)

    @app.get('/api/stock/documents/{kind}')
    def documents(kind: Literal['receipts', 'issues'], u=Depends(principal)):
        view(u)
        table = 'stock_receipts' if kind == 'receipts' else 'stock_issues'
        with db() as c:
            return [dict(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY id DESC LIMIT 100')]

    @app.get('/api/stock/documents/{kind}/{document_id}')
    def get_document(kind: Literal['receipts', 'issues'], document_id: int, u=Depends(principal)):
        view(u)
        with db() as c:
            return visible(document(c, kind, document_id), u)

    @app.get('/api/stock/documents/{kind}/{document_id}/print')
    @export_slot
    def print_document(kind: Literal['receipts', 'issues'], document_id: int, u=Depends(principal)):
        view(u)
        from .stock_exports import document_pdf
        with db() as c:
            data = visible(document(c, kind, document_id), u)
            payload = document_pdf(kind, data, read_profile(c))
        return Response(payload, media_type='application/pdf')

    @app.get('/api/reports/stock')
    def report(u=Depends(principal), month: str | None = None, quarter: int | None = None, year: int | None = None,
               date_from: str | None = None, date_to: str | None = None):
        view(u)
        with db() as c:
            return visible(stock_report(c, *period(month, quarter, year, date_from, date_to)), u)

    @app.get('/api/stock/export.xlsx')
    @export_slot
    def export_stock(u=Depends(principal), stock_filter: Literal['', 'expiring', 'below_minimum'] = ''):
        view(u)
        from .stock_exports import stock_xlsx
        with db() as c:
            payload = stock_xlsx(visible(stock_rows(c, stock_filter), u))
        return Response(payload, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="Ton_kho.xlsx"'})

    @app.get('/api/reports/stock/export')
    @export_slot
    def export_report(u=Depends(principal), fmt: Literal['xlsx', 'pdf'] = 'xlsx', month: str | None = None,
                      quarter: int | None = Query(default=None, ge=1, le=4), year: int | None = None,
                      date_from: str | None = None, date_to: str | None = None):
        view(u)
        from .stock_exports import report_export
        with db() as c:
            data = visible(stock_report(c, *period(month, quarter, year, date_from, date_to)), u)
            payload = report_export(data, fmt, read_profile(c))
        return Response(payload, media_type='application/pdf' if fmt == 'pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
