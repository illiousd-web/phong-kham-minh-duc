"""Chụp màn hình giao diện từng vai trò (máy tính 1440px và điện thoại 390px) bằng dữ liệu giả lập.

Chạy: python -m scripts.ui_screenshots --out docs/giao-dien
Khởi động bản demo cục bộ với CSDL tạm, tạo dữ liệu mẫu qua API, đăng nhập từng vai trò rồi chụp.
Không dùng dữ liệu thật, không kết nối Internet.
"""
import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from scripts.ui_wait import wait_for_login

ROOT = Path(__file__).resolve().parents[1]
ROLES = [('letan', 'le-tan'), ('bs_noi', 'bac-si'), ('kythuat', 'ky-thuat-vien'), ('dieuduong', 'dieu-duong'),
         ('duoc', 'duoc'), ('thungan', 'thu-ngan'), ('quanly', 'quan-ly'), ('quantri', 'quan-tri')]
# Trang chụp thêm cho giao diện cũ (trước khi sắp xếp lại): menu chính của vai trò.
BEFORE_PAGE = {'letan': 'reception', 'bs_noi': 'clinical', 'kythuat': 'orders', 'dieuduong': 'nursing',
               'duoc': 'rx', 'thungan': 'cashier', 'quanly': 'finance', 'quantri': 'accounts'}


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def seed(base, password):
    def login(user):
        c = httpx.Client(base_url=base, headers={'X-Clinic-Request': '1'}, trust_env=False, timeout=10)
        token = c.post('/api/login', json={'username': user, 'password': password}).json()['access_token']
        c.headers['Authorization'] = 'Bearer ' + token
        return c
    manager, reception, doctor = login('quanly'), login('letan'), login('bs_noi')
    tech, pharmacy, cashier = login('kythuat'), login('duoc'), login('thungan')
    ok = lambda r: (r.raise_for_status(), r.json())[1]
    ok(manager.post('/api/catalog/services', json={'name': 'Xét nghiệm đường huyết (mẫu)', 'category': 'lab', 'price': 45000}))
    ok(manager.post('/api/catalog/services', json={'name': 'Siêu âm bụng (mẫu)', 'category': 'ultrasound', 'price': 120000}))
    med = next(m for m in ok(manager.get('/api/catalog'))['medicines'] if not m['controlled'])
    ok(manager.put(f"/api/medicines/{med['id']}/price", json={'unit_price': 1500}))
    doctor_id = next(d['id'] for d in ok(reception.get('/api/staff')) if d['full_name'] == 'BS Nội')
    nurse_id = None
    names = [('Nguyễn Văn Mẫu', 'Nam', '1980-04-12'), ('Trần Thị Thử', 'Nữ', '1992-11-05'), ('Lê Văn Giả', 'Nam', '1975-01-30')]
    visits = []
    for i, (name, sex, dob) in enumerate(names):
        p = ok(reception.post('/api/patients', json={'full_name': name, 'sex': sex, 'date_of_birth': dob, 'phone': f'090000000{i}'}))
        visits.append(ok(reception.post('/api/visits', json={'patient_id': p['id'], 'doctor_id': doctor_id, 'service_id': 1}))['id'])
    v = visits[0]
    current = ok(doctor.get(f'/api/visits/{v}'))
    ok(doctor.put(f'/api/visits/{v}/clinical', json={'version': current['version'], 'chief_complaint': 'Mệt, khát nước (giả lập)',
        'history': '', 'diagnosis': 'Theo dõi đái tháo đường (giả lập)', 'treatment': 'Ăn giảm đường', 'vitals': 'Mạch 82 l/p; HA 135/85 mmHg', 'follow_up': None}))
    lab = next(s for s in ok(doctor.get('/api/cls-services')) if s['category'] == 'lab')
    order = ok(doctor.post('/api/orders', json={'visit_id': v, 'category': 'lab', 'service_id': lab['id'], 'request_key': secrets.token_hex(8), 'defer_approval': False}))
    us = next(s for s in ok(doctor.get('/api/cls-services')) if s['category'] == 'ultrasound')
    ok(doctor.post('/api/orders', json={'visit_id': visits[1], 'category': 'ultrasound', 'service_id': us['id'], 'request_key': secrets.token_hex(8), 'defer_approval': False}))
    ok(tech.put(f"/api/orders/{order['id']}/result", json={'version':0,'result_text': 'Glucose | 9,2 | mmol/L | 3,9–5,6 | H\nKết luận: Đường huyết cao (giả lập)'}))
    ok(doctor.post(f"/api/orders/{order['id']}/approve"))
    ok(doctor.post('/api/prescriptions', json={'visit_id': v, 'items': [{'medicine_id': med['id'], 'quantity': 10, 'unit_id': None, 'directions': 'Uống sau ăn (giả lập)'}], 'instructions': 'Tái khám khi mệt', 'follow_up': None}))
    nurses = ok(doctor.get('/api/nurses'))
    if nurses:
        ok(doctor.post(f'/api/visits/{v}/nurses', json={'nurse_id': nurses[0]['id']}))
        ok(doctor.post(f'/api/visits/{v}/nursing-tasks', json={'nurse_id': nurses[0]['id'], 'content': 'Đo lại huyết áp sau 30 phút', 'request_key': secrets.token_hex(8)}))
    ok(cashier.post('/api/payments', json={'visit_id': visits[2], 'amount': 50000, 'method': 'cash', 'idempotency_key': secrets.token_hex(8)}))
    ok(cashier.post('/api/adjustments', json={'visit_id': visits[2], 'kind': 'discount', 'amount': 20000, 'reason': 'Giảm phí người cao tuổi (giả lập)'}))
    return visits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='docs/giao-dien')
    parser.add_argument('--suffix', default='')
    parser.add_argument('--before', action='store_true', help='giao diện cũ: bấm menu chính theo vai trò')
    parser.add_argument('--chromium', default=os.getenv('CHROMIUM_PATH'))
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(18)
    tmp = Path(tempfile.mkdtemp(prefix='md_shots_'))
    env = {**os.environ, 'DEMO_PASSWORD': password, 'CLINIC_DB_PATH': str(tmp / 'demo.sqlite3'), 'CLINIC_UPLOAD_DIR': str(tmp / 'up'), 'CLINIC_MODE': 'demo'}
    port = free_port()
    base = f'http://127.0.0.1:{port}'
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                              cwd=os.getcwd(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if httpx.get(base + '/api/health', trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        seed(base, password)
        with sync_playwright() as p:
            launch = {'headless': True, 'args': ['--no-sandbox']}
            if args.chromium:
                launch['executable_path'] = args.chromium
            browser = p.chromium.launch(**launch)
            for user, slug in ROLES:
                for device, viewport in (('may-tinh', {'width': 1440, 'height': 900}), ('dien-thoai', {'width': 390, 'height': 844})):
                    ctx = browser.new_context(viewport=viewport, device_scale_factor=1, locale='vi-VN')
                    page = ctx.new_page()
                    page.goto(base, wait_until='networkidle')
                    page.locator('[data-form="login"] select[name="username"]').select_option(user)
                    page.locator('[data-form="login"] input[name="password"]').fill(password)
                    page.locator('[data-form="login"] button').click()
                    wait_for_login(page)
                    page.locator('#workspace[aria-busy="false"]').wait_for()
                    if args.before:
                        page.locator(f'[data-action="navigate"][data-page="{BEFORE_PAGE[user]}"]').first.click()
                        page.locator('#workspace[aria-busy="false"]').wait_for()
                    page.wait_for_load_state('networkidle')
                    page.locator('#toast').evaluate("e=>e.classList.add('hidden')")
                    page.screenshot(path=str(out / f'{slug}-{device}{args.suffix}.png'), full_page=True)
                    extra = {'quantri': ('settings', 'cai-dat'), 'letan': ('prices', 'bang-gia')}
                    if not args.before and user in extra:
                        target, name = extra[user]
                        page.locator(f'[data-action="navigate"][data-page="{target}"]').click()
                        page.locator(f'#workspace[data-page="{target}"][aria-busy="false"]').wait_for()
                        page.locator('#toast').evaluate("e=>e.classList.add('hidden')")
                        page.screenshot(path=str(out / f'{name}-{device}{args.suffix}.png'), full_page=True)
                    ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    print('Đã chụp vào', out)


if __name__ == '__main__':
    main()
