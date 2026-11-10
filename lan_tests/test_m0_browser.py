"""M0 through real HTTPS; same test runs on pinned Chromium 109 in CI."""
import base64
import hashlib
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import expect, sync_playwright

from .conftest import IDS, PASSWORDS, db
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle, pick, no_horizontal_scroll


def test_m0_six_sections_keyboard_allergies_and_responsive_evidence(https_server, clients):
    reception = clients['reception']
    pid = reception.post('/api/patients', json={'full_name': 'Đặng Thị M0 giao diện giả lập', 'sex': 'Nữ',
        'date_of_birth': '1990-01-01', 'phone': '0900000109'}).json()['id']
    visits = []
    with db(True) as c:
        for _ in range(4):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
                      (pid, IDS['doctor'], IDS['reception'], '2026-11-10T00:00:00+00:00'))
            visits.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence = Path('test_evidence/m0'); evidence.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):
            assert browser.version.split('.')[0] == os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page = browser.new_page(viewport={'width': 1366, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(origin)
        page.locator('[name="username"]').fill('test_doctor'); page.locator('[name="password"]').fill(PASSWORDS['doctor'])
        page.locator('[data-form="login"] button').click(); page.locator('#logout').wait_for(); settle(page)
        # Date is explicit, independent of the clock on a CI runner.
        page.locator('[name="doctor_day"]').fill('10/11/2026')
        page.locator('[name="doctor_query"]').fill('dang thi m0 giao dien')
        page.locator('[data-form="doctor-filter"] button').click(); settle(page)
        assert page.locator('[data-kind="visit"][data-action="pick"]').count() == 4
        for width, vid in zip((1366, 1280, 900, 390), visits):
            page.set_viewport_size({'width': width, 'height': 900})
            pick(page, 'visit', vid)
            expect(page.locator('.doctor-patient')).to_contain_text('Chưa khai thác' if width == 1366 else 'Thuốc A: phát ban')
            if width == 1366:
                page.locator('[data-action="edit-allergies"]').click()
                page.locator('[name="allergy_state"]').select_option('none')
                with page.expect_response(lambda r: '/allergies' in r.url and r.request.method == 'PUT') as saved:
                    page.locator('[data-form="allergies"] button.btn').click()
                assert saved.value.status == 200; settle(page)
                expect(page.locator('.doctor-patient')).to_contain_text('Không dị ứng')
                page.locator('[data-action="edit-allergies"]').click()
                expect(page.locator('#m0-dialog')).to_be_visible()
                page.keyboard.press('Escape'); expect(page.locator('#m0-dialog')).not_to_be_visible()
                page.locator('[data-action="edit-allergies"]').click()
                page.locator('[name="allergy_state"]').select_option('known')
                page.locator('[name="allergy_text"]').fill('Thuốc A: phát ban '+('giả lập dài '*140))
                with page.expect_response(lambda r: '/allergies' in r.url and r.request.method == 'PUT'):
                    page.locator('[data-form="allergies"] button.btn').click()
                settle(page)
                page.set_viewport_size({'width': 390, 'height': 844})
                warning = page.locator('.doctor-patient .allergy-warning')
                assert warning.evaluate('el=>el.scrollHeight>el.clientHeight')
                assert warning.bounding_box()['height'] < 180
                no_horizontal_scroll(page)
                page.locator('[data-action="edit-allergies"]').click()
                page.locator('[name="allergy_text"]').fill('Thuốc A: phát ban')
                with page.expect_response(lambda r: '/allergies' in r.url and r.request.method == 'PUT'):
                    page.locator('[data-form="allergies"] button.btn').click()
                settle(page)
                page.set_viewport_size({'width': width, 'height': 900})
            page.locator('[data-form="clinical"] [name="diagnosis"]').fill('Chẩn đoán giả lập M0')
            with page.expect_response(lambda r: '/clinical' in r.url and r.request.method == 'PUT') as saved:
                page.keyboard.press('F2')
            assert saved.value.status == 200; settle(page)
            for target in ('exam', 'orders', 'rx', 'results', 'history', 'payment'):
                page.locator(f'[data-action="doctor-tab"][data-target="{target}"]').click()
                expect(page.locator(f'#doctor-{target}')).to_be_visible()
                if target == 'rx': expect(page.locator('#doctor-rx .allergy-warning')).to_contain_text('Thuốc A: phát ban')
                if target == 'payment':
                    expect(page.locator('#doctor-payment-status')).to_have_text('Đã thu')
                    assert not page.locator('#doctor-payment button').count()
                no_horizontal_scroll(page)
            page.locator('[data-action="doctor-tab"][data-target="exam"]').click()
            if width in (1366, 390):
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(evidence / f'doctor-{width}.png'), full_page=True)
            with page.expect_response(lambda r: '/complete' in r.url and r.request.method == 'POST') as completed:
                page.keyboard.press('F8')
            assert completed.value.status == 200; settle(page)
            expect(page.locator('[data-form="clinical"] button.btn')).to_be_disabled()
        # A date-filtered completed visit remains selectable beyond the legacy
        # 100-item closed-history picker. No widening of clinical permissions.
        old_visits = []
        with db(True) as c:
            for _ in range(101):
                c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at,status) VALUES(?,?,?,?,'completed')",
                          (pid, IDS['doctor'], IDS['reception'], '2020-01-01T00:00:00+00:00'))
                old_visits.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
        page.locator('[name="doctor_day"]').fill('01/01/2020')
        page.locator('[data-form="doctor-filter"] button').click(); settle(page)
        pick(page, 'visit', old_visits[0])
        expect(page.locator('[data-form="clinical"] [name="visit_id"]')).to_have_value(str(old_visits[0]))
        expect(page.locator('[data-form="clinical"] button.btn')).to_be_disabled()
        assert not errors
        browser.close()
