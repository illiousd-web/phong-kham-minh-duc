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
import re
import secrets
import ssl
from urllib.parse import urlsplit

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


class AuditLedger:
    """Kỳ vọng độc lập: nghiệp vụ do kịch bản khai báo, đọc/truy cập theo HTTP.

    Không lấy tên sự kiện hoặc số lượng kỳ vọng từ audit_log của ứng dụng.
    Hook chỉ dùng hợp đồng cố định cho đăng nhập, đọc hồ sơ và xuất phiếu.
    """
    def __init__(self):
        with db() as c:
            self.start = c.execute('SELECT COALESCE(MAX(id),0) FROM audit_log').fetchone()[0]
        self.expected = []
        self.accesses = Counter()
        self.rx_visits = {}
        self.browser_sessions = set()

    def record(self, event, object_type, ident, role):
        self.expected.append((event, object_type, str(ident), IDS[role]))

    def http(self, role, method, url, status, cookie):
        path = urlsplit(str(url)).path
        if path == '/api/login' and method == 'POST' and status == 200:
            self.record('login_succeeded', 'session', None, role)
        if '__Host-clinic=' not in cookie or not path.startswith('/api/'):
            return
        if status != 503 and path not in ('/api/health', '/api/login', '/api/audit', '/api/queue-counts'):
            self.record('api_access', 'http', None, role)
            self.accesses[(IDS[role], f'{method} {path} {status}')] += 1
        if method != 'GET' or status != 200:
            return
        visit = re.fullmatch(r'/api/visits/(\d+)(?:/(care|revisions))?', path)
        if visit:
            vid, part = visit.groups()
            event = {'care': 'care_viewed', 'revisions': 'clinical_revisions_viewed'}.get(part)
            if not part and role == 'doctor':
                event = 'clinical_viewed'
            if event:
                self.record(event, 'visit', int(vid), role)
        receipt = re.fullmatch(r'/api/print/receipt/(\d+)', path)
        if receipt:
            self.record('form_pdf_generated_demo', 'receipt', int(receipt[1]), role)
        prescription = re.fullmatch(r'/api/forms/rx/(\d+)', path)
        if prescription:
            self.record('draft_form_exported', 'visit', self.rx_visits[int(prescription[1])], role)

    def httpx(self, role, response):
        request = response.request
        self.http(role, request.method, request.url, response.status_code, request.headers.get('cookie', ''))

    def browser(self, role, response):
        request = response.request
        if urlsplit(request.url).path == '/api/login' and response.status == 200:
            self.browser_sessions.add(role)
        # Chỉ quan sát metadata; không gọi RPC all_headers() trong callback response
        # vì vòng lặp Playwright có thể xử lý lồng các phản hồi/rerender đang chờ.
        # Mỗi context C4 đăng nhập một lần, không đăng xuất hoặc đổi tài khoản.
        cookie = '__Host-clinic=phiên-kiểm-thử' if role in self.browser_sessions else ''
        self.http(role, request.method, request.url, response.status, cookie)


def assert_audit_exact(actual, expected):
    missing, extra = Counter(expected) - Counter(actual), Counter(actual) - Counter(expected)
    assert not missing and not extra, (
        f'Nhật ký thiếu: {dict(missing)}; sự kiện lạ/thừa: {dict(extra)}; '
        f'tên sự kiện lạ/thừa: {sorted({key[0] for key in extra})}')


class Day:
    def __init__(self, clients, pages, ledger):
        self.clients, self.pages = clients, pages
        self.tag = 'C4' + secrets.token_hex(5)
        self.today = datetime.now(VN).date()
        self.yesterday = self.today - timedelta(days=1)
        self.visits, self.medicines, self.lots = [], [], {}
        self.ledger = ledger
        self.audit_expected = ledger.expected
        self.baseline = ok(clients['manager'].get('/api/overview'))
        self.report_before = {day: self.report(day) for day in (self.today, self.yesterday)}

    def call(self, role, method, path, payload=None, status=200, **kwargs):
        return ok(self.clients[role].request(method, path, json=payload, **kwargs), status)

    def audit(self, event, object_type, ident, role):
        self.ledger.record(event, object_type, ident, role)

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
        self.audit('service_prices_imported', 'service_import', None, 'manager')
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
            pid = submit(page, 'patient').json()['id']
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
        self.audit('patient_created', 'patient', pid, 'reception')
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
        if v['index'] in (8, 9):
            oid = self.order(v, self.services[25 + v['index'] % 2], result=True)
            v['procedure_order'] = oid
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
        self.ledger.rx_visits[rid] = vid
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
        self.audit('order_created', 'order', oid, 'doctor')
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
            expect(c.locator('[data-form="payment"] [name="visit_id"]')).to_have_value(str(v['id']))
            expect(c.locator('[data-form="payment"]')).to_have_attribute('data-unpriced', '1' if v['unpriced'] else '0')
            c.locator('[data-form="payment"] [name="amount"]').fill(str(amount))
            result = submit(c, 'payment').json()
        else:
            result = self.call('cashier', 'POST', '/api/payments', {'visit_id': v['id'], 'amount': amount,
                               'method': 'cash', 'idempotency_key': secrets.token_hex(12), 'prepayment': kind == 'advance'}, 201)
        assert result['kind'] == kind, result
        v['payments'].append({'id': result['id'], 'amount': amount, 'kind': kind, 'day': self.today})
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
            self.refund_before = self.refund_filter(v)
            state = self.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement')
            assert state['billing']['refund_due'] == 17021 and state['payment_status'] == 'refund_due'
            self.adjust(v, 'refund', 17021, pid)
            self.refund_after = self.refund_filter(v)
            return
        elif index == 6:
            self.pay(v, 12013, 'advance')
        elif index == 7:
            # Không được coi là đã thu đủ dù đã trả toàn bộ phần giá đã biết.
            # API hiện tự phân loại thành provisional; UI chỉ có nút thu tạm.
            self.unpriced_attempt = self.clients['cashier'].post('/api/payments', json={
                'visit_id': v['id'], 'amount': v['gross'], 'method': 'cash',
                'idempotency_key': secrets.token_hex(12), 'prepayment': False})
            result = ok(self.unpriced_attempt, 201)
            assert result['kind'] == 'provisional', result
            v['payments'].append({'id': result['id'], 'amount': v['gross'], 'kind': 'provisional', 'day': self.today})
            self.audit('payment_recorded_demo', 'payment', result['id'], 'cashier')
            return
        self.pay(v, v['gross'] - v['discount'] - sum(p['amount'] for p in v['payments']))

    def refund_filter(self, v):
        params = {'date_from': self.today.strftime('%d/%m/%Y'), 'date_to': self.today.strftime('%d/%m/%Y'),
                  'q': v['name'], 'money': 'refund'}
        api = self.call('manager', 'GET', '/api/manager/visits', params=params)
        page = self.ui('manager')
        page.get_by_role('tab', name='Lượt khám', exact=True).click(); settle(page)
        for name, value in [('vs_from', params['date_from']), ('vs_to', params['date_to']), ('vs_q', params['q'])]:
            page.locator(f'[name="{name}"]').fill(value)
        page.locator('[name="vs_money"]').select_option('refund')
        browser = search_manager(page)
        visible = {int(x) for x in page.locator('[data-kind="mgr-visit"]').evaluate_all('els=>els.map(e=>e.dataset.id)')}
        page.screenshot(path=str(EVIDENCE / f'can-hoan-{len(v["payments"])}-{v["refund"]}.png'), full_page=True)
        return {'api': api, 'browser': browser, 'visible': visible}

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

    def boundary_clock(self, v, day, hour, minute, payment_day=None):
        # Chỉ các bản ghi thuộc lượt vừa tạo trong database clinic_test_* dùng một lần.
        timestamp = datetime.combine(day, datetime.min.time(), VN).replace(hour=hour, minute=minute).astimezone(timezone.utc).isoformat(timespec='seconds')
        with db(True) as c:
            for table, column in [('visits', 'id'), ('charges', 'visit_id')]:
                c.execute(f'UPDATE {table} SET created_at=? WHERE {column}=?', (timestamp, v['id']))
            pay_time = timestamp if payment_day is None else datetime.combine(payment_day, datetime.min.time(), VN).replace(
                hour=0, minute=10).astimezone(timezone.utc).isoformat(timespec='seconds')
            c.execute('UPDATE payments SET created_at=? WHERE visit_id=?', (pay_time, v['id']))
        for payment in v['payments']:
            payment['day'] = day if payment_day is None else payment_day
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
    ledger = AuditLedger()
    with ExitStack() as stack:
        clients = {}
        for role in ROLES:
            client = stack.enter_context(httpx.Client(base_url=origin, verify=ssl.create_default_context(cafile=str(certdir / 'ca.crt')),
                                        trust_env=False, headers={'Origin': origin, 'X-Clinic-Request': '1'},
                                        event_hooks={'response': [lambda response, role=role: ledger.httpx(role, response)]}))
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
            page.on('response', lambda response, role=role: ledger.browser(role, response))
            response = page.goto(origin)
            assert response.status == 200 and response.security_details()['protocol'] in ('TLS 1.2', 'TLS 1.3')
            page.locator('[name="username"]').fill('test_' + role)
            page.locator('[name="password"]').fill(PASSWORDS[role])
            page.locator('[data-form="login"] button').click()
            page.locator('#logout').wait_for(); settle(page)
        scenario = Day(clients, pages, ledger)
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
                                        23 if index == 28 else 0, 50 if index == 28 else 10,
                                        payment_day=scenario.today)
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
            for payment in v['payments']:
                if payment['day'] == date:
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
        gross_receipts = sum(report['payments'][kind]['total'] - day.report_before[date]['payments'][kind]['total']
                             for kind in expected)
        refunds = sum(v['refund'] for v in day.visits if v['day'] == date)
        assert gross_receipts - refunds == sum(p['amount'] for v in day.visits for p in v['payments'] if p['day'] == date) - refunds
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


def test_c4_01_thu_khi_chua_co_gia_bat_buoc_la_thu_tam(day):
    # Quyết định đã chốt: nhận tiền nhưng tuyệt đối không coi là tất toán.
    response = day.unpriced_attempt
    result = ok(response, 201)
    assert result['kind'] == 'provisional'
    v = day.visits[7]
    printed = day.clients['cashier'].get(f'/api/print/receipt/{result["id"]}')
    assert printed.status_code == 200
    path = EVIDENCE / 'C4-01-thu-tam.pdf'; path.write_bytes(printed.content)
    pdf_text(path, 'PHIẾU THU TẠM', v['name'])
    due = next(x for x in day.call('cashier', 'GET', '/api/dues') if x['visit_id'] == v['id'])
    assert due['unpriced_count'] > 0
    state = day.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement')
    assert state['payment_status'] == 'unpriced' and state['billing']['due'] is None
    page = day.ui('cashier')
    assert page.locator(f'[data-kind="cash"][data-id="{v["id"]}"]').count() == 1
    page.locator('#cash_choose').select_option(str(v['id'])); settle(page)
    expect(page.locator('[data-form="payment"] button')).to_have_text('Thu tạm một phần')


def test_tu_choi_thu_vuot_sau_khi_da_nhap_du_gia(day):
    v = day.visits[1]
    before = day.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement')
    assert before['billing']['unpriced_count'] == 0 and before['billing']['due'] == 0
    pays_before = day.call('manager', 'GET', f'/api/manager/visits/{v["id"]}')['payments']
    response = day.clients['cashier'].post('/api/payments', json={'visit_id': v['id'], 'amount': 1,
        'method': 'cash', 'idempotency_key': secrets.token_hex(12)})
    assert response.status_code == 409, response.text
    assert day.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement') == before
    assert day.call('manager', 'GET', f'/api/manager/visits/{v["id"]}')['payments'] == pays_before


def test_loc_can_hoan_truoc_va_sau_khi_duyet_hoan(day):
    vid = day.visits[5]['id']
    for source in ('api', 'browser'):
        before, after = day.refund_before[source], day.refund_after[source]
        assert before['total'] == 1 and {x['visit_id'] for x in before['items']} == {vid}
        assert before['items'][0]['money_status'] == 'refund'
        assert before['items'][0]['refund_due'] == 17021
        assert after['total'] == 0 and after['items'] == []
    assert day.refund_before['visible'] == {vid} and day.refund_after['visible'] == set()


def test_luot_hom_truoc_nhung_thu_tien_hom_nay(day):
    v = day.visits[28]
    info = day.call('manager', 'GET', f'/api/manager/visits/{v["id"]}')
    created = datetime.fromisoformat(info['visit']['created_at']).astimezone(VN)
    assert created.date() == day.yesterday and (created.hour, created.minute) == (23, 50)
    assert len(info['payments']) == 1
    paid = datetime.fromisoformat(info['payments'][0]['created_at']).astimezone(VN)
    assert paid.date() == day.today and (paid.hour, paid.minute) == (0, 10)
    assert v['payments'][0]['day'] == day.today and v['day'] == day.yesterday
    # Bài báo cáo ngày ở trên kiểm toàn bộ tổng từng loại theo ngày thu độc lập ngày tạo.
    assert day.report(day.yesterday)['payments'] == day.report_before[day.yesterday]['payments']


def test_hai_luot_thu_thuat_chi_dinh_tinh_phi_thu_tien(day):
    for index in (8, 9):
        v = day.visits[index]
        order = next(x for x in day.call('doctor', 'GET', '/api/orders') if x['id'] == v['procedure_order'])
        assert order['category'] == 'procedure' and order['status'] == 'approved'
        lines = day.call('cashier', 'GET', f'/api/charges/{v["id"]}')
        charge = next(x for x in lines if x['source_type'] == 'order' and x['source_id'] == order['id'])
        assert charge['amount'] == day.services[25 + index % 2]['expected_price'] and not charge['void_reason']
        assert day.expected(v)[2] == 0 and sum(p['amount'] for p in v['payments']) == v['gross']
        assert day.call('cashier', 'GET', f'/api/visits/{v["id"]}/settlement')['payment_status'] == 'settled'


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
    m.locator('[name="vs_money"]').select_option('')
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
    vid = day.visits[0]['id']
    for role in ('reception', 'nurse', 'doctor', 'technician', 'pharmacy', 'admin'):
        assert day.clients[role].post('/api/payments', json={'visit_id': vid, 'amount': 1, 'method': 'cash',
            'idempotency_key': secrets.token_hex(12)}).status_code == 403
    for role in ('reception', 'nurse', 'doctor', 'technician', 'cashier', 'admin'):
        assert day.clients[role].post(f'/api/prescriptions/{day.visits[0]["rx"]}/dispense').status_code == 403
    assert day.clients['reception'].get('/api/dues').status_code == 403
    assert day.clients['reception'].get(f'/api/charges/{vid}').status_code == 403
    records, offset = [], 0
    while True:
        page = day.call('admin', 'GET', '/api/audit', params={'limit': 200, 'offset': offset})
        records.extend(a for a in page if a['id'] > day.ledger.start)
        if len(page) < 200 or page[-1]['id'] <= day.ledger.start:
            break
        offset += 200
    assert all(datetime.fromisoformat(a['created_at']).astimezone(VN).date() == day.today for a in records)
    actual = [(a['event'], a['object_type'], str(a['object_id']), a['user_id']) for a in records]
    (EVIDENCE / 'nhat-ky-doi-chieu.json').write_text(json.dumps(
        {'actual': records, 'expected': day.audit_expected}, ensure_ascii=False, indent=2), encoding='utf-8')
    assert_audit_exact(actual, day.audit_expected)
    access_actual = Counter((a['user_id'], a['details']) for a in records if a['event'] == 'api_access')
    assert access_actual == day.ledger.accesses, (access_actual - day.ledger.accesses, day.ledger.accesses - access_actual)
    # Chứng minh bộ đối chiếu hai chiều báo lỗi và in tên khi có sự kiện ngoài danh sách.
    with pytest.raises(AssertionError, match='su_kien_la_C4'):
        assert_audit_exact(actual + [('su_kien_la_C4', 'visit', str(vid), IDS['doctor'])], day.audit_expected)


def test_ba_luot_trinh_duyet_va_sau_pdf(day):
    assert [v['ui'] for v in day.visits] == [True] * 3 + [False] * 27
    for v in day.visits[:3]:
        pdf_text(EVIDENCE / f'{v["index"]}-don-thuoc.pdf', 'ĐƠN THUỐC NGOẠI TRÚ', v['name'])
        for payment in v['payments']:
            pdf_text(EVIDENCE / f'{v["index"]}-phieu-{payment["id"]}.pdf',
                     'PHIẾU THU TẠM' if payment['kind'] == 'provisional' else 'PHIẾU THU', v['name'])
    assert not day.errors, day.errors
    (EVIDENCE / 'trinh-duyet.json').write_text(json.dumps({'version': day.browser_version, 'errors': day.errors}), encoding='utf-8')
