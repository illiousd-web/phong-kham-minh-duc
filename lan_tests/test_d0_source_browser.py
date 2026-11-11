"""Choosing supplied source codes by name is explicit, at 1366 and 390px."""
import base64,hashlib,os,secrets
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright,expect
from .conftest import db,PASSWORDS
from .test_tls_chrome_compat import https_server
from .browser_helpers import settle,no_horizontal_scroll

@pytest.mark.parametrize('width',[1366,390])
def test_source_link_suggestions_require_user_choice(https_server,clients,width):
    from app.d0_sources import seed_sources
    a=clients['admin'];suffix=secrets.token_hex(4)
    with db(True) as c:
        seed_sources(c,'2026-11-11T00:00:00+00:00')
        pair=c.execute('''SELECT l.pl01_code,l.pl02_id,p.name AS pl01_name,q.name AS pl02_name FROM tech_pl02_links l JOIN tech_catalog_pl01 p ON p.ma_ky_thuat=l.pl01_code JOIN tech_catalog_pl02 q ON q.id=l.pl02_id WHERE l.needs_review=0 AND q.active=1 ORDER BY q.id LIMIT 1''').fetchone()
        shared=c.execute("SELECT code,name FROM shared_lab_codes WHERE active=1 AND name<>'' AND loinc<>'' ORDER BY code LIMIT 1").fetchone()
        c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)',('Dịch vụ nguồn giả lập '+suffix,12345,'FAKE-SOURCE-'+suffix));sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        before=dict(c.execute('SELECT * FROM service_catalog WHERE id=?',(sid,)).fetchone())
    tid=a.post('/api/lab/catalog',json={'code':'FAKE-SRC-'+suffix,'name':'Chỉ số nguồn giả lập '+suffix,'abbreviation':'FAKE','group_name':'other','result_type':'number','unit':'đv giả lập'}).json()['id']
    origin,certdir=https_server;cert=x509.load_pem_x509_certificate((certdir/'server.crt').read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode();errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):assert browser.version.split('.')[0]==os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page=browser.new_page(viewport={'width':width,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin);page.locator('[name=username]').fill('test_admin');page.locator('[name=password]').fill(PASSWORDS['admin']);page.locator('[data-form=login] button').click();page.locator('#logout').wait_for();settle(page)
        page.locator('[data-kind=admin][data-tab=catalog]').click();settle(page)
        f=page.locator('[data-d0=link][data-kind=lab-tests]');f.locator('[name=id]').select_option(str(tid));f.locator('[data-d0-link-search]').fill(shared['name'])
        target=f.locator('[data-d0-link-pick="'+shared['code']+'"]');target.wait_for()
        with db() as c:assert c.execute('SELECT shared_code FROM lab_tests WHERE id=?',(tid,)).fetchone()[0] is None
        target.click()
        with db() as c:assert c.execute('SELECT shared_code FROM lab_tests WHERE id=?',(tid,)).fetchone()[0] is None
        with page.expect_response(lambda r:r.request.method=='PUT' and '/standards/lab-tests/' in r.url) as saved:f.locator('button',has_text='Gắn các mục đã chọn').click()
        assert saved.value.status==200;settle(page)
        f=page.locator('[data-d0=link][data-kind=services]');f.locator('[name=id]').select_option(str(sid));f.locator('[data-d0-link-search=tech_catalog]').fill(pair['pl01_name'])
        f.locator('[data-d0-link-pick="'+pair['pl01_code']+'"]').click()
        f.locator('[data-d0-link-search=tech_catalog_pl02]').fill(pair['pl02_name'])
        f.locator('[data-d0-link-pick="'+str(pair['pl02_id'])+'"]').click()
        with db() as c:assert not c.execute('SELECT 1 FROM service_tech_codes WHERE service_id=?',(sid,)).fetchone()
        with page.expect_response(lambda r:r.request.method=='PUT' and '/standards/services/' in r.url) as saved:f.locator('button',has_text='Gắn các mục đã chọn').click()
        assert saved.value.status==200;settle(page);no_horizontal_scroll(page)
        with db() as c:
            assert dict(c.execute('SELECT * FROM service_catalog WHERE id=?',(sid,)).fetchone())==before
            assert c.execute('SELECT pl02_id FROM service_pl02_codes WHERE service_id=?',(sid,)).fetchone()[0]==pair['pl02_id']
        assert not errors,errors;browser.close()
