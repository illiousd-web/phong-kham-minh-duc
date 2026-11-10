"""C4: một ngày giả lập, PostgreSQL thật, mọi nghiệp vụ đi qua HTTPS.

Sổ kỳ vọng được tính từ tệp giá/đơn/số tiền kịch bản, không gọi domain.invoice.
Chỉ sửa đồng hồ của hai lượt ranh giới trong CSDL dùng một lần; không seed
phiếu thu, số dư, tồn, quyền hoặc trạng thái nghiệp vụ bằng SQL.
Chạy cả file trong job Chromium 109; không mock, xfail hoặc bỏ qua sai lệch.
"""
import base64
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import serialization
import httpx
import pymupdf
import pytest
from playwright.sync_api import expect, sync_playwright

from .conftest import IDS, PASSWORDS, db
from .browser_helpers import go, pick, send, settle, submit
from .test_price_import import excel, headers
from .test_tls_chrome_compat import https_server


VN = timezone(timedelta(hours=7))
EVIDENCE = Path('test_evidence/mot-ngay-kham')
GROUPS = [('Khám', 'consultation'), ('Xét nghiệm', 'lab'),
          ('Siêu âm', 'ultrasound'), ('X-quang', 'xray'),
          ('Điện tim', 'ecg'), ('Thủ thuật', 'procedure')]
ROLES = ('reception', 'nurse', 'doctor', 'technician', 'cashier', 'pharmacy', 'manager', 'admin')


def ok(response, status=200):
    assert response.status_code == status, (response.request.method, response.url, response.status_code, response.text)
    return response.json()


def pdf_text(path, title, patient):
    content = Path(path).read_bytes()
    assert content.startswith(b'%PDF-'), path
    with pymupdf.open(stream=content, filetype='pdf') as document:
        assert not document.is_encrypted and len(document) > 0
        text = ''.join(page.get_text() for page in document)
    assert title in text and patient in text, (path, text)
    if title == 'PHIẾU THU':
        assert 'PHIẾU THU TẠM' not in text and 'PHIẾU THU TIỀN ỨNG TRƯỚC' not in text
    return text


def search_manager(page):
    # Tìm kiếm là GET, không dùng submit() dành cho nghiệp vụ POST/PUT.
    with page.expect_response(lambda r: '/api/manager/visits?' in r.url and r.request.method == 'GET') as response:
        page.locator('[data-form="mgr-visit-search"] button.btn').click()
    assert response.value.status == 200, response.value.text()
    result = response.value.json()
    settle(page)
    return result


class Day:
    def __init__(self, clients, pages):
        self.clients, self.pages = clients, pages
        self.tag = 'C4' + secrets.token_hex(5)
        self.today = datetime.now(VN).date()
        self.yesterday = self.today - timedelta(days=1)
        self.visits, self.medicines, self.lots = [], [], {}
        self.audit_expected = []
        self.baseline = ok(clients['manager'].get('/api/overview'))
        self.report_before = {day: self.report(day) for day in (self.today, self.yesterday)}

    def call(self, role, method, path, payload=None, status=200, **kwargs):
        return ok(self.clients[role].request(method, path, json=payload, **kwargs), status)

    def audit(self, event, object_type, ident, role):
        self.audit_expected.append((event, object_type, str(ident), IDS[role]))

    def report(self, day):
        return ok(self.clients['manager'].get('/api/reports/manual-prices', params={'day': day.strftime('%d/%m/%Y')}))

    def setup_catalog_and_stock(self):
        rows = []
        for group_no, (label, category) in enumerate(GROUPS):
            for n in range(5):
                index = group_no * 5 + n
                price = None if index in (9, 24) else 20001 + index * 1003
                rows.append((self.tag + str(index), f'{self.tag} dịch vụ giả lập {index}', label, price))
        content = excel(rows)
        (EVIDENCE / 'bang-gia-30-dich-vu.xlsx').write_bytes(content)
        preview = ok(self.clients['manager'].post('/api/catalog/services/import/preview', content=content, headers=headers()))
        assert preview['can_confirm'] and len(preview['rows']) == 30, preview
        result = ok(self.clients['manager'].post('/api/catalog/services/import/confirm', content=content,
                    headers=headers(preview_id=preview['preview_id'])))
        assert result == {'rows': 30, 'added': 30, 'changed': 0, 'unchanged': 0}
        catalog = self.call('manager', 'GET', '/api/catalog')['services']
        self.services = []
        for code, name, label, price in rows:
            service = next(s for s in catalog if s['code'] == code)
            assert service['name'] == name
            assert bool(service['price_at_collection']) == (price is None)
            assert service['price'] == (price or 0)
            self.services.append({**service, 'expected_price': price})
            self.audit('service_added_from_import', 'service', service['id'], 'manager')
        assert Counter(s['category'] for s in self.services) == Counter({c: 5 for _, c in GROUPS})
        for n in range(5):
            mid = self.call('manager', 'POST', '/api/catalog/medicines',
                            {'name': f'{self.tag} thuốc giả lập {n}', 'base_unit': 'viên'}, 201)['id']
            price = 1001 + 137 * n
            self.call('manager', 'PUT', f'/api/medicines/{mid}/price', {'unit_price': price})
            self.medicines.append((mid, price))
            self.audit('medicine_created', 'medicine', mid, 'manager')
            self.audit('medicine_price_changed', 'medicine', mid, 'manager')
            # Nhập lô xa hạn trước: FEFO không được nhầm với FIFO hoặc thứ tự ID.
            for days, qty in ([(400, 200), (100, 7)] if n == 0 else [(400, 200)]):
                expiry = (self.today + timedelta(days=days)).isoformat()
                result = self.call('pharmacy', 'POST', '/api/stock/receipts',
                                   {'medicine_id': mid, 'lot_number': f'{self.tag}-{n}-{days}',
                                    'expiry_date': expiry, 'quantity': qty}, 201)
                lid = result['stock_lot_id']
                self.lots[lid] = {'medicine_id': mid, 'expiry': expiry, 'initial': qty, 'remaining': qty}
                self.audit('stock_received_demo', 'stock_lot', lid, 'pharmacy')

    def ui(self, role):
        return go(self.pages[role], {'technician': 'lab'}.get(role, role))

    def create_visit(self, index, ui=False):
        patient = f'{self.tag} bệnh nhân giả lập {index:02}'
        service = self.services[index % 5]
        payload = {'full_name': patient, 'sex': 'Nữ', 'date_of_birth': '1990-01-01', 'phone': f'090000{index:04}'}
        if ui:
            page = self.ui('reception')
            page.locator('details.inline-fold summary').click()
            form = page.locator('[data-form="patient"]')
            for name, value in {**payload, 'date_of_birth': '01/01/1990'}.items():
                field = form.locator(f'[name="{name}"]')
                field.select_option(value) if name == 'sex' else field.fill(value)
            submit(page, 'patient')
            page.locator('[data-form="visit"] [name="doctor_id"]').select_option(str(IDS['doctor']))
            page.locator('[data-form="visit"] [name="service_id"]').select_option(str(service['id']))
            vid = submit(page, 'visit').json()['id']
        else:
            pid = self.call('reception', 'POST', '/api/patients', payload, 201)['id']
            vid = self.call('reception', 'POST', '/api/visits',
                            {'patient_id': pid, 'doctor_id': IDS['doctor'], 'service_id': service['id']}, 201)['id']
        visit = {'id': vid, 'index': index, 'name': patient, 'ui': ui, 'gross': service['expected_price'],
                 'discount': 0, 'refund': 0, 'payments': [], 'unpriced': 0, 'orders': [],
                 'quantities': {}, 'cancelled': False, 'day': self.today}
        self.visits.append(visit)
        self.audit('visit_created', 'visit', vid, 'reception')
        return visit

    def medical(self, v):
        vid, ui = v['id'], v['ui']
        if ui:
            d = self.ui('doctor'); pick(d, 'visit', vid)
            d.locator('[data-form="assign-nurse"] [name="nurse_id"]').select_option(str(IDS['nurse']))
            send(d, d.locator('[data-form="assign-nurse"] button'))
            n = self.ui('nurse'); pick(n, 'nurse-visit', vid)
            n.locator('#v_pulse').fill('78'); n.locator('#v_bp').fill('120/80')
            submit(n, 'nurse-vitals')
            d = self.ui('doctor'); pick(d, 'visit', vid)
            d.locator('[data-form="clinical"] [name="diagnosis"]').fill('Chẩn đoán giả lập C4')
            submit(d, 'clinical')
        else:
            self.call('doctor', 'POST', f'/api/visits/{vid}/nurses', {'nurse_id': IDS['nurse']}, 201)
            state = self.call('nurse', 'GET', f'/api/visits/{vid}')
            self.call('nurse', 'PUT', f'/api/visits/{vid}/vitals', {'version': state['version'], 'vitals': 'Mạch 78 l/p; HA 120/80 mmHg'})
            state = self.call('doctor', 'GET', f'/api/visits/{vid}')
            self.call('doctor', 'PUT', f'/api/visits/{vid}/clinical',
                      {'version': state['version'], 'diagnosis': 'Chẩn đoán giả lập C4', 'vitals': state['vitals']})
        self.audit('nurse_assigned', 'visit', vid, 'doctor')
        self.audit('nurse_vitals_recorded', 'visit', vid, 'nurse')
        self.audit('clinical_updated', 'visit', vid, 'doctor')
        for group_no in range(1, 5):
            index = group_no * 5 + v['index'] % 4
            if v['index'] == 1 and group_no == 1:
                index = 9
            if v['index'] == 7 and group_no == 4:
                index = 24
            self.order(v, self.services[index], result=True)
        items = self.medicines[:1] if ui else self.medicines
        quantities = {mid: (3 if mid == self.medicines[0][0] else 2) for mid, _ in items}
        if ui:
            d.locator('[data-form="rx"] [name="medicine_id"]').select_option(str(items[0][0]))
            d.locator('[data-form="rx"] [name="quantity"]').fill('3')
            d.locator('[data-form="rx"] [name="directions"]').fill('Giả lập C4, không dùng điều trị')
            rid = submit(d, 'rx').json()['id']
            send(d, d.locator('[data-action="complete-visit"]'))
        else:
            rid = self.call('doctor', 'POST', '/api/prescriptions', {'visit_id': vid, 'items': [
                {'medicine_id': mid, 'quantity': qty, 'directions': 'Giả lập C4, không dùng điều trị'}
                for mid, qty in quantities.items()]}, 201)['id']
            state = self.call('doctor', 'GET', f'/api/visits/{vid}')
            self.call('doctor', 'POST', f'/api/visits/{vid}/complete', {'version': state['version']})
        v.update(rx=rid, quantities=quantities)
        self.audit('rx_draft_created', 'prescription', rid, 'doctor')
        self.audit('visit_completed', 'visit', vid, 'doctor')
        if ui:
            pharm = self.ui('pharmacy')
            dispensed = send(pharm, pharm.locator(f'[data-action="dispense"][data-id="{rid}"]')).json()
            path = EVIDENCE / f'{v["index"]}-don-thuoc.pdf'
            with pharm.expect_download() as download:
                pharm.locator(f'[data-kind="rx"][data-id="{rid}"][data-format="pdf"]').first.click()
            download.value.save_as(str(path))
            pdf_text(path, 'ĐƠN THUỐC NGOẠI TRÚ', v['name'])
        else:
            dispensed = self.call('pharmacy', 'POST', f'/api/prescriptions/{rid}/dispense', status=201)
        self.audit('rx_dispensed', 'prescription', rid, 'pharmacy')
        v['dispensed'] = dispensed
        v['gross'] += sum(qty * dict(self.medicines)[mid] for mid, qty in quantities.items())
        expected_lots = []
        for mid, qty in quantities.items():
            for lid, lot in sorted(self.lots.items(), key=lambda pair: (pair[1]['expiry'], pair[0])):
                if lot['medicine_id'] != mid or not qty:
                    continue
                take = min(qty, lot['remaining'])
                if take:
                    expected_lots.append((mid, lid, take, take * dict(self.medicines)[mid]))
                    lot['remaining'] -= take; qty -= take
            assert qty == 0
        v['expected_lots'] = expected_lots

    def order(self, v, service, result=False):
        if v['ui']:
            d = self.pages['doctor']
            d.locator('[data-form="order"] [name="service_id"]').select_option(str(service['id']))
            oid = submit(d, 'order').json()['id']
        else:
            oid = self.call('doctor', 'POST', '/api/orders', {'visit_id': v['id'], 'category': service['category'],
                            'service_id': service['id'], 'request_key': secrets.token_hex(12)}, 201)['id']
        v['orders'].append(oid)
        if service['expected_price'] is None:
            v['unpriced'] += 1
        else:
            v['gross'] += service['expected_price']
        self.audit('order_authorized', 'order', oid, 'doctor')
        if result:
            text = f'Kết luận: Kết quả {service["category"]} giả lập {self.tag}'
            if v['ui']:
                t = self.ui('technician'); pick(t, 'order', oid)
                t.locator('[data-form="result"] [name="result_text"]').fill(text)
                submit(t, 'result')
                d = self.ui('doctor')
                send(d, d.locator(f'[data-action="approve"][data-id="{oid}"]'))
            else:
                self.call('technician', 'PUT', f'/api/orders/{oid}/result', {'result_text': text})
                self.call('doctor', 'POST', f'/api/orders/{oid}/approve')
            self.audit('result_submitted', 'order', oid, 'technician')
            self.audit('result_approved_demo', 'order', oid, 'doctor')
        return oid

    def pay(self, v, amount, kind='regular'):
        if v['ui']:
            c = self.ui('cashier'); c.locator('#cash_choose').select_option(str(v['id'])); settle(c)
            c.locator('[data-form="payment"] [name="amount"]').fill(str(amount))
            result = submit(c, 'payment').json()
        else:
            result = self.call('cashier', 'POST', '/api/payments', {'visit_id': v['id'], 'amount': amount,
                               'method': 'cash', 'idempotency_key': secrets.token_hex(12), 'prepayment': kind == 'advance'}, 201)
        assert result['kind'] == kind, result
        v['payments'].append({'id': result['id'], 'amount': amount, 'kind': kind})
        self.audit('payment_recorded_demo', 'payment', result['id'], 'cashier')
        if v['ui']:
            self.print_receipt(v, result['id'], 'PHIẾU THU TẠM' if kind == 'provisional' else 'PHIẾU THU')
        return result['id']

    def print_receipt(self, v, pid, title):
        c = self.pages['cashier']
        with c.expect_download() as download:
            c.locator(f'[data-action="export-receipt"][data-id="{pid}"]').first.click()
        path = EVIDENCE / f'{v["index"]}-phieu-{pid}.pdf'
        download.value.save_as(str(path))
        pdf_text(path, title, v['name'])

    def adjust(self, v, kind, amount, payment_id=None):
        if v['ui']:
            c = self.ui('cashier'); c.locator('#cash_choose').select_option(str(v['id'])); settle(c)
            form = c.locator('[data-form="adjustment"]')
            form.locator('[name="kind"]').select_option(kind)
            form.locator('[name="amount"]').fill(str(amount))
            form.locator('[name="reason"]').fill('Đối chiếu giả lập C4 đã thống nhất')
            form.locator('button.btn').click()
            expect(form.locator('[data-adjust-confirm]')).to_contain_text(f'lượt #{v["id"]}')
            aid = send(c, form.locator('button.btn')).json()['id']
            m = self.ui('manager')
            send(m, m.locator(f'[data-action="review-adjustment"][data-id="{aid}"][data-value="approve"]'))
        else:
            aid = self.call('cashier', 'POST', '/api/adjustments', {'visit_id': v['id'], 'kind': kind,
                            'amount': amount, 'payment_id': payment_id, 'reason': 'Đối chiếu giả lập C4 đã thống nhất'}, 201)['id']
            self.call('manager', 'POST', f'/api/adjustments/{aid}/review', {'approve': True})
        v[kind] += amount
        self.audit('adjustment_requested', 'adjustment', aid, 'cashier')
        self.audit('adjustment_approved', 'adjustment', aid, 'manager')

    def collect(self, v):
        index = v['index']
        if index == 1:
            provisional = self.pay(v, 10007, 'provisional')
            c = self.pages['cashier']
            form = c.locator('[data-form="manual-price"]')
            cid = int(form.locator('[name="charge_id"]').input_value())
            form.locator('[name="amount"]').fill('73123')
            form.locator('[name="description"]').fill('Xét nghiệm giả lập C4 nhập giá cụ thể')
            submit(c, 'manual-price')
            v['gross'] += 73123; v['unpriced'] = 0
            self.audit('manual_price_entered', 'charge', cid, 'cashier')
            self.print_receipt(v, provisional, 'PHIẾU THU TẠM')
        elif index == 2:
            self.adjust(v, 'discount', 12347)
        elif index == 3:
            self.pay(v, 10009); self.pay(v, 23011)
        elif index == 4:
            return  # Nợ toàn bộ.
        elif index == 5:
            pid = self.pay(v, v['gross'])
            self.adjust(v, 'discount', 17021)
            self.adjust(v, 'refund', 17021, pid)
            return
        elif index == 6:
            self.pay(v, 12013, 'advance')
        elif index == 7:
            # Không được coi là đã thu đủ dù đã trả toàn bộ phần giá đã biết.
            # API hiện tự phân loại thành provisional; UI chỉ có nút thu tạm.
            self.unpriced_attempt = self.clients['cashier'].post('/api/payments', json={
                'visit_id': v['id'], 'amount': v['gross'], 'method': 'cash',
                'idempotency_key': secrets.token_hex(12), 'prepayment': False})
            assert self.unpriced_attempt.status_code in (201, 409), self.unpriced_attempt.text
            if self.unpriced_attempt.status_code == 201:
                result = self.unpriced_attempt.json()
                v['payments'].append({'id': result['id'], 'amount': v['gross'], 'kind': result['kind']})
                self.audit('payment_recorded_demo', 'payment', result['id'], 'cashier')
            return
        self.pay(v, v['gross'] - v['discount'] - sum(p['amount'] for p in v['payments']))

    def cancel(self, v, after_order=False):
        if after_order:
            oid = self.order(v, self.services[5])
            rid = self.call('doctor', 'POST', f'/api/orders/{oid}/request-cancel', {'reason': 'Hủy chỉ định giả lập C4'}, 201)['id']
            self.call('manager', 'POST', f'/api/orders/cancellation-requests/{rid}/review', {'approve': True})
            self.audit('order_cancel_requested', 'order', oid, 'doctor')
            self.audit('order_cancel_approved', 'order', oid, 'manager')
        self.call('manager', 'POST', f'/api/visits/{v["id"]}/cancel', {'reason': 'Hủy lượt giả lập C4 chưa thu tiền'})
        v.update(gross=0, cancelled=True)
        self.audit('visit_cancelled', 'visit', v['id'], 'manager')

    def boundary_clock(self, v, day, hour, minute):
        # Chỉ các bản ghi thuộc lượt vừa tạo trong database clinic_test_* dùng một lần.
        timestamp = datetime.combine(day, datetime.min.time(), VN).replace(hour=hour, minute=minute).astimezone(timezone.utc).isoformat(timespec='seconds')
        with db(True) as c:
            for table, column in [('visits', 'id'), ('charges', 'visit_id'), ('payments', 'visit_id')]:
                c.execute(f'UPDATE {table} SET created_at=? WHERE {column}=?', (timestamp, v['id']))
        v['day'] = day

    @staticmethod
    def expected(v):
        charged = v['gross'] - v['discount']
        paid = sum(p['amount'] for p in v['payments']) - v['refund']
        return charged, paid, charged - paid


@pytest.fixture(scope='module')
def day(https_server):
    origin, certdir = https_server
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors = []
    with ExitStack() as stack:
        clients = {}
        for role in ROLES:
            client = stack.enter_context(httpx.Client(base_url=origin, verify=ssl.create_default_context(cafile=str(certdir / 'ca.crt')),
                                        trust_env=False, headers={'Origin': origin, 'X-Clinic-Request': '1'}))
            ok(client.post('/api/login', json={'username': 'test_' + role, 'password': PASSWORDS[role]}))
            client.headers['X-CSRF-Token'] = client.cookies['__Host-clinic-csrf']
            clients[role] = client
        cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
        pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
        p = stack.enter_context(sync_playwright())
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
                                   args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        stack.callback(browser.close)
        major = os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR')
        if major:
            assert browser.version.split('.')[0] == major, browser.version
        pages = {}
        for role in ROLES[:-1]:
            context = browser.new_context(accept_downloads=True, viewport={'width': 1440, 'height': 1000})
            stack.callback(context.close)
            page = context.new_page(); pages[role] = page
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            response = page.goto(origin)
            assert response.status == 200 and response.security_details()['protocol'] in ('TLS 1.2', 'TLS 1.3')
            page.locator('[name="username"]').fill('test_' + role)
            page.locator('[name="password"]').fill(PASSWORDS[role])
            page.locator('[data-form="login"] button').click()
            page.locator('#logout').wait_for(); settle(page)
        scenario = Day(clients, pages)
        scenario.browser_version, scenario.errors = browser.version, errors
        scenario.setup_catalog_and_stock()
        for index in range(30):
            v = scenario.create_visit(index, ui=index < 3)
            if index in (26, 27):
                scenario.cancel(v, after_order=index == 27)
            else:
                scenario.medical(v)
                scenario.collect(v)
            if index in (28, 29):
                scenario.boundary_clock(v, scenario.yesterday if index == 28 else scenario.today,
                                        23 if index == 28 else 0, 50 if index == 28 else 10)
        (EVIDENCE / 'so-doi-chieu.json').write_text(json.dumps({'chromium': browser.version,
            'today': str(scenario.today), 'visits': scenario.visits, 'lots': scenario.lots}, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        yield scenario


def test_tung_luot_khop_tung_dong(day):
    assert len(day.visits) == 30
    for v in day.visits:
        state = day.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement')
        charged, paid, due = day.expected(v)
        expected = {'gross': v['gross'], 'discount': v['discount'], 'charged': charged, 'paid': paid,
                    'unpriced_count': v['unpriced'], 'known_due': due,
                    'due': None if v['unpriced'] else due, 'refund_due': 0}
        assert state['billing'] == expected, (v, state)
        assert state['clinical_status'] == ('cancelled' if v['cancelled'] else 'completed')
        lines = day.call('cashier', 'GET', f'/api/charges/{v["id"]}')
        assert sum(x['amount'] or 0 for x in lines if not x['void_reason']) == v['gross'], (v, lines)
    overview = day.call('manager', 'GET', '/api/overview')
    assert overview['visits'] - day.baseline['visits'] == 30
    for field, position in [('charged', 0), ('paid', 1)]:
        assert overview[field] - day.baseline[field] == sum(day.expected(v)[position] for v in day.visits)


def test_bao_cao_ngay_va_hai_moc_gio_viet_nam(day):
    # Báo cáo thu tách loại là gross receipts; hoàn tiền đối chiếu riêng ở sổ lượt.
    for date in (day.yesterday, day.today):
        report = day.report(date)
        expected = {kind: {'count': 0, 'total': 0} for kind in ('regular', 'provisional', 'advance')}
        for v in day.visits:
            if v['day'] == date:
                for payment in v['payments']:
                    expected[payment['kind']]['count'] += 1
                    expected[payment['kind']]['total'] += payment['amount']
        for kind, values in expected.items():
            for field, value in values.items():
                assert report['payments'][kind][field] - day.report_before[date]['payments'][kind][field] == value, (date, kind, report, expected)
        result = day.call('manager', 'GET', '/api/manager/visits', params={
            'date_from': date.strftime('%d/%m/%Y'), 'date_to': date.strftime('%d/%m/%Y'), 'q': day.tag})
        assert {x['visit_id'] for x in result['items']} == {v['id'] for v in day.visits if v['day'] == date}
        for field, position in [('charged', 0), ('paid', 1)]:
            assert sum(x[field] for x in result['items']) == sum(day.expected(v)[position] for v in day.visits if v['day'] == date)
        gross_receipts = sum(values['total'] for values in expected.values())
        refunds = sum(v['refund'] for v in day.visits if v['day'] == date)
        assert gross_receipts - refunds == sum(day.expected(v)[1] for v in day.visits if v['day'] == date)
    assert len([v for v in day.visits if v['day'] == day.today]) == 29


def test_hang_cho_khong_thua_khong_thieu_va_chan_thu_du(day):
    expected = {v['id'] for v in day.visits if day.expected(v)[2] > 0 or v['unpriced']}
    dues = day.call('cashier', 'GET', '/api/dues')
    actual = {x['visit_id'] for x in dues if x['charged'] > x['paid'] or x['unpriced_count']}
    ids = {v['id'] for v in day.visits}
    assert actual & ids == expected
    assert day.call('cashier', 'GET', '/api/queue-counts')['cashier'] == len(actual)
    c = day.ui('cashier')
    visible = {int(x) for x in c.locator('[data-kind="cash"]').evaluate_all('els=>els.map(e=>e.dataset.id)')}
    assert visible == actual
    v = day.visits[7]
    c.locator('#cash_choose').select_option(str(v['id'])); settle(c)
    expect(c.locator('[data-form="payment"] button')).to_have_text('Thu tạm một phần')
    assert c.get_by_role('button', name='Thu tiền', exact=True).count() == 0
    state = day.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement')
    assert all(p['kind'] == 'provisional' for p in v['payments'])
    assert state['payment_status'] == 'unpriced' and state['billing']['due'] is None


def test_tu_choi_thu_du_khi_con_khoan_chua_co_gia(day):
    # Giữ nguyên tiêu chí C4: từ chối giao dịch thu đủ, không chỉ đổi loại phiếu.
    # C3 hiện trả 201/provisional. Không xfail hoặc tự sửa nghiệp vụ để làm xanh.
    response = day.unpriced_attempt
    assert response.status_code == 409, (
        'C4-01: yêu cầu thu không ứng trước khi còn khoản chưa có giá không bị từ chối; '
        f'API trả {response.status_code}: {response.text}. '
        'Cần chủ dự án chốt tiêu chí từ chối thu đủ so với tự chuyển thành THU TẠM của C3.')


def test_quan_ly_tim_du_30_luot_va_loc_tien(day):
    params = {'date_from': day.yesterday.strftime('%d/%m/%Y'), 'date_to': day.today.strftime('%d/%m/%Y'), 'q': day.tag}
    expected = {status: set() for status in ('owing', 'settled', 'unpriced', 'refund')}
    for v in day.visits:
        charged, paid, due = day.expected(v)
        status = 'unpriced' if v['unpriced'] else 'owing' if due > 0 else 'refund' if paid > charged else 'settled'
        expected[status].add(v['id'])
    result = day.call('manager', 'GET', '/api/manager/visits', params=params)
    assert result['total'] == 30 and {x['visit_id'] for x in result['items']} == {v['id'] for v in day.visits}
    m = day.ui('manager'); m.get_by_role('tab', name='Lượt khám', exact=True).click(); settle(m)
    for name, value in [('vs_from', params['date_from']), ('vs_to', params['date_to']), ('vs_q', day.tag)]:
        m.locator(f'[name="{name}"]').fill(value)
    search_manager(m)
    expect(m.locator('#mgr-visit-count')).to_contain_text('30 lượt')
    m.screenshot(path=str(EVIDENCE / 'quan-ly-30-luot.png'), full_page=True)
    for status, ids in expected.items():
        result = day.call('manager', 'GET', '/api/manager/visits', params={**params, 'money': status})
        assert result['total'] == len(ids) and {x['visit_id'] for x in result['items']} == ids
        m.locator('[name="vs_money"]').select_option(status); search_manager(m)
        visible = {int(x) for x in m.locator('[data-kind="mgr-visit"]').evaluate_all('els=>els.map(e=>e.dataset.id)')}
        assert visible == ids, (status, visible, ids)


def test_kho_theo_lo_fefo_va_luot_huy(day):
    assert len(day.medicines) == 5 and len(day.lots) == 6
    stock = {x['id']: x['quantity'] for x in day.call('pharmacy', 'GET', '/api/stock')}
    for lid, lot in day.lots.items():
        assert stock[lid] == lot['remaining'], (lid, stock[lid], lot)
        with db() as c:
            movements = [dict(x) for x in c.execute('SELECT * FROM stock_movements WHERE stock_lot_id=?', (lid,))]
        assert sum(x['quantity'] if x['movement_type'] == 'receipt' else -x['quantity'] for x in movements) == stock[lid]
        assert all(x['created_by'] == IDS['pharmacy'] for x in movements)
    for v in day.visits:
        if not v['cancelled']:
            actual = [(x['medicine_id'], x['stock_lot_id'], x['quantity'], x['amount']) for x in v['dispensed']['lots']]
            assert actual == v['expected_lots'], (v['id'], actual, v['expected_lots'])
        else:
            assert day.expected(v) == (0, 0, 0)
            with db() as c:
                assert c.execute('SELECT COUNT(*) FROM payments WHERE visit_id=?', (v['id'],)).fetchone()[0] == 0
                assert c.execute('SELECT COUNT(*) FROM dispensations WHERE visit_id=?', (v['id'],)).fetchone()[0] == 0
            response = day.clients['cashier'].post('/api/payments', json={'visit_id': v['id'], 'amount': 1,
                'method': 'cash', 'idempotency_key': secrets.token_hex(12)})
            assert response.status_code == 409, response.text
    # Lượt UI thứ ba phải vượt hết lô sớm và dùng tiếp lô xa hạn.
    assert [x[2] for x in day.visits[2]['expected_lots']] == [1, 2]


def test_nhat_ky_du_thao_tac_dung_nguoi_va_quyen_api(day):
    records, offset = [], 0
    while True:
        page = day.call('admin', 'GET', '/api/audit', params={'limit': 200, 'offset': offset})
        records.extend(page)
        if len(page) < 200:
            break
        offset += 200
    actual = Counter((a['event'], a['object_type'], str(a['object_id']), a['user_id']) for a in records)
    for key, count in Counter(day.audit_expected).items():
        assert actual[key] == count, (key, actual[key], count)
    vid = day.visits[0]['id']
    for role in ('reception', 'nurse', 'doctor', 'technician', 'pharmacy', 'admin'):
        assert day.clients[role].post('/api/payments', json={'visit_id': vid, 'amount': 1, 'method': 'cash',
            'idempotency_key': secrets.token_hex(12)}).status_code == 403
    for role in ('reception', 'nurse', 'doctor', 'technician', 'cashier', 'admin'):
        assert day.clients[role].post(f'/api/prescriptions/{day.visits[0]["rx"]}/dispense').status_code == 403
    assert day.clients['reception'].get('/api/dues').status_code == 403
    assert day.clients['reception'].get(f'/api/charges/{vid}').status_code == 403


def test_ba_luot_trinh_duyet_va_sau_pdf(day):
    assert [v['ui'] for v in day.visits] == [True] * 3 + [False] * 27
    for v in day.visits[:3]:
        pdf_text(EVIDENCE / f'{v["index"]}-don-thuoc.pdf', 'ĐƠN THUỐC NGOẠI TRÚ', v['name'])
        for payment in v['payments']:
            pdf_text(EVIDENCE / f'{v["index"]}-phieu-{payment["id"]}.pdf',
                     'PHIẾU THU TẠM' if payment['kind'] == 'provisional' else 'PHIẾU THU', v['name'])
    assert not day.errors, day.errors
    (EVIDENCE / 'trinh-duyet.json').write_text(json.dumps({'version': day.browser_version, 'errors': day.errors}), encoding='utf-8')
