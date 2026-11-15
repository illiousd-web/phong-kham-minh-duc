"""Cùng kiểm thử hàng chờ trên PostgreSQL thật và API HTTPS origin."""
import pytest
from tests.pending_queue_cases import pending_data,assert_pending_queues,assert_more_than_100_pending_approvals
from lan_tests.conftest import db,IDS,client_for
from app.ui_settings import read_settings,settings_path
from app.main import FILES


def test_pending_queues_postgresql_keep_old_work_counts_and_permissions():
    roles=('technician','reception','doctor','doctor2','nurse','manager','anonymous')
    clients={role:client_for(None if role=='anonymous' else role) for role in roles}
    try:
        def get(role,path):return clients[role].get(path)
        before={role:get(role,'/api/queue-counts').json() for role in ('technician','reception','doctor','nurse','manager')}
        with pending_data(db,IDS) as data:
            assert_pending_queues(get,data,before,read_settings(settings_path(FILES))['addendum'])
            assert_more_than_100_pending_approvals(db,get,data,before,read_settings(settings_path(FILES))['addendum'])
    finally:
        for client in clients.values():client.close()


def test_pending_queues_chromium109_show_all_old_work(https_server):
    import base64,hashlib,os
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from playwright.sync_api import sync_playwright,expect
    from .conftest import PASSWORDS
    from .browser_helpers import settle,no_horizontal_scroll
    origin,certdir=https_server
    cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    errors=[]
    with pending_data(db,IDS) as data,sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        for role in ('technician','reception','doctor','nurse','manager'):
            context=browser.new_context(viewport={'width':390,'height':844})
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(origin);page.locator('[name="username"]').fill('test_'+role);page.locator('[name="password"]').fill(PASSWORDS[role])
            page.locator('[data-form="login"] button').click();page.locator('.account-trigger').wait_for();settle(page)
            if role=='technician':
                ids=[int(x) for x in page.locator('[data-action="pick"][data-kind="order"]').evaluate_all('els=>els.map(e=>e.dataset.id)')]
                assert len(ids)==len(set(ids)) and set(data['ordered'])<=set(ids)
                page.locator(f'[data-action="pick"][data-kind="order"][data-id="{data["ordered"][0]}"]').click();settle(page)
                expect(page.locator('[data-form="result"] [name="order_id"]')).to_have_value(str(data['ordered'][0]))
            elif role=='reception':
                expect(page.locator(f'[data-action="export-form"][data-kind="intake"][data-format="pdf"][data-id="{data["visits"][0]}"]')).to_have_count(1)
            elif role in ('doctor','nurse'):
                kind='visit' if role=='doctor' else 'nurse-visit'
                expect(page.locator(f'[data-action="pick"][data-kind="{kind}"][data-id="{data["visits"][0]}"]')).to_have_count(1)
                if role=='doctor':
                    page.locator('summary').filter(has_text='Lượt đã kết thúc (100 gần nhất)').click()
                    page.locator('#visit_choose').select_option(str(data['visits'][-1]));settle(page)
                    expect(page.locator('[data-form="clinical"] [name="diagnosis"]')).to_be_disabled()
            else:
                for path,action in (('/api/adjustments','review-adjustment'),('/api/orders/cancellation-requests','review-cancel'),('/api/medication-returns','review-return'),('/api/visits/addenda/pending','review-addendum')):
                    expect(page.locator(f'[data-action="{action}"][data-id="{data["pending"][path]}"][data-value="approve"]')).to_have_count(1)
            key='lab' if role=='technician' else role
            expected=page.evaluate("async key=>(await api('/queue-counts'))[key]",key)
            expect(page.locator(f'#navigation [data-count="{key}"]')).to_have_text(str(expected))
            no_horizontal_scroll(page);context.close()
        assert not errors
        browser.close()


from .test_tls_chrome_compat import https_server as https_server  # pytest discovers this imported fixture.


def test_r5_pharmacy_and_nurse_layouts(https_server, clients, visit):
    import base64
    import hashlib
    import os
    import secrets
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from playwright.sync_api import sync_playwright, expect
    from .conftest import PASSWORDS
    from .browser_helpers import settle, pick, no_horizontal_scroll

    medicine_name = 'Thuốc giả lập R5 ' + secrets.token_hex(5)
    response = clients['manager'].post('/api/catalog/medicines', json={'name': medicine_name, 'base_unit': 'viên'})
    assert response.status_code == 201, response.text
    mid = response.json()['id']
    assert clients['pharmacy'].post('/api/stock/receipts', json={
        'medicine_id': mid, 'lot_number': 'R5-LOT',
        'expiry_date': (datetime.now(timezone(timedelta(hours=7))).date() + timedelta(days=30)).isoformat(),
        'quantity': 20}).status_code == 201
    assert clients['doctor'].put(f'/api/visits/{visit}/clinical', json={
        'version': 0, 'diagnosis': 'Chẩn đoán giả lập R5'}).status_code == 200
    rx = clients['doctor'].post('/api/prescriptions', json={
        'visit_id': visit, 'items': [{'medicine_id': mid, 'quantity': 3, 'directions': 'Chỉ mô phỏng'}]})
    assert rx.status_code == 201, rx.text
    rid = rx.json()['id']
    assert clients['doctor'].post(f'/api/visits/{visit}/nurses', json={'nurse_id': IDS['nurse']}).status_code == 201
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    evidence = Path('test_evidence/r5')
    evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        try:
            errors = []
            for role in ('pharmacy', 'nurse'):
                context = browser.new_context()
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin)
                page.locator('[name=username]').fill('test_' + role)
                page.locator('[name=password]').fill(PASSWORDS[role])
                page.locator('[data-form=login] button').click()
                page.locator('.account-trigger').wait_for()
                settle(page)
                for width in (1366, 390):
                    page.set_viewport_size({'width': width, 'height': 844})
                    pick(page, 'pharmacy-rx' if role == 'pharmacy' else 'nurse-visit', rid if role == 'pharmacy' else visit)
                    expect(page.locator('.r5-hero h1')).to_have_text('Nhà thuốc' if role == 'pharmacy' else 'Điều dưỡng')
                    expect(page.locator('.r5-hero')).to_have_css('background-color', 'rgba(0, 118, 66, 0.9)')
                    no_horizontal_scroll(page)
                    page.evaluate('window.scrollTo(0,0)')
                    page.screenshot(path=str(evidence / f'{role}-{width}.png'))
                    if role == 'pharmacy':
                        expect(page.locator('#r5-rx-detail')).to_contain_text(medicine_name)
                        search = page.locator('[data-r5-search]')
                        expect(search).to_have_css('border-radius', '999px')
                        search_box = search.bounding_box()
                        hero_box = page.locator('.r5-hero-wrap').bounding_box()
                        assert search_box['x'] >= hero_box['x']
                        assert search_box['x'] + search_box['width'] <= hero_box['x'] + hero_box['width']
                        search.fill('khong co don nay R5')
                        expect(page.locator('[data-r5-no-match]')).to_be_visible()
                        search.fill(str(rid))
                        expect(page.locator(f'[data-kind=pharmacy-rx][data-id="{rid}"]')).to_be_visible()
                        search.fill('')
                        page.locator('[data-r5-jump=r5-stock]').click()
                        expect(page.locator('#r5-stock')).to_have_attribute('open', '')
                        expect(page.locator('#r5-stock')).to_contain_text('R5-LOT')
                        expect(page.locator('#r5-stock')).to_contain_text('Sắp hết hạn')
                        expect(page.locator('[data-r2-stat=expiring] strong')).to_have_text('1')
                        receipt = page.locator('[data-form=stock-receipt]')
                        assert set(receipt.locator('[name]').evaluate_all('es=>es.map(e=>e.name)')) == {
                            'medicine_id', 'lot_number', 'expiry_date', 'quantity'}
                        issue = page.locator('[data-form=stock-issue]')
                        assert set(issue.locator('[name]').evaluate_all('es=>es.map(e=>e.name)')) == {
                            'medicine_id', 'quantity', 'purpose'}
                        if width > 900:
                            assert receipt.bounding_box()['x'] > page.locator('.r5-stock-layout .table').bounding_box()['x']
                        no_horizontal_scroll(page)
                        assert page.locator('#r5-stock').bounding_box()['y'] >= page.locator('.r5-tabs').bounding_box()['y'] + page.locator('.r5-tabs').bounding_box()['height']
                        page.screenshot(path=str(evidence / f'stock-{width}.png'))
                    else:
                        expect(page.locator('[data-form=nurse-vitals] [name=visit_id]')).to_have_value(str(visit))
                        expect(page.locator('[name=diagnosis], [data-form=rx], [data-form=payment]')).to_have_count(0)
                        assert page.locator('.vitals').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ").length') == (4 if width > 900 else 2)
                    for button in page.locator('#workspace button:visible').all():
                        box = button.bounding_box()
                        assert box['height'] >= 44, button.inner_text()
                        if width == 390:
                            assert box['width'] >= 88, button.inner_text()
                    page.emulate_media(media='print')
                    expect(page.locator('.card').first).to_have_css('backdrop-filter', 'none')
                    page.emulate_media(media='screen')
                context.close()
            assert not errors, errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1366, 390])
def test_r5_selected_prescription_dispense_pdf_cancel_and_pages(https_server, clients, visit, width):
    import base64
    import hashlib
    import os
    from datetime import datetime, timezone
    from pathlib import Path
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from playwright.sync_api import sync_playwright, expect
    from .conftest import PASSWORDS, SERVICE
    from .test_v050_abcd import medicine, rx
    from .browser_helpers import settle, pick, send, go
    import secrets

    patient_id = clients['doctor'].get(f'/api/visits/{visit}').json()['patient_id']
    other_name = 'Người bệnh tìm kiếm B ' + secrets.token_hex(5)
    patient_b = clients['reception'].post('/api/patients', json={
        'full_name': other_name, 'sex': 'Nữ', 'date_of_birth': '1990-01-01', 'phone': '0900000010'})
    assert patient_b.status_code == 201, patient_b.text
    other = clients['reception'].post('/api/visits', json={
        'patient_id': patient_b.json()['id'], 'doctor_id': IDS['doctor'], 'service_id': SERVICE})
    assert other.status_code == 201, other.text
    mid = medicine(clients)
    first = rx(clients, visit, mid, qty=3)
    second = rx(clients, other.json()['id'], mid, qty=2)
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        try:
            page = browser.new_page(viewport={'width': width, 'height': 844}, accept_downloads=True)
            errors = []
            confirmations = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: confirmations.append(dialog.message) if dialog.type == 'confirm' else None)
            page.on('dialog', lambda dialog: dialog.accept('Hủy đơn giả lập R5 để kiểm tra đúng đơn')
                if dialog.type == 'prompt' else dialog.accept())
            page.goto(origin)
            page.locator('[name=username]').fill('test_pharmacy')
            page.locator('[name=password]').fill(PASSWORDS['pharmacy'])
            page.locator('[data-form=login] button').click()
            page.locator('.account-trigger').wait_for()
            settle(page)
            detail = page.locator('#r5-rx-detail')
            pick(page, 'pharmacy-rx', first)
            expect(detail.locator('[data-action=dispense]')).to_have_attribute('data-id', str(first))
            search = page.locator('[data-r5-search]')
            search.fill(other_name)
            expect(detail).to_be_hidden()
            expect(page.locator('[data-r5-choose-rx] h3')).to_have_text('Chọn một đơn trong kết quả tìm kiếm')
            expect(page.locator('[data-r5-choose-rx]')).to_be_visible()
            expect(detail.locator(f'[data-action=dispense][data-id="{first}"]')).to_be_disabled()
            expect(page.locator(f'[data-action=dispense][data-id="{first}"]:visible')).to_have_count(0)
            pick(page, 'pharmacy-rx', second)
            expect(detail).to_be_visible()
            expect(detail.locator('[data-action=dispense]')).to_have_attribute('data-id', str(second))
            with page.expect_download() as download:
                detail.locator(f'[data-kind=rx][data-id="{second}"][data-format=pdf]').click()
            assert Path(download.value.path()).read_bytes().startswith(b'%PDF-')
            sent = send(page, detail.locator(f'[data-action=dispense][data-id="{second}"]'))
            assert sent.url.endswith(f'/api/prescriptions/{second}/dispense')
            assert confirmations[-1].startswith(f'Cấp thuốc cho {other_name} · đơn #{second}?')
            with db() as c:
                states = {row['id']: row['status'] for row in c.execute(
                    'SELECT id,status FROM prescriptions WHERE id IN (?,?)', (first, second))}
                assert states == {first: 'draft', second: 'dispensed'}
                assert c.execute('SELECT COUNT(*) FROM dispensations WHERE prescription_id=?', (first,)).fetchone()[0] == 0
                assert c.execute('SELECT COUNT(*) FROM dispensations WHERE prescription_id=?', (second,)).fetchone()[0] == 1
            search.fill('')
            pick(page, 'pharmacy-rx', first)
            cancelled = send(page, detail.locator(f'[data-action=cancel-rx][data-id="{first}"]'))
            assert cancelled.url.endswith(f'/api/prescriptions/{first}/cancel')
            with db() as c:
                assert c.execute('SELECT status FROM prescriptions WHERE id=?', (first,)).fetchone()[0] == 'cancelled'
                assert c.execute('SELECT status FROM prescriptions WHERE id=?', (second,)).fetchone()[0] == 'dispensed'

            # Only pagination data is seeded: 101 independent legacy draft prescriptions.
            seeded = []
            created = datetime.now(timezone.utc).isoformat()
            with db(True) as c:
                for _ in range(101):
                    c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at,diagnosis) VALUES(?,?,?,?,?)',
                        (patient_id, IDS['doctor'], IDS['reception'], created, 'Chẩn đoán giả lập phân trang R5'))
                    vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    c.execute('INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,created_at) VALUES(?,?,?,?)',
                        (vid, IDS['doctor'], 'Thuốc giả lập kiểm tra phân trang R5', created))
                    seeded.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
            go(page, 'pharmacy')
            expect(detail.locator('[data-action=dispense]')).to_have_attribute('data-id', str(seeded[-1]))
            expect(page.locator(f'[data-kind=pharmacy-rx][data-id="{seeded[0]}"]')).to_have_count(0)
            page.locator('[data-action=rx-page][data-id="100"]').click()
            settle(page)
            expect(page.locator('.r5-rx-queue')).to_contain_text('Trang 2')
            pick(page, 'pharmacy-rx', seeded[0])
            expect(detail.locator('[data-action=dispense]')).to_have_attribute('data-id', str(seeded[0]))
            expect(detail.locator('[data-action=cancel-rx]')).to_be_enabled()
            with page.expect_download() as download:
                detail.locator(f'[data-kind=rx][data-id="{seeded[0]}"][data-format=pdf]').click()
            assert Path(download.value.path()).read_bytes().startswith(b'%PDF-')
            page.locator('[data-action=rx-page][data-id="0"]').click()
            settle(page)
            expect(page.locator('.r5-rx-queue')).to_contain_text('Trang 1')
            expect(detail.locator('[data-action=dispense]')).to_have_attribute('data-id', str(seeded[-1]))
            # The daily count is a lower bound once the response reaches its 100-row cap.
            def recent_dispensations(route):
                route.fulfill(json=[{'id': i, 'patient_name': other_name, 'dispensed_at': created,
                    'prescription_id': second} for i in range(100)])

            page.route('**/api/dispensations', recent_dispensations)
            go(page, 'pharmacy')
            stat = page.locator('[data-r2-stat=dispensed]')
            expect(stat.locator('strong')).to_have_text('≥ 100')
            expect(stat).to_have_attribute('title', 'Đếm trong 100 phiếu gần nhất')
            page.unroute('**/api/dispensations', recent_dispensations)
            assert not errors, errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1366, 390])
def test_r6_pharmacy_empty_and_tabs(https_server, width):
    import base64
    import hashlib
    import os
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from playwright.sync_api import sync_playwright, expect
    from .conftest import PASSWORDS
    from .browser_helpers import settle, no_horizontal_scroll
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    pin = base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        try:
            page = browser.new_page(viewport={'width': width, 'height': 844})
            page.route('**/api/prescriptions**', lambda route: route.fulfill(json=[]))
            page.goto(origin)
            page.locator('[name=username]').fill('test_pharmacy')
            page.locator('[name=password]').fill(PASSWORDS['pharmacy'])
            page.locator('[data-form=login] button').click()
            page.locator('.account-trigger').wait_for(); settle(page)
            expect(page.locator('#r5-rx-detail')).to_have_count(0)
            expect(page.locator('#r5-dispensing .r4-state:visible')).to_have_count(1)
            hero = page.locator('.r5-top').bounding_box()
            tabs = page.locator('.r5-tabs').bounding_box()
            queue = page.locator('#r5-dispensing').bounding_box()
            assert tabs['y'] >= hero['y'] + hero['height']
            assert tabs['y'] + tabs['height'] <= queue['y']
            if width == 390:
                menu = page.locator('#navigation').bounding_box()
                assert tabs['y'] + tabs['height'] <= menu['y']
            no_horizontal_scroll(page)
        finally:
            browser.close()
