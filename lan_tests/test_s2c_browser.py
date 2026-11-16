"""Real password dialog, signature image and invalidation at desktop/mobile widths."""
import base64
import hashlib
from io import BytesIO
import os

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader
import pytest

from app.database import db
from tests.s2c_cases import document, signature_image
from .conftest import IDS, PASSWORDS, SERVICE
from .test_tls_chrome_compat import https_server as https_server
from .browser_helpers import settle, pick, no_horizontal_scroll


@pytest.mark.parametrize('width', [1366, 390])
def test_s2c_sign_password_dialog_and_actual_pdf(https_server, clients, width, tmp_path):
    vid, rid, url, _ = document(clients, IDS, db, SERVICE, 'clinical_rx')
    assert clients['admin'].put(f'/api/users/{IDS["doctor"]}/signature', files={'file': ('fake.png', signature_image(), 'image/png')}).status_code == 200
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list='+pin])
        page = browser.new_page(viewport={'width': width, 'height': 900}, accept_downloads=True)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(origin)
        page.locator('[name=username]').fill('test_doctor')
        page.locator('[name=password]').fill(PASSWORDS['doctor'])
        page.locator('[data-form=login] button').click()
        page.locator('.account-trigger').wait_for()
        settle(page)
        pick(page, 'visit', vid)
        page.locator('[data-action=doctor-tab][data-target=rx]').click()
        page.locator(f'[data-s2c-sign=clinical_rx][data-id="{rid}"]').click()
        dialog = page.locator('.s2c-sign-dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('input')).to_have_attribute('type', 'password')
        dialog.locator('input').fill('Mật khẩu sai giả lập')
        dialog.locator('[type=submit]').click()
        expect(dialog.locator('[role=alert]')).to_contain_text('Mật khẩu xác nhận không đúng')
        expect(dialog.locator('input')).to_have_value('')
        dialog.locator('input').fill(PASSWORDS['doctor'])
        with page.expect_response(lambda r: '/api/document-signatures/' in r.url and r.request.method == 'POST') as response:
            dialog.locator('[type=submit]').click()
        assert response.value.status == 200
        expect(dialog).to_have_count(0)
        settle(page)
        with page.expect_download() as download:
            page.locator(f'[data-m6-download="{rid}"][data-fmt=pdf]:not([data-r3-print])').click()
        path = tmp_path/'signed.pdf'
        download.value.save_as(path)
        pdf = PdfReader(BytesIO(path.read_bytes()))
        assert len(pdf.pages) == 1 and len(pdf.pages[0].images) == 2
        assert 'bởi tài khoản test_doctor' in pdf.pages[0].extract_text()
        row = page.locator('.m6-row').first
        row.locator('[name=timing]').fill('Thời điểm giả lập đã sửa')
        form = page.locator('[data-m6-form=rx]')
        with page.expect_response(lambda r: r.url.endswith('/clinical-prescriptions/'+str(rid)) and r.request.method == 'PUT'):
            form.locator('button.btn').click()
        settle(page)
        assert len(PdfReader(BytesIO(clients['doctor'].get(url).content)).pages[0].images) == 1
        no_horizontal_scroll(page)
        assert not errors, errors
        browser.close()
