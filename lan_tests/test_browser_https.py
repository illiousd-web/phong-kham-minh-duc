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
                    page.locator('.account-trigger').wait_for(state='visible')
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
                assert r.locator('#workspace form').count()==0
                assert r.locator('#workspace button:not([data-r2-group])').count()==0
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
            assert abs(page.locator('.login-logo').bounding_box()['width']-(220 if width<=900 else 340))<1
            expect(page.locator('.login-logo')).to_have_attribute('src','/assets/MinhDuc_logo_trang.svg')
            assert page.locator('[name="username"]').locator('..').bounding_box()['height']>=56
            no_horizontal_scroll(page)
            evidence=Path('test_evidence/u1b');evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/f'login-{width}.png'),full_page=True)
            page.locator('[name="username"]').fill('test_reception')
            page.locator('[name="password"]').fill(PASSWORDS['reception'])
            page.locator('[data-form="login"] button').click()
            expect(page.locator('.account-trigger')).to_be_visible();settle(page)
            expect(page.locator('.shell-header')).to_be_visible()
            assert page.locator('.shell-header').evaluate('e=>getComputedStyle(e).position')==('static' if width<=900 else 'sticky')
            active=page.locator('.navbutton[aria-current="page"]')
            assert active.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(255, 255, 255, 0.9)'
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
            page.locator('[data-form="login"] button').click();expect(page.locator('.account-trigger')).to_be_visible();settle(page)
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
            if width<=900:
                assert rectangles['offset']==0
                expect(page.locator('.queue-item.current')).to_have_css('background-color','rgba(255, 255, 255, 0.72)')
                expect(page.locator('.queue-item.current')).to_have_css('border-radius','28px')
                expect(page.locator('.queue-item.current')).to_have_css('border-top-width','1px')
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
                # The new card padding lets History align without reaching the page end.
                # Payment is still the final, clamped section; retain the bottom regression.
                if target=='payment':
                    assert page.evaluate('scrollY+innerHeight>=document.documentElement.scrollHeight-2'),target
                # Force the scroll handler again even when scrollIntoView was clamped.
                page.evaluate("window.dispatchEvent(new Event('scroll'))")
                expect(tab).to_have_attribute('aria-current','true')
            page.locator('.doctor-tabs button[data-target="exam"]').click()
            expect(page.locator('.doctor-tabs button[data-target="exam"]')).to_have_attribute('aria-current','true')
            page.wait_for_timeout(1200)  # Explicitly exercise expiry of the one-second click priority.
            page.mouse.move(width-4,height-10)
            page.mouse.wheel(0,100000)
            expect(page.locator('.doctor-tabs button[data-target="payment"]')).to_have_attribute('aria-current','true')
            assert page.evaluate('scrollY+innerHeight>=document.documentElement.scrollHeight-2')

        finally:browser.close()


@pytest.mark.parametrize('width,height',[(1366,768),(390,844)])
def test_u1c_doctor_queue_and_prescription(https_server,clients,width,height):
    import secrets
    reception=clients['reception']
    patient=reception.post('/api/patients',json={'full_name':'Người bệnh U1c giả lập tên rất dài để kiểm dấu chấm lửng '+secrets.token_hex(4),'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'})
    assert patient.status_code==201,patient.text
    pid=patient.json()['id']
    with db(True) as c:c.execute('UPDATE patients SET allergies=? WHERE id=?',('Dị ứng giả lập sticky: '+('Chất giả lập gây dị ứng; '*12),pid))
    visit=reception.post('/api/visits',json={'patient_id':pid,'doctor_id':IDS['doctor'],'service_id':SERVICE})
    assert visit.status_code==201,visit.text
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            # Queue badges come from list flags, without reading clinical records.
            held=[];page.route('**/api/visits/*',lambda route:held.append(route))
            page.goto(origin)
            page.locator('[name="username"]').fill('test_doctor');page.locator('[name="password"]').fill(PASSWORDS['doctor'])
            page.locator('[data-form="login"] button').click();expect(page.locator('.account-trigger')).to_be_visible();settle(page)
            expect(page.locator('.doctor-waiting .queue-item').first).to_be_visible()
            assert held==[]
            page.unroute('**/api/visits/*')
            queued=page.locator(f'.queue-item[data-kind="visit"][data-id="{visit.json()["id"]}"]')
            queued.scroll_into_view_if_needed()
            expect(queued.locator('.waiting-allergy')).to_contain_text('Dị ứng')
            page.set_viewport_size({'width':390,'height':844})
            expect(page.locator('html')).to_have_css('--shell-h','0px')
            page.set_viewport_size({'width':1366,'height':768})
            page.set_viewport_size({'width':width,'height':height})
            pick(page,'visit',visit.json()['id'])
            expect(page.locator('.doctor-sticky .allergy-warning')).to_contain_text('Dị ứng giả lập sticky')
            expect(page.locator('#toast')).to_be_hidden()
            evidence=Path('test_evidence/u1c');evidence.mkdir(parents=True,exist_ok=True)
            if width>900:
                page.evaluate('window.scrollTo(0,1500)')
                waiting=page.locator('.doctor-waiting').bounding_box()
                assert waiting['y']>=0 and waiting['y']+waiting['height']<=height,waiting
            else:
                page.locator('.doctor-sticky').scroll_into_view_if_needed()
                assert page.locator('.doctor-sticky').bounding_box()['height']<=253
                expect(page.locator('.doctor-sticky .allergy-warning')).to_contain_text('DỊ ỨNG')
                assert page.locator('[data-action="patient-details"]').evaluate("e=>!e.closest('.doctor-sticky')")
            expect(page.locator('.queue-item.current .waiting-allergy')).to_contain_text('Dị ứng')
            assert page.locator('.queue-item.current .queue-ticket').bounding_box()['width']==44
            assert page.locator('.queue-item.current .waiting-name').evaluate("e=>e.scrollWidth>e.clientWidth && getComputedStyle(e).textOverflow==='ellipsis'")
            no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'doctor-{width}.png'))
            page.locator('.doctor-tabs [data-target="rx"]').click()
            expect(page.locator('[data-m6-form="rx"]')).to_be_visible()
            row=page.locator('.m6-row').first
            row.locator('[name="name"]').fill('Thuốc giả lập U1c')
            row.locator('[name="strength"]').fill('10 mg')
            if width>900:
                positions=[row.locator('[name="'+key+'"]').bounding_box()['y'] for key in ('dose','frequency','days','quantity')]
                assert max(positions)-min(positions)<1,positions
            assert row.locator('[name="name"]').evaluate('e=>getComputedStyle(e).fontSize')=='16px'
            no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'prescription-{width}.png'))
            assert not errors,errors
        finally:browser.close()


@pytest.mark.parametrize('width,height',[(1366,768),(390,844)])
def test_u1c_queue_allergy_flags_do_not_view_records(https_server,clients,width,height):
    import re
    import secrets
    from urllib.parse import urlsplit
    tag='Nhãn dị ứng giả lập '+secrets.token_hex(5)
    ids=[]
    allergies=[None,'Không dị ứng','   ','Chất giả lập A','Chất giả lập B','Chất giả lập C']
    for number,allergy in enumerate(allergies):
        patient=clients['reception'].post('/api/patients',json={
            'full_name':f'{tag} {number}','sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'})
        assert patient.status_code==201,patient.text
        pid=patient.json()['id']
        with db(True) as c:c.execute('UPDATE patients SET allergies=? WHERE id=?',(allergy,pid))
        response=clients['reception'].post('/api/visits',json={
            'patient_id':pid,'doctor_id':IDS['doctor'],'service_id':SERVICE})
        assert response.status_code==201,response.text
        ids.append(response.json()['id'])
    def viewed():
        marks=','.join('?' for _ in ids)
        with db() as c:
            return [r['object_id'] for r in c.execute(
                f"SELECT object_id FROM audit_log WHERE event='clinical_viewed' AND user_id=? AND object_type='visit' AND object_id IN ({marks})",
                (IDS['doctor'],*ids))]
    assert viewed()==[]
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            details=[]
            page.on('request',lambda request:details.append(request.url) if re.fullmatch(r'/api/visits/\d+',urlsplit(request.url).path) else None)
            page.goto(origin)
            page.locator('[name="username"]').fill('test_doctor');page.locator('[name="password"]').fill(PASSWORDS['doctor'])
            page.locator('[data-form="login"] button').click();expect(page.locator('.account-trigger')).to_be_visible();settle(page)
            page.locator('[name="doctor_query"]').fill(tag)
            page.locator('[data-form="doctor-filter"] button').click();settle(page)
            cards=page.locator('.doctor-waiting .queue-item')
            expect(cards).to_have_count(6)
            for i in range(6):cards.nth(i).scroll_into_view_if_needed()
            labels=page.locator('.doctor-waiting .waiting-allergy').filter(has_text='Dị ứng')
            assert viewed()==[]
            expect(labels).to_have_count(3)
            assert details==[]
            assert labels.evaluate_all('es=>es.every(e=>!e.hasAttribute("title"))')
            pick(page,'visit',ids[3])
            expect(page.locator('.doctor-sticky .allergy-warning')).to_contain_text('Chất giả lập A')
            assert viewed()==[ids[3]]
            assert len(details)==1 and urlsplit(details[0]).path==f'/api/visits/{ids[3]}'
        finally:browser.close()
    for path in ('/api/visits','/api/doctor/queue?q='+tag):
        response=clients['doctor'].get(path)
        assert response.status_code==200,response.text
        payload=response.json()
        rows=payload['visits'] if isinstance(payload,dict) else payload
        selected={r['id']:r for r in rows if r['id'] in ids}
        assert set(selected)==set(ids)
        assert [selected[i]['has_allergy'] for i in ids]==[0,0,0,1,1,1]
        for row in selected.values():
            assert 'allergies' not in row and 'patient_allergies' not in row
            assert not any(value in str(row) for value in allergies[3:])
    rows=clients['reception'].get('/api/visits').json()
    selected=[r for r in rows if r['id'] in ids]
    assert len(selected)==6
    assert all('has_allergy' not in r and 'allergies' not in r and 'patient_allergies' not in r for r in selected)


@pytest.mark.parametrize('width,height',[(1366,768),(390,844)])
@pytest.mark.parametrize('role_name',['reception','doctor','cashier'])
def test_u1r1_shared_shell(https_server,clients,width,height,role_name):
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            # Synthetic nonzero counts exercise the visible badge even on an empty database.
            def badge_counts(route):
                route.fulfill(json={key:1 for key in ('reception','doctor','cashier','prices','m6-list','m5-queue')})
            page.route('**/api/queue-counts',badge_counts)
            page.goto(origin)
            expect(page.locator('[data-form=login]')).to_be_visible()
            expect(page.locator('.glass-small-copy')).to_have_count(0)
            expect(page.locator('.trial-strip')).to_be_visible()
            expect(page.locator('.trial-strip')).to_have_css('font-size','13px')
            expect(page.locator('.trial-strip')).to_contain_text('Chưa được thẩm định')
            if width<=900:
                assert page.locator('.trial-strip').evaluate("e=>{const s=getComputedStyle(e);return e.scrollWidth<=e.clientWidth && e.clientHeight-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom)<=36}")
            page.evaluate("document.fonts.load('900 40px \"Be Vietnam Pro\"','Phòng khám')")
            assert page.evaluate("document.fonts.check('900 40px \"Be Vietnam Pro\"','Phòng khám')")
            assert page.evaluate("performance.getEntriesByType('resource').some(r=>r.name.includes('/assets/fonts/')&&r.name.includes('900-normal.woff2'))")
            evidence=Path('test_evidence/u1r1');evidence.mkdir(parents=True,exist_ok=True)
            no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'login-{role_name}-{width}.png'))
            page.locator('[name=username]').fill('test_'+role_name)
            page.locator('[name=password]').fill(PASSWORDS[role_name])
            page.locator('[data-form=login] button').click()
            expect(page.locator('.account-trigger')).to_be_visible();settle(page)
            expect(page.locator('#navigation .badge').first).to_be_visible()
            for badge in page.locator('#navigation .badge:visible').all():
                expect(badge).to_have_css('background-color','rgb(180, 35, 24)')
                assert badge.evaluate('e=>e.getBoundingClientRect().height>=24')
            expect(page.locator('.trial-strip')).to_have_css('font-size','13px')
            expect(page.locator('.glass-small-copy')).to_have_count(0)
            if width<=900:
                toast=page.locator('#toast').bounding_box();nav=page.locator('#navigation').bounding_box()
                assert toast and toast['y']>=0 and toast['y']+toast['height']<=nav['y'],(toast,nav)
            page.emulate_media(media='print')
            expect(page.locator('.card').first).to_have_css('background-color','rgb(255, 255, 255)')
            expect(page.locator('.card').first).to_have_css('box-shadow','none')
            expect(page.locator('.card').first).to_have_css('backdrop-filter','none')
            page.emulate_media(media='screen')
            expect(page.locator('.sidebar, aside.sidebar')).to_have_count(0)
            expect(page.locator('.eyebrow')).to_have_count(0)
            expect(page.locator('.trial-strip')).to_contain_text('Bản thử nghiệm')
            expect(page.locator('.trial-strip')).to_contain_text('Chưa được thẩm định')
            if width<=900:
                nav=page.locator('#navigation')
                expect(nav).to_have_css('position','fixed')
                box=nav.bounding_box();assert abs(box['x']-16)<1 and abs(box['y']+box['height']-(height-22))<1
                assert page.locator('.trial-strip').evaluate("e=>{const s=getComputedStyle(e);return e.scrollWidth<=e.clientWidth && e.clientHeight-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom)<=36}")
            expect(page.locator('.shell-header img')).to_have_attribute('src','/assets/MinhDuc_logo_mau.svg')
            active=page.locator('#navigation [aria-current=page]')
            expect(active).to_have_css('background-color','rgba(255, 255, 255, 0.9)')
            assert page.locator('#navigation').evaluate("e=>getComputedStyle(e).flexWrap==='nowrap'")
            assert page.locator('#navigation [data-action=navigate]').evaluate_all('es=>es.map(e=>e.dataset.page)')==page.evaluate('menus[role()].map(p=>p[0])')
            assert page.locator('#navigation [data-count]').count()==page.locator('#navigation [data-action=navigate]').count()
            assert page.locator('body').evaluate("e=>getComputedStyle(e).backgroundImage.includes('15% 10%')" if width<=900 else "e=>getComputedStyle(e).backgroundImage.includes('255, 217, 160')")
            assert page.locator('.card').first.evaluate("e=>getComputedStyle(e).boxShadow.includes('inset')")
            page.locator('.account-trigger').click()
            expect(page.locator('#logout')).to_be_visible()
            page.locator('#change-password').click();settle(page)
            expect(page.locator('[data-form=password]')).to_be_visible()
            page.locator('#navigation [data-action=navigate]').first.click();settle(page)
            expect(page.locator('#toast')).to_be_hidden()
            no_horizontal_scroll(page)
            page.screenshot(path=str(evidence/f'{role_name}-{width}.png'))
            if width<=900:
                page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
                footer=page.locator('footer').bounding_box();nav=page.locator('#navigation').bounding_box()
                assert footer['y']+footer['height']<=nav['y'],(footer,nav)
            page.locator('.account-trigger').click();page.locator('#logout').click()
            expect(page.locator('[data-form=login]')).to_be_visible()
            assert not errors,errors
        finally:browser.close()


@pytest.mark.parametrize('width,height',[(1366,768),(390,844)])
def test_u1r2_reception_prices_login_password(https_server,clients,width,height):
    import secrets
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence=Path('test_evidence/u1r2');evidence.mkdir(parents=True,exist_ok=True)
    def check(page,name):
        no_horizontal_scroll(page)
        small=page.locator('#workspace *').evaluate_all("es=>es.filter(e=>e.getClientRects().length&&e.textContent.trim()&&parseFloat(getComputedStyle(e).fontSize)<13).map(e=>[e.tagName,e.className,getComputedStyle(e).fontSize])")
        assert not small,small
        page.screenshot(path=str(evidence/f'{name}-{width}.png'),full_page=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin);expect(page.locator('[data-form=login]')).to_be_visible()
            expect(page.locator('.r2-login-brand img')).to_have_attribute('src','/assets/MinhDuc_logo_trang.svg')
            check(page,'login')
            page.locator('[name=username]').fill('test_reception');page.locator('[name=password]').fill(PASSWORDS['reception'])
            page.locator('[data-form=login] button').click();expect(page.locator('.account-trigger')).to_be_visible();settle(page)
            rows=clients['reception'].get('/api/visits').json()
            for status in ['waiting','in_progress','completed']:
                expect(page.locator(f'[data-r2-stat={status}] strong')).to_have_text(str(sum(v['status']==status for v in rows)))
            page.keyboard.press('F2');expect(page.locator('#search-patients')).to_be_focused()
            expect(page.locator('[data-r2-new]')).to_have_css('background-color','rgb(201, 240, 160)')
            page.locator('[data-r2-new]').hover()
            expect(page.locator('[data-r2-new]')).to_have_css('background-color','rgb(201, 240, 160)')
            page.locator('[data-r2-new]').click()
            form=page.locator('[data-form=patient]');name='Người bệnh giả lập R2 '+secrets.token_hex(4)
            form.locator('[name=full_name]').fill(name);form.locator('[name=date_of_birth]').fill('01/01/1990');form.locator('[name=sex]').select_option('Nữ');form.locator('[name=phone]').fill('0900000345')
            form.locator('button.btn').click();settle(page)
            expect(page.locator('[data-form=visit]')).to_be_visible()
            check(page,'reception')
            dock=page.locator('.r2-dock').bounding_box();assert dock and dock['y']>=0 and dock['y']+dock['height']<=height
            if width<=900:
                nav=page.locator('#navigation').bounding_box();assert dock['y']+dock['height']<=nav['y']
            page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
            footer=page.locator('footer').bounding_box();assert footer['y']+footer['height']<=dock['y'],(footer,dock)
            with page.expect_response(lambda r:r.url.endswith('/api/visits') and r.request.method=='POST') as created:
                page.locator('[data-form=visit] button[type=submit]').click()
            assert created.value.status==201
            vid=created.value.json()['id'];settle(page)
            assert any(v['id']==vid for v in clients['reception'].get('/api/visits').json())
            go(page,'prices');check(page,'prices')
            services=clients['reception'].get('/api/services').json()
            for key,n in [('services',len(services)),('fixed',sum(not x['price_at_collection'] for x in services)),('collection',sum(bool(x['price_at_collection']) for x in services))]:
                expect(page.locator(f'[data-r2-stat={key}] strong')).to_have_text(str(n))
            assert page.locator('#workspace [data-form]').count()==0
            page.locator('#price-filter').fill('không có dịch vụ giả lập này');expect(page.locator('tr[data-search]:visible')).to_have_count(0)
            page.locator('#price-filter').fill('');expect(page.locator('tr[data-search]:visible').first).to_be_visible()
            page.locator('.account-trigger').click();page.locator('#change-password').click();settle(page)
            f=page.locator('[data-form=password]');f.locator('[name=current_password]').fill('mat-khau-cu');f.locator('[name=new_password]').fill('mat-khau-moi-gia-lap');f.locator('[name=confirm_password]').fill('mat-khau-moi-gia-lap')
            expect(f.locator('[data-r2-check][data-passed=true]')).to_have_count(3)
            f.locator('[name=confirm_password]').fill('khac');expect(f.locator('[data-r2-check=match]')).to_have_attribute('data-passed','false')
            check(page,'password');assert not errors,errors
        finally:browser.close()
