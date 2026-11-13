"""Real HTTPS, configured resource-light worker, three isolated concurrent browser sessions."""
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
from playwright.sync_api import sync_playwright,expect
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from .conftest import ROOT,PASSWORDS,IDS,SERVICE,db
from .browser_helpers import settle,go,pick,send,submit,no_horizontal_scroll
from .test_tls_chrome_compat import https_server


def test_real_https_three_browser_roles_and_pdf():
    # Pricing and medicine data must exist before the clinician can order/prescribe.
    with db(True) as c:
        c.execute('INSERT INTO service_catalog(name,price) VALUES(?,?)',('Xét nghiệm HTTPS giả lập',42000))
        srv=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(srv,'lab'))
        c.execute('INSERT INTO medicines(name,base_unit) VALUES(?,?)',('Thuốc HTTPS giả lập','viên'))
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
                # Mỗi vai trò vào thẳng màn hình công việc, chỉ thấy menu của mình, không còn menu mang số phiên bản.
                expected={'reception':['reception','prices','m6-list','m5-queue'],'doctor':['doctor','m6-list'],'cashier':['cashier'],'technician':['lab','m5-queue'],'pharmacy':['pharmacy','m6-list'],'admin':['admin','price-management','settings','m6-admin','m5-admin']}
                for role,page in pages.items():
                    settle(page)
                    nav=page.locator('#navigation [data-action="navigate"]')
                    assert [nav.nth(i).get_attribute('data-page') for i in range(nav.count())]==expected[role]
                    assert 'v0.5' not in page.locator('#navigation').inner_text() and 'Quy trình' not in page.locator('#navigation').inner_text()
                    expect(page.locator('#workspace')).to_have_attribute('data-page',expected[role][0])
                # Bác sĩ đang mở màn hình khám, chưa bấm gì thêm.
                d=go(pages['doctor'],'doctor')
                r=pages['reception']
                # Lễ tân xem bảng giá dịch vụ chỉ đọc để báo giá.
                r=go(r,'prices')
                expect(r.locator('#workspace tr[data-search]').filter(has_text='Khám giả lập')).to_contain_text('150.000')
                assert r.locator('#workspace form').count()==0 and r.locator('#workspace button').count()==0
                r.locator('#price-filter').fill('xét nghiệm https')
                expect(r.locator('#workspace tr[data-search]:visible')).to_have_count(1)
                r=go(r,'reception')
                r.locator('#workspace summary').filter(has_text='Thêm bệnh nhân mới').click()
                r.locator('[data-form="patient"] [name="full_name"]').fill('Bệnh nhân giả lập HTTPS ba máy')
                r.locator('[data-form="patient"] [name="date_of_birth"]').fill('15/03/1985')
                r.locator('[data-form="patient"] [name="sex"]').select_option('Nữ')
                r.locator('[data-form="patient"] [name="phone"]').fill('0900000099')
                submit(r,'patient','Đã lưu bệnh nhân')
                # Bệnh nhân vừa tạo được chọn sẵn ở bước 2.
                expect(r.locator('#visit-step .patient-head')).to_contain_text('Bệnh nhân giả lập HTTPS ba máy')
                r.locator('[data-form="visit"] select[name="doctor_id"]').select_option(str(IDS['doctor']))
                vid=str(submit(r,'visit','Đã tiếp nhận lượt khám').json()['id'])
                expect(r.locator(f'[data-kind="intake"][data-id="{vid}"]').first).to_be_visible()
                # Số đếm Tiếp đón đúng bằng số dòng của hàng chờ Tiếp đón.
                rows=r.locator('#workspace [data-kind="intake"][data-format="pdf"]').count()
                expect(r.locator('#navigation [data-count="reception"]')).to_have_text(str(rows))
                # Số đếm tự cập nhật không cần bấm: mô phỏng lần hỏi định kỳ (cùng đường chạy khi quay lại tab).
                with db() as c:open_visits=c.execute("SELECT COUNT(*) FROM visits WHERE doctor_id=? AND status NOT IN ('completed','cancelled')",(IDS['doctor'],)).fetchone()[0]
                d.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                expect(d.locator('#navigation [data-count="doctor"]')).to_have_text(str(open_visits))
                expect(d.locator('#queue-news')).to_contain_text('Hàng chờ có thêm 1 việc mới')
                d.locator('#queue-news button').click();settle(d)
                pick(d,'visit',vid)
                d.locator('[data-form="clinical"] [name="chief_complaint"]').fill('Ghi khám giả lập HTTPS')
                d.locator('[data-form="clinical"] [name="diagnosis"]').fill('Chẩn đoán giả lập')
                d.locator('#v_pulse').fill('88')
                d.locator('#v_bp').fill('150/95')
                expect(d.locator('#vitals-flags')).to_contain_text('Huyết áp cao')
                d.locator('[data-form="clinical"] [name="follow_up"]').fill('01/01/2027')
                submit(d,'clinical','Đã lưu phiếu khám')
                expect(d.locator('#v_bp')).to_have_value('150/95')
                cash=go(pages['cashier'],'cashier')
                # Three authenticated browser contexts stay open together.
                for role in ('reception','doctor','cashier'):
                    assert pages[role].evaluate("fetch('/api/me').then(r=>r.status)")==200
                    pages[role].screenshot(path=str(evidence/(role+'.png')),full_page=True)
                d.locator('[data-form="order"] [name="service_id"]').select_option(label='Xét nghiệm – Xét nghiệm HTTPS giả lập (42.000 đ)')
                submit(d,'order','Đã lập chỉ định')
                tech=go(pages['technician'],'lab')
                tech.locator('[data-action="pick"][data-kind="order"]').filter(has_text='Xét nghiệm HTTPS giả lập').first.click();settle(tech)
                expect(tech.locator('#workspace .patient-head')).to_contain_text('Xét nghiệm HTTPS giả lập')
                tech.locator('[data-form="result"] [name="result_text"]').fill('Glucose | 9,2 | mmol/L | 3,9–5,6 | H\nKết luận: Kết quả giả lập HTTPS')
                submit(tech,'result','Đã chuyển kết quả')
                d=go(d,'doctor')
                send(d,d.locator('[data-action="approve"]').first,'Đã duyệt kết quả')
                with d.expect_download() as download:d.locator('[data-kind="lab"][data-format="pdf"]').first.click()
                download.value.save_as(str(evidence/'result.pdf'))
                d.get_by_text('Kê / cấp thuốc từ kho (quy trình hiện có)',exact=True).click()
                d.locator('[data-form="rx"] [name="quantity"]').fill('2')
                submit(d,'rx','Đã lưu đơn thuốc')
                with d.expect_download() as download:d.locator('[data-kind="rx"][data-format="pdf"]').first.click()
                download.value.save_as(str(evidence/'rx.pdf'))
                cash=go(cash,'cashier');pick(cash,'cash',vid)
                expect(cash.locator('[data-form="payment"] [name="amount"]')).to_have_value('192000')
                cash.locator('[data-form="payment"] [name="amount"]').fill('150000')
                submit(cash,'payment','Đã thu tiền')
                with cash.expect_download() as download:cash.locator('[data-action="export-receipt"]').first.click()
                download.value.save_as(str(evidence/'receipt.pdf'))
                for name in ('result.pdf','rx.pdf','receipt.pdf'):
                    assert (evidence/name).read_bytes().startswith(b'%PDF-'),name
                admin=pages['admin'];admin.locator('[data-form="account"]').wait_for()
                # Cài đặt: chỉ quản trị thấy; bật/tắt ứng trước lưu phía máy chủ.
                admin=go(admin,'settings')
                expect(admin.locator('[name="advance_payment"]')).not_to_be_checked()
                admin.locator('[name="advance_payment"]').check();submit(admin,'ui-settings','Đã lưu cài đặt')
                expect(admin.locator('[name="advance_payment"]')).to_be_checked()
                cash=go(cash,'cashier');pick(cash,'cash',vid)
                expect(cash.locator('#workspace summary').filter(has_text='Nhận tiền ứng trước')).to_have_count(1)
                admin.locator('[name="advance_payment"]').uncheck();submit(admin,'ui-settings','Đã lưu cài đặt')
                cash=go(cash,'cashier')
                expect(cash.locator('#workspace summary').filter(has_text='Nhận tiền ứng trước')).to_have_count(0)
                # Bác sĩ dùng được trên điện thoại 390px: không tràn ngang.
                d.set_viewport_size({'width':390,'height':844});d=go(d,'doctor')
                no_horizontal_scroll(d)
                # Existing teal/white styles and logo load through HTTPS.
                assert r.locator('img').first.evaluate('(img)=>img.complete && img.naturalWidth>0')
                assert not errors,errors
                for context in contexts.values():context.close()
                browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()


@pytest.mark.parametrize('width,height',[(1366,768),(390,844)])
def test_u1b_glass_login_and_shell(https_server,width,height):
    import re
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':height});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin)
            expect(page.locator('[data-form="login"]')).to_be_visible()
            expect(page.locator('html')).not_to_have_class(re.compile('fonts-pending'))
            expect(page.locator('.login-logo')).to_be_visible()
            assert page.locator('.login-logo').bounding_box()['height']==96
            assert page.locator('[name="username"]').bounding_box()['height']>=48
            no_horizontal_scroll(page)
            evidence=Path('test_evidence/u1b');evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/f'login-{width}.png'),full_page=True)
            page.locator('[name="username"]').fill('test_reception')
            page.locator('[name="password"]').fill(PASSWORDS['reception'])
            page.locator('[data-form="login"] button').click()
            expect(page.locator('#logout')).to_be_visible();settle(page)
            expect(page.locator('.shell-header')).to_be_visible()
            assert page.locator('.shell-header').evaluate('e=>getComputedStyle(e).position')==('static' if width<=900 else 'sticky')
            active=page.locator('.navbutton[aria-current="page"]')
            assert active.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(11, 31, 23)'
            no_horizontal_scroll(page)
            if width<=900:
                assert page.locator('#navigation').evaluate('e=>getComputedStyle(e).flexWrap')=='nowrap'
                assert page.locator('#navigation').evaluate('e=>e.scrollWidth>e.clientWidth')
            expect(page.locator('#toast')).to_be_hidden()
            page.screenshot(path=str(evidence/f'shell-{width}.png'),full_page=True)
            assert not errors,errors
        finally: browser.close()


@pytest.mark.parametrize('width,height',[(1366,768),(390,844)])
def test_u1b_doctor_sticky_below_shell_after_scroll(https_server,clients,width,height):
    import secrets
    reception=clients['reception']
    patient=reception.post('/api/patients',json={'full_name':'Người bệnh sticky giả lập '+secrets.token_hex(4),'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'})
    assert patient.status_code==201,patient.text
    pid=patient.json()['id']
    with db(True) as c:c.execute('UPDATE patients SET allergies=? WHERE id=?',('Dị ứng giả lập sticky',pid))
    visit=reception.post('/api/visits',json={'patient_id':pid,'doctor_id':IDS['doctor'],'service_id':SERVICE})
    assert visit.status_code==201,visit.text
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            page.goto(origin)
            page.locator('[name="username"]').fill('test_doctor');page.locator('[name="password"]').fill(PASSWORDS['doctor'])
            page.locator('[data-form="login"] button').click();expect(page.locator('#logout')).to_be_visible();settle(page)
            page.set_viewport_size({'width':390,'height':844})
            expect(page.locator('html')).to_have_css('--shell-h','0px')
            page.set_viewport_size({'width':1366,'height':768})
            page.set_viewport_size({'width':width,'height':height})
            pick(page,'visit',visit.json()['id'])
            expect(page.locator('.doctor-sticky .allergy-warning')).to_contain_text('Dị ứng giả lập sticky')
            page.locator('.doctor-sticky').scroll_into_view_if_needed()
            start_scroll=page.evaluate('scrollY')
            page.evaluate('window.scrollBy(0,600)')
            expect(page.locator('#toast')).to_be_hidden()
            rectangles=page.evaluate('''()=>{
                const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};};
                return {header:rect('.shell-header'),warning:rect('.doctor-sticky .allergy-warning'),tabs:rect('.doctor-tabs'),offset:parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--shell-h')),scroll:scrollY};
            }''')
            assert rectangles['scroll']-start_scroll==600,rectangles
            for key in ('warning','tabs'):
                r=rectangles[key]
                assert 0<=r['top']<r['bottom']<=height,rectangles
                assert r['top']>=rectangles['header']['bottom'],rectangles
            if width<=900:assert rectangles['offset']==0
            else:assert rectangles['offset']>0
            no_horizontal_scroll(page)
            evidence=Path('test_evidence/u1b');evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/f'doctor-sticky-{width}.png'))
            for target in page.locator('.doctor-tabs button').evaluate_all('es=>es.map(e=>e.dataset.target)'):
                tab=page.locator('.doctor-tabs button[data-target="'+target+'"]')
                tab.click()
                if target=='history': expect(page.locator('#patient-history h2')).to_be_visible()
                if target=='payment': expect(page.locator('#doctor-payment-status')).not_to_contain_text('Chọn Thanh toán')
                expect(tab).to_have_attribute('aria-current','true')
                heading=page.locator('#doctor-'+target+' h2, #doctor-'+target+' h3').first
                expect(heading).to_be_visible()
                geometry=heading.evaluate("e=>{const r=e.getBoundingClientRect(),sticky=document.querySelector('.doctor-sticky').getBoundingClientRect();return {top:r.top,bottom:r.bottom,stickyBottom:sticky.bottom,height:innerHeight};}")
                assert geometry['top']>=geometry['stickyBottom'] and geometry['bottom']<=geometry['height'],(target,geometry)
                if target in ('history','payment'):
                    assert page.evaluate('scrollY+innerHeight>=document.documentElement.scrollHeight-2'),target
                # Force the scroll handler again even when scrollIntoView was clamped.
                page.evaluate("window.dispatchEvent(new Event('scroll'))")
                expect(tab).to_have_attribute('aria-current','true')

        finally:browser.close()
