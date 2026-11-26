"""H1: báo cáo doanh thu/lượt/thu ngân lọc kỳ trong SQL, số câu SQL không tăng theo số lượt.

Dùng chung cho SQLite (tests/) và PostgreSQL (lan_tests/). Chỉ dữ liệu giả lập.
Các hàm reference_* là bản sao nguyên văn của app/s2e_reports.py trước H1 (main c1712ab),
dùng làm đối chứng: bản mới phải cho đúng cùng kết quả.
"""
from datetime import date, timedelta
import secrets

from fastapi import HTTPException

from app.domain import invoice
from app.labels import vi, METHOD
from app.s2e_reports import NOTE, UNPRICED_WARNING, day, local_stamp, in_period


# ---- Bản cũ (đối chứng) -------------------------------------------------------------------
def reference_revenue_report(c, start, end):
    """Current effective prices, classified by *actual* charge_sources codes.

    Dates are the dates of individual charge/payment events, not the visit date.
    An edited historic price remains attached to the original charge date.
    """
    days = {}

    def bucket(key):
        return days.setdefault(key, dict(day=key, medicine=0, clinical=0, procedure=0, other=0,
                                         gross=0, discount=0, revenue=0, payments=0,
                                         refund=0, paid=0, outstanding=0, unpriced_count=0))

    for ch in c.execute("""SELECT ch.amount,ch.created_at,cs.source_type,o.category
        FROM effective_charges ch
        LEFT JOIN charge_sources cs ON cs.charge_id=ch.id
        LEFT JOIN orders o ON cs.source_type='order' AND o.id=cs.source_id
        WHERE NOT EXISTS (SELECT 1 FROM charge_voids cv WHERE cv.charge_id=ch.id)
        ORDER BY ch.created_at,ch.id"""):
        if not in_period(ch['created_at'], start, end):
            continue
        row = bucket(day(ch['created_at']))
        value = ch['amount']
        if value is None:
            row['unpriced_count'] += 1
            continue
        if ch['source_type'] == 'dispense_item':
            group = 'medicine'
        elif ch['source_type'] == 'order' and ch['category'] in ('lab', 'ultrasound', 'xray', 'ecg'):
            group = 'clinical'
        elif ch['source_type'] == 'order' and ch['category'] == 'procedure':
            group = 'procedure'
        else:
            group = 'other'
        row[group] += value
        row['gross'] += value

    for payment in c.execute('SELECT amount,created_at FROM payments ORDER BY created_at,id'):
        if in_period(payment['created_at'], start, end):
            row = bucket(day(payment['created_at']))
            row['payments'] += payment['amount']

    # The effective_adjustments view automatically excludes reversed discounts.
    # Reviewed-at is the accounting event day for discounts and paid refunds.
    for adjustment in c.execute("""SELECT kind,amount,reviewed_at
        FROM effective_adjustments WHERE status='approved' AND kind IN ('discount','refund')
        ORDER BY reviewed_at,id"""):
        if in_period(adjustment['reviewed_at'], start, end):
            row = bucket(day(adjustment['reviewed_at']))
            row['discount' if adjustment['kind'] == 'discount' else 'refund'] += adjustment['amount']

    rows = [days[key] for key in sorted(days)]
    for row in rows:
        row['revenue'] = row['gross'] - row['discount']
        row['paid'] = row['payments'] - row['refund']
        row['outstanding'] = row['revenue'] - row['paid']
    totals = {key: sum(row[key] for row in rows) for key in
              ('medicine','clinical','procedure','other','gross','discount','revenue',
               'payments','refund','paid','outstanding','unpriced_count')}

    # Vietnamese midnight starts at 17:00 UTC on the preceding day.
    # Compare the raw UTC ISO timestamp so the partial index remains usable.
    first = date.fromisoformat(start)
    begin = (first - timedelta(days=1)).isoformat() + 'T17:00' if first > date.min else start
    finish = end + 'T17:00'
    waivers = c.execute("""SELECT w.waived_amount,s.id IS NOT NULL AS active
        FROM visit_settlements w LEFT JOIN active_visit_settlements s ON s.id=w.id
        WHERE w.kind='mien_thu' AND w.created_at>=? AND w.created_at<?
        AND (LENGTH(w.created_at)>10 OR w.created_at>=?)""", (begin, finish, start)).fetchall()
    totals['waived_amount'] = sum(row['waived_amount'] for row in waivers if row['active'])
    totals['waived_visits'] = sum(1 for row in waivers if row['active'])
    totals['waiver_approval_count'] = len(waivers)

    # Daily outstanding is an accounting flow; actual debt comes from a whole-visit invoice.
    unpaid_visits = []
    for visit in c.execute("""SELECT v.id,v.created_at,p.code AS patient_code,
        p.full_name AS patient_name FROM visits v JOIN patients p ON p.id=v.patient_id
        WHERE v.status <> 'cancelled' AND NOT EXISTS (
            SELECT 1 FROM active_visit_settlements s WHERE s.visit_id=v.id AND s.kind='mien_thu')
        ORDER BY v.created_at,v.id"""):
        if not in_period(visit['created_at'], start, end):
            continue
        item = {'visit_id': visit['id'], 'patient_code': visit['patient_code'],
                'patient_name': visit['patient_name'], 'visit_date': day(visit['created_at']),
                'note': ''}
        try:
            bill = invoice(c, visit['id'])
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            item.update(charged=None, paid=None, known_due=None,
                        unpriced_count=c.execute("""SELECT COUNT(*) FROM effective_charges
                            WHERE visit_id=? AND amount IS NULL""", (visit['id'],)).fetchone()[0],
                        note='Giảm phí vượt phí, cần kiểm tra')
            unpaid_visits.append(item)
            continue
        item.update(charged=bill['charged'], paid=bill['paid'],
                    known_due=bill['known_due'], unpriced_count=bill['unpriced_count'])
        if bill['known_due'] > 0 or bill['unpriced_count'] > 0:
            unpaid_visits.append(item)
    totals['known_due'] = sum(item['known_due'] or 0 for item in unpaid_visits)
    result = {'date_from': start, 'date_to': end, 'rows': rows,
              'totals': totals, 'unpaid_visits': unpaid_visits, 'note': NOTE}
    warnings = []
    if totals['unpriced_count'] > 0 or any(
        visit['unpriced_count'] > 0 for visit in unpaid_visits
    ):
        warnings.append(UNPRICED_WARNING)
    if any(visit['note'] == 'Giảm phí vượt phí, cần kiểm tra' for visit in unpaid_visits):
        warnings.append('Có lượt giảm phí vượt phí, số chưa thu chưa đầy đủ')
    if warnings:
        result['warning'] = '\n'.join(warnings)
    return result


def reference_visits_report(c, start, end):
    rows = []
    by_day, by_doctor, by_status = {}, {}, {}
    active = cancelled = 0
    for v in c.execute("""SELECT v.id,v.created_at,v.status,p.code AS patient_code,
        p.full_name AS patient_name,u.full_name AS doctor_name,u.id AS doctor_id
        FROM visits v JOIN patients p ON p.id=v.patient_id
        JOIN users u ON u.id=v.doctor_id ORDER BY v.created_at,v.id"""):
        if not in_period(v['created_at'], start, end):
            continue
        item = dict(v)
        item['day'] = day(v['created_at'])
        item['status_name'] = vi(v['status'])
        rows.append(item)
        is_cancelled = v['status'] == 'cancelled'
        cancelled += int(is_cancelled)
        active += int(not is_cancelled)
        daily = by_day.setdefault(item['day'], {'day': item['day'], 'visits': 0, 'cancelled': 0})
        daily['cancelled' if is_cancelled else 'visits'] += 1
        doctor = by_doctor.setdefault(v['doctor_id'], {'doctor_id': v['doctor_id'], 'doctor_name': v['doctor_name'],
                                                       'visits': 0, 'cancelled': 0})
        doctor['cancelled' if is_cancelled else 'visits'] += 1
        status = by_status.setdefault(v['status'], {'status': v['status'], 'status_name': vi(v['status']), 'count': 0})
        status['count'] += 1
    return {'date_from': start, 'date_to': end, 'rows': rows,
            'by_day': [by_day[k] for k in sorted(by_day)],
            'by_doctor': sorted(by_doctor.values(), key=lambda r: (r['doctor_name'], r['doctor_id'])),
            'by_status': sorted(by_status.values(), key=lambda r: r['status']),
            'total': active, 'cancelled': cancelled, 'note': NOTE}


def reference_cashier_report(c, start, end):
    rows = []
    by_cashier, by_method = {}, {}
    for payment in c.execute("""SELECT m.id,m.created_at,m.amount,m.method,m.created_by AS cashier_id,
        u.full_name AS cashier_name,p.code AS patient_code,p.full_name AS patient_name
        FROM payments m JOIN users u ON u.id=m.created_by
        JOIN visits v ON v.id=m.visit_id JOIN patients p ON p.id=v.patient_id
        ORDER BY m.created_at,m.id"""):
        if not in_period(payment['created_at'], start, end):
            continue
        item = dict(payment)
        item['collected_at'] = local_stamp(payment['created_at'])
        item['method_name'] = vi(payment['method'], METHOD)
        rows.append(item)
        cashier = by_cashier.setdefault(item['cashier_id'], {'cashier_id': item['cashier_id'],
            'cashier_name': item['cashier_name'], 'count': 0, 'amount': 0})
        cashier['count'] += 1
        cashier['amount'] += item['amount']
        method = by_method.setdefault(item['method'], {'method': item['method'],
            'method_name': item['method_name'], 'count': 0, 'amount': 0})
        method['count'] += 1
        method['amount'] += item['amount']
    return {'date_from': start, 'date_to': end, 'rows': rows, 'total': sum(r['amount'] for r in rows),
            'by_cashier': sorted(by_cashier.values(), key=lambda r: (r['cashier_name'], r['cashier_id'])),
            'by_method': sorted(by_method.values(), key=lambda r: r['method']), 'note': NOTE}


# ---- Kiểm H1 -------------------------------------------------------------------------------
PERIOD = '2031-03-10'
INSIDE = ['2031-03-09T17:00:00+00:00', '2031-03-10T16:59:59+00:00', '2031-03-10', '2031-03-10T20:00:00',
          '2031-03-10T05:00:00Z']
OUTSIDE = ['2031-03-09T16:59:59+00:00', '2031-03-10T17:00:00+00:00', '2031-03-09', '2031-03-11',
           '2031-03-08T20:00:00', '2030-01-01T03:00:00+00:00']


class CountingConnection:
    """Đếm số câu SQL một báo cáo gửi tới CSDL."""
    def __init__(self, c):
        self.c, self.count = c, 0

    def execute(self, sql, params=()):
        self.count += 1
        return self.c.execute(sql, params)


def add_visits(db, stamps, tag):
    with db(True) as c:
        user = c.execute('SELECT MIN(id) FROM users').fetchone()[0]
        c.execute('INSERT INTO patients(code,full_name,sex,created_at) VALUES(?,?,?,?)',
                  ('H1' + tag, 'Người bệnh H1 giả lập ' + tag, 'Nữ', '2030-01-01T03:00:00+00:00'))
        pid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        for i, stamp in enumerate(stamps):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (pid, user, user, stamp))
            vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)', (vid, 'Khám H1', 100000, stamp))

            def pay(amount, at):
                c.execute("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                             VALUES(?,?,'cash',?,?,?)""", (vid, amount, user, at, 'h1-' + secrets.token_hex(10)))

            def adjust(amount, at):
                c.execute("""INSERT INTO adjustments(visit_id,kind,amount,reason,status,proposed_by,reviewed_by,proposed_at,reviewed_at)
                             VALUES(?,'discount',?,'Giảm phí H1 giả lập','approved',?,?,?,?)""", (vid, amount, user, user, at, at))
            kind = i % 6
            if kind == 0:
                c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,NULL,?)', (vid, 'Thủ thuật chưa giá H1', stamp))
            elif kind == 1:
                pay(100000, stamp)
            elif kind == 2:
                # Giảm phí trong kỳ, tiền thu ngoài kỳ: nợ hiện hành vẫn tính cả giao dịch ngoài kỳ.
                adjust(30000, stamp)
                pay(50000, '2031-04-01T03:00:00+00:00')
            elif kind == 3:
                adjust(150000, stamp)  # Giảm quá phí: giữ cảnh báo.
            elif kind == 4:
                pay(120000, stamp)  # Thu thừa: không nằm trong danh sách còn nợ.
            else:
                c.execute("UPDATE visits SET status='cancelled' WHERE id=?", (vid,))


def reports(c, start, end):
    from app.s2e_reports import revenue_report, visits_report, cashier_report
    return {'revenue': revenue_report(c, start, end), 'visits': visits_report(c, start, end),
            'cashier': cashier_report(c, start, end)}


def references(c, start, end):
    return {'revenue': reference_revenue_report(c, start, end), 'visits': reference_visits_report(c, start, end),
            'cashier': reference_cashier_report(c, start, end)}


def check_reports_filter_in_sql_with_same_results(db):
    from app.s2e_reports import revenue_report
    tag = secrets.token_hex(4)
    add_visits(db, INSIDE + OUTSIDE, tag)
    first = date.fromisoformat(PERIOD)
    periods = [(PERIOD, PERIOD), ((first - timedelta(days=1)).isoformat(), (first + timedelta(days=1)).isoformat()),
               ('2031-03-11', '2031-03-11'), ('2000-01-01', '2100-12-31')]
    with db() as c:
        for start, end in periods:
            assert reports(c, start, end) == references(c, start, end), (start, end)
        result = revenue_report(c, PERIOD, PERIOD)
        mine = [v for v in result['unpaid_visits'] if v['patient_code'] == 'H1' + tag]
        # Mỗi mốc trong kỳ thuộc đúng một nhóm: chưa giá, đã thu, nợ sau giảm phí, giảm quá phí, thu thừa.
        assert [(v['unpriced_count'], v['known_due'], v['note']) for v in mine] == [
            (1, 100000, ''), (0, 20000, ''), (0, None, 'Giảm phí vượt phí, cần kiểm tra')]
        assert 'Có lượt giảm phí vượt phí, số chưa thu chưa đầy đủ' in result['warning']
        counted = CountingConnection(c)
        revenue_report(counted, PERIOD, PERIOD)
        before = counted.count
    # Thêm 25 lượt trong kỳ: số câu SQL không đổi (trước H1: thêm 5 câu cho mỗi lượt).
    add_visits(db, [INSIDE[i % len(INSIDE)] for i in range(25)], tag + 'b')
    with db() as c:
        counted = CountingConnection(c)
        revenue_report(counted, PERIOD, PERIOD)
        assert counted.count == before <= 6, (before, counted.count)
        for start, end in periods:
            assert reports(c, start, end) == references(c, start, end), (start, end)


def check_refunds_and_waiver_match_reference(db):
    """Bán trong kỳ, hoàn khác kỳ; giá 0, miễn thu và mốc có múi giờ."""
    tag = secrets.token_hex(4)
    sale_at = '2031-03-10T23:59:59.125+07:00'
    refund_at = '2031-03-11T00:00:00.250+07:00'
    with db(True) as c:
        user = c.execute('SELECT MIN(id) FROM users').fetchone()[0]
        c.execute('INSERT INTO patients(code,full_name,sex,created_at) VALUES(?,?,?,?)',
                  ('H1R' + tag, 'Người bệnh hoàn tiền giả lập', 'Nữ', sale_at))
        patient = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        for amount, refunded in ((100000, 100000), (100000, 40000)):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
                      (patient, user, user, sale_at))
            visit = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',
                      (visit, 'Bán giả lập', amount, sale_at))
            c.execute("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                         VALUES(?,?,'cash',?,?,?)""", (visit, amount, user, sale_at, secrets.token_hex(16)))
            payment = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("""INSERT INTO adjustments(visit_id,payment_id,kind,amount,reason,status,
                         proposed_by,reviewed_by,proposed_at,reviewed_at)
                         VALUES(?,?,'refund',?,'Hoàn giả lập','approved',?,?,?,?)""",
                      (visit, payment, refunded, user, user, refund_at, refund_at))
        c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
                  (patient, user, user, sale_at))
        visit = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',
                  (visit, 'Giá 0', 0, sale_at))
        c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',
                  (visit, 'Miễn thu', 30000, sale_at))
        c.execute("""INSERT INTO visit_settlements(visit_id,actor_id,created_at,charged,paid,due,
                     refund_due,kind,waived_amount,reason,approved_by)
                     VALUES(?,?,?,30000,0,30000,0,'mien_thu',30000,'Miễn thu giả lập',?)""",
                  (visit, user, '2031-03-10T16:59:59.125+00:00', user))
    with db() as c:
        for start, end in ((PERIOD, PERIOD), ('2031-03-11', '2031-03-11'),
                           (PERIOD, '2031-03-11')):
            assert reports(c, start, end) == references(c, start, end), (start, end)
        from app.s2e_reports import revenue_report
        sale = revenue_report(c, PERIOD, PERIOD)['totals']
        later = revenue_report(c, '2031-03-11', '2031-03-11')['totals']
        assert sale['waived_amount'] == 30000 and sale['waived_visits'] == 1
        assert later['refund'] == 140000


def check_unpaid_matches_invoice(db):
    """Nợ hiện hành của từng lượt trong báo cáo bằng đúng domain.invoice của lượt đó."""
    from app.s2e_reports import revenue_report
    with db() as c:
        for visit in revenue_report(c, PERIOD, PERIOD)['unpaid_visits']:
            try:
                bill = invoice(c, visit['visit_id'])
            except HTTPException:
                assert visit['note'] == 'Giảm phí vượt phí, cần kiểm tra' and visit['known_due'] is None
                continue
            assert (visit['charged'], visit['paid'], visit['known_due'], visit['unpriced_count']) == (
                bill['charged'], bill['paid'], bill['known_due'], bill['unpriced_count'])
