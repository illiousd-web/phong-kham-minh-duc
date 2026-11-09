"""Quản lý tra cứu lượt khám (chỉ đọc).

- Chỉ vai trò manager. Quản trị đơn thuần không xem; quyền kiểm ở API.
- Không trả nội dung bệnh án (lý do khám, sinh hiệu, chẩn đoán, điều trị...),
  không trả số điện thoại: số điện thoại chỉ dùng làm điều kiện tìm.
- Không đổi /api/dues và hàng chờ thu ngân: tra cứu dùng truy vấn riêng.
- Khoảng ngày tính theo giờ Việt Nam, mặc định 7 ngày gần nhất (kể cả hôm nay).
- Tình trạng tiền tính đúng như /api/visits/{id}/settlement (domain.invoice):
  còn khoản chưa có giá -> unpriced; phải thu > đã thu -> owing;
  đã thu > phải thu -> refund; bằng nhau -> settled.
"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException

from .labels import parse_day, VN_TZ

PAGE_SIZE = 50
VISIT_STATUS = ('waiting', 'in_progress', 'waiting_results', 'completed', 'cancelled')
MONEY_STATUS = ('owing', 'settled', 'unpriced', 'refund')
DEFAULT_DAYS = 7

# Tính tiền chỉ cho các lượt đã lọc (base), cùng công thức với domain.invoice và DUES_SQL.
SEARCH_SQL = '''WITH base AS (
  SELECT v.id,v.patient_id,v.status,v.created_at,p.code AS patient_code,p.full_name AS patient_name
  FROM visits v JOIN patients p ON p.id=v.patient_id
  WHERE {where}),
ch AS (SELECT visit_id,COALESCE(SUM(amount),0) AS total,
  SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END) AS unpriced
  FROM effective_charges WHERE visit_id IN (SELECT id FROM base) GROUP BY visit_id),
adj AS (SELECT visit_id,SUM(CASE WHEN kind='discount' THEN amount ELSE 0 END) AS discount,
  SUM(CASE WHEN kind='refund' THEN amount ELSE 0 END) AS refund
  FROM effective_adjustments WHERE status='approved' AND visit_id IN (SELECT id FROM base) GROUP BY visit_id),
pay AS (SELECT visit_id,SUM(amount) AS total FROM payments WHERE visit_id IN (SELECT id FROM base) GROUP BY visit_id),
t AS (SELECT b.*,COALESCE(ch.total,0)-COALESCE(adj.discount,0) AS charged,
  COALESCE(pay.total,0)-COALESCE(adj.refund,0) AS paid,COALESCE(ch.unpriced,0) AS unpriced_count
  FROM base b LEFT JOIN ch ON ch.visit_id=b.id LEFT JOIN adj ON adj.visit_id=b.id LEFT JOIN pay ON pay.visit_id=b.id),
m AS (SELECT t.*,CASE WHEN unpriced_count>0 THEN 'unpriced' WHEN charged>paid THEN 'owing'
  WHEN paid>charged THEN 'refund' ELSE 'settled' END AS money_status FROM t)
SELECT {select} FROM m {money}'''


def _day(value, label):
    try:
        return parse_day(value)
    except ValueError:
        raise HTTPException(422, f'{label} phải là ngày có thật, dạng ngày/tháng/năm (ví dụ 05/12/2026)')


def _utc_start(iso_day):
    """0 giờ ngày đó theo giờ Việt Nam, đổi ra chuỗi UTC cùng dạng cột created_at."""
    start = datetime.fromisoformat(iso_day).replace(tzinfo=VN_TZ)
    return start.astimezone(timezone.utc).isoformat(timespec='seconds')


def _like(text):
    return '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search_filters(date_from, date_to, q, status, money, today=None):
    today = today or datetime.now(VN_TZ).date()
    start = _day(date_from, 'Từ ngày') or (today - timedelta(days=DEFAULT_DAYS - 1)).isoformat()
    end = _day(date_to, 'Đến ngày') or today.isoformat()
    if start > end:
        raise HTTPException(422, 'Từ ngày phải trước hoặc bằng Đến ngày')
    if status and status not in VISIT_STATUS:
        raise HTTPException(422, 'Trạng thái lượt không hợp lệ')
    if money and money not in MONEY_STATUS:
        raise HTTPException(422, 'Tình trạng tiền không hợp lệ')
    after = (datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat()
    where = ['v.created_at>=?', 'v.created_at<?']
    args = [_utc_start(start), _utc_start(after)]
    q = ' '.join(str(q or '').split())[:100]
    if q:
        # Tên: so cả nguyên văn lẫn chữ thường; mã: không phân biệt hoa/thường; điện thoại: theo chữ số.
        parts = ["p.full_name LIKE ? ESCAPE '\\'", "LOWER(p.full_name) LIKE ? ESCAPE '\\'", "UPPER(p.code) LIKE ? ESCAPE '\\'"]
        args += [_like(q), _like(q.lower()), _like(q.upper())]
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits and len(digits) == len(q.replace(' ', '').replace('.', '').replace('-', '')):
            parts.append("p.phone LIKE ? ESCAPE '\\'")
            args.append(_like(digits))
        where.append('(' + ' OR '.join(parts) + ')')
    if status:
        where.append('v.status=?')
        args.append(status)
    return start, end, ' AND '.join(where), args, money


def install_manager_visits(app, db, principal, require):
    @app.get('/api/manager/visits')
    def manager_visit_search(date_from: str = '', date_to: str = '', q: str = '', status: str = '',
                             money: str = '', page: str = '1', u=Depends(principal)):
        require(u, 'manager')
        try:
            page_no = int(page)
        except ValueError:
            page_no = 0
        if page_no < 1 or page_no > 100000:
            raise HTTPException(422, 'Số trang không hợp lệ')
        start, end, where, args, money = search_filters(date_from, date_to, q, status, money)
        money_sql = 'WHERE money_status=?' if money else ''
        margs = [money] if money else []
        with db() as c:
            total = c.execute(SEARCH_SQL.format(where=where, select='COUNT(*)', money=money_sql), (*args, *margs)).fetchone()[0]
            rows = c.execute(SEARCH_SQL.format(
                where=where, money=money_sql,
                select='id AS visit_id,created_at,status,patient_code,patient_name,charged,paid,unpriced_count,money_status')
                + ' ORDER BY id DESC LIMIT ? OFFSET ?', (*args, *margs, PAGE_SIZE, (page_no - 1) * PAGE_SIZE)).fetchall()
        items = []
        for r in rows:
            x = dict(r)
            unpriced = x['unpriced_count'] > 0
            x['due'] = None if unpriced else max(0, x['charged'] - x['paid'])
            x['refund_due'] = 0 if unpriced else max(0, x['paid'] - x['charged'])
            items.append(x)
        return {'items': items, 'total': total, 'page': page_no, 'page_size': PAGE_SIZE,
                'pages': max(1, -(-total // PAGE_SIZE)), 'date_from': start, 'date_to': end}

    @app.get('/api/manager/visits/{vid}')
    def manager_visit_money(vid: int, u=Depends(principal)):
        """Phiếu thu và đề nghị giảm phí/hoàn tiền của MỘT lượt, kể cả lượt rất cũ."""
        require(u, 'manager')
        with db() as c:
            v = c.execute('''SELECT v.id,v.status,v.created_at,p.code AS patient_code,p.full_name AS patient_name
                FROM visits v JOIN patients p ON p.id=v.patient_id WHERE v.id=?''', (vid,)).fetchone()
            if not v:
                raise HTTPException(404, 'Không tìm thấy lượt khám')
            payments = [dict(x) for x in c.execute('''SELECT m.id,m.visit_id,m.amount,m.method,m.created_at,m.external_ref,m.kind,
                users.full_name AS cashier_name FROM payments m JOIN users ON users.id=m.created_by
                WHERE m.visit_id=? ORDER BY m.id''', (vid,))]
            adjustments = [dict(x) for x in c.execute('''SELECT a.id,a.visit_id,a.payment_id,a.kind,a.amount,a.reason,a.status,
                a.proposed_at,a.reviewed_at,users.full_name AS proposed_name,
                EXISTS(SELECT 1 FROM adjustment_reversals r WHERE r.adjustment_id=a.id) AS reversed
                FROM adjustments a JOIN users ON users.id=a.proposed_by WHERE a.visit_id=? ORDER BY a.id''', (vid,))]
            for a in adjustments:
                a['reversed'] = bool(a['reversed'])
        return {'visit': dict(v), 'payments': payments, 'adjustments': adjustments}
