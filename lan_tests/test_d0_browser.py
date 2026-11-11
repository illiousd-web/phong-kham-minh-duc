"""Synthetic D0 preview and bounded diagnosis search at workstation/mobile widths."""
import base64,hashlib,os,secrets
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright,expect
from .conftest import IDS,PASSWORDS,SERVICE
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle,go,pick,no_horizontal_scroll
from tests.d0_cases import upload,raw

@pytest.mark.parametrize('width',[1366,390])
def test_d0_source_preview_and_diagnosis_search(https_server,clients,width):
    a,r=clients['admin'],clients['reception'];suffix=secrets.token_hex(4)
    rows=[{'code':'FAKE-UI-'+suffix,'name_vi':'Bệnh giao diện giả lập '+suffix}]
    upload(a,'icd10',rows)
    pid=r.post('/api/patients',json={'full_name':'Người D0 giao diện giả lập '+suffix,'date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':pid,'doctor_id':IDS['doctor'],'service_id':SERVICE}).json()['id']
    origin,certdir=https_server;cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode();errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':width,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
        def login(role):
            page.goto(origin);page.locator('[name=username]').fill('test_'+role);page.locator('[name=password]').fill(PASSWORDS[role]);page.locator('[data-form=login] button').click();page.locator('#logout').wait_for();settle(page)
        login('doctor');pick(page,'visit',vid);settle(page)
        form=page.locator('[data-d0=diagnosis]');form.locator('[data-d0-search]').fill('benh giao dien gia lap '+suffix)
        form.locator('[data-d0-code]').click();expect(form.locator('[name=primary]')).to_have_value(rows[0]['code'])
        form.locator('button',has_text='Lưu mã chẩn đoán').click();settle(page);expect(page.locator('[data-d0=diagnosis]')).to_contain_text('Đã mã hóa');no_horizontal_scroll(page)
        page.locator('#logout').click();page.locator('[data-form=login]').wait_for();login('admin')
        page.locator('[data-kind=admin][data-tab=catalog]').click();settle(page)
        imp=page.locator('[data-d0=import]');expect(imp.locator('.d0-confirm')).to_be_hidden()
        for name,value in [('document_number','Văn bản giả lập'),('document_date','01/01/2026'),('source','Nguồn giả lập'),('version','ui-test')]:imp.locator('[name='+name+']').fill(value)
        imp.locator('[name=file]').set_input_files({'name':'fake.csv','mimeType':'text/csv','buffer':raw('icd10',rows)})
        imp.locator('[value=preview]').click();expect(imp.locator('.d0-confirm')).to_be_visible();no_horizontal_scroll(page)
        imp.locator('[name=version]').fill('ui-test-changed');expect(imp.locator('.d0-confirm')).to_be_hidden()
        assert not errors,errors;browser.close()
