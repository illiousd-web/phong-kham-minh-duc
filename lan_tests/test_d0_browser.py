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


@pytest.mark.parametrize('width',[1366,390])
def test_link_editor_filter_modes_and_single_lab_code(https_server,clients,width):
    from .conftest import db
    from tests.d0_isolation import service,lab
    a=clients['admin'];suffix=secrets.token_hex(6)
    code_a,code_b='FAKE-A-'+suffix,'FAKE-B-'+suffix
    name_a,name_b='Kỹ thuật giao diện giả lập A '+suffix,'Kỹ thuật giao diện giả lập B '+suffix
    upload(a,'tech_catalog',[{'code':code_a,'name':name_a},{'code':code_b,'name':name_b}])
    shared=[{'code':'9000003','name':'Chỉ số giao diện giả lập A '+suffix},{'code':'9000004','name':'Chỉ số giao diện giả lập B '+suffix}]
    upload(a,'shared_lab_codes',shared)
    sid_a,sid_new,sid_pack=[service(db) for _ in range(3)];tid=lab(a)
    assert a.put('/api/standards/services/'+str(sid_a),json={'codes':[code_a]}).status_code==200
    assert a.put('/api/standards/services/'+str(sid_pack),json={'codes':[code_a,code_b],'package':True}).status_code==200
    origin,certdir=https_server;cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode();errors=[];writes=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':width,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
        page.on('request',lambda r:writes.append(r.url) if r.method=='PUT' and '/api/standards/' in r.url else None)
        # Scope list responses to this scenario's real rows; writes still reach the real API.
        def own_services(route):
            response=a.get('/api/standards/links/services');assert response.status_code==200
            body=response.json();body['items']=[x for x in body['items'] if x['id'] in (sid_a,sid_new,sid_pack)];body['total']=len(body['items']);route.fulfill(status=200,json=body)
        page.route('**/api/standards/links/services',own_services)
        page.goto(origin);page.locator('[name=username]').fill('test_admin');page.locator('[name=password]').fill(PASSWORDS['admin']);page.locator('[data-form=login] button').click();page.locator('#logout').wait_for();settle(page)
        page.locator('[data-kind=admin][data-tab=catalog]').click();settle(page)
        f=page.locator('[data-d0=link][data-kind=services]');f.locator('[name=id]').select_option(str(sid_a));expect(f.locator('[name=codes]')).to_have_value(code_a)
        # A select value change without its change event must never send stale codes.
        f.locator('[name=id]').evaluate('(el,id)=>{el.value=id}',str(sid_new))
        f.locator('button',has_text='Gắn các mục đã chọn').click();expect(f).to_have_attribute('data-hydrated-for',str(sid_new));assert not writes
        expect(page.locator('body')).to_contain_text('Vui lòng xem lại mã trước khi lưu')
        f.locator('[name=id]').select_option(str(sid_a));f.locator('[name=mode]').select_option('add');expect(f.locator('[name=codes]')).to_have_value('')
        f.locator('[data-d0-link-search=tech_catalog]').fill(name_b);f.locator('[data-d0-link-pick="'+code_b+'"]').click();expect(f.locator('[name=codes]')).to_have_value(code_b)
        f.locator('[name=mode]').select_option('replace');expect(f.locator('[name=codes]')).to_have_value(code_a)
        f.locator('[data-d0-link-filter]').select_option('unlinked');expect(f.locator('[name=id]')).to_have_value(str(sid_new));expect(f.locator('[name=codes]')).to_have_value('');expect(f).to_have_attribute('data-hydrated-for',str(sid_new))
        with page.expect_response(lambda r:r.request.method=='PUT' and '/standards/services/'+str(sid_new) in r.url) as saved:f.locator('button',has_text='Gắn các mục đã chọn').click()
        assert saved.value.status==200 and saved.value.request.post_data_json['codes']==[];settle(page)
        with db() as c:
            assert [x[0] for x in c.execute('SELECT tech_code FROM service_tech_codes WHERE service_id=?',(sid_a,))]==[code_a]
            assert not c.execute('SELECT 1 FROM service_tech_codes WHERE service_id=?',(sid_new,)).fetchone()
        f=page.locator('[data-d0=link][data-kind=services]');f.locator('[name=id]').select_option(str(sid_pack));f.locator('[name=mode]').select_option('remove')
        expect(f.locator('[data-d0-existing]:checked')).to_have_count(0);expect(f.locator('[name=codes]')).to_have_value('')
        f.locator('.d0-existing label').filter(has_text=code_b).locator('input').check();expect(f.locator('[name=codes]')).to_have_value(code_b)
        expect(f.locator('.d0-chosen')).to_contain_text(code_a);expect(f.locator('.d0-chosen')).not_to_contain_text(code_b)
        f.locator('[name=reason]').fill('Bỏ mã gói giả lập đã kiểm');f.locator('[name=confirmed]').check()
        with page.expect_response(lambda r:r.request.method=='PUT' and '/standards/services/'+str(sid_pack) in r.url) as saved:f.locator('button',has_text='Gắn các mục đã chọn').click()
        body=saved.value.request.post_data_json;assert saved.value.status==200 and body['mode']=='remove' and body['codes']==[code_b] and body['removed_codes']==[code_b];settle(page)
        with db() as c:assert [x[0] for x in c.execute('SELECT tech_code FROM service_tech_codes WHERE service_id=?',(sid_pack,))]==[code_a]
        f=page.locator('[data-d0=link][data-kind=lab-tests]');f.locator('[name=id]').select_option(str(tid));expect(f.locator('select[name=mode]')).to_have_count(0)
        for row in shared:
            f.locator('[data-d0-link-search]').fill(row['name']);f.locator('[data-d0-link-pick="'+row['code']+'"]').click();expect(f.locator('[name=codes]')).to_have_value(row['code'])
        with page.expect_response(lambda r:r.request.method=='PUT' and '/standards/lab-tests/'+str(tid) in r.url) as saved:f.locator('button',has_text='Gắn các mục đã chọn').click()
        assert saved.value.status==200 and saved.value.request.post_data_json['code']==shared[-1]['code'];settle(page)
        with db() as c:assert c.execute('SELECT shared_code FROM lab_tests WHERE id=?',(tid,)).fetchone()[0]==shared[-1]['code']
        f=page.locator('[data-d0=link][data-kind=services]');f.locator('[data-d0-link-filter]').select_option('inactive');expect(f.locator('[name=id]')).to_have_value('');expect(f.locator('button',has_text='Gắn các mục đã chọn')).to_be_disabled();expect(f).to_contain_text('Không có mục phù hợp')
        no_horizontal_scroll(page);assert not errors,errors;browser.close()
