"""M6 entry and row-specific lock errors on HTTPS / Chromium 109."""
import base64
import hashlib
import os
from pathlib import Path
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright,expect
from .conftest import IDS,PASSWORDS,SERVICE
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle,pick,no_horizontal_scroll


@pytest.mark.parametrize('width',[1366,390])
def test_m6_missing_ingredient_complete_on_row_and_lock(https_server,clients,request,width):
    a,r,d=clients['admin'],clients['reception'],clients['doctor']
    from app.practitioners import COLUMNS
    old_settings=a.get('/api/prescription-settings').json()
    old=next(x for x in a.get('/api/practitioners').json()['items'] if x['id']==IDS['doctor'])
    request.addfinalizer(lambda:a.put('/api/practitioners/'+str(IDS['doctor']),json={k:old[k] for k in COLUMNS}))
    request.addfinalizer(lambda:a.put('/api/prescription-settings',json=old_settings))
    assert a.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ001','clinic_name':'Cơ sở giao diện giả lập'}).status_code==200
    assert a.put('/api/practitioners/'+str(IDS['doctor']),json={'printed_name':'Bác sĩ giao diện giả lập','practice_license':'GP-GIA-LAP','practice_scopes':['Nội']}).status_code==200
    p=r.post('/api/patients',json={'full_name':'Người giả lập M6 giao diện '+str(width),'date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':p,'doctor_id':IDS['doctor'],'service_id':SERVICE}).json()['id']
    assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán giả lập giao diện'}).status_code==200
    assert d.put(f'/api/patients/{p}/allergies',json={'allergies':'Amoxicillin'}).status_code==200
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':width,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin);page.locator('[name=username]').fill('test_doctor');page.locator('[name=password]').fill(PASSWORDS['doctor']);page.locator('[data-form=login] button').click();page.locator('#logout').wait_for();settle(page);pick(page,'visit',vid)
        row=page.locator('.m6-row').first
        for key,value in {'name':'Tên thuốc mới giả lập '+str(width),'strength':'2 mg','dose':'1','frequency':'2','days':'5','unit':'viên','route':'Uống','timing':'sau ăn'}.items():row.locator('[name='+key+']').fill(value)
        expect(row.locator('[name=quantity]')).to_have_value('10')
        row.locator('[name=quantity]').fill('11')
        form=page.locator('[data-m6-form=rx]')
        with page.expect_response(lambda x:'/api/clinical-prescriptions' in x.url and x.request.method=='POST') as response:form.locator('button.btn').click()
        assert response.value.status==201;settle(page)
        form=page.locator('[data-m6-form=rx]');expect(form.locator('[name=quantity]')).to_have_value('11')
        with page.expect_response(lambda x:x.url.endswith('/lock')) as response:form.locator('[data-m6=lock]').click()
        assert response.value.status==422
        expect(form.locator('.m6-row')).to_have_class('m6-row fields m6-invalid')
        expect(form.locator('[name=ingredient]')).to_have_attribute('aria-invalid','true')
        expect(form).to_contain_text('Bổ sung hoạt chất để in đúng tên theo TT 26/2025')
        form.locator('[name=ingredient]').fill('Amoxicillin + Acid clavulanic')
        form.locator('[name=brand_name]').fill('Tên thương mại giả lập')
        with page.expect_response(lambda x:'/api/clinical-prescriptions/' in x.url and x.request.method=='PUT') as response:form.locator('button.btn').click()
        assert response.value.status==200;settle(page)
        form=page.locator('[data-m6-form=rx]')
        with page.expect_response(lambda x:x.url.endswith('/lock')) as response:form.locator('[data-m6=lock]').click()
        assert response.value.status==422
        expect(form).to_contain_text('Trùng dị ứng thuốc')
        form.locator('[name=allergy_acknowledged]').check()
        form.locator('[name=allergy_reason]').fill('Đã đánh giá nguy cơ giả lập')
        with page.expect_response(lambda x:'/api/clinical-prescriptions/' in x.url and x.request.method=='PUT') as response:form.locator('button.btn').click()
        assert response.value.status==200;settle(page)
        form=page.locator('[data-m6-form=rx]')
        expect(form.locator('[name=allergy_acknowledged]')).to_be_checked()
        form.locator('[name=quantity]').fill('15')
        with page.expect_response(lambda x:'/api/clinical-prescriptions/' in x.url and x.request.method=='PUT') as response:form.locator('button.btn').click()
        assert response.value.status==200;settle(page)
        form=page.locator('[data-m6-form=rx]')
        with page.expect_response(lambda x:x.url.endswith('/lock')) as response:form.locator('[data-m6=lock]').click()
        assert response.value.status==422
        expect(form.locator('[name=quantity_reason]')).to_have_attribute('aria-invalid','true')
        form.locator('[name=quantity_acknowledged]').check()
        form.locator('[name=quantity_reason]').fill('Số lượng khác cách dùng giả lập')
        with page.expect_response(lambda x:'/api/clinical-prescriptions/' in x.url and x.request.method=='PUT') as response:form.locator('button.btn').click()
        assert response.value.status==200;settle(page)
        form=page.locator('[data-m6-form=rx]')
        with page.expect_response(lambda x:x.url.endswith('/lock')) as response:form.locator('[data-m6=lock]').click()
        assert response.value.status==200;settle(page)
        expect(page.locator('#doctor-rx')).to_contain_text('Đã khóa')
        with page.expect_download() as download:page.locator('#doctor-rx [data-m6-download][data-fmt=pdf]').click()
        target=Path('test_evidence/m6');target.mkdir(parents=True,exist_ok=True);download.value.save_as(str(target/f'don-gia-lap-{width}.pdf'))
        page.screenshot(path=str(target/f'ke-don-{width}.png'),full_page=True)
        no_horizontal_scroll(page)
        page.locator('#logout').click();page.locator('[name=username]').fill('test_admin');page.locator('[name=password]').fill(PASSWORDS['admin']);page.locator('[data-form=login] button').click();page.locator('#logout').wait_for();settle(page)
        from .browser_helpers import go
        go(page,'m6-admin');expect(page.locator('#workspace')).to_contain_text('Thuốc chưa rà soát')
        expect(page.locator('[data-m6-form=settings] [name=clinic_facility_code]')).to_have_value('ZZ001')
        with page.expect_download() as template:page.locator('[data-m6=template]').click()
        template.value.save_as(str(target/f'mau-gia-lap-{width}.xlsx'))
        no_horizontal_scroll(page);assert not errors,errors
        browser.close()


@pytest.mark.parametrize('width',[1366,390])
def test_s1_text_result_two_tabs_keep_first_version(https_server,clients,width):
    import secrets
    a,r,d=clients['admin'],clients['reception'],clients['doctor']
    suffix=secrets.token_hex(5)
    patient=r.post('/api/patients',json={'full_name':'Giả lập hai tab '+suffix,'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':patient,'doctor_id':IDS['doctor'],'service_id':SERVICE}).json()['id']
    service=a.post('/api/catalog/services',json={'name':'Siêu âm hai tab giả lập '+suffix,'category':'ultrasound','price':12345})
    assert service.status_code==201,service.text
    order=d.post('/api/orders',json={'visit_id':vid,'service_id':service.json()['id'],'category':'ultrasound','request_key':'s1-ui-'+suffix})
    assert order.status_code==201,order.text
    oid=order.json()['id'];origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        context=browser.new_context(viewport={'width':width,'height':900})
        first=context.new_page();first.on('pageerror',lambda e:errors.append(str(e)))
        first.goto(origin);first.locator('[name=username]').fill('test_technician');first.locator('[name=password]').fill(PASSWORDS['technician']);first.locator('[data-form=login] button').click();first.locator('#logout').wait_for();settle(first);pick(first,'order',oid)
        second=context.new_page();second.on('pageerror',lambda e:errors.append(str(e)));second.goto(origin);second.locator('#logout').wait_for();settle(second);pick(second,'order',oid)
        first.locator('[name=result_text]').fill('Phiên bản đầu giả lập S1')
        second.locator('[name=result_text]').fill('Nội dung chưa được phép ghi đè')
        with first.expect_response(lambda response:response.url.endswith(f'/orders/{oid}/result')) as sent:first.locator('[data-form=result] button').click()
        assert sent.value.status==200;settle(first)
        with second.expect_response(lambda response:response.url.endswith(f'/orders/{oid}/result')) as stale:second.locator('[data-form=result] button').click()
        assert stale.value.status==409
        expect(second.locator('[name=result_text]')).to_have_value('Nội dung chưa được phép ghi đè')
        selected=first.locator(f'[data-action="pick"][data-kind="order"][data-id="{oid}"]').first
        if not selected.is_visible():first.locator('details').filter(has=selected).first.locator('summary').click()
        pick(first,'order',oid)
        first.locator('[data-s1-result-history]').click()
        expect(first.locator('dialog')).to_contain_text('Phiên bản đầu giả lập S1')
        expect(first.locator('dialog')).not_to_contain_text('Nội dung chưa được phép ghi đè')
        no_horizontal_scroll(first);no_horizontal_scroll(second);assert not errors,errors
        context.close();browser.close()
