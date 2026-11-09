"""End-to-end A/B/C/D on real HTTPS, concurrent isolated staff browsers, fake data."""
import os,ssl,subprocess,sys,time,base64,hashlib,secrets
from pathlib import Path
import httpx,pytest
from playwright.sync_api import sync_playwright,expect
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from .conftest import ROOT,PASSWORDS,IDS
from .test_v050_abcd import medicine,service
from .browser_helpers import settle,go,pick,send,submit,no_horizontal_scroll,small_targets


def test_v050_all_workflows_https_browser(clients,visit):
    mid=medicine(clients);sid=service(clients)
    unit=clients['manager'].post(f'/api/medicines/{mid}/units',json={'name':'vỉ','base_factor':5}).json()['id']
    certdir=ROOT/'v050-certs'
    subprocess.run([sys.executable,'-m','scripts.create_lan_certificate','--name','minhduc.internal','--ip','127.0.0.1','--output',str(certdir)],check=True)
    env={**os.environ,'CLINIC_TLS_CERT':str(certdir/'server.crt'),'CLINIC_TLS_KEY':str(certdir/'server.key')}
    origin=env['CLINIC_ORIGIN'];evidence=Path('test_evidence/v050');evidence.mkdir(parents=True,exist_ok=True)
    errors=[]
    with (ROOT/'v050-https.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','scripts.run_lan'],env=env,stdout=log,stderr=log)
        try:
            with httpx.Client(verify=ssl.create_default_context(cafile=str(certdir/'ca.crt')),trust_env=False,timeout=2) as probe:
                for _ in range(100):
                    if server.poll() is not None:pytest.fail((ROOT/'v050-https.log').read_text())
                    try:
                        if probe.get(origin+'/api/health').status_code==200:break
                    except (httpx.HTTPError,OSError):pass
                    time.sleep(.1)
                else:pytest.fail('No HTTPS response')
            cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
            pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
                contexts={role:browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1050}) for role in ('doctor','technician','nurse','cashier','pharmacy','manager')}
                pages={role:context.new_page() for role,context in contexts.items()}
                expected={'doctor':'doctor','technician':'lab','nurse':'nurse','cashier':'cashier','pharmacy':'pharmacy','manager':'manager'}
                for role,page in pages.items():
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda response:errors.append(f'HTTP {response.status} {response.url}') if response.status>=400 and not response.url.endswith('/api/me') else None)
                    page.on('dialog',lambda dialog:dialog.accept('Đã thực hiện y lệnh giả lập, theo dõi ổn định') if dialog.type=='prompt' else dialog.accept())
                    page.goto(origin,wait_until='networkidle')
                    assert page.evaluate("showDay('2026-11-08T18:30:01.123456+00:00')")=='09/11/2026 01:30'
                    page.locator('[name="username"]').fill('test_'+role);page.locator('[name="password"]').fill(PASSWORDS[role])
                    page.locator('[data-form="login"] button').click();page.locator('#logout').wait_for();settle(page)
                    # Một menu theo việc cho mỗi vai trò, không còn menu "Quy trình v0.5".
                    nav=page.locator('#navigation [data-action="navigate"]')
                    assert nav.count()==1 and nav.first.get_attribute('data-page')==expected[role]
                    assert 'v0.5' not in page.locator('body').inner_text().replace('v0.5.0','')
                    assert page.evaluate('typeof v050Workflows')=='undefined'
                d=go(pages['doctor'],'doctor');pick(d,'visit',visit)
                d.locator('[data-form="clinical"] [name="diagnosis"]').fill('Chẩn đoán giả lập v0.5 trên HTTPS')
                submit(d,'clinical','Đã lưu phiếu khám')
                assert clients['doctor'].get(f'/api/visits/{visit}').json()['diagnosis']=='Chẩn đoán giả lập v0.5 trên HTTPS'
                d.locator('[data-form="assign-nurse"] [name="nurse_id"]').select_option(str(IDS['nurse']))
                send(d,d.locator('[data-form="assign-nurse"] button'),'Đã phân công')
                d.locator('[data-form="order"] [name="service_id"]').select_option(str(sid))
                d.locator('[data-form="order"] [name="defer_approval"]').select_option('1');submit(d,'order','Đã lưu nháp')
                send(d,d.locator('[data-action="authorize-order"]').first,'Đã duyệt chỉ định')
                d.screenshot(path=str(evidence/'A-chi-dinh.png'),full_page=True)
                order=next(o for o in clients['doctor'].get('/api/orders').json() if o['visit_id']==visit)
                tech=go(pages['technician'],'lab');pick(tech,'order',order['id'])
                tech.locator('[data-form="result"] [name="result_text"]').fill('Glucose | 5,0 | mmol/L | 3,9–5,6 |\nKết luận: Kết quả giả lập')
                submit(tech,'result','Đã chuyển kết quả')
                d=go(d,'doctor');send(d,d.locator(f'[data-action="approve"][data-id="{order["id"]}"]'),'Đã duyệt kết quả')
                d.locator('[data-form="rx"] [name="medicine_id"]').select_option(str(mid))
                expect(d.locator('[data-form="rx"] [name="unit_id"] option')).to_have_count(2)
                d.locator('[data-form="rx"] [name="unit_id"]').select_option(str(unit));d.locator('[data-form="rx"] [name="quantity"]').fill('2');d.locator('[data-form="rx"] [name="directions"]').fill('Chỉ dùng giả lập')
                submit(d,'rx','Đã lưu đơn thuốc')
                prescription=next(x for x in clients['doctor'].get('/api/prescriptions').json() if x['visit_id']==visit)
                assert prescription['items'][0]['quantity']==10,prescription
                rid=prescription['id']
                pharm=go(pages['pharmacy'],'pharmacy')
                expect(pharm.locator('#navigation [data-count="pharmacy"]')).to_have_text(str(sum(x['status']=='draft' for x in clients['pharmacy'].get('/api/prescriptions').json())))
                send(pharm,pharm.locator(f'[data-action="dispense"][data-id="{rid}"]'),'Đã cấp thuốc')
                with pharm.expect_download() as download:pharm.locator(f'[data-kind="rx"][data-id="{rid}"][data-format="pdf"]').first.click()
                download.value.save_as(str(evidence/'B-don-da-cap.pdf'))
                did=next(x['id'] for x in clients['pharmacy'].get('/api/dispensations').json() if x['visit_id']==visit)
                pick(pharm,'dispense',did);pharm.locator('[data-form="return"]').wait_for();pharm.screenshot(path=str(evidence/'B-cap-phat.png'),full_page=True)
                d.locator('[data-form="nursing-task"] [name="content"]').fill('Theo dõi sinh hiệu giả lập sau khám')
                submit(d,'nursing-task','Đã giao y lệnh')
                n=go(pages['nurse'],'nurse');pick(n,'nurse-visit',visit)
                n.locator('#v_pulse').fill('78');n.locator('#v_bp').fill('120/80');submit(n,'nurse-vitals','Đã lưu sinh hiệu')
                vitals=clients['doctor'].get(f'/api/visits/{visit}').json()['vitals']
                assert 'Mạch 78 l/p' in vitals and 'HA 120/80 mmHg' in vitals,vitals
                n.locator('[data-form="care-note"] [name="content"]').fill('Ghi nhận chăm sóc giả lập: người bệnh ổn định')
                submit(n,'care-note','Đã lưu ghi nhận chăm sóc')
                send(n,n.locator('[data-action="execute-task"]').first,'Đã ghi nhận thực hiện')
                expect(n.locator('#workspace')).to_contain_text('Đã thực hiện y lệnh giả lập, theo dõi ổn định');n.screenshot(path=str(evidence/'C-dieu-duong.png'),full_page=True)
                # Ứng trước mặc định TẮT: không hiện trên màn hình thu ngân cho tới khi quản trị bật.
                cash=go(pages['cashier'],'cashier');pick(cash,'cash',visit)
                assert cash.locator('[data-form="advance"]').count()==0
                assert clients['admin'].put('/api/ui-settings',json={'advance_payment':True}).status_code==200
                cash=go(cash,'cashier');pick(cash,'cash',visit)
                cash.locator('#workspace summary').filter(has_text='Nhận tiền ứng trước').click()
                cash.locator('[data-form="advance"] [name="amount"]').fill('50000');submit(cash,'advance','Đã nhận tiền ứng trước')
                assert clients['admin'].put('/api/ui-settings',json={'advance_payment':False}).status_code==200
                d=go(d,'doctor');send(d,d.locator('[data-action="complete-visit"]'),'Đã hoàn tất')
                d.locator('[data-form="addendum"]').wait_for();d.screenshot(path=str(evidence/'D-khoa-luot.png'),full_page=True)
                state=clients['cashier'].get(f'/api/visits/{visit}/settlement').json()
                assert state['clinical_status']=='completed' and state['billing']['due']==155000 and state['dispensing_status']=='dispensed',state
                d.locator('[data-form="addendum"] [name="reason"]').fill('Bổ sung ghi chú giả lập sau đối soát')
                d.locator('[data-form="addendum"] [name="content"]').fill('BROWSER_ADDENDUM_V050 giả lập, giữ nguyên hồ sơ gốc')
                submit(d,'addendum','Đã gửi phụ lục')
                aid=clients['doctor'].get(f'/api/visits/{visit}/addenda').json()[0]['id']
                # Phụ lục tắt: ẩn khỏi màn hình quản lý và bác sĩ; bật lại thì hiện.
                assert clients['admin'].put('/api/ui-settings',json={'addendum':False}).status_code==200
                manager=go(pages['manager'],'manager')
                assert manager.locator(f'[data-action="review-addendum"][data-id="{aid}"]').count()==0
                assert clients['admin'].put('/api/ui-settings',json={'addendum':True}).status_code==200
                manager=go(manager,'manager');send(manager,manager.locator(f'[data-action="review-addendum"][data-id="{aid}"][data-value="approve"]'),'Đã xử lý phụ lục')
                d=go(d,'doctor');d.locator('#visit_choose').select_option(str(visit));settle(d)
                expect(d.locator('[data-form="clinical"] [name="diagnosis"]')).to_be_disabled()
                with d.expect_download() as download:d.locator('[data-kind="visit"][data-format="pdf"]').click()
                download.value.save_as(str(evidence/'phieu-kham-phu-luc.pdf'))
                assert (evidence/'phieu-kham-phu-luc.pdf').read_bytes().startswith(b'%PDF-')
                # Return through the browser after clinical completion, credit before cash refund.
                form=pharm.locator('[data-form="return"]');form.locator('[name="quantity"]').fill('2');form.locator('[name="reason"]').fill('Trả thuốc giả lập sau khóa, cách ly đối soát')
                submit(pharm,'return','Đã gửi phiếu trả')
                manager=go(manager,'manager')
                expect(manager.locator('#navigation [data-count="manager"]')).not_to_have_text('')
                send(manager,manager.locator('[data-action="review-return"][data-value="approve"]').first,'Đã xử lý phiếu trả')
                assert clients['cashier'].get(f'/api/visits/{visit}/settlement').json()['billing']['due']==153000
                # Quản lý dùng được trên điện thoại 390px: không tràn ngang, nút đủ lớn.
                manager.set_viewport_size({'width':390,'height':844})
                for tab in ('approve','visits','catalog','report'):
                    manager.locator(f'[data-action="tab"][data-tab="{tab}"]').click();settle(manager)
                    no_horizontal_scroll(manager)
                    assert not small_targets(manager),small_targets(manager)
                # An independent reviewer can use the queue without any assigned visit.
                username='fake_ui_review_'+secrets.token_hex(5);password=secrets.token_urlsafe(24)
                assert clients['admin'].post('/api/accounts',json={'username':username,'password':password,'full_name':'Bác sĩ duyệt giả lập','roles':['doctor','controlled_reviewer']}).status_code==201
                independent=browser.new_context(viewport={'width':1440,'height':1050});review=independent.new_page()
                review.on('pageerror',lambda e:errors.append(str(e)))
                review.goto(origin,wait_until='networkidle');review.locator('[name="username"]').fill(username);review.locator('[name="password"]').fill(password)
                review.locator('[data-form="login"] button').click();review.locator('#logout').wait_for();settle(review)
                review.locator('[data-form="controlled-approve"]').wait_for()
                # Thuốc kiểm soát tắt: biểu mẫu duyệt ẩn khỏi giao diện.
                assert clients['admin'].put('/api/ui-settings',json={'controlled_drugs':False}).status_code==200
                go(review,'doctor');assert review.locator('[data-form="controlled-approve"]').count()==0
                assert clients['admin'].put('/api/ui-settings',json={'controlled_drugs':True}).status_code==200
                independent.close()
                assert not errors,errors
                for context in contexts.values():context.close()
                browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
