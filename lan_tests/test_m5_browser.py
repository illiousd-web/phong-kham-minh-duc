"""Real HTTPS structured laboratory entry, review, doctor view and reception print."""
import base64,hashlib,os,secrets
from pathlib import Path
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright,expect
from .conftest import IDS,PASSWORDS,SERVICE
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle,go,pick,no_horizontal_scroll
from app.database import db


@pytest.mark.parametrize('width',[1366,390])
def test_m5_numeric_entry_review_snapshot_and_group_print(https_server,clients,request,width):
    suffix=secrets.token_hex(4);a,r,d,t=[clients[k] for k in ('admin','reception','doctor','technician')]
    from app.practitioners import COLUMNS
    old=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==IDS['doctor'])
    request.addfinalizer(lambda:a.put('/api/practitioners/'+str(IDS['doctor']),json={k:old[k] for k in COLUMNS}))
    assert a.put('/api/practitioners/'+str(IDS['doctor']),json={**{k:old[k] for k in COLUMNS},'practice_scopes':[]}).status_code==200
    test={'code':'BROWSER-'+suffix,'name':'Chỉ số giao diện giả lập '+suffix,'abbreviation':'FAKE','group_name':'hematology','result_type':'number','unit':'đv giả lập','decimals':1,'references':[{'sex':'chung','lower_value':'10','upper_value':'20'}]}
    tid=a.post('/api/lab/catalog',json=test).json()['id']
    with db(True) as c:
        c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)',('Xét nghiệm giao diện giả lập '+suffix,12345,'M5-'+suffix));sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(sid,'lab'))
    assert a.put('/api/lab/services/'+str(sid),json={'test_ids':[tid]}).status_code==200
    p=r.post('/api/patients',json={'full_name':'Người giao diện giả lập M5 '+suffix,'date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':p,'doctor_id':IDS['doctor'],'service_id':SERVICE}).json()['id']
    oid=d.post('/api/orders',json={'visit_id':vid,'category':'lab','service_id':sid,'request_key':'m5-ui-'+suffix}).json()['id']
    rid=t.post(f'/api/lab/orders/{oid}/reports').json()['id']
    origin,certdir=https_server;cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[];target=Path('test_evidence/m5');target.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':width,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
        def login(role):
            page.goto(origin);page.locator('[name=username]').fill('test_'+role);page.locator('[name=password]').fill(PASSWORDS[role]);page.locator('[data-form=login] button').click();page.locator('#logout').wait_for();settle(page)
        login('technician');go(page,'m5-queue')
        page.locator(f'[data-m5=open][data-id="{rid}"]').click();settle(page)
        form=page.locator('[data-m5-form=result]');expect(form.locator('[name=value]')).to_have_attribute('inputmode','decimal')
        form.locator('[name=sample_at]').fill('02/01/2026 08:00');form.locator('[name=result_at]').fill('02/01/2026 09:00');form.locator('[name=value]').fill('21,5');form.locator('[name=note]').fill('Ghi chú giao diện giả lập');form.locator('[name=comment]').fill('Nhận xét giao diện giả lập')
        with page.expect_response(lambda x:x.url.endswith('/lab/reports/'+str(rid)) and x.request.method=='PUT') as response:form.locator('button.btn').click()
        assert response.value.status==200;settle(page)
        expect(page.locator('.m5-result-row [name=value]')).to_have_value('21.5');expect(page.locator('.m5-result-row .m5-abnormal')).to_contain_text('H')
        with page.expect_download() as download:page.locator(f'[data-m5=print][data-id="{rid}"][data-fmt=pdf]').click()
        download.value.save_as(str(target/f'nhap-{width}.pdf'))
        with page.expect_response(lambda x:x.url.endswith('/submit')) as response:page.locator('[data-m5=submit]').click()
        assert response.value.status==200;settle(page);no_horizontal_scroll(page)
        assert d.get(f'/api/lab/reports/{rid}').json()['items']==[]
        page.locator('#logout').click();login('doctor');pick(page,'visit',vid)
        expect(page.locator('#doctor-results')).to_contain_text('Đang làm')
        expect(page.locator('#doctor-results')).not_to_contain_text('21.5')
        page.locator(f'[data-m5=review][data-id="{rid}"]').click();expect(page.locator('dialog')).to_contain_text('21.5')
        with page.expect_response(lambda x:x.url.endswith('/approve')) as response:page.locator('dialog [data-m5=approve]').click()
        assert response.value.status==200;settle(page)
        expect(page.locator('#doctor-results .m5-abnormal')).to_contain_text('21.5')
        expect(page.locator(f'[data-scope-warning="{oid}"]')).to_contain_text('Xét nghiệm')
        page.locator('#doctor-results [data-m5=history]').click();expect(page.locator('dialog')).to_contain_text('21.5');page.locator('dialog [data-m5=close]').click()
        page.screenshot(path=str(target/f'ket-qua-{width}.png'),full_page=True);no_horizontal_scroll(page)
        page.locator('#logout').click();login('reception');go(page,'m5-queue');page.locator(f'[data-m5=open][data-id="{rid}"]').click();settle(page)
        assert page.locator('[data-m5-form=result]').count()==0
        assert page.locator('[data-m5=print][data-group=urine]').count()==0
        with page.expect_download() as download:page.locator(f'[data-m5=print][data-id="{rid}"][data-fmt=docx]').click()
        download.value.save_as(str(target/f'da-duyet-{width}.docx'));no_horizontal_scroll(page)
        page.locator('#logout').click();login('admin');go(page,'m5-admin')
        expect(page.locator('#workspace')).to_contain_text('Khung chỉ số chỉ gợi ý')
        page.locator('[data-m5-test]').select_option(str(tid));settle(page)
        expect(page.locator('[name=code]')).to_have_value(test['code']);expect(page.locator('.m5-reference [name=lower_value]')).to_have_value('10')
        with page.expect_download() as download:page.locator('[data-m5=template]').click()
        download.value.save_as(str(target/f'mau-rong-{width}.xlsx'));no_horizontal_scroll(page)
        assert not errors,errors;browser.close()
