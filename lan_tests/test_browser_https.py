"""Real HTTPS, two server workers, three isolated concurrent browser sessions."""
import base64
import hashlib
from io import BytesIO
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
import httpx
import pytest
from playwright.sync_api import sync_playwright
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from .conftest import ROOT,PASSWORDS,IDS,SERVICE


def test_real_https_three_browser_roles_and_pdf():
    certdir=ROOT/'certs'
    subprocess.run([sys.executable,'-m','scripts.create_lan_certificate','--name','minhduc.internal','--ip','127.0.0.1','--output',str(certdir)],check=True)
    env=os.environ.copy();env.update(CLINIC_TLS_CERT=str(certdir/'server.crt'),CLINIC_TLS_KEY=str(certdir/'server.key'))
    errors=[]
    origin=env['CLINIC_ORIGIN']
    log=ROOT/'https-server.log'
    with log.open('w') as output:
        server=subprocess.Popen([sys.executable,'-m','scripts.run_lan'],env=env,stdout=output,stderr=output)
        try:
            context=ssl.create_default_context(cafile=str(certdir/'ca.crt'))
            with httpx.Client(verify=context,trust_env=False,timeout=2) as probe:
                for _ in range(100):
                    if server.poll() is not None:pytest.fail(log.read_text())
                    try:
                        response=probe.get(origin+'/api/health')
                        if response.status_code==200:break
                    except (httpx.HTTPError,OSError):pass
                    time.sleep(0.1)
                else:pytest.fail('HTTPS server did not become ready')
                assert response.json()['mode']=='lan'
                assert response.headers['strict-transport-security']
            # Pin only this synthetic test server's public key in Chromium.
            cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
            spki=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            pin=base64.b64encode(hashlib.sha256(spki).digest()).decode()
            evidence=Path('test_evidence/lan');evidence.mkdir(parents=True,exist_ok=True)
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
                contexts={r:browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000}) for r in ('reception','doctor','cashier','technician','pharmacy','admin')}
                pages={r:c.new_page() for r,c in contexts.items()}
                for role,page in pages.items():
                    page.on('pageerror',lambda err:errors.append(str(err)))
                    page.goto(origin,wait_until='networkidle')
                    page.locator('input[name="username"]').fill('test_'+role)
                    page.locator('input[name="password"]').fill(PASSWORDS[role])
                    page.locator('[data-form="login"] button').click()
                    page.locator('#logout').wait_for(state='visible')
                    assert page.evaluate("sessionStorage.getItem('md_token')") is None
                    assert '__Host-clinic=' not in page.evaluate('document.cookie')
                def go(role,where):
                    page=pages[role];page.locator(f'[data-page="{where}"]').click()
                    page.locator('#page-title').get_by_text({'reception':'Tiếp đón','clinical':'Khám bệnh','cashier':'Thu ngân','orders':'Chỉ định / kết quả','rx':'Đơn thuốc','stock':'Kho thuốc','accounts':'Tài khoản'}[where],exact=True).wait_for()
                    return page
                r=go('reception','reception')
                r.locator('[data-form="patient"] [name="full_name"]').fill('Bệnh nhân giả lập HTTPS ba máy')
                r.locator('[data-form="patient"] button').click()
                r.get_by_text('Đã lưu bệnh nhân',exact=False).wait_for()
                # Select the newly created synthetic patient explicitly.
                patient_option=r.locator('[data-form="visit"] select[name="patient_id"] option').filter(has_text='Bệnh nhân giả lập HTTPS ba máy').first
                r.locator('[data-form="visit"] select[name="patient_id"]').select_option(patient_option.get_attribute('value'))
                r.locator('[data-form="visit"] select[name="doctor_id"]').select_option(str(IDS['doctor']))
                r.locator('[data-form="visit"] button').click()
                r.get_by_text('Đã tiếp nhận lượt khám',exact=False).wait_for()
                r.locator('[data-kind="intake"]').first.wait_for()
                vid=r.locator('[data-kind="intake"]').first.get_attribute('data-id')
                d=go('doctor','clinical')
                d.locator('select[name="visit_choose"]').select_option(vid)
                d.locator('[name="chief_complaint"]').fill('Ghi khám giả lập HTTPS')
                d.locator('[name="diagnosis"]').fill('Chẩn đoán giả lập')
                d.locator('[name="follow_up"]').fill('2027-01-01')
                d.locator('[data-form="clinical"] button.btn').click()
                d.get_by_text('Đã lưu phiếu khám',exact=False).wait_for()
                cash=go('cashier','cashier')
                # Three authenticated browser contexts stay open together.
                for role in ('reception','doctor','cashier'):
                    assert pages[role].evaluate("fetch('/api/me').then(r=>r.status)")==200
                    pages[role].screenshot(path=str(evidence/(role+'.png')),full_page=True)
                d=go('doctor','orders')
                d.locator('[data-form="order"] [name="visit_id"]').select_option(vid)
                d.locator('[data-form="order"] [name="name"]').fill('Xét nghiệm giả lập HTTPS')
                d.locator('[data-form="order"] button').click();d.get_by_text('Đã lập chỉ định',exact=False).wait_for()
                tech=pages['technician'];tech.locator('[data-page="orders"]').click()
                tech.locator('[data-form="result"] [name="result_text"]').fill('Kết quả giả lập HTTPS')
                tech.locator('[data-form="result"] button').click();tech.get_by_text('Đã chuyển kết quả',exact=False).wait_for()
                d=go('doctor','clinical');d=go('doctor','orders')
                d.locator('[data-action="approve"]').first.click();d.get_by_text('Đã duyệt quy trình mô phỏng',exact=False).wait_for()
                with d.expect_download() as download:d.locator('[data-kind="lab"][data-format="pdf"]').first.click()
                download.value.save_as(str(evidence/'result.pdf'))
                d=go('doctor','rx');d.locator('[data-form="rx"] [name="visit_id"]').select_option(vid)
                d.locator('[data-form="rx"] [name="drug_lines"]').fill('Thuốc giả lập | 2 | Không điều trị')
                d.locator('[data-form="rx"] button').click();d.get_by_text('Đã tạo đơn nháp',exact=False).wait_for()
                with d.expect_download() as download:d.locator('[data-kind="rx"][data-format="pdf"]').first.click()
                download.value.save_as(str(evidence/'rx.pdf'))
                cash.locator('[data-form="payment"] [name="visit_id"]').select_option(vid)
                cash.locator('[data-form="payment"] [name="amount"]').fill('150000')
                cash.locator('[data-form="payment"] button').click();cash.get_by_text('Đã ghi khoản thu vào cơ sở dữ liệu demo',exact=False).wait_for()
                assert (evidence/'result.pdf').read_bytes().startswith(b'%PDF-')
                assert (evidence/'rx.pdf').read_bytes().startswith(b'%PDF-')
                admin=go('admin','accounts');admin.locator('[data-form="account"]').wait_for()
                # Existing teal/white styles and logo load through HTTPS.
                assert r.locator('img').first.evaluate('(img)=>img.complete && img.naturalWidth>0')
                assert not errors,errors
                for context in contexts.values():context.close()
                browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
