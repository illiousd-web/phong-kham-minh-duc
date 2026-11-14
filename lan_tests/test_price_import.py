"""Real PostgreSQL + HTTPS + Chromium upload/preview/confirm at desktop and 390px."""
import base64
import hashlib
import io
import json
import os
import re
import secrets
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from openpyxl import Workbook, load_workbook
from playwright.sync_api import sync_playwright, expect

from .conftest import PASSWORDS
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle, no_horizontal_scroll, small_targets


def excel(rows):
    w = Workbook()
    w.active.append(['Hướng dẫn: dữ liệu giả lập'])
    w.active.append(['Mã dịch vụ (không bắt buộc)', 'Tên dịch vụ', 'Nhóm', 'Giá (đồng, số nguyên ≥ 0)'])
    for row in rows:
        w.active.append(row)
    out = io.BytesIO(); w.save(out)
    return out.getvalue()


def headers(name='BANG_GIA.xlsx', preview_id=None):
    return {'X-File-Name': name, **({'X-Preview-Id': preview_id} if preview_id else {})}


def test_lan_import_atomic_permissions_and_historical_prices(clients, visit):
    mgr, doc, cash = clients['manager'], clients['doctor'], clients['cashier']
    code, name = 'LAN' + secrets.token_hex(6), 'Xét nghiệm nhập giả lập ' + secrets.token_hex(6)
    sid = mgr.post('/api/catalog/services', json={'code': code, 'name': name, 'price': 41000, 'category': 'lab'}).json()['id']
    body = {'visit_id': visit, 'category': 'lab', 'service_id': sid}
    old = doc.post('/api/orders', json={**body, 'request_key': secrets.token_hex(12)})
    assert old.json()['charge_amount'] == 41000
    draft = doc.post('/api/orders', json={**body, 'defer_approval': True, 'request_key': secrets.token_hex(12)}).json()['id']
    paid = cash.post('/api/payments', json={'visit_id': visit, 'amount': 10000, 'method': 'cash', 'idempotency_key': secrets.token_hex(12)}).json()['id']
    before = cash.get(f'/api/charges/{visit}').json()
    receipt = cash.get(f'/api/print/receipt/{paid}').content
    invalid = excel([(code, name, 'Xét nghiệm', 82000), ('BAD', '', 'Khám', -1)])
    p = mgr.post('/api/catalog/services/import/preview', content=invalid, headers=headers()).json()
    assert not p['can_confirm']
    assert mgr.post('/api/catalog/services/import/confirm', content=invalid, headers=headers(preview_id=p['preview_id'])).status_code == 422
    assert next(s['price'] for s in mgr.get('/api/catalog').json()['services'] if s['id'] == sid) == 41000
    data = excel([(code, name, 'Xét nghiệm', 82000)])
    p = mgr.post('/api/catalog/services/import/preview', content=data, headers=headers()).json()
    for role in ('reception', 'doctor', 'doctor2', 'technician', 'pharmacy', 'cashier'):
        c = clients[role]
        assert c.post('/api/catalog/services/import/preview', content=data, headers=headers()).status_code == 403
        assert c.post('/api/catalog/services/import/confirm', content=data, headers=headers(preview_id=p['preview_id'])).status_code == 403
    assert mgr.post('/api/catalog/services/import/confirm', content=data, headers=headers(preview_id=p['preview_id'])).status_code == 200
    assert cash.get(f'/api/charges/{visit}').json() == before
    # PDF metadata may vary between generations; compare printed content.
    import pymupdf
    def text(pdf):
        with pymupdf.open(stream=pdf, filetype='pdf') as document:
            value = ''.join(p.get_text() for p in document)
        return re.sub(r'Ngày in:\s*\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}', 'Ngày in: [thời điểm in]', value)
    assert text(cash.get(f'/api/print/receipt/{paid}').content) == text(receipt)
    assert doc.post(f'/api/orders/{draft}/authorize').json()['charge_amount'] == 41000
    assert doc.post('/api/orders', json={**body, 'request_key': secrets.token_hex(12)}).json()['charge_amount'] == 82000
    assert mgr.post('/api/catalog/services/import/preview', content=data, headers=headers()).json()['rows'][0]['status'] == 'KHÔNG ĐỔI'


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('role', ['manager', 'admin'])
def test_price_import_browser(https_server, clients, width, role):
    origin, certdir = https_server
    code, name = 'UI' + secrets.token_hex(5), 'Giá giao diện giả lập ' + secrets.token_hex(5)
    service = clients['manager'].post('/api/catalog/services', json={'code': code, 'name': name, 'price': 32000, 'category': 'lab'})
    assert service.status_code == 201
    new_code = 'NEWUI' + secrets.token_hex(4)
    data = excel([(code, name, 'Xét nghiệm', 64000), (new_code, 'Khám giao diện ' + new_code, 'Khám', 0)])
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence = Path('test_evidence/price-import'); evidence.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        expected_major = os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR')
        if expected_major:
            assert browser.version.split('.')[0] == expected_major
        context = browser.new_context(accept_downloads=True, viewport={'width': width, 'height': 1000})
        page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(origin, wait_until='networkidle')
        page.locator('[name="username"]').fill('test_' + role)
        page.locator('[name="password"]').fill(PASSWORDS[role])
        page.locator('[data-form="login"] button').click(); page.locator('.account-trigger').wait_for(); settle(page)
        if role == 'manager':
            page.get_by_role('tab', name='Nhập bảng giá', exact=True).click(); settle(page)
        else:
            page.locator('[data-page="price-management"]').click(); settle(page)
        with page.expect_download() as download:
            page.get_by_role('button', name='Tải tệp mẫu', exact=True).click()
        assert download.value.suggested_filename == 'BANG_GIA.xlsx'
        assert len(load_workbook(io.BytesIO(Path(download.value.path()).read_bytes())).sheetnames) == 1
        file = {'name': 'BANG_GIA.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': data}
        page.locator('#price-file').set_input_files(file)
        with page.expect_response(lambda r: r.url.endswith('/import/preview')) as response:
            page.get_by_role('button', name='Xem trước', exact=True).click()
        assert response.value.status == 200; settle(page)
        expect(page.locator('#workspace')).to_contain_text('ĐỔI GIÁ')
        expect(page.locator('#workspace')).to_contain_text('THÊM MỚI')
        expect(page.locator('#workspace')).to_contain_text('32.000 đ → 64.000 đ')
        expect(page.locator('#workspace')).to_contain_text('Dịch vụ trong hệ thống không có trong tệp')
        no_horizontal_scroll(page)
        if width == 390:
            assert not small_targets(page)
        page.screenshot(path=str(evidence / f'preview-{role}-{width}.png'), full_page=True)
        with page.expect_response(lambda r: r.url.endswith('/import/confirm')) as response:
            page.get_by_role('button', name='Xác nhận nhập bảng giá', exact=True).click()
        assert response.value.status == 200; settle(page)
        expect(page.locator('#workspace [role="status"]')).to_contain_text('Đã nhập 2 dòng: 1 thêm mới, 1 đổi giá, 0 không đổi.')
        # Same workbook uploaded again is entirely unchanged.
        page.locator('#price-file').set_input_files(file)
        with page.expect_response(lambda r: r.url.endswith('/import/preview')):
            page.get_by_role('button', name='Xem trước', exact=True).click()
        settle(page)
        expect(page.locator('#workspace tbody b')).to_have_text(['KHÔNG ĐỔI', 'KHÔNG ĐỔI'])
        bad = excel([(code, name, 'Xét nghiệm', -1)])
        page.locator('#price-file').set_input_files({**file, 'buffer': bad})
        assert page.get_by_role('button', name='Xác nhận nhập bảng giá', exact=True).count() == 0
        with page.expect_response(lambda r: r.url.endswith('/import/preview')):
            page.get_by_role('button', name='Xem trước', exact=True).click()
        settle(page)
        expect(page.locator('#workspace')).to_contain_text('LỖI')
        assert page.get_by_role('button', name='Xác nhận nhập bảng giá', exact=True).count() == 0
        no_horizontal_scroll(page)
        # An empty fixed-price field must never silently become a free service.
        if role == 'admin':
            page.locator('#navigation [data-page="admin"]').click(); settle(page)
        page.get_by_role('tab', name='Danh mục', exact=True).click(); settle(page)
        catalogue_form = page.locator('[data-form="service"]')
        catalogue_name = 'Giá nhập tay danh mục ' + secrets.token_hex(5)
        catalogue_form.locator('[name="name"]').fill(catalogue_name)
        catalogue_form.locator('button').click()
        expect(page.locator('#toast')).to_contain_text('Giá cố định không được để trống')
        assert not any(s['name'] == catalogue_name for s in clients['manager'].get('/api/catalog').json()['services'])
        catalogue_form.locator('[name="price_at_collection"]').select_option('1')
        with page.expect_response(lambda r: r.url.endswith('/api/catalog/services') and r.request.method == 'POST') as saved:
            catalogue_form.locator('button').click()
        assert saved.value.status == 201; settle(page)
        assert next(s for s in clients['manager'].get('/api/catalog').json()['services'] if s['name'] == catalogue_name)['price_at_collection'] == 1
        catalogue_form = page.locator('[data-form="service"]')
        catalogue_form.locator('[name="name"]').fill(catalogue_name + ' giá 0')
        catalogue_form.locator('[name="price"]').fill('0')
        with page.expect_response(lambda r: r.url.endswith('/api/catalog/services') and r.request.method == 'POST') as saved:
            catalogue_form.locator('button').click()
        assert saved.value.status == 201; settle(page)
        fixed = next(s for s in clients['manager'].get('/api/catalog').json()['services'] if s['name'] == catalogue_name + ' giá 0')
        assert fixed['price'] == 0 and fixed['price_at_collection'] == 0
        (evidence / f'browser-{role}-{width}.json').write_text(json.dumps({'version': browser.version, 'width': width, 'errors': errors}))
        assert not errors
        context.close(); browser.close()
