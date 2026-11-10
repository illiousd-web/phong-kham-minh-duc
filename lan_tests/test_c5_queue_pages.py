"""Hàng chờ thu ngân phân trang vẫn chứa đủ mọi lượt nợ cũ qua HTTPS/Chromium."""
import base64
import hashlib
import os
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright,expect

from .conftest import db,IDS,PASSWORDS,client_for
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle,pick,no_horizontal_scroll


def test_cashier_pages_keep_all_old_debts_selectable(https_server):
    visits=[];patient=None
    try:
        with db(True) as c:
            c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES(?,?,'Nữ',?)",
                      ('C5-'+secrets.token_hex(6),'Giả lập phân trang thu ngân C5','2024-01-01T00:00:00+00:00'))
            patient=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for _ in range(205):
                c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)",
                          (patient,IDS['doctor'],IDS['reception'],'2024-01-01T00:00:00+00:00'))
                vid=c.execute('SELECT last_insert_rowid()').fetchone()[0];visits.append(vid)
                c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,'Giả lập C5',1000,?)",(vid,'2024-01-01T00:00:00+00:00'))
        with client_for('cashier') as api:
            expected=[x['visit_id'] for x in api.get('/api/dues').json() if x['charged']>x['paid'] or x['unpriced_count']>0]
        assert set(visits)<=set(expected)
        origin,certdir=https_server
        certificate=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
        pin=base64.b64encode(hashlib.sha256(certificate.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
        errors=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
                args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
            if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):
                assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
            page=browser.new_page(viewport={'width':390,'height':844})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(origin)
            page.locator('[name="username"]').fill('test_cashier');page.locator('[name="password"]').fill(PASSWORDS['cashier'])
            page.locator('[data-form="login"] button').click();page.locator('#logout').wait_for();settle(page)
            found=[]
            while True:
                rows=page.locator('[data-action="pick"][data-kind="cash"]')
                ids=[int(x) for x in rows.evaluate_all('els=>els.map(e=>e.dataset.id)')]
                assert len(ids)<=100;found.extend(ids)
                if visits[0] in ids:
                    pick(page,'cash',visits[0])
                    expect(page.locator('[data-form="payment"] [name="visit_id"]')).to_have_value(str(visits[0]))
                    expect(page.locator('[data-form="payment"] [name="amount"]')).to_have_value('1000')
                no_horizontal_scroll(page)
                following=page.locator('[data-action="cash-page"]').filter(has_text='Trang sau')
                if not following.count():break
                following.click();settle(page)
            assert found==expected and len(found)==len(set(found))
            previous=page.locator('[data-action="cash-page"]').filter(has_text='Trang trước')
            assert previous.count()==1;previous.click();settle(page)
            assert not errors
            browser.close()
    finally:
        if visits:
            marks=','.join('?' for _ in visits)
            with db(True) as c:
                c.execute('DELETE FROM charges WHERE visit_id IN ('+marks+')',visits)
                c.execute('DELETE FROM visits WHERE id IN ('+marks+')',visits)
                c.execute('DELETE FROM patients WHERE id=?',(patient,))
