"""L1/L2 and refund UI over HTTPS, including Chromium 109 in CI."""
import base64
import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import expect, sync_playwright

from .conftest import IDS, PASSWORDS, SERVICE, db
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle, pick, go, no_horizontal_scroll
from app.labels import VN_TZ


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
