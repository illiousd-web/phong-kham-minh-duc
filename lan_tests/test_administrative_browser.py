"""L1/L2 and refund UI over HTTPS, including Chromium 109 in CI."""
import base64
import hashlib
import os
from datetime import datetime
from pathlib import Path
import secrets
import pytest

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import expect, sync_playwright

from .conftest import IDS, PASSWORDS, SERVICE, db
from .test_tls_chrome_compat import https_server as https_server  # pytest discovers this imported fixture.
from .browser_helpers import settle, pick, go, no_horizontal_scroll
from app.labels import VN_TZ
from tests.test_self_review import manager_setup as manager_setup


def test_administrative_practitioner_and_refund_ui(https_server, clients, request):
    from app.practitioners import COLUMNS
    prior=next(x for x in clients['admin'].get('/api/practitioners').json()['items'] if x['id']==IDS['doctor'])
    prior={key:prior[key] for key in COLUMNS}
    request.addfinalizer(lambda: clients['admin'].put(f'/api/practitioners/{IDS["doctor"]}',json=prior))
    r=clients['reception']
    today=datetime.now(VN_TZ).date()
    born=today.replace(year=today.year-5,day=min(today.day,28)).isoformat()
    pid=r.post('/api/patients',json={'full_name':'Người bệnh L1 giao diện giả lập','date_of_birth':born,'sex':'Nữ',
        'phone':'0900000000','document_type':'identity','document_number':'000000001234','address':'Địa chỉ cũ giả lập'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':pid,'doctor_id':IDS['doctor'],'service_id':SERVICE}).json()['id']
    with db(True) as c:
        # Synthetic ledger for the precise overpayment regression (100,000 / 150,000).
        c.execute('INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(?,?,?,?,?,?)',
            (vid,150000,'cash',IDS['cashier'],datetime.now(VN_TZ).isoformat(),secrets.token_hex(16)))
        charge=c.execute('SELECT id FROM charges WHERE visit_id=?',(vid,)).fetchone()[0]
        c.execute('INSERT INTO charge_pricing(charge_id,amount) VALUES(?,?)',(charge,100000))
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence=Path('test_evidence/l12');evidence.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':1366,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
        def login(role):
            page.goto(origin)
            page.locator('[name=username]').fill('test_'+role);page.locator('[name=password]').fill(PASSWORDS[role])
            page.locator('[data-form=login] button').click();page.locator('.account-trigger').wait_for();settle(page)
        def logout():page.locator('.account-trigger').click();page.locator('#logout').click();page.locator('[data-form=login]').wait_for()
        login('reception')
        for width in (1366,390):
            page.set_viewport_size({'width':width,'height':900})
            page.locator('[data-form=patient-search] [name=q]').fill('000000001234')
            page.locator('[data-form=patient-search] button').first.click();settle(page)
            table=page.locator('.r2-patients')
            expect(table).to_contain_text('••••1234');assert '000000001234' not in table.inner_text()
            pick(page,'patient',pid)
            expect(page.locator('[data-form=patient-administrative] [name=document_number]')).to_have_value('000000001234')
            expect(page.locator('[data-form=patient-administrative]')).to_contain_text('Địa chỉ cũ giả lập')
            page.locator('[data-form=patient-administrative] [name=occupation]').fill('Nghề giả lập giao diện')
            with page.expect_response(lambda res:'/administrative' in res.url and res.request.method=='PATCH') as saved:
                page.locator('[data-form=patient-administrative] button').click()
            assert saved.value.status==200;settle(page);no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'reception-{width}.png'),full_page=True)
        logout();login('doctor');pick(page,'visit',vid)
        for width in (1366,390):
            page.set_viewport_size({'width':width,'height':900})
            expect(page.locator('.doctor-patient')).to_contain_text('tháng')
            page.locator('[data-action=doctor-tab][data-target=payment]').click()
            expect(page.locator('#doctor-payment-status')).to_contain_text('Cần hoàn: 50.000 đồng')
            expect(page.locator('#doctor-payment-status')).to_contain_text('Phải thu: 100.000 đ')
            expect(page.locator('#doctor-payment-status')).to_contain_text('Đã thu: 150.000 đ')
            page.locator('[data-action=doctor-tab][data-target=exam]').click()
            form=page.locator('[data-form=child-details]')
            form.locator('[name=weight_kg]').fill('12.5');form.locator('[name=escort_name]').fill('Người giả lập')
            form.locator('[name=escort_relationship]').fill('Mẹ');form.locator('[name=escort_phone]').fill('0900000000')
            with page.expect_response(lambda res:'/child-details' in res.url and res.request.method=='PUT') as saved:form.locator('button').click()
            assert saved.value.status==200;settle(page);no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'doctor-{width}.png'),full_page=True)
        logout();login('admin')
        for width in (1366,390):
            page.set_viewport_size({'width':width,'height':900})
            page.locator('#account_choose').select_option(str(IDS['doctor']));settle(page)
            form=page.locator('[data-form=practitioner]')
            form.locator('[name=printed_name]').fill('Người hành nghề giả lập')
            form.locator('[name=printed_title]').fill('ThS.BS')
            form.locator('[name=certificate_expiry]').fill('01/01/2000')
            form.locator('[name=practice_scopes][value="Nội"]').check()
            with page.expect_response(lambda res:'/practitioners/' in res.url and res.request.method=='PUT') as saved:form.locator('button').click()
            assert saved.value.status==200;settle(page)
            expect(page.locator('#m0-dialog')).to_contain_text('đã hết hạn')
            page.locator('[data-action=close-m0-dialog]').click();no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'admin-{width}.png'),full_page=True)
        # Scope warning is visible after successful approval, not merely returned by API.
        clients['admin'].put(f'/api/practitioners/{IDS["doctor"]}',json={})
        with db(True) as c:
            c.execute("INSERT INTO service_catalog(name,price) VALUES('Xét nghiệm giao diện giả lập',1000)")
            sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO service_categories VALUES(?,'lab')",(sid,))
        oid=clients['doctor'].post('/api/orders',json={'visit_id':vid,'category':'lab','service_id':sid,'request_key':secrets.token_hex(16)}).json()['id']
        assert clients['technician'].put(f'/api/orders/{oid}/result',json={'version':0,'result_text':'Kết luận: giả lập'}).status_code==200
        logout();login('doctor');pick(page,'visit',vid)
        page.locator('[data-action=doctor-tab][data-target=orders]').click()
        page.locator(f'[data-action=approve][data-id="{oid}"]').click();settle(page)
        expect(page.locator(f'[data-scope-warning="{oid}"]')).to_contain_text('chưa khai phạm vi Xét nghiệm')
        assert not errors,errors
        browser.close()
    clients['admin'].put(f'/api/practitioners/{IDS["doctor"]}',json=prior)


def test_public_catalog_comboboxes_default_province_and_explicit_ethnicity(https_server, clients, request):
    from app.ui_settings import settings_path
    from app.main import FILES
    settings=settings_path(FILES);previous=settings.read_bytes() if settings.exists() else None
    def restore():
        if previous is None:settings.unlink(missing_ok=True)
        else:settings.write_bytes(previous)
    request.addfinalizer(restore)
    assert clients['admin'].put('/api/ui-settings',json={'default_province_code':'06'}).status_code==200
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':1366,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin);page.locator('[name=username]').fill('test_reception');page.locator('[name=password]').fill(PASSWORDS['reception'])
        page.locator('[data-form=login] button').click();page.locator('.account-trigger').wait_for();settle(page)
        for width in (1366,390):
            page.set_viewport_size({'width':width,'height':900});go(page,'reception')
            page.locator('summary').filter(has_text='Thêm bệnh nhân mới').click()
            form=page.locator('[data-form=patient]')
            expect(form.locator('[name=province_code]')).to_have_value('06')
            expect(form.locator('[name=ethnicity_code]')).to_have_value('')
            expect(form.locator('[name=ethnicity_search]')).to_have_value('')
            # Both extra choices are discoverable without assigning any default ethnicity.
            ethnic=form.locator('[name=ethnicity_search]');ethnic.focus()
            with page.expect_response(lambda r:'/patient-catalog?' in r.url and 'kind=ethnicity' in r.url):ethnic.press('ArrowDown')
            expect(form.locator('[data-code=FOREIGN]')).to_be_visible();expect(form.locator('[data-code=UNKNOWN]')).to_be_visible()
            expect(form.locator('[name=ethnicity_code]')).to_have_value('')
            with page.expect_response(lambda r:'/patient-catalog?' in r.url and 'kind=ethnicity' in r.url):ethnic.fill('viet')
            option=form.locator('[data-catalog-combo=ethnicity] [data-code="01"]')
            expect(option.locator('span')).to_have_text('Kinh');expect(option.locator('small.muted')).to_have_text('Việt')
            option.click();expect(form.locator('[name=ethnicity_code]')).to_have_value('01')
            with page.expect_response(lambda r:'/patient-catalog?' in r.url and 'kind=ethnicity' in r.url):ethnic.fill('tho')
            ethnic.press('ArrowDown');ethnic.press('Enter');expect(form.locator('[name=ethnicity_code]')).to_have_value('02')
            commune=form.locator('[name=commune_search]')
            with page.expect_response(lambda r:'/patient-catalog?' in r.url and 'kind=commune' in r.url) as response:commune.fill('cat thanh')
            rows=response.value.json();assert len(rows)<=30 and all(x['parent_code']=='06' for x in rows)
            form.locator('[data-catalog-combo=commune] [data-code="11311067"]').click()
            expect(form.locator('[name=commune_search]')).to_have_value('Xã Cát Thành')
            form.locator('[name=province_code]').select_option('01')
            expect(form.locator('[name=commune_search]')).to_have_value('');expect(form.locator('[name=commune_code]')).to_have_value('')
            form.locator('[name=province_code]').select_option('06')
            with page.expect_response(lambda r:'/patient-catalog?' in r.url and 'kind=commune' in r.url):commune.fill('phuong nam dinh')
            form.locator('[data-catalog-combo=commune] [data-code="11301122"]').click()
            form.locator('[name=full_name]').fill('Người bệnh giả lập danh mục '+str(width));form.locator('[name=date_of_birth]').fill('01/01/1990')
            form.locator('[name=sex]').select_option('Nữ');form.locator('[name=phone]').fill('0900000000')
            with page.expect_response(lambda r:r.url.endswith('/api/patients') and r.request.method=='POST') as saved:form.locator('button.btn').click()
            assert saved.value.status==201,saved.value.text();settle(page)
            record=clients['reception'].get('/api/patients/'+str(saved.value.json()['id'])).json()
            assert (record['province_code'],record['commune_code'],record['ethnicity_code'])==('06','11301122','02')
            no_horizontal_scroll(page)
            out=Path('test_evidence/l1-catalog');out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/f'catalog-{width}.png'),full_page=True)
        page.locator('.account-trigger').click();page.locator('#logout').click();page.locator('[name=username]').fill('test_admin');page.locator('[name=password]').fill(PASSWORDS['admin'])
        page.locator('[data-form=login] button').click();page.locator('.account-trigger').wait_for();settle(page)
        go(page,'settings');expect(page.locator('[name=default_province_code]')).to_have_value('06')
        go(page,'admin');page.locator('[data-action=tab][data-tab=catalog]').click();settle(page)
        with page.expect_response(lambda r:'/patient-catalog/import' in r.url and r.request.method=='POST') as reload:
            page.locator('[data-form=patient-catalog] button').click()
        assert reload.value.status==200;settle(page)
        assert not errors,errors
        browser.close()


def test_cashier_transfer_radio_keyboard_persists_method(https_server,clients,visit):
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':390,'height':844})
            page.goto(origin)
            page.locator('[name=username]').fill('test_cashier')
            page.locator('[name=password]').fill(PASSWORDS['cashier'])
            page.locator('[data-form=login] button').click()
            page.locator('.account-trigger').wait_for();settle(page);pick(page,'cash',visit)
            form=page.locator('[data-form=payment]')
            expect(form.locator('button')).to_have_count(1)
            cash=form.locator('[type=radio][name=method][value=cash]')
            transfer=form.locator('[type=radio][name=method][value=transfer]')
            expect(cash).to_be_checked()
            for radio in (cash,transfer):
                assert radio.bounding_box()['height']>=44
            cash.focus();cash.press('ArrowRight')
            expect(transfer).to_be_checked();expect(transfer).to_be_focused()
            assert transfer.evaluate("e=>getComputedStyle(e.nextElementSibling).outlineStyle")=='solid'
            form.locator('[name=amount]').fill('1000')
            reference='R4-transfer-'+secrets.token_hex(6)
            form.locator('[name=external_ref]').fill(reference)
            with page.expect_response(lambda response:response.url.endswith('/api/payments') and response.request.method=='POST') as paid:
                form.locator('button').click()
            assert paid.value.status==201,paid.value.text()
            assert paid.value.request.post_data_json['method']=='transfer'
            records=clients['cashier'].get('/api/payments').json()
            saved=next(row for row in records if row['visit_id']==visit and row['external_ref']==reference)
            assert saved['method']=='transfer' and saved['amount']==1000
            with db() as c:
                stored=c.execute('SELECT method,amount FROM payments WHERE id=?',(saved['id'],)).fetchone()
                assert stored['method']=='transfer' and stored['amount']==1000
            no_horizontal_scroll(page)
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1366, 390])
def test_cashier_cash_change_is_ui_only(https_server, clients, visit, width):
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        try:
            page = browser.new_page(viewport={'width': width, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin)
            page.locator('[name=username]').fill('test_cashier')
            page.locator('[name=password]').fill(PASSWORDS['cashier'])
            page.locator('[data-form=login] button').click()
            page.locator('.account-trigger').wait_for()
            settle(page)
            pick(page, 'cash', visit)
            form = page.locator('[data-form=payment]')
            expect(form.locator('button')).to_have_count(1)
            payment_posts = []
            page.on('request', lambda r: payment_posts.append(r.post_data_json)
                if r.url.endswith('/api/payments') and r.method == 'POST' else None)
            given = form.get_by_label('Khách đưa', exact=True)
            assert given.get_attribute('name') is None
            expect(given).to_be_visible()
            amount = form.locator('[name=amount]')
            amount.fill('1000')
            given.fill('500')
            expect(form.locator('output')).to_have_text('Thiếu 500 đ')
            expect(form.locator('button')).to_be_disabled()
            expect(form.locator('[data-r5-cash-short]')).to_have_text('Khách đưa chưa đủ')
            expect(form.locator('[data-r5-cash-short]')).to_be_visible()
            # requestSubmit exercises the guard even if the disabled button is bypassed.
            form.evaluate('f => f.requestSubmit()')
            expect(page.locator('#toast')).to_have_text('Khách đưa chưa đủ')
            expect(form.locator('button')).to_be_disabled()
            assert payment_posts == []
            given.fill('')
            expect(form.locator('button')).to_be_enabled()
            expect(form.locator('[data-r5-cash-short]')).to_be_hidden()
            given.fill('2000')
            expect(form.locator('output')).to_have_text('1.000 đ')
            amount.fill('500')
            expect(form.locator('output')).to_have_text('1.500 đ')
            amount.fill('1000')
            given.fill('500')
            form.locator('[name=method][value=transfer]').check()
            expect(given).to_be_hidden()
            expect(form.locator('output')).to_be_hidden()
            expect(form.locator('button')).to_be_enabled()
            form.locator('[name=method][value=cash]').check()
            expect(form.locator('button')).to_be_disabled()
            given.fill('2000')
            expect(given).to_be_visible()
            expect(form.locator('output')).to_have_text('1.000 đ')
            no_horizontal_scroll(page)
            evidence = Path('test_evidence/r5')
            evidence.mkdir(parents=True, exist_ok=True)
            form.screenshot(path=str(evidence / f'cash-change-{width}.png'))
            given.fill('1000')
            expect(form.locator('output')).to_have_text('0 đ')
            expect(form.locator('button')).to_be_enabled()
            assert payment_posts == []
            with page.expect_response(lambda r: r.url.endswith('/api/payments') and r.request.method == 'POST') as paid:
                form.locator('button').click()
            assert paid.value.status == 201, paid.value.text()
            payload = paid.value.request.post_data_json
            assert payment_posts == [payload]
            assert set(payload) == {'visit_id', 'amount', 'method', 'external_ref', 'idempotency_key', 'confirm_over_limit'}
            assert payload['amount'] == 1000 and payload['method'] == 'cash'
            saved = next(x for x in clients['cashier'].get('/api/payments').json() if x['id'] == paid.value.json()['id'])
            assert saved['amount'] == 1000 and saved['method'] == 'cash'
            assert not errors, errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1366, 390])
def test_r6_screens_template_geometry(https_server, clients, visit, width):
    import re
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with db(True) as c:
        c.execute('INSERT INTO drugs(name,name_key,strength_key) VALUES(?,?,?)',
            ('Thuốc rà soát R6 '+str(width), 'r6-review-'+str(width)+'-'+secrets.token_hex(4), ''))
    proposal = clients['cashier'].post('/api/adjustments', json={
        'visit_id': visit, 'kind': 'discount', 'amount': 1000, 'reason': 'Đề nghị giả lập R6'})
    assert proposal.status_code == 201, proposal.text
    target = Path('test_evidence/r6'); target.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        try:
            errors = []
            for role, screens in [('manager', [('manager', 'approve'), ('manager', 'report'), ('manager', 'visits')]),
                                  ('admin', [('admin', 'accounts'), ('admin', 'audit'), ('price-management', None),
                                             ('settings', None), ('m6-admin', None), ('m5-admin', None)])]:
                context = browser.new_context(viewport={'width': width, 'height': 900})
                page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin)
                page.locator('[name=username]').fill('test_' + role)
                page.locator('[name=password]').fill(PASSWORDS[role])
                page.locator('[data-form=login] button').click()
                page.locator('.account-trigger').wait_for(); settle(page)
                for screen, tab in screens:
                    go(page, screen)
                    if tab:
                        page.locator(f'[data-action=tab][data-tab={tab}]').click(); settle(page)
                    expect(page.locator('#workspace')).to_have_class(re.compile(r'\br6-screen\b'))
                    no_horizontal_scroll(page)
                    small = page.locator('#workspace *:visible').evaluate_all('''es => es.filter(e =>
                        [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) &&
                        parseFloat(getComputedStyle(e).fontSize) < 13).map(e => e.textContent.slice(0,80))''')
                    assert not small, small
                    for button in page.locator('#workspace button:visible').all():
                        assert button.bounding_box()['height'] >= 44, button.inner_text()
                    if screen == 'manager' and tab == 'approve':
                        expect(page.locator(f'.r6-approval [data-action=review-adjustment][data-id="{proposal.json()["id"]}"][data-value=approve]')).to_be_visible()
                    if tab == 'audit':
                        assert page.locator('#workspace [data-form], #workspace [data-action*="delete"], #workspace [data-action*="edit"]').count() == 0
                    page.screenshot(path=str(target / f'{screen}-{tab or "main"}-{width}.png'))
                context.close()
            assert not errors, errors
        finally:
            browser.close()


def test_s2a_allergies_settings_and_today_at_vietnam_midnight(https_server, clients, tmp_path):
    from tests.s2a_cases import PROFILE, signature_image, draft_prescription, retire_test_medicine
    r = clients['reception']
    pid = r.post('/api/patients', json={'full_name': 'Người bệnh giao diện giả lập S2a', 'sex': 'Nữ', 'date_of_birth': '1990-01-01', 'phone': '0000000000'}).json()['id']
    vid = r.post('/api/visits', json={'patient_id': pid, 'doctor_id': IDS['doctor'], 'service_id': SERVICE}).json()['id']
    rx = draft_prescription(clients, vid)
    allergy = 'Thuốc giả lập <A> & B: nổi mẩn'
    assert r.put(f'/api/patients/{pid}/allergies', json={'allergies': allergy}).status_code == 200
    with db(True) as c:
        # More than one page; UTC April 1 at 18:30 is April 2 in Vietnam.
        for _ in range(52):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
                      (pid, IDS['doctor'], IDS['reception'], '2030-04-01T18:30:00+00:00'))
        for outside in ('2030-04-01T16:59:59+00:00', '2030-04-02T17:00:00+00:00'):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)', (pid, IDS['doctor'], IDS['reception'], outside))
    origin, certdir = https_server
    certificate = x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(certificate.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    before = clients['admin'].get('/api/clinic-profile').json()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
                                        args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list='+pin])
            if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):
                assert browser.version.split('.')[0] == os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
            page = browser.new_page(viewport={'width': 1366, 'height': 900}, timezone_id='UTC')
            page.add_init_script("""{
                const RealDate=Date;
                window.Date=class extends RealDate {
                    constructor(...args){super(...(args.length?args:['2030-04-01T18:30:00Z']));}
                    static now(){return new RealDate('2030-04-01T18:30:00Z').getTime();}
                };
            }""")
            page.on('pageerror', lambda error: errors.append(str(error)))

            def login(role):
                page.goto(origin)
                page.locator('[name=username]').fill('test_'+role)
                page.locator('[name=password]').fill(PASSWORDS[role])
                page.locator('[data-form=login] button').click()
                page.locator('.account-trigger').wait_for()
                settle(page)

            def logout():
                page.locator('.account-trigger').click()
                page.locator('#logout').click()
                page.locator('[data-form=login]').wait_for()

            login('pharmacy')
            for width in (1366, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                pick(page, 'pharmacy-rx', rx)
                expect(page.locator(f'[data-kind=pharmacy-rx][data-id="{rx}"]')).to_contain_text('Dị ứng')
                warning = page.locator('#r5-rx-detail .pharmacy-allergy')
                expect(warning).to_have_text('DỊ ỨNG: '+allergy)
                assert warning.evaluate("el=>getComputedStyle(el).backgroundColor") == 'rgb(180, 35, 24)'
                assert page.locator('#r5-rx-detail').evaluate("el=>!!el.querySelector('h2 + .pharmacy-allergy') && !!(el.querySelector('.pharmacy-allergy').compareDocumentPosition(el.querySelector('table')) & Node.DOCUMENT_POSITION_FOLLOWING)")
                messages = []
                page.once('dialog', lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
                page.locator(f'[data-action=dispense][data-id="{rx}"]').click()
                assert len(messages) == 1 and 'Người bệnh dị ứng: '+allergy in messages[0]
                evidence = Path('test_evidence/s2a'); evidence.mkdir(parents=True, exist_ok=True)
                page.locator('#r5-rx-detail').screenshot(path=str(evidence/f'allergy-{width}.png'))
                no_horizontal_scroll(page)
            # No red warning for unknown history or explicitly recorded no allergy.
            for value in (None, 'Không dị ứng'):
                assert r.put(f'/api/patients/{pid}/allergies', json={'allergies': value}).status_code == 200
                go(page, 'pharmacy')
                pick(page, 'pharmacy-rx', rx)
                expect(page.locator('.pharmacy-allergy')).to_have_count(0)
                messages = []
                page.once('dialog', lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
                page.locator(f'[data-action=dispense][data-id="{rx}"]').click()
                assert len(messages) == 1 and 'Người bệnh dị ứng:' not in messages[0]
            logout()
            login('manager')
            expected = clients['manager'].get('/api/manager/visits?date_from=2030-04-02&date_to=2030-04-02').json()
            assert expected['total'] == 52 and len(expected['items']) == 50
            expect(page.locator('[data-r2-stat=visits] strong')).to_have_text('52')
            expect(page.locator('[data-r2-stat=revenue] strong')).to_have_text('—')
            logout()
            login('admin')
            for width in (1366, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                go(page, 'settings')
                form = page.locator('[data-form=clinic-profile]')
                for key, value in PROFILE.items():
                    form.locator('[name=clinic_'+key+']').fill(value)
                with page.expect_response(lambda res: '/api/clinic-profile' in res.url and res.request.method == 'PUT') as saved:
                    form.locator('button').click()
                assert saved.value.status == 200
                settle(page)
                expect(page.locator('[data-form=clinic-profile] [name=clinic_name]')).to_have_value(PROFILE['name'])
                image = tmp_path/'generated.png'
                image.write_bytes(signature_image())
                page.locator('[name=signature_user_id]').select_option(str(IDS['doctor']))
                page.locator('[name=signature_file]').set_input_files(image)
                with page.expect_response(lambda res: res.url.endswith('/signature') and res.request.method == 'PUT') as saved:
                    page.locator('[data-form=user-signature] button.btn').click()
                assert saved.value.status == 200
                settle(page)
                page.locator('[name=signature_user_id]').select_option(str(IDS['doctor']))
                page.locator('[data-action=view-user-signature]').click()
                expect(page.locator('#signature-preview img')).to_be_visible()
                expect(page.locator('#signature-preview img')).to_have_js_property('naturalWidth', 160)
                expect(page.locator('[data-form=user-signature]')).to_contain_text('Chờ S2b')
                no_horizontal_scroll(page)
                page.locator('[data-form=user-signature]').screenshot(path=str(evidence/f'signature-{width}.png'))
                page.locator('[name=signature_user_id]').select_option(str(IDS['admin']))
                expect(page.locator('#signature-preview img')).to_have_count(0)
            assert not errors
            browser.close()
    finally:
        retire_test_medicine(db, rx)
        clients['admin'].put('/api/clinic-profile', json=before)
        with db(True) as c:
            c.execute('DELETE FROM user_signatures WHERE user_id=?', (IDS['doctor'],))


def test_cashier_financial_settlement_over_https(https_server, clients, visit):
    from tests.test_s2e_settlements import checked, complete_visit

    complete_visit(clients['doctor'], visit)
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'),
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):
            assert browser.version.split('.')[0] == os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin)
        page.locator('[name=username]').fill('test_cashier')
        page.locator('[name=password]').fill(PASSWORDS['cashier'])
        page.locator('[data-form=login] button').click()
        page.locator('.account-trigger').wait_for()
        settle(page)
        queue_row = page.locator(f'[data-kind=cash-settlement][data-id="{visit}"]')
        expect(queue_row).to_be_visible()
        queue_row.click()
        settle(page)
        finish = page.get_by_role('button', name='Kết thúc lượt', exact=True)
        expect(finish).to_be_disabled()
        expect(finish.locator('..')).to_contain_text('Còn phải thu 150.000 đồng')
        no_horizontal_scroll(page)
        with page.expect_response(lambda r: r.url.endswith('/api/payments') and r.request.method == 'POST') as payment_saved:
            page.locator('[data-form=payment]').get_by_role('button', name='Thu tiền', exact=True).click()
        assert payment_saved.value.status == 201
        settle(page)
        expect(finish).to_be_enabled()
        expect(page.get_by_role('button', name='Duyệt miễn thu')).to_have_count(0)
        with page.expect_response(lambda r: r.url.endswith(f'/api/visits/{visit}/settle')) as result:
            finish.click()
        assert result.value.status == 200 and result.value.json()['kind'] == 'du_thu'
        settle(page)
        expect(page.locator('#toast')).to_have_text('Đã kết thúc tài chính')
        expect(queue_row).to_have_count(0)
        stored = checked(clients['cashier'].get(f'/api/visits/{visit}/settlement'))
        assert stored['financial_settlement']['kind'] == 'du_thu'

        page.locator('.account-trigger').click()
        page.locator('#logout').click()
        page.locator('[name=username]').fill('test_admin')
        page.locator('[name=password]').fill(PASSWORDS['admin'])
        page.locator('[data-form=login] button').click()
        page.locator('.account-trigger').wait_for()
        settle(page)
        go(page, 'financial-settlements')
        page.get_by_role('button', name='Đã kết thúc', exact=True).click()
        settle(page)
        pick(page, 'financial-visit', visit)
        page.once('dialog', lambda dialog: dialog.accept('Đối soát thử nghiệm trên trình duyệt'))
        with page.expect_response(lambda r: r.url.endswith(f'/api/visits/{visit}/settlement-reopen')) as reopened:
            page.get_by_role('button', name='Mở lại', exact=True).click()
        assert reopened.value.status == 200
        settle(page)
        manager = browser.new_page(viewport={'width': 390, 'height': 844})
        manager.on('pageerror', lambda error: errors.append(str(error)))
        manager.goto(origin)
        manager.locator('[name=username]').fill('test_manager')
        manager.locator('[name=password]').fill(PASSWORDS['manager'])
        manager.locator('[data-form=login] button').click()
        manager.locator('.account-trigger').wait_for()
        settle(manager)
        manager.locator('[data-action=tab][data-tab=financial]').click()
        settle(manager)
        expect(manager.get_by_role('heading', name='Lượt bác sĩ đã khóa nhưng chưa kết thúc tài chính')).to_be_visible()
        pick(manager, 'financial-visit', visit)
        expect(manager.get_by_role('button', name='Duyệt miễn thu')).to_have_count(0)
        no_horizontal_scroll(manager)
        manager.close()
        page.get_by_role('button', name='Chờ kết thúc', exact=True).click()
        settle(page)
        pick(page, 'financial-visit', visit)
        waiver = page.get_by_role('button', name='Duyệt miễn thu', exact=True)
        expect(waiver).to_be_disabled()
        expect(waiver.locator('..')).to_contain_text('Lượt khám đã thu đủ, không có khoản để miễn thu.')
        with page.expect_response(lambda r: r.url.endswith(f'/api/visits/{visit}/settle')) as closed:
            page.get_by_role('button', name='Kết thúc lượt', exact=True).click()
        assert closed.value.status == 200 and closed.value.json()['kind'] == 'du_thu'
        settle(page)
        no_horizontal_scroll(page)
        assert not errors, errors
        browser.close()


def test_sole_manager_self_review_requires_reason_at_390px(https_server, clients, visit, manager_setup):
    from tests.test_self_review import SELF_REASON, submit_request

    endpoint, request_id, _ = submit_request(clients, visit, 'discount')
    cashier, _, configure = manager_setup
    configure(cashier, second=False)
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    public_key = cert.public_key().public_bytes(serialization.Encoding.DER,
                                                serialization.PublicFormat.SubjectPublicKeyInfo)
    pin = base64.b64encode(hashlib.sha256(public_key).digest()).decode()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'),
                                   headless=True, args=['--no-sandbox', '--disable-dev-shm-usage',
                                                        '--ignore-certificate-errors-spki-list='+pin])
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        page.goto(origin)
        page.locator('[name=username]').fill('test_cashier')
        page.locator('[name=password]').fill(PASSWORDS['cashier'])
        page.locator('[data-form=login] button').click()
        page.locator('.account-trigger').wait_for()
        settle(page)
        page.locator('#role_switch').select_option('manager')
        go(page, 'manager')
        button = page.locator(f'[data-action=review-adjustment][data-id="{request_id}"][data-value=approve]')
        reason = button.locator('xpath=ancestor::div[contains(@class,"financial-decision")]').locator('textarea')
        expect(reason).to_be_visible()
        assert reason.get_attribute('required') is not None
        assert button.bounding_box()['height'] >= 44
        assert button.bounding_box()['width'] >= 88
        no_horizontal_scroll(page)
        button.click()
        expect(reason).to_be_focused()
        expect(page.get_by_text('Tự duyệt cần ghi lý do (ít nhất 10 ký tự)', exact=True)).to_be_visible()
        reason.fill('ả' * 501)
        button.click()
        expect(reason).to_be_focused()
        expect(page.get_by_text('Lý do tự duyệt không được quá 500 ký tự', exact=True)).to_be_visible()
        reason.fill(SELF_REASON)
        with page.expect_response(lambda res: res.url.endswith(f'{endpoint}/{request_id}/review')
                                  and res.request.method == 'POST') as response:
            button.click()
        assert response.value.status == 200
        assert response.value.json()['status'] == 'approved'
        browser.close()
