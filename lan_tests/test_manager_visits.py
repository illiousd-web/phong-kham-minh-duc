"""C3c trên PostgreSQL/HTTPS thật: Quản lý → Lượt khám tra lại được lượt cũ đã thu đủ.

Job Chromium 109 chạy đúng luồng trình duyệt này. Chỉ dữ liệu giả lập.
"""
import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymupdf
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright, expect

from .conftest import PASSWORDS, IDS, SERVICE, client_for
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle, go, pick, send, no_horizontal_scroll, small_targets
from tests import manager_visits_cases as cases

ROLES = ('manager', 'admin', 'reception', 'doctor', 'technician', 'nurse', 'pharmacy', 'cashier')


@pytest.fixture
def api():
    clients = {role: client_for(role) for role in ROLES}
    clients[None] = client_for()
    get = lambda role, path: clients[role].get(path)
    post = lambda role, path, body: clients[role].post(path, json=body)
    yield get, post
    for client in clients.values():
        client.close()


def test_c3c_pg_search_filters_pages_and_roles(api):
    get, post = api
    target, _, _ = cases.old_settled_visit_is_found(get, post, SERVICE, IDS['doctor'])
    cases.money_filters_are_exact(get, post)
    cases.pagination_is_exact(get, post)
    cases.only_manager_may_read(get, target)


@pytest.mark.parametrize('width', [1440, 390])
def test_c3c_browser_find_and_open_old_visit(https_server, api, width):
    get, post = api
    target, name, tag = cases.old_settled_visit_is_found(get, post, SERVICE, IDS['doctor'])
    old_day = get('manager', f'/api/manager/visits/{target}').json()['visit']['created_at']
    since = (datetime.fromisoformat(old_day).astimezone(cases.VN) - timedelta(days=3)).strftime('%d/%m/%Y')
    payment_id = get('manager', f'/api/manager/visits/{target}').json()['payments'][0]['id']
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence = Path('test_evidence/manager-visits'); evidence.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        expected_major = os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR')
        if expected_major:
            assert browser.version.split('.')[0] == expected_major
        context = browser.new_context(accept_downloads=True, viewport={'width': width, 'height': 1000})
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(origin, wait_until='networkidle')
        page.locator('[name="username"]').fill('test_manager')
        page.locator('[name="password"]').fill(PASSWORDS['manager'])
        page.locator('[data-form="login"] button').click(); page.locator('#logout').wait_for(); settle(page)
        go(page, 'manager')
        page.get_by_role('tab', name='Lượt khám', exact=True).click(); settle(page)
        # Mặc định 7 ngày gần nhất, ngày hiện dd/mm/yyyy theo giờ Việt Nam.
        today = datetime.now(cases.VN).date()
        expect(page.locator('#vs_from')).to_have_value((today - timedelta(days=6)).strftime('%d/%m/%Y'))
        expect(page.locator('#vs_to')).to_have_value(today.strftime('%d/%m/%Y'))
        # Tìm theo tên trong 7 ngày: không thấy lượt 30 ngày trước, có hướng dẫn sửa Từ ngày.
        page.locator('#vs_q').fill(name)
        with page.expect_response(lambda r: '/api/manager/visits?' in r.url) as first:
            page.locator('[data-form="mgr-visit-search"] button.btn').click()
        assert first.value.status == 200 and first.value.json()['total'] == 0
        settle(page)
        expect(page.locator('#workspace')).to_contain_text('Lượt cũ hơn: sửa ô Từ ngày')
        # Ngày sai: báo lỗi tiếng Việt, không gửi.
        page.locator('#vs_from').fill('31/02/2026')
        page.locator('[data-form="mgr-visit-search"] button.btn').click()
        expect(page.locator('#toast')).to_contain_text('Từ ngày không có thật')
        # Mở rộng Từ ngày và tìm lại.
        page.locator('#vs_from').fill(since)
        with page.expect_response(lambda r: '/api/manager/visits?' in r.url) as found:
            page.locator('[data-form="mgr-visit-search"] button.btn').click()
        body = found.value.json()
        assert [x['visit_id'] for x in body['items']] == [target] and body['total'] == 1
        settle(page)
        expect(page.locator('#mgr-visit-count')).to_contain_text('1 lượt')
        expect(page.locator('#vs_from')).to_have_value(since)
        expect(page.locator('#vs_q')).to_have_value(name)
        row = page.locator('#workspace tr').filter(has_text=f'#{target}')
        expect(row).to_contain_text('Đã đủ')
        no_horizontal_scroll(page)
        pick(page, 'mgr-visit', target)
        detail = page.locator('#mgr-visit-detail')
        expect(detail).to_contain_text(name)
        expect(detail).to_contain_text(f'lượt #{target}')
        expect(page.locator('#workspace')).to_contain_text('Bảng kê và điều chỉnh giá')
        expect(page.locator('#workspace')).to_contain_text('Phiếu thu của lượt')
        with page.expect_download() as download:
            page.locator(f'[data-action="export-receipt"][data-id="{payment_id}"]').first.click()
        with pymupdf.open(stream=Path(download.value.path()).read_bytes(), filetype='pdf') as doc:
            assert 'PHIẾU THU' in ''.join(p.get_text() for p in doc)
        no_horizontal_scroll(page)
        if width == 390:
            assert not small_targets(page)
        page.screenshot(path=str(evidence / f'manager-visit-detail-{width}.png'), full_page=True)
        # Lọc tình trạng tiền trên giao diện: "Còn nợ" không có lượt đã thu đủ này.
        page.locator('#vs_money').select_option('owing')
        with page.expect_response(lambda r: '/api/manager/visits?' in r.url) as owing:
            page.locator('[data-form="mgr-visit-search"] button.btn').click()
        assert 'money=owing' in owing.value.url and owing.value.json()['total'] == 0
        settle(page)
        expect(page.locator('#mgr-visit-detail')).to_have_count(0)
        no_horizontal_scroll(page)
        if width == 390:
            assert not small_targets(page)
        page.screenshot(path=str(evidence / f'manager-visits-{width}.png'), full_page=True)
        (evidence / f'browser-{width}.json').write_text(json.dumps({'version': browser.version, 'width': width, 'errors': errors}))
        assert not errors
        context.close()
        browser.close()
