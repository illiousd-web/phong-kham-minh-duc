"""Cùng kiểm thử hàng chờ trên PostgreSQL thật và API HTTPS origin."""
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
            page.locator('[data-form="login"] button').click();page.locator('#logout').wait_for();settle(page)
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


from .test_tls_chrome_compat import https_server
