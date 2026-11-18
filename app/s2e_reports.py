"""Read-only management reports; local-day grouping matches the stock ledger (UTC+7)."""
from datetime import datetime
from io import BytesIO

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from .labels import local_day, VN_TZ, vi, METHOD
from .resources import export_slot
from .stock import period
from .domain import invoice


NOTE = 'Số liệu theo giá hiện hành tại thời điểm xuất báo cáo; khoản sửa giá được tính vào ngày phát sinh khoản phí.'
UNPRICED_WARNING = 'Còn khoản chưa nhập giá, doanh thu chưa đầy đủ'


def day(stamp):
    return local_day(stamp)[:10]


def local_stamp(stamp):
    if not stamp:
        return ''
    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    return parsed.astimezone(VN_TZ).strftime('%Y-%m-%d %H:%M:%S') if parsed.tzinfo else parsed.strftime('%Y-%m-%d %H:%M:%S')


def in_period(stamp, start, end):
    return bool(stamp) and start <= day(stamp) <= end


def revenue_report(c, start, end):
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

    # Daily outstanding is an accounting flow; actual debt comes from a whole-visit invoice.
    unpaid_visits = []
    for visit in c.execute("""SELECT v.id,v.created_at,p.code AS patient_code,
        p.full_name AS patient_name FROM visits v JOIN patients p ON p.id=v.patient_id
        WHERE v.status <> 'cancelled' ORDER BY v.created_at,v.id"""):
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
    if totals['unpriced_count'] > 0:
        result['warning'] = UNPRICED_WARNING
    return result


def visits_report(c, start, end):
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


def cashier_report(c, start, end):
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


def corrections_report(c, start, end):
    rows = []

    def collect(sql, kind):
        for event in c.execute(sql):
            if not in_period(event['occurred_at'], start, end):
                continue
            item = dict(type=kind, patient_code=event['patient_code'],
                        content=event['content'], actor=event['actor'],
                        occurred_at=local_stamp(event['occurred_at']), reason=event['reason'])
            for extra in ('medicine_name', 'quantity', 'status'):
                if extra in event.keys():
                    item[extra] = event[extra]
            rows.append(item)

    collect("""SELECT p.code AS patient_code,ch.label AS content,u.full_name AS actor,
        cv.created_at AS occurred_at,cv.reason FROM charge_voids cv
        JOIN charges ch ON ch.id=cv.charge_id JOIN visits v ON v.id=ch.visit_id
        JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=cv.approved_by""", 'Hủy khoản thu')
    collect("""SELECT p.code AS patient_code,rx.drug_lines AS content,u.full_name AS actor,
        x.created_at AS occurred_at,x.reason FROM prescription_cancellations x
        JOIN prescriptions rx ON rx.id=x.prescription_id JOIN visits v ON v.id=rx.visit_id
        JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=x.actor_id""", 'Hủy đơn thuốc')
    collect("""SELECT p.code AS patient_code,o.name AS content,u.full_name AS actor,
        x.reviewed_at AS occurred_at,x.reason FROM order_cancel_requests x
        JOIN orders o ON o.id=x.order_id JOIN visits v ON v.id=o.visit_id
        JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=x.reviewed_by
        WHERE x.status='approved' AND o.status='cancelled'""", 'Hủy chỉ định')
    collect("""SELECT p.code AS patient_code,rx.local_code AS content,u.full_name AS actor,
        rx.cancelled_at AS occurred_at,rx.cancellation_reason AS reason
        FROM clinical_prescriptions rx JOIN visits v ON v.id=rx.visit_id
        JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=rx.doctor_id
        WHERE rx.status='cancelled' AND rx.cancelled_at IS NOT NULL""", 'Hủy đơn thuốc lâm sàng')
    collect("""SELECT p.code AS patient_code,('Phiếu hình ảnh #' || CAST(r.replaces_id AS TEXT)) AS content,
        u.full_name AS actor,s.signed_at AS occurred_at,r.reason
        FROM imaging_reports r JOIN orders o ON o.id=r.order_id
        JOIN visits v ON v.id=o.visit_id JOIN patients p ON p.id=v.patient_id
        JOIN document_signatures s ON s.id=(SELECT s2.id FROM document_signatures s2
            WHERE s2.document_kind=o.category AND s2.document_id=r.id ORDER BY s2.id DESC LIMIT 1)
        JOIN users u ON u.id=s.signed_by
        WHERE r.replaces_id IS NOT NULL AND r.snapshot IS NOT NULL""", 'Đính chính hình ảnh')
    collect("""SELECT p.code AS patient_code,
        ('Giảm giá #' || CAST(a.id AS TEXT) || ': ' || CAST(a.amount AS TEXT) || ' đ') AS content,
        u.full_name AS actor,r.created_at AS occurred_at,r.reason
        FROM adjustment_reversals r JOIN adjustments a ON a.id=r.adjustment_id
        JOIN visits v ON v.id=a.visit_id JOIN patients p ON p.id=v.patient_id
        JOIN users u ON u.id=r.reversed_by WHERE a.kind='discount'""", 'Hoàn tác giảm giá')
    collect("""SELECT p.code AS patient_code,
        ('Lượt khám #' || CAST(v.id AS TEXT)) AS content,
        u.full_name AS actor,x.created_at AS occurred_at,x.reason
        FROM visit_cancellations x JOIN visits v ON v.id=x.visit_id
        JOIN patients p ON p.id=v.patient_id
        JOIN users u ON u.id=x.actor_id""", 'Hủy lượt khám')
    collect("""SELECT p.code AS patient_code,
        (m.name || ': ' || CAST(ri.quantity AS TEXT) || ' ' || m.base_unit
         || ' (' || r.status || ')') AS content,
        u.full_name AS actor,r.created_at AS occurred_at,r.reason,
        m.name AS medicine_name,ri.quantity,r.status
        FROM medication_returns r
        JOIN medication_return_items ri ON ri.return_id=r.id
        JOIN dispensation_items di ON di.id=ri.dispensation_item_id
        JOIN medicines m ON m.id=di.medicine_id
        JOIN dispensations d ON d.id=r.dispensation_id
        JOIN visits v ON v.id=d.visit_id JOIN patients p ON p.id=v.patient_id
        JOIN users u ON u.id=r.requested_by""", 'Trả thuốc')
    for kind, label in (('discount', 'Giảm giá'), ('refund', 'Hoàn tiền')):
        collect("""SELECT p.code AS patient_code,
            (a.kind || ' #' || CAST(a.id AS TEXT) || ': ' || CAST(a.amount AS TEXT) || ' đ') AS content,
            u.full_name AS actor,a.reviewed_at AS occurred_at,a.reason
            FROM effective_adjustments a JOIN visits v ON v.id=a.visit_id
            JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=a.reviewed_by
            WHERE a.status='approved' AND a.kind=?""".replace('a.kind=?', "a.kind='" + kind + "'"), label)
    rows.sort(key=lambda r: (r['occurred_at'],r['type'],r['patient_code']))
    return {'date_from': start, 'date_to': end, 'rows': rows, 'total': len(rows), 'note': NOTE}


COLS = {
    'revenue': [('day','Ngày',''),('medicine','Thuốc','n'),('clinical','Cận lâm sàng','n'),
                ('procedure','Thủ thuật','n'),('other','Khám và dịch vụ khác','n'),
                ('gross','Tổng phát sinh trước giảm','n'),
                ('discount','Giảm giá','n'),('revenue','Phát sinh sau giảm','n'),
                ('payments','Tiền thu trước hoàn','n'),('refund','Hoàn tiền','n'),
                ('paid','Đã thu thuần','n'),('outstanding','Chênh lệch trong ngày','n'),
                ('unpriced_count','Khoản chưa có giá','n')],
    'unpaid_visits': [('patient_code','Mã NB',''),('patient_name','Họ tên',''),
                     ('visit_date','Ngày khám',''),('charged','Phải thu','n'),
                     ('paid','Đã thu','n'),('known_due','Còn thiếu','n'),
                     ('unpriced_count','Khoản chưa có giá','n'),('note','Ghi chú','')],
    'visits': [('day','Ngày',''),('patient_code','Mã người bệnh',''),
               ('patient_name','Họ tên',''),('doctor_name','Bác sĩ',''),
               ('status_name','Trạng thái','')],
    'cashier': [('collected_at','Giờ thu (Việt Nam)',''),('patient_code','Mã người bệnh',''),
                ('patient_name','Họ tên',''),('amount','Số tiền','n'),
                ('method_name','Phương thức',''),('cashier_name','Người thu','')],
    'corrections': [('type','Loại',''),('patient_code','Mã người bệnh',''),
                    ('content','Nội dung',''),('actor','Người thực hiện / duyệt',''),
                    ('occurred_at','Thời gian (Việt Nam)',''),('reason','Lý do',''),
                    ('medicine_name','Tên thuốc',''),('quantity','Số lượng','n'),
                    ('status','Trạng thái yêu cầu','')],
}


def xlsx(kind, data):
    book = Workbook()
    sheet = book.active

    def add_sheet(ws, columns, rows):
        ws.append([data['note']])
        if kind == 'revenue' and data.get('warning'):
            ws.append([data['warning']])
            ws.cell(2, 1).font = Font(bold=True, color='B91C1C')
        header_row = ws.max_row + 1
        ws.append([title for _, title, _ in columns])
        for entry in rows:
            ws.append([entry.get(key, '') for key, _, _ in columns])
        ws.freeze_panes = f'A{header_row + 1}'
        ws.auto_filter.ref = f'A{header_row}:{ws.cell(header_row, len(columns)).column_letter}{ws.max_row}'
        ws.cell(1, 1).font = Font(italic=True, color='475569')
        for cells in ws.columns:
            column = cells[0].column_letter
            ws.column_dimensions[column].width = min(48, max(18, max(len(str(cell.value or '')) for cell in cells) + 2))
            for cell in cells:
                if cell.row == header_row:
                    cell.font = Font(bold=True, color='FFFFFF')
                    cell.fill = PatternFill('solid', fgColor='008249')
                elif cell.row > header_row:
                    if cell.data_type == 'f' or (isinstance(cell.value, str) and cell.value.startswith(('=', '+', '-', '@'))):
                        cell.data_type = 's'
                    if isinstance(cell.value, (int, float)):
                        cell.number_format = '#,##0'
                    cell.alignment = Alignment(vertical='top')

    sheet.title = {'revenue':'Doanh thu','visits':'Lượt khám','cashier':'Sổ thu tiền','corrections':'Sửa và hủy'}[kind]
    add_sheet(sheet, COLS[kind], data['rows'])
    if kind == 'revenue':
        total = dict(data['totals'], day='TỔNG KỲ')
        total_columns = [(key, 'Chênh lệch thu – phát sinh trong kỳ' if key == 'outstanding'
                          else label, fmt) for key, label, fmt in COLS[kind]]
        total_columns.append(('known_due', 'Chưa thu', 'n'))
        add_sheet(book.create_sheet('Tổng kỳ'), total_columns, [total])
        add_sheet(book.create_sheet('Lượt khám còn thiếu tiền'), COLS['unpaid_visits'], data['unpaid_visits'])
    if kind == 'visits':
        add_sheet(book.create_sheet('Theo ngày'), [('day','Ngày',''),('visits','Lượt khám','n'),('cancelled','Lượt hủy','n')], data['by_day'])
        add_sheet(book.create_sheet('Theo bác sĩ'), [('doctor_name','Bác sĩ',''),('visits','Lượt khám','n'),('cancelled','Lượt hủy','n')], data['by_doctor'])
        add_sheet(book.create_sheet('Theo trạng thái'), [('status_name','Trạng thái',''),('count','Số lượt','n')], data['by_status'])
    if kind == 'cashier':
        add_sheet(book.create_sheet('Theo thu ngân'), [('cashier_name','Người thu',''),('count','Số lần','n'),('amount','Tổng tiền','n')], data['by_cashier'])
        add_sheet(book.create_sheet('Theo phương thức'), [('method_name','Phương thức',''),('count','Số lần','n'),('amount','Tổng tiền','n')], data['by_method'])
    out = BytesIO()
    book.save(out)
    return out.getvalue()


REPORTS = {'revenue': revenue_report, 'visits': visits_report,
           'cashier': cashier_report, 'corrections': corrections_report}


def install_s2e_reports(app, db, principal, require):
    def read(kind, user, month, quarter, year, date_from, date_to):
        require(user, 'manager', 'admin')
        start, end = period(month, quarter, year, date_from, date_to)
        with db() as c:
            return REPORTS[kind](c, start, end)

    # Distinct functions preserve the FastAPI OpenAPI route identity and signatures.
    for kind in REPORTS:
        def route(u=Depends(principal), month: str | None = None, quarter: int | None = None,
                  year: int | None = None, date_from: str | None = None, date_to: str | None = None,
                  _kind=kind):
            return read(_kind, u, month, quarter, year, date_from, date_to)

        # _kind is captured in a parameter, never exposed to API callers.
        route.__signature__ = __import__('inspect').Signature(
            [p for name,p in __import__('inspect').signature(route).parameters.items() if name != '_kind'])
        route.__name__ = 's2e_' + kind
        app.add_api_route('/api/reports/' + kind, route, methods=['GET'])

        def exporter(u=Depends(principal), month: str | None = None, quarter: int | None = None,
                     year: int | None = None, date_from: str | None = None, date_to: str | None = None,
                     _kind=kind):
            data = read(_kind, u, month, quarter, year, date_from, date_to)
            return Response(xlsx(_kind, data),
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={'Content-Disposition': f'attachment; filename="Bao_cao_{_kind}.xlsx"'})

        exporter.__signature__ = __import__('inspect').Signature(
            [p for name,p in __import__('inspect').signature(exporter).parameters.items() if name != '_kind'])
        exporter.__name__ = 's2e_export_' + kind
        app.add_api_route('/api/reports/' + kind + '/export', export_slot(exporter), methods=['GET'])
