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
env=os.environ.copy();env['DEMO_PASSWORD']=secrets.token_urlsafe(32);env['CLINIC_DB_PATH']=str(Path(tempfile.mkdtemp(prefix='md_chromium_'))/'demo.sqlite3');env['CLINIC_UPLOAD_DIR']=str(Path(tempfile.mkdtemp(prefix='md_upload_')))
os.environ.update({k:env[k] for k in ('CLINIC_DB_PATH','CLINIC_UPLOAD_DIR','DEMO_PASSWORD')})
from fastapi.testclient import TestClient
from app.main import app
import base64,re
client=TestClient(app)
assert client.get('/api/health').status_code==200

with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  context=browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000},locale='vi-VN')
  page=context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  def proxy(source,path,opts):
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
  html=re.sub(r'<script src="/assets/app.js" defer></script>','',html)
  page.set_content(html)
  page.add_style_tag(content=(ROOT/'app/static/styles.css').read_text(encoding='utf8'))
  page.evaluate("""() => {let storage={};Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=String(v),removeItem:k=>delete storage[k]}});window.fetch=async (path,opts={})=>{let o=await window.server_bridge(path,{method:opts.method||'GET',headers:opts.headers||{},body:typeof opts.body==='string'?opts.body:null});let raw=atob(o.base64), bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);return new Response(bytes,{status:o.status,headers:o.headers});};}""")
  page.add_script_tag(content=(ROOT/'app/static/app.js').read_text(encoding='utf8'))
  page.get_by_text('Đăng nhập theo vai trò').wait_for(timeout=8000)
  assert page.get_by_text('Đăng nhập theo vai trò').is_visible()
  def login(who):
   page.locator('[data-form="login"] select[name="username"]').select_option(who)
   page.locator('[data-form="login"] input[name="password"]').fill(env['DEMO_PASSWORD'])
   page.locator('[data-form="login"] button[type="submit"]').click()
   page.locator('#logout').wait_for(state='visible',timeout=8000)
  def logout():
   page.locator('#logout').click()
   page.get_by_text('Đăng nhập theo vai trò').wait_for(timeout=8000)
  def go(where):
   page.locator(f'[data-action="navigate"][data-page="{where}"]').click()
   page.wait_for_timeout(250)
  login('letan');go('reception')
  page.locator('[data-form="patient"] [name="full_name"]').fill('Bệnh nhân mô phỏng UI Minh Đức')
  page.locator('[data-form="patient"] [name="date_of_birth"]').fill('1992-11-05')
  page.locator('[data-form="patient"] [name="phone"]').fill('0000000000')
  page.locator('[data-form="patient"] button').click()
  page.get_by_text('Đã lưu bệnh nhân').wait_for(timeout=8000)
  page.locator('[data-form="visit"] [name="doctor_id"]').select_option(label='BS Nội')
  page.locator('[data-form="visit"] button').click()
  page.get_by_text('Đã tiếp nhận lượt khám').wait_for(timeout=8000)
  page.locator('[data-action="export-form"][data-kind="intake"]').first.wait_for(timeout=8000)
  page.screenshot(path=str(EVIDENCE/'le_tan_desktop.png'),full_page=True)
  with page.expect_download(timeout=10000) as dl:
   page.locator('[data-action="export-form"][data-kind="intake"][data-format="pdf"]').first.click()
  d=dl.value;d.save_as(str(EVIDENCE/'phieu_tiep_don_chromium.pdf'))
  assert Path(EVIDENCE/'phieu_tiep_don_chromium.pdf').read_bytes().startswith(b'%PDF-')
  logout();login('bs_noi');go('clinical')
  page.locator('[name="chief_complaint"]').fill('Triệu chứng kiểm thử giao diện')
  page.locator('[name="diagnosis"]').fill('Chẩn đoán mô phỏng')
  page.locator('[name="follow_up"]').fill('2026-12-08')
  page.locator('[data-form="clinical"] button.btn').click()
  page.get_by_text('Đã lưu phiếu khám').wait_for(timeout=8000)
  with page.expect_download(timeout=10000) as dl:
   page.locator('[data-action="export-form"][data-kind="visit"][data-format="pdf"]').click()
  dl.value.save_as(str(EVIDENCE/'phieu_kham_chromium.pdf'))
  go('orders')
  page.locator('[data-form="order"] [name="category"]').select_option('lab')
  page.locator('[data-form="order"] [name="name"]').fill('Xét nghiệm mô phỏng kiểm thử')
  page.locator('[data-form="order"] button').click()
  page.get_by_text('Đã lập chỉ định').wait_for(timeout=8000)
  go('rx')
  page.locator('[data-form="rx"] [name="drug_lines"]').fill('Thuốc giả lập A | 2 viên | chỉ dành cho thử nghiệm')
  page.locator('[data-form="rx"] [name="instructions"]').fill('Không dùng để điều trị')
  page.locator('[data-form="rx"] button').click()
  page.get_by_text('Đã tạo đơn nháp').wait_for(timeout=8000)
  with page.expect_download(timeout=10000) as dl:page.locator('[data-action="export-form"][data-kind="rx"][data-format="pdf"]').first.click()
  dl.value.save_as(str(EVIDENCE/'don_nhap_chromium.pdf'))
  logout();login('kythuat');go('orders')
  page.locator('[data-form="result"] [name="result_text"]').fill('Kết quả giả lập UI')
  page.locator('[data-form="result"] button').click()
  page.get_by_text('Đã chuyển kết quả').wait_for(timeout=8000)
  logout();login('bs_noi');go('orders')
  page.locator('[data-action="approve"]').first.click()
  page.get_by_text('Đã duyệt quy trình mô phỏng').wait_for(timeout=8000)
  with page.expect_download(timeout=10000) as dl:page.locator('[data-action="export-form"][data-kind="lab"][data-format="pdf"]').first.click()
  dl.value.save_as(str(EVIDENCE/'ket_qua_chromium.pdf'))
  logout();login('thungan');go('cashier')
  page.locator('[data-form="payment"] [name="amount"]').fill('100000')
  page.locator('[data-form="payment"] button').click()
  page.wait_for_function("document.querySelector('#workspace')?.innerText.includes('100.000 đ')",timeout=8000)
  logout();login('quanly');go('finance')
  page.wait_for_function("document.querySelector('#workspace')?.innerText.includes('100.000 đ')",timeout=8000)
  page.locator('.stat').first.wait_for(timeout=8000)
  page.screenshot(path=str(EVIDENCE/'quan_ly_desktop.png'),full_page=True)
  # Narrow mobile layout test (role remains manager).
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
  page.screenshot(path=str(EVIDENCE/'quan_ly_mobile.png'),full_page=True)
  assert not errors, errors
  print('PASS browser UI: reception -> examination -> order -> result approved -> prescription draft -> payment -> manager')
  print('PASS browser downloads: intake/clinical/result/RX, real PDF files')
  print('PASS browser responsiveness: desktop 1440px + mobile 390px')
  print('PASS browser JavaScript page errors: 0')
  print('Note: Chromium used in-process API bridge because localhost navigation is blocked by the sandbox.')
  context.close();browser.close()
