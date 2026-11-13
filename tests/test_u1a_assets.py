"""Brand assets must remain available on a workstation without Internet."""
import os
import re
from urllib.parse import urlsplit
from tests.test_workflows import client


def test_be_vietnam_pro_fonts_are_self_hosted_and_load_offline():
    from playwright.sync_api import sync_playwright
    css=client.get('/assets/styles.css')
    assert css.status_code==200
    urls=re.findall(r"url\(['\"]?([^)'\"]+)",css.text)
    assert len(urls)==10
    for path in urls:
        assert path.startswith('/assets/fonts/') and path.endswith('.woff2')
        response=client.get(path)
        assert response.status_code==200 and response.content[:4]==b'wOF2'
    assert client.get('/assets/fonts/OFL.txt').status_code==200
    # Deny any network access; serve only the application's local static files.
    requests=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH'),headless=True,args=['--no-sandbox'])
        page=browser.new_page()
        def local(route):
            url=urlsplit(route.request.url)
            requests.append(route.request.url)
            assert url.netloc=='clinic.test' and url.path.startswith('/assets/')
            result=client.get(url.path)
            route.fulfill(status=result.status_code,body=result.content,headers={'content-type':result.headers['content-type']})
        page.route('**/*',local)
        page.set_content('<link rel="stylesheet" href="http://clinic.test/assets/styles.css"><p>Phòng khám Minh Đức</p><button class="btn">Tiếp tục</button><button class="btn-danger smallbtn">Hủy</button><button class="allergy-edit smallbtn">Sửa dị ứng</button><div class="field"><input><select><option>Chọn</option></select><textarea></textarea></div><div class="card">Thông tin</div>')
        page.evaluate('''async()=>{for(const weight of [400,500,600,700,800]){await document.fonts.load(weight+' 15px "Be Vietnam Pro"','Phòng khám Việt Nam');}}''')
        assert page.evaluate('document.fonts.check(\'800 15px "Be Vietnam Pro"\',"Việt Nam")')
        assert page.locator('body').evaluate('e=>getComputedStyle(e).fontSize')=='15px'
        for width in (1366,390):
            page.set_viewport_size({'width':width,'height':900})
            assert all(height>=44 for height in page.locator('button').evaluate_all('es=>es.map(e=>e.getBoundingClientRect().height)'))
        assert page.locator('.btn-danger').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(180, 35, 24)'
        allergy=page.locator('.allergy-edit').evaluate('e=>{const s=getComputedStyle(e);return [s.borderTopColor,s.borderTopWidth,s.color,s.backgroundColor]}')
        assert allergy==['rgb(180, 35, 24)','2px','rgb(180, 35, 24)','rgb(255, 255, 255)']
        input_colors=page.locator('input,select,textarea').evaluate_all('es=>es.map(e=>getComputedStyle(e).borderTopColor)')
        assert input_colors==['rgb(111, 143, 126)']*3
        browser.close()
    assert any('/assets/fonts/' in u for u in requests)
    def luminance(hex_color):
        values=[int(hex_color[i:i+2],16)/255 for i in (0,2,4)]
        linear=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in values]
        return sum(x*y for x,y in zip(linear,(.2126,.7152,.0722)))
    assert (luminance('FFFFFF')+.05)/(luminance('6F8F7E')+.05)>=3
    for background in ('FFFFFF','F3F9F6'):
        assert (luminance(background)+.05)/(luminance('1F3A31')+.05)>=4.5


def test_favicon_returns_200_and_is_linked():
    response=client.get('/assets/favicon.ico')
    assert response.status_code==200 and response.content[:4]==b'\x00\x00\x01\x00'
    html=client.get('/').text
    assert '<link rel="icon" href="/assets/favicon.ico">' in html
    assert '/assets/MinhDuc_bieutuong_vuong.svg' in html
    assert 'logo_minh_duc.png' not in html
