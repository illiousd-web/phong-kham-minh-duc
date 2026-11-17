"""Imaging orders expose the structured report only, before and after creation."""
import base64
import hashlib
import os
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright, expect
import pytest

from tests.s2c_cases import new_visit
from .conftest import IDS, PASSWORDS, SERVICE
from .test_tls_chrome_compat import https_server as https_server
from .browser_helpers import settle, pick, no_horizontal_scroll


@pytest.mark.parametrize('width',[1366,390])
@pytest.mark.parametrize('category,code',[('ultrasound','S2D-001'),('xray','S2D-013')])
def test_imaging_orders_never_show_legacy_result_or_attachment_form(https_server,clients,width,category,code):
    vid=new_visit(clients,IDS,SERVICE)
    tag=secrets.token_hex(6)
    service=clients['admin'].post('/api/catalog/services',json={'name':'Giao diện hình ảnh giả lập '+tag,'category':category,'price':1000})
    assert service.status_code==201,service.text
    order=clients['doctor'].post('/api/orders',json={'visit_id':vid,'category':category,'service_id':service.json()['id'],'request_key':tag})
    assert order.status_code==201,order.text
    oid=order.json()['id']
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':900})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin)
            page.locator('[name=username]').fill('test_technician')
            page.locator('[name=password]').fill(PASSWORDS['technician'])
            page.locator('[data-form=login] button').click()
            page.locator('.account-trigger').wait_for();settle(page)
            for created in (False,True):
                pick(page,'order',oid)
                expect(page.locator('[data-form=result]')).to_have_count(0)
                expect(page.locator('[data-form=attach]')).to_have_count(0)
                button=page.locator(f'[data-s2d-order="{oid}"]')
                expect(button).to_have_text('Mở phiếu Siêu âm/X-quang')
                button.click()
                dialog=page.locator('.s2d-dialog')
                if not created:
                    dialog.locator('[data-s2d-template]').select_option(code)
                    dialog.locator('[data-s2d-create]').click()
                else:
                    dialog.locator('[data-s2d-read]').first.click()
                expect(dialog.locator('[data-s2d-row="0"]')).to_be_visible()
                dialog.locator('[data-s2d-close]').click()
                page.reload();settle(page)
            no_horizontal_scroll(page)
            assert not errors,errors
        finally:
            browser.close()
