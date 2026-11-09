"""C3 on real PostgreSQL/HTTPS; Chrome 109 CI runs this exact user workflow."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import secrets

import pymupdf
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright, expect

from .conftest import PASSWORDS, IDS
from .test_price_import import excel, headers
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle, go, pick, submit, send, no_horizontal_scroll, small_targets


def imported_service(clients):
    code, name = 'C3' + secrets.token_hex(6), 'Thủ thuật C3 giả lập ' + secrets.token_hex(6)
    content = excel([(code, name, 'Thủ thuật', None)])
    p = clients['manager'].post('/api/catalog/services/import/preview', content=content, headers=headers()).json()
    assert p['can_confirm'], p
    assert clients['manager'].post('/api/catalog/services/import/confirm', content=content, headers=headers(preview_id=p['preview_id'])).status_code == 200
    sid = next(s['id'] for s in clients['manager'].get('/api/catalog').json()['services'] if s['code'] == code)
    return sid, name


def test_c3_pg_api_guards_queue_report_and_audit(clients, visit):
    mgr, doc, cash = clients['manager'], clients['doctor'], clients['cashier']
    sid, name = imported_service(clients)
    o = doc.post('/api/orders', json={'visit_id': visit, 'category': 'procedure', 'service_id': sid, 'request_key': secrets.token_hex(12)})
    assert o.status_code == 201 and o.json()['charge_amount'] is None
    ch = next(c for c in cash.get(f'/api/charges/{visit}').json() if c['source_id'] == o.json()['id'] and c['source_type'] == 'order')
    payload = {'amount': 125000, 'description': 'Tiêm giả lập ghi rõ nội dung', 'request_key': secrets.token_hex(12)}
    for role in ('reception', 'doctor', 'technician', 'pharmacy', 'admin'):
        assert clients[role].post(f"/api/charges/{ch['id']}/manual-price", json=payload).status_code == 403
    # Thu tạm vượt 3 lần tổng khoản đã có giá (150.000 đ) mà chưa xác nhận: từ chối.
    assert cash.post('/api/payments', json={'visit_id': visit, 'amount': 2_000_000, 'method': 'cash', 'idempotency_key': secrets.token_hex(12)}).status_code == 409
    provisional = cash.post('/api/payments', json={'visit_id': visit, 'amount': 25000, 'method': 'cash', 'idempotency_key': secrets.token_hex(12)})
    assert provisional.status_code == 201 and provisional.json()['kind'] == 'provisional'
    for query in ('', '?provisional=false', '?provisional=0'):
        printed = cash.get(f"/api/print/receipt/{provisional.json()['id']}{query}")
        assert printed.status_code == 200
        with pymupdf.open(stream=printed.content, filetype='pdf') as pdf:
            assert 'PHIẾU THU TẠM' in ''.join(page.get_text() for page in pdf)
    assert cash.post(f"/api/charges/{ch['id']}/manual-price", json=payload).status_code == 200
    assert cash.post(f"/api/charges/{ch['id']}/manual-price", json={**payload, 'amount': 126000}).status_code == 409
    dues = cash.get('/api/dues').json()
    assert cash.get('/api/queue-counts').json()['cashier'] == sum(d['charged'] > d['paid'] or d['unpriced_count'] > 0 for d in dues)
    report = mgr.get('/api/reports/manual-prices').json()
    assert any(x['charge_id'] == ch['id'] and x['amount'] == 125000 and x['description'] == payload['description'] for x in report['entries'])
    audit = clients['admin'].get('/api/audit?limit=200').json()
    record = next(a for a in audit if a['event'] == 'manual_price_entered' and str(a['object_id']) == str(ch['id']))
    assert record['user_id'] == IDS['cashier'] and json.loads(record['details'])['amount'] == 125000


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('ordering_role', ['doctor', 'nurse'])
def test_c3_manual_price_browser(https_server, clients, visit, width, ordering_role):
    origin, certdir = https_server
    sid, name = imported_service(clients)
    if ordering_role == 'nurse':
        assigned = clients['doctor'].post(f'/api/visits/{visit}/nurses', json={'nurse_id': IDS['nurse']})
        assert assigned.status_code == 201, assigned.text
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence = Path('test_evidence/manual-prices'); evidence.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        expected_major = os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR')
        if expected_major:
            assert browser.version.split('.')[0] == expected_major
        contexts = {role: browser.new_context(accept_downloads=True, viewport={'width': width, 'height': 1000}) for role in (ordering_role, 'cashier', 'manager')}
        pages = {role: context.new_page() for role, context in contexts.items()}
        for role, page in pages.items():
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(origin, wait_until='networkidle')
            page.locator('[name="username"]').fill('test_' + role)
            page.locator('[name="password"]').fill(PASSWORDS[role])
            page.locator('[data-form="login"] button').click(); page.locator('#logout').wait_for(); settle(page)
        clinician = go(pages[ordering_role], ordering_role)
        pick(clinician, 'visit' if ordering_role == 'doctor' else 'nurse-visit', visit)
        clinician.locator('[data-form="order"] [name="service_id"]').select_option(str(sid))
        submitted = submit(clinician, 'order', 'CHƯA CÓ GIÁ')
        assert submitted.json()['charge_amount'] is None
        no_horizontal_scroll(clinician)
        cash = go(pages['cashier'], 'cashier')
        cash.locator('#cash_choose').select_option(str(visit)); settle(cash)
        expect(cash.locator('[data-form="payment"] button')).to_have_text('Thu tạm một phần')
        expect(cash.locator('#workspace')).to_contain_text('CHƯA CÓ GIÁ')
        # Vượt trần thu tạm (3 lần khoản đã có giá) thì hiện ô xác nhận ngay trong trang.
        cash.locator('[data-form="payment"] [name="amount"]').fill('2000000')
        expect(cash.locator('[data-form="payment"] [data-cap-confirm]')).to_be_visible()
        cash.locator('[data-form="payment"] [name="amount"]').fill('25000')
        expect(cash.locator('[data-form="payment"] [data-cap-confirm]')).to_be_hidden()
        temporary_id = submit(cash, 'payment', 'Đã thu tạm').json()['id']
        with cash.expect_download() as download:
            cash.locator(f'[data-action="export-receipt"][data-id="{temporary_id}"]').first.click()
        with pymupdf.open(stream=Path(download.value.path()).read_bytes(), filetype='pdf') as doc:
            assert 'PHIẾU THU TẠM' in ''.join(p.get_text() for p in doc)
        no_horizontal_scroll(cash)
        if width == 390:
            assert not small_targets(cash)
        cash.screenshot(path=str(evidence / f'unpriced-{ordering_role}-{width}.png'), full_page=True)
        cash.locator('[data-form="manual-price"] [name="amount"]').fill('123000')
        cash.locator('[data-form="manual-price"] [name="description"]').fill('Tiêm giả lập C3 cụ thể ' + name)
        submit(cash, 'manual-price', 'Đã nhập giá')
        # In lại phiếu thu tạm sau khi đã nhập đủ giá: vẫn là PHIẾU THU TẠM (theo loại đã lưu).
        with cash.expect_download() as download:
            cash.locator(f'[data-action="export-receipt"][data-id="{temporary_id}"]').first.click()
        with pymupdf.open(stream=Path(download.value.path()).read_bytes(), filetype='pdf') as doc:
            assert 'PHIẾU THU TẠM' in ''.join(p.get_text() for p in doc)
        expect(cash.locator('[data-form="payment"] [name="amount"]')).to_have_value('248000')
        submit(cash, 'payment', 'Đã thu tiền')
        state = clients['cashier'].get(f'/api/visits/{visit}/settlement').json()
        assert state['payment_status'] == 'settled'
        # Correction is a proposal: the paid amount stays unchanged until an independent manager approves.
        cash.locator('details').filter(has= cash.locator('[data-form="manual-price-change"]')).locator('summary').click()
        form = cash.locator('[data-form="manual-price-change"]')
        form.locator('[name="amount"]').fill('130000'); form.locator('[name="description"]').fill('Nội dung C3 đã sửa ' + name)
        form.locator('[name="reason"]').fill('Đối soát lại thủ thuật giả lập C3')
        rid = submit(cash, 'manual-price-change', 'chờ quản lý duyệt').json()['id']
        manager = go(pages['manager'], 'manager')
        send(manager, manager.locator(f'[data-action="review-manual-price"][data-id="{rid}"][data-value="approve"]'), 'Đã xử lý đề nghị')
        assert clients['cashier'].get(f'/api/visits/{visit}/settlement').json()['billing']['due'] == 7000
        manager.get_by_role('tab', name='Báo cáo', exact=True).click(); settle(manager)
        expect(manager.locator('#workspace')).to_contain_text('Khoản giá nhập tay')
        expect(manager.locator('#workspace')).to_contain_text('Nội dung C3 đã sửa ' + name)
        no_horizontal_scroll(manager)
        manager.screenshot(path=str(evidence / f'report-{ordering_role}-{width}.png'), full_page=True)
        cash = go(cash, 'cashier'); cash.locator('#cash_choose').select_option(str(visit)); settle(cash)
        expect(cash.locator('[data-form="payment"] [name="amount"]')).to_have_value('7000')
        last_id = submit(cash, 'payment', 'Đã thu tiền').json()['id']
        with cash.expect_download() as download:
            cash.locator(f'[data-action="export-receipt"][data-id="{last_id}"]').first.click()
        assert Path(download.value.path()).read_bytes().startswith(b'%PDF')
        assert clients['cashier'].get(f'/api/visits/{visit}/settlement').json()['payment_status'] == 'settled'
        (evidence / f'browser-{ordering_role}-{width}.json').write_text(json.dumps({'version': browser.version, 'width': width, 'errors': errors}))
        assert not errors
        for context in contexts.values():
            context.close()
        browser.close()
