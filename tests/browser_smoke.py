"""Optional real-Chromium UI smoke test. Run with `python tests/browser_smoke.py`.
Requires playwright package and installed Chromium; does not contact the Internet.
"""
import os,sys,tempfile,time,socket,subprocess,secrets
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
EVIDENCE=ROOT/'test_evidence';EVIDENCE.mkdir(exist_ok=True)
env=os.environ.copy();env['DEMO_PASSWORD']=secrets.token_urlsafe(32);env['CLINIC_DB_PATH']=str(Path(tempfile.mkdtemp(prefix='md_chromium_'))/'demo.sqlite3');env['CLINIC_UPLOAD_DIR']=str(Path(tempfile.mkdtemp(prefix='md_upload_'))/'attachments')
os.environ.update({k:env[k] for k in ('CLINIC_DB_PATH','CLINIC_UPLOAD_DIR','DEMO_PASSWORD')})
from fastapi.testclient import TestClient
from app.main import app
import base64,re
client=TestClient(app)
assert client.get('/api/health').status_code==200
# Tạo bảng giá CLS để tránh yêu cầu vô giá trong màn hình bác sĩ.
manager=client.post('/api/login',json={'username':'quanly','password':env['DEMO_PASSWORD']}).json()
headers={'Authorization':'Bearer '+manager['access_token']}
assert client.post('/api/catalog/services',headers=headers,json={
    'name':'Xét nghiệm mô phỏng kiểm thử','category':'lab','price':35000}).status_code==201


with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  context=browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000},locale='vi-VN')
  page=context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  requests=[]
  def proxy(source,path,opts):
      requests.append((opts.get('method','GET'),path))
      method=opts.get('method','GET')
      headers=opts.get('headers',{})
      body=opts.get('body')
      response=client.request(method,path,headers=headers,content=body.encode('utf8') if isinstance(body,str) else None)
      return {'status':response.status_code,'headers':{'Content-Type':response.headers.get('content-type','application/octet-stream')},'base64':base64.b64encode(response.content).decode('ascii')}
  page.expose_binding('server_bridge',proxy)
  html=(ROOT/'app/static/index.html').read_text(encoding='utf8')
  logo64=base64.b64encode((ROOT/'app/static/logo_minh_duc.png').read_bytes()).decode('ascii')
  html=html.replace('/assets/logo_minh_duc.png','data:image/png;base64,'+logo64)
  html=re.sub(r'<link rel="stylesheet" href="/assets/styles.css">','',html)
  html=re.sub(r'<script src="/assets/(?:app|m6|m5)\.js" defer></script>','',html)
  def assets(route):
   from urllib.parse import urlsplit
   response=client.get(urlsplit(route.request.url).path)
   route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','application/octet-stream')})
  page.route('http://clinic.test/assets/**',assets)
  page.set_content(html.replace('<head>','<head><base href="http://clinic.test/">'))
  page.add_style_tag(content=(ROOT/'app/static/styles.css').read_text(encoding='utf8'))
  page.evaluate("""() => {let storage={};Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=String(v),removeItem:k=>delete storage[k]}});window.fetch=async (path,opts={})=>{let o=await window.server_bridge(path,{method:opts.method||'GET',headers:opts.headers||{},body:typeof opts.body==='string'?opts.body:null});let raw=atob(o.base64), bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);return new Response(bytes,{status:o.status,headers:o.headers});};}""")
  page.add_script_tag(content=(ROOT/'app/static/app.js').read_text(encoding='utf8'))
  for script in ('m6.js','m5.js'):page.add_script_tag(content=(ROOT/'app/static'/script).read_text(encoding='utf8'))
  page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'));window.dispatchEvent(new Event('load'))")
  page.locator('[data-form=login]').wait_for(timeout=8000)
  assert page.locator('[data-form=login]').is_visible()
  def login(who):
   page.locator('[data-form="login"] select[name="username"]').select_option(who)
   page.locator('[data-form="login"] input[name="password"]').fill(env['DEMO_PASSWORD'])
   page.locator('[data-form="login"] button[type="submit"]').click()
   page.locator('.account-trigger').wait_for(state='visible',timeout=8000)
  def logout():
   page.locator('.account-trigger').click();page.locator('#logout').click()
   page.locator('[data-form=login]').wait_for(timeout=8000)
  def settle():
   page.wait_for_function("document.getElementById('workspace').getAttribute('aria-busy')==='false'")
  def go(where):
   page.locator(f'[data-action="navigate"][data-page="{where}"]').click()
   page.wait_for_function(f"document.getElementById('workspace').dataset.page==='{where}'");settle()
  def done(text):
   page.locator('#toast').get_by_text(text,exact=False).wait_for(timeout=8000);settle()
  login('letan');settle()
  # R2 debt: verify actual DOM growth, not pre-rendered hidden cards.
  page.evaluate('''()=>{const saved=patientList;const host=document.createElement('div');try{patientList=Array.from({length:65},(_,i)=>({id:i+10000,full_name:'Người giả lập '+i,code:'GIA'+i}));host.innerHTML=patientTable(patientList);document.body.append(host);if(host.querySelectorAll('[data-r2-patient-card]').length!==30)throw Error('Rendered more than30');host.querySelector('[data-r2-more]').click();if(host.querySelectorAll('[data-r2-patient-card]').length!==60)throw Error('Did not append30');host.querySelector('[data-r2-more]').click();if(host.querySelectorAll('[data-r2-patient-card]').length!==65)throw Error('Wrong final page')}finally{host.remove();patientList=saved}}''')
  page.locator('.account-trigger').click();page.locator('#change-password').click();settle()
  pw=page.locator('[data-form=password]');pw.locator('[name=current_password]').fill('cu-gia-lap');pw.locator('[name=new_password]').fill('moi-gia-lap-123');pw.locator('[name=confirm_password]').fill('khac')
  before=len(requests);pw.locator('button.btn').click();pw.locator('.r2-field-error').wait_for()
  assert not any(method=='POST' and path=='/api/password' for method,path in requests[before:])
  pw.locator('[name=confirm_password]').fill('moi-gia-lap-123')
  assert pw.locator('.r2-field-error').count()==0
  assert pw.locator('[name=confirm_password]').get_attribute('aria-invalid') is None
  go('reception')
  page.locator('#workspace summary').filter(has_text='Thêm bệnh nhân mới').click()
  page.locator('[data-form="patient"] [name="full_name"]').fill('Bệnh nhân mô phỏng UI Minh Đức')
  page.locator('[data-form="patient"] [name="date_of_birth"]').fill('05/11/1992')
  page.locator('[data-form="patient"] [name="sex"]').select_option('Nữ')
  page.locator('[data-form="patient"] [name="phone"]').fill('0000000000')
  page.locator('[data-form="patient"] button').click();done('Đã lưu bệnh nhân')
  page.locator('[data-form="visit"] [name="doctor_id"]').select_option(label='BS Nội')
  page.locator('[data-form="visit"] button[type=submit]').click();done('Đã tiếp nhận lượt khám')
  page.locator('[data-action="export-form"][data-kind="intake"]').first.wait_for(timeout=8000)
  page.screenshot(path=str(EVIDENCE/'le_tan_desktop.png'),full_page=True)
  with page.expect_download(timeout=10000) as dl:
   page.locator('[data-action="export-form"][data-kind="intake"][data-format="pdf"]').first.click()
  d=dl.value;d.save_as(str(EVIDENCE/'phieu_tiep_don_chromium.pdf'))
  assert Path(EVIDENCE/'phieu_tiep_don_chromium.pdf').read_bytes().startswith(b'%PDF-')
  logout();before=len(requests);login('bs_noi');settle()
  assert not any(re.fullmatch(r'/api/visits/\d+',path) for method,path in requests[before:])
  page.locator('[data-action=pick][data-kind=visit]').first.click();settle()
  page.locator('#toast').wait_for(state='hidden')
  for width,height in ((1366,768),(390,844)):
   page.set_viewport_size({'width':width,'height':height})
   assert page.evaluate('document.documentElement.scrollWidth')<=width
   assert page.locator('#workspace *').evaluate_all("es=>es.filter(e=>e.getClientRects().length&&e.textContent.trim()).every(e=>parseFloat(getComputedStyle(e).fontSize)>=13)")
   page.screenshot(path=str(EVIDENCE/f'r3-doctor-{width}.png'))
   page.locator('[data-action=doctor-tab][data-target=rx]').click()
   page.wait_for_function("document.querySelector('.r3-layout').dataset.r3Tab==='rx'")
   assert page.locator('.m6-dose-grid input').evaluate_all('es=>es.every(e=>e.getBoundingClientRect().width>=50)')
   page.screenshot(path=str(EVIDENCE/f'r3-rx-{width}.png'))
   page.locator('[data-action=doctor-tab][data-target=exam]').click()
  go('m6-list')
  for width,height in ((1366,768),(390,844)):
   page.set_viewport_size({'width':width,'height':height})
   assert page.evaluate('document.documentElement.scrollWidth')<=width
   page.screenshot(path=str(EVIDENCE/f'r3-locked-{width}.png'))
  go('doctor');page.locator('[data-action=pick][data-kind=visit]').first.click();settle()
  page.set_viewport_size({'width':1366,'height':768})
  page.locator('[name="chief_complaint"]').fill('Triệu chứng kiểm thử giao diện')
  page.locator('[name="diagnosis"]').fill('Chẩn đoán mô phỏng')
  page.locator('[name="follow_up"]').fill('08/12/2026')
  page.locator('[data-form="clinical"] button.btn').click();done('Đã lưu phiếu khám')
  with page.expect_download(timeout=10000) as dl:
   page.locator('[data-action="export-form"][data-kind="visit"][data-format="pdf"]').click()
  dl.value.save_as(str(EVIDENCE/'phieu_kham_chromium.pdf'))
  page.locator('[data-form="order"] [name="service_id"]').select_option(index=0)
  page.locator('[data-form="order"] button').click();done('Đã lập chỉ định')
  page.get_by_text('Kê / cấp thuốc từ kho (quy trình hiện có)',exact=True).click()
  page.locator('[data-form="rx"] [name="quantity"]').fill('2')
  page.locator('[data-form="rx"] [name="instructions"]').fill('Không dùng để điều trị')
  page.locator('[data-form="rx"] button.btn').click();done('Đã lưu đơn thuốc')
  with page.expect_download(timeout=10000) as dl:page.locator('[data-action="export-form"][data-kind="rx"][data-format="pdf"]').first.click()
  dl.value.save_as(str(EVIDENCE/'don_nhap_chromium.pdf'))
  logout();login('kythuat');settle()
  page.locator('[data-form="result"] [name="result_text"]').fill('Kết quả giả lập UI')
  page.locator('[data-form="result"] button').click();done('Đã chuyển kết quả')
  logout();login('bs_noi');settle()
  page.locator('[data-action=pick][data-kind=visit]').first.click();settle()
  page.locator('[data-action="approve"]').first.click();done('Đã duyệt kết quả')
  with page.expect_download(timeout=10000) as dl:page.locator('[data-action="export-form"][data-kind="lab"][data-format="pdf"]').first.click()
  dl.value.save_as(str(EVIDENCE/'ket_qua_chromium.pdf'))
  logout();login('thungan');settle()
  page.locator('[data-form="payment"] [name="amount"]').fill('100000')
  page.locator('[data-form="payment"] button').click();done('Đã thu tiền')
  page.wait_for_function("document.querySelector('#workspace')?.innerText.includes('100.000 đ')",timeout=8000)
  logout();login('quanly');settle()
  page.locator('[data-action="tab"][data-tab="report"]').click();settle()
  page.wait_for_function("document.querySelector('#workspace')?.innerText.includes('100.000 đ')",timeout=8000)
  page.locator('.stat').first.wait_for(timeout=8000)
  page.screenshot(path=str(EVIDENCE/'quan_ly_desktop.png'),full_page=True)
  # Narrow mobile layout test (role remains manager).
  page.set_viewport_size({'width':390,'height':844});settle()
  assert page.evaluate('document.documentElement.scrollWidth')<=390
  page.screenshot(path=str(EVIDENCE/'quan_ly_mobile.png'),full_page=True)
  assert not errors, errors
  print('PASS browser UI: reception -> examination -> order -> result approved -> prescription draft -> payment -> manager')
  print('PASS browser downloads: intake/clinical/result/RX, real PDF files')
  print('PASS browser responsiveness: desktop 1440px + mobile 390px')
  print('PASS browser JavaScript page errors: 0')
  print('Note: Chromium used in-process API bridge because localhost navigation is blocked by the sandbox.')
  context.close();browser.close()
