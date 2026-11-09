"""End-to-end A/B/C/D on real HTTPS, concurrent isolated staff browsers, fake data."""
import os,ssl,subprocess,sys,time,base64,hashlib,secrets
from pathlib import Path
import httpx,pytest
from playwright.sync_api import sync_playwright,expect
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from .conftest import ROOT,PASSWORDS,IDS
from .test_v050_abcd import medicine,service


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
                for role,page in pages.items():
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda response:errors.append(f'HTTP {response.status} {response.url}') if response.status>=400 and not response.url.endswith('/api/me') else None)
                    page.on('dialog',lambda dialog:dialog.accept('Đã thực hiện y lệnh giả lập, theo dõi ổn định') if dialog.type=='prompt' else dialog.accept())
                    page.goto(origin,wait_until='networkidle')
                    assert page.evaluate('typeof v050Workflows')=='function',errors
                    assert page.evaluate("showDay('2026-11-08T18:30:01.123456+00:00')")=='09/11/2026 01:30'
                    page.locator('[name="username"]').fill('test_'+role);page.locator('[name="password"]').fill(PASSWORDS[role])
                    page.locator('[data-form="login"] button').click();page.locator('#logout').wait_for()
                def go(role,where):
                    page=pages[role];expect(page.locator('#workspace')).not_to_have_attribute('aria-busy','true');page.locator(f'[data-page="{where}"]').click();page.wait_for_load_state('networkidle')
                    expect(page.locator('#workspace')).not_to_have_attribute('aria-busy','true')
                    assert 'Không thể tải trang:' not in page.locator('#workspace').inner_text(),page.locator('#workspace').inner_text()
                    if where=='v050':
                        page.locator('#workflow-visit').wait_for();page.locator('#workflow-visit').select_option(str(visit))
                        expect(page.locator('#workflow-visit')).to_have_value(str(visit))
                    return page
                def submit(page,kind):
                    with page.expect_response(lambda response:'/api/' in response.url and response.request.method in ('POST','PUT')) as sent:
                        page.locator(f'[data-form="{kind}"] button.btn').click()
                    response=sent.value
                    assert response.status in (200,201),(response.status,response.text(),errors)
                d=go('doctor','clinical');d.locator('#visit_choose').select_option(str(visit));d.locator('[name="diagnosis"]').fill('Chẩn đoán giả lập v0.5 trên HTTPS')
                submit(d,'clinical');d.get_by_text('Đã lưu phiếu khám',exact=False).wait_for()
                assert clients['doctor'].get(f'/api/visits/{visit}').json()['diagnosis']=='Chẩn đoán giả lập v0.5 trên HTTPS'
                d.locator('[data-form="assign-nurse"] [name="nurse_id"]').select_option(str(IDS['nurse']))
                d.locator('[data-form="assign-nurse"] button').click();d.get_by_text('Đã phân công',exact=False).wait_for()
                d=go('doctor','orders');d.locator('[data-form="order"] [name="visit_id"]').select_option(str(visit));d.locator('[name="service_id"]').select_option(str(sid))
                d.locator('[name="defer_approval"]').select_option('1');submit(d,'order');d.get_by_text('Đã lưu nháp',exact=False).wait_for()
                d.locator('[data-action="authorize-order"]').first.click();d.get_by_text('Đã duyệt chỉ định',exact=False).wait_for()
                expect(d.locator('#workspace')).not_to_have_attribute('aria-busy','true')
                d.screenshot(path=str(evidence/'A-chi-dinh.png'),full_page=True)
                order=next(o for o in clients['doctor'].get('/api/orders').json() if o['visit_id']==visit)
                tech=go('technician','orders');tech.locator('[data-form="result"] [name="order_id"]').select_option(str(order['id']))
                tech.locator('[name="result_text"]').fill('Glucose | 5,0 | mmol/L | 3,9–5,6 |\nKết luận: Kết quả giả lập')
                submit(tech,'result');tech.get_by_text('Đã chuyển kết quả',exact=False).wait_for()
                d=go('doctor','orders');d.locator(f'[data-action="approve"][data-id="{order["id"]}"]').click();d.get_by_text('Đã duyệt quy trình',exact=False).wait_for()
                d=go('doctor','rx');d.locator('[data-form="rx"] [name="visit_id"]').select_option(str(visit));d.locator('[data-form="rx"] [name="medicine_id"]').select_option(str(mid))
                expect(d.locator('[data-form="rx"] [name="unit_id"] option')).to_have_count(2)
                d.locator('[name="unit_id"]').select_option(str(unit));d.locator('[name="quantity"]').fill('2');d.locator('[name="directions"]').fill('Chỉ dùng giả lập')
                submit(d,'rx');d.get_by_text('Đã lưu đơn thuốc cấu trúc',exact=False).wait_for()
                prescription=next(x for x in clients['doctor'].get('/api/prescriptions').json() if x['visit_id']==visit)
                assert prescription['items'][0]['quantity']==10,prescription
                rid=prescription['id']
                pharm=go('pharmacy','rx');pharm.locator(f'[data-action="dispense"][data-id="{rid}"]').click();pharm.get_by_text('Đã cấp phát và tính tiền',exact=False).wait_for()
                pharm=go('pharmacy','v050');pharm.locator('[data-form="v050-return"]').wait_for();pharm.screenshot(path=str(evidence/'B-cap-phat.png'),full_page=True)
                d=go('doctor','v050');d.locator('[data-form="v050-task"] [name="content"]').fill('Theo dõi sinh hiệu giả lập sau khám')
                submit(d,'v050-task');d.get_by_text('Đã ghi nhận, có nhật ký',exact=False).wait_for()
                n=go('nurse','nursing');n.locator('[name="visit_id"]').select_option(str(visit));n.locator('#v_pulse').fill('78');n.locator('#v_bp').fill('120/80');submit(n,'nurse-vitals');n.get_by_text('Đã lưu sinh hiệu theo phân công',exact=False).wait_for()
                vitals=clients['doctor'].get(f'/api/visits/{visit}').json()['vitals']
                assert 'Mạch 78 l/p' in vitals and 'HA 120/80 mmHg' in vitals,vitals
                n=go('nurse','v050');n.locator('[data-form="v050-note"] [name="content"]').fill('Ghi nhận chăm sóc giả lập: người bệnh ổn định')
                submit(n,'v050-note');n.get_by_text('Đã ghi nhận, có nhật ký',exact=False).wait_for()
                n.locator('[data-action="v050-execute-task"]').click();n.get_by_text('Đã xử lý theo phân quyền',exact=False).wait_for()
                n.get_by_text('Đã thực hiện y lệnh giả lập, theo dõi ổn định',exact=True).wait_for();n.screenshot(path=str(evidence/'C-dieu-duong.png'),full_page=True)
                cash=go('cashier','v050');cash.locator('[data-form="v050-advance"] [name="amount"]').fill('50000');submit(cash,'v050-advance');cash.get_by_text('Đã ghi nhận, có nhật ký',exact=False).wait_for()
                d=go('doctor','v050');d.locator('[data-action="v050-complete"]').click();d.get_by_text('Đã xử lý theo phân quyền',exact=False).wait_for()
                d.locator('[data-form="v050-addendum"]').wait_for();d.screenshot(path=str(evidence/'D-khoa-luot.png'),full_page=True)
                state=clients['cashier'].get(f'/api/visits/{visit}/settlement').json()
                assert state['clinical_status']=='completed' and state['billing']['due']==155000 and state['dispensing_status']=='dispensed',state
                d.locator('[data-form="v050-addendum"] [name="reason"]').fill('Bổ sung ghi chú giả lập sau đối soát')
                d.locator('[data-form="v050-addendum"] [name="content"]').fill('BROWSER_ADDENDUM_V050 giả lập, giữ nguyên hồ sơ gốc')
                submit(d,'v050-addendum');d.get_by_text('Đã ghi nhận, có nhật ký',exact=False).wait_for()
                aid=clients['doctor'].get(f'/api/visits/{visit}/addenda').json()[0]['id']
                assert clients['manager'].post(f'/api/visits/addenda/{aid}/review',json={'approve':True}).status_code==200
                d=go('doctor','clinical');d.locator('#visit_choose').select_option(str(visit));expect(d.locator('[name="diagnosis"]')).to_be_disabled()
                with d.expect_download() as download:d.locator('[data-kind="visit"][data-format="pdf"]').click()
                download.value.save_as(str(evidence/'phieu-kham-phu-luc.pdf'))
                assert (evidence/'phieu-kham-phu-luc.pdf').read_bytes().startswith(b'%PDF-')
                # Return through the browser after clinical completion, credit before cash refund.
                form=pharm.locator('[data-form="v050-return"]');form.locator('[name="quantity"]').fill('2');form.locator('[name="reason"]').fill('Trả thuốc giả lập sau khóa, cách ly đối soát')
                submit(pharm,'v050-return');pharm.get_by_text('Đã ghi nhận, có nhật ký',exact=False).wait_for()
                manager=go('manager','v050');manager.locator('[data-action="v050-return-approve"]').first.click();manager.get_by_text('Đã xử lý theo phân quyền',exact=False).wait_for()
                assert clients['cashier'].get(f'/api/visits/{visit}/settlement').json()['billing']['due']==153000
                # An independent reviewer can use the queue without any assigned visit.
                username='fake_ui_review_'+secrets.token_hex(5);password=secrets.token_urlsafe(24)
                assert clients['admin'].post('/api/accounts',json={'username':username,'password':password,'full_name':'Bác sĩ duyệt giả lập','roles':['doctor','controlled_reviewer']}).status_code==201
                independent=browser.new_context(viewport={'width':1440,'height':1050});review=independent.new_page()
                review.on('pageerror',lambda e:errors.append(str(e)))
                review.goto(origin,wait_until='networkidle');review.locator('[name="username"]').fill(username);review.locator('[name="password"]').fill(password)
                review.locator('[data-form="login"] button').click();review.locator('#logout').wait_for()
                expect(review.locator('#workspace')).not_to_have_attribute('aria-busy','true')
                review.locator('[data-page="v050"]').click();review.locator('[data-form="v050-controlled-approve"]').wait_for()
                independent.close()
                assert not errors,errors
                for context in contexts.values():context.close()
                browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
