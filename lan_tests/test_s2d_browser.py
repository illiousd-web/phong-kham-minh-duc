"""Real imaging entry, normal sentences, paste/drop and signed corrections."""
import base64
import hashlib
from io import BytesIO
import os
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader
import pytest

from app.database import db
from tests.s2c_cases import new_visit, signature_image
from PIL import Image
from .conftest import IDS, PASSWORDS, SERVICE
from .test_tls_chrome_compat import https_server as https_server
from .browser_helpers import settle, pick, no_horizontal_scroll


def pixels():
    out=BytesIO();Image.new('RGB',(320,180),'white').save(out,format='JPEG');return out.getvalue()


@pytest.mark.parametrize('width',[1366,390])
def test_imaging_entry_buttons_files_paste_sign_and_print(https_server,clients,width,tmp_path):
    vid=new_visit(clients,IDS,SERVICE)
    tag=secrets.token_hex(5)
    service=clients['admin'].post('/api/catalog/services',json={'name':'Siêu âm giả lập '+tag,'category':'ultrasound','price':1000})
    assert service.status_code==201,service.text
    order=clients['doctor'].post('/api/orders',json={'visit_id':vid,'category':'ultrasound','service_id':service.json()['id'],'request_key':tag})
    assert order.status_code==201,order.text
    oid=order.json()['id']
    assert clients['admin'].put(f'/api/users/{IDS["doctor"]}/signature',files={'file':('fake.png',signature_image(),'image/png')}).status_code==200
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        page=browser.new_page(viewport={'width':width,'height':900},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin)
        page.locator('[name=username]').fill('test_doctor');page.locator('[name=password]').fill(PASSWORDS['doctor'])
        page.locator('[data-form=login] button').click();page.locator('.account-trigger').wait_for();settle(page)
        pick(page,'visit',vid)
        page.locator('[data-action=doctor-tab][data-target=orders]').click() if page.locator('[data-action=doctor-tab][data-target=orders]').count() else None
        page.locator(f'[data-s2d-order="{oid}"]').click()
        dialog=page.locator('.s2d-dialog').first
        expect(dialog.locator('[data-s2d-template]')).to_have_value('S2D-002') # Female variant suggested, still selectable.
        dialog.locator('[data-s2d-template]').select_option('S2D-001')
        dialog.locator('[data-s2d-create]').click()
        first=dialog.locator('[data-s2d-row="0"]')
        expect(first).to_have_value('')
        dialog.locator('[data-s2d-normal="0"]').click()
        with db() as c:
            import json
            normal=json.loads(c.execute("SELECT content FROM imaging_templates WHERE code='S2D-001'").fetchone()['content'])['rows'][0][1]
        expect(first).to_have_value('\n'.join(normal))
        dialog.locator('[data-s2d-unclear="0"]').click()
        expect(first).to_have_value('Không khảo sát rõ.')
        for button in dialog.locator('[data-s2d-unclear]').all():
            button.click()
        dialog.locator('[data-s2d-conclusion]').fill('Còn …… cần đo')
        dialog.locator('[data-s2d-sign]').click()
        expect(dialog.locator('[data-s2d-error]')).to_contain_text('Kết luận')
        dialog.locator('[data-s2d-conclusion]').fill('Kết luận siêu âm giả lập.')
        with page.expect_response(lambda r:'/images' in r.url and r.request.method=='POST') as result:
            dialog.locator('[data-s2d-upload]').set_input_files({'name':'fake.jpg','mimeType':'image/jpeg','buffer':pixels()})
        assert result.value.status==201
        expect(dialog.locator('[data-s2d-images] img')).to_have_count(1)
        # A browser clipboard paste supplies PNG pixels and must be stored as JPEG.
        data=base64.b64encode(signature_image('red')).decode()
        with page.expect_response(lambda r:'/images' in r.url and r.request.method=='POST') as result:
            dialog.evaluate('''async (box,data)=>{const blob=new Blob([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],{type:'image/png'});const transfer=new DataTransfer();transfer.items.add(new File([blob],'capture.png',{type:'image/png'}));box.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,clipboardData:transfer}));}''',data)
        assert result.value.status==201
        expect(dialog.locator('[data-s2d-images] img')).to_have_count(2)
        with db() as c:
            rid=c.execute('SELECT id FROM imaging_reports WHERE order_id=?',(oid,)).fetchone()['id']
            types=[r['media_type'] for r in c.execute('SELECT media_type FROM imaging_images WHERE report_id=?',(rid,))]
        assert types==['image/jpeg','image/jpeg']
        # Drop of a third image is rejected; both existing images remain.
        with page.expect_response(lambda r:'/images' in r.url and r.request.method=='POST') as result:
            dialog.locator('[data-s2d-drop]').evaluate('''async (box,data)=>{const blob=new Blob([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],{type:'image/png'});const transfer=new DataTransfer();transfer.items.add(new File([blob],'drop.png',{type:'image/png'}));box.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:transfer}));}''',data)
        assert result.value.status==409
        expect(dialog.locator('[data-s2d-error]')).to_contain_text('tối đa 2 ảnh')
        dialog.locator('[data-s2d-sign]').click()
        confirm=page.locator('.s2d-dialog').last
        expect(confirm.locator('input')).to_have_attribute('type','password')
        confirm.locator('input').fill(PASSWORDS['doctor'])
        confirm.locator('form button').click()
        expect(page.locator('.s2d-dialog')).to_have_count(1)
        expect(dialog.locator('[data-s2d-correct]')).to_be_visible()
        assert all(dialog.locator('[data-s2d-row]').evaluate_all('(xs)=>xs.map(x=>x.readOnly)'))
        with page.expect_download() as download:
            dialog.locator('[data-s2d-print="pdf"]').click()
        output=tmp_path/'imaging.pdf';download.value.save_as(output)
        pdf=PdfReader(BytesIO(output.read_bytes()))
        assert len(pdf.pages)==1 and len(pdf.pages[0].images)==4 # Logo, two report images, signature.
        assert 'cần ký lại' not in pdf.pages[0].extract_text()
        assert dialog.locator('[data-s2d-images] img').evaluate_all('(xs)=>xs.every(x=>x.complete&&x.naturalWidth>0)')
        page.screenshot(path=str(tmp_path/f'imaging-{width}.png'),full_page=True)
        dialog.locator('[data-s2d-close]').click();no_horizontal_scroll(page)
        assert not errors,errors
        browser.close()


def test_admin_template_toggle_and_technician_reopens_signed_report(https_server,clients):
    vid=new_visit(clients,IDS,SERVICE)
    tag=secrets.token_hex(5)
    service=clients['admin'].post('/api/catalog/services',json={'name':'X-quang giao diện giả lập '+tag,'category':'xray','price':1000})
    assert service.status_code==201
    order=clients['doctor'].post('/api/orders',json={'visit_id':vid,'category':'xray','service_id':service.json()['id'],'request_key':tag})
    assert order.status_code==201
    oid=order.json()['id']
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        def login(role):
            page=browser.new_page(viewport={'width':390,'height':900})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin);page.locator('[name=username]').fill('test_'+role);page.locator('[name=password]').fill(PASSWORDS[role])
            page.locator('[data-form=login] button').click();page.locator('.account-trigger').wait_for();settle(page)
            return page
        tech=login('technician');pick(tech,'order',oid)
        tech.locator(f'[data-s2d-order="{oid}"]').click()
        dialog=tech.locator('.s2d-dialog')
        dialog.locator('[data-s2d-template]').select_option('S2D-013');dialog.locator('[data-s2d-create]').click()
        dialog.locator('[data-s2d-normal="0"]').click();dialog.locator('[data-s2d-conclusion]').fill('Kết luận X-quang giả lập.')
        with tech.expect_response(lambda r:'/imaging/reports/' in r.url and r.request.method=='PUT') as saved:
            dialog.locator('[data-s2d-save]').click()
        assert saved.value.status==200
        dialog.locator('[data-s2d-close]').click();settle(tech)
        with db() as c:
            rid=c.execute('SELECT id FROM imaging_reports WHERE order_id=?',(oid,)).fetchone()['id']
        assert clients['admin'].put(f'/api/users/{IDS["doctor"]}/signature',files={'file':('fake.png',signature_image(),'image/png')}).status_code==200
        endpoint=f'/api/document-signatures/xray/{rid}'
        state=clients['doctor'].get(endpoint)
        assert state.status_code==200,state.text
        assert clients['doctor'].post(endpoint,json={'password':PASSWORDS['doctor'],'content_hash':state.json()['content_hash']}).status_code==200
        tech.reload();settle(tech);pick(tech,'order',oid)
        tech.locator(f'[data-s2d-order="{oid}"]').click()
        tech.locator(f'[data-s2d-read="{rid}"]').click()
        expect(tech.locator('[data-s2d-correct]')).to_be_visible()
        assert tech.locator('[data-s2d-row="0"]').get_attribute('readonly') is not None
        admin=login('admin');admin.locator('[data-s2d-catalog]').click()
        toggle=admin.locator('[data-template="S2D-028"]')
        try:
            toggle.click();expect(toggle).to_have_text('Bật mẫu')
            assert not any(t['code']=='S2D-028' for t in clients['doctor'].get('/api/imaging/templates').json())
            toggle.click();expect(toggle).to_have_text('Tắt mẫu')
        finally:
            assert clients['admin'].put('/api/imaging/templates/S2D-028',json={'active':True}).status_code==200
        assert not errors,errors
        browser.close()
