"""CI-only checks after the real Windows install (synthetic data only).

Run with the installed venv from C:\\MinhDuc as administrator:
  python .github/scripts/windows_e2e.py login|seed|count|restore-test
Reads C:\\ProgramData\\MinhDuc\\clinic.env and the CI admin password from the
MINHDUC_ADMIN_* environment variables. Never prints secrets.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import tempfile
import urllib.request

DATA = Path(os.environ.get('MINHDUC_DATA', r'C:\ProgramData\MinhDuc'))
sys.path.insert(0, os.environ.get('MINHDUC_CODE', r'C:\MinhDuc'))
from scripts.install_env import read_env  # noqa: E402

ENV = read_env(DATA / 'clinic.env')
ORIGIN = ENV['CLINIC_ORIGIN']


def session():
    context = ssl.create_default_context(cafile=str(DATA / 'tls' / 'ca.crt'))
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(jar))

    def call(method, path, body=None):
        headers = {'Origin': ORIGIN, 'X-Clinic-Request': '1', 'Content-Type': 'application/json'}
        for cookie in jar:
            if cookie.name == '__Host-clinic-csrf':
                headers['X-CSRF-Token'] = cookie.value
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(ORIGIN + path, data=data, method=method, headers=headers)
        with opener.open(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b'null')

    status, _ = call('POST', '/api/login', {'username': os.environ['MINHDUC_ADMIN_USER'], 'password': os.environ['MINHDUC_ADMIN_PASSWORD']})
    assert status == 200, status
    return call


def page_check():
    context = ssl.create_default_context(cafile=str(DATA / 'tls' / 'ca.crt'))
    with urllib.request.urlopen(ORIGIN + '/', context=context, timeout=30) as response:
        page = response.read().decode('utf-8')
    assert response.status == 200 and 'app.js' in page and 'PHÒNG KHÁM' in page
    print('PASS: HTTPS (chứng chỉ phòng khám hợp lệ) trả về trang đăng nhập', ORIGIN)


def owner_url():
    return read_env(DATA / 'quantri' / 'owner.env')['CLINIC_DATABASE_URL']


def count():
    import psycopg
    with psycopg.connect(owner_url()) as c:
        result = {
            'service_catalog': c.execute('SELECT count(*) FROM service_catalog').fetchone()[0],
            'users': c.execute('SELECT count(*) FROM users').fetchone()[0],
            'ci_probe': c.execute("SELECT to_regclass('public.ci_probe_update') IS NOT NULL").fetchone()[0],
        }
    print(json.dumps(result))
    return result


def seed():
    call = session()
    name = 'Dịch vụ giả lập CI ' + secrets.token_hex(3)
    status, _ = call('POST', '/api/catalog/services', {'name': name, 'price': 120000, 'category': 'consultation'})
    if status not in (200, 201):
        raise SystemExit(f'seed failed {status}')
    print('PASS: đăng nhập quản trị và ghi dữ liệu giả lập qua HTTPS')


def restore_test():
    """Restore the newest verified backup into a separate empty database."""
    import psycopg
    from psycopg import sql
    from urllib.parse import urlsplit, urlunsplit
    os.environ.update(ENV)
    from scripts.backup_lan import restore
    backups = sorted((DATA / 'backups').glob('minhduc-*.mdbackup'), key=lambda p: p.stat().st_mtime)
    assert backups, 'no backup'
    sup = read_env(DATA / 'quantri' / 'postgres.env')['MINHDUC_PG_SUPER_PASSWORD']
    owner = urlsplit(owner_url())
    target = 'minhduc_restore_ci'
    super_url = urlunsplit(owner._replace(netloc=f'postgres:{sup}@127.0.0.1:5432', path='/postgres'))
    with psycopg.connect(super_url, autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(target)))
        c.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(target), sql.Identifier(owner.username)))
    target_url = urlunsplit(owner._replace(path='/' + target))
    with tempfile.TemporaryDirectory(dir=DATA) as temp:
        restore(backups[-1], DATA / 'quantri' / 'backup.key', target_url, Path(temp) / 'attachments')
    live = count()
    with psycopg.connect(target_url) as c:
        restored = c.execute('SELECT count(*) FROM service_catalog').fetchone()[0]
        users = c.execute('SELECT count(*) FROM users').fetchone()[0]
    with psycopg.connect(super_url, autocommit=True) as c:
        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
    assert restored == live['service_catalog'] and users == live['users'], (restored, users, live)
    print(f'PASS: khôi phục bản sao lưu {backups[-1].name} sang CSDL riêng, khớp {restored} dịch vụ, {users} tài khoản')


def pg_set_password():
    """CI: change the postgres superuser password to NEW_PG_PW (accented) with the current one."""
    import psycopg
    from psycopg import sql
    old = read_env(DATA / 'quantri' / 'postgres.env')['MINHDUC_PG_SUPER_PASSWORD']
    with psycopg.connect(host='127.0.0.1', user='postgres', password=old, dbname='postgres', autocommit=True) as c:
        c.execute(sql.SQL('ALTER ROLE postgres PASSWORD {}').format(sql.Literal(os.environ['NEW_PG_PW'])))
    print('postgres password changed to an accented one')


def pg_accent_check():
    """CI: postgres.env written by the manual-entry path is UTF-8 and logs in with real SCRAM."""
    import psycopg
    from scripts import install_db
    password = os.environ['NEW_PG_PW']
    path = DATA / 'quantri' / 'postgres.env'
    assert read_env(path)['MINHDUC_PG_SUPER_PASSWORD'] == password, 'password file does not round-trip'
    raw = path.read_bytes()
    assert password.encode('utf-8') in raw and b'?' not in raw.split(b'=', 1)[1], 'password file is not UTF-8'

    class Args:
        clinic_env = str(DATA / 'clinic.env')
        owner_env = None
        super_env = str(path)
    saved = dict(os.environ)
    try:
        url = install_db.load(Args)['super']
    finally:
        os.environ.clear(); os.environ.update(saved)
    with psycopg.connect(url) as c:
        scram = c.execute("SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname='postgres'").fetchone()[0]
        method = c.execute('SHOW password_encryption').fetchone()[0]
    assert scram and method == 'scram-sha-256', (scram, method)
    try:
        psycopg.connect(host='127.0.0.1', user='postgres', dbname='postgres',
                        password=password.encode('ascii', 'ignore').decode()).close()
    except psycopg.OperationalError:
        pass
    else:
        raise SystemExit('password without diacritics must be rejected')
    print('PASS: mật khẩu postgres có dấu -> tệp UTF-8, đăng nhập SCRAM-SHA-256 thật đạt; bản bỏ dấu bị từ chối')


SETTINGS_FILE = DATA / 'caidat' / 'ui_settings.json'
CHOSEN = {'default_province_code': None, 'block_practitioner_scope': False, 'advance_payment': True, 'addendum': True, 'controlled_drugs': False}


def settings_set():
    """CI: quản trị đổi Cài đặt qua HTTPS (dịch vụ phải ghi được thư mục caidat)."""
    call = session()
    status, body = call('PUT', '/api/ui-settings', CHOSEN)
    assert status == 200 and body == {**CHOSEN, 'source': 'file'}, (status, body)
    assert json.loads(SETTINGS_FILE.read_text(encoding='utf-8')) == CHOSEN
    print('PASS: quản trị lưu Cài đặt qua HTTPS; tệp caidat\\ui_settings.json đã ghi')


def settings_check():
    """CI: sau khi CAP_NHAT lỗi tự quay về, cài đặt vẫn đúng và dịch vụ vẫn ghi được."""
    call = session()
    status, body = call('GET', '/api/ui-settings')
    assert status == 200 and body == {**CHOSEN, 'source': 'file'}, (status, body)
    kept = list(SETTINGS_FILE.parent.glob('ui_settings.loi-*.json'))
    assert kept, 'quay lui phải giữ bản cài đặt lúc lỗi để đối chiếu'
    leftovers = [p.name for p in SETTINGS_FILE.parent.iterdir() if 'khoiphuc' in p.name]
    assert not leftovers, leftovers
    status, body = call('PUT', '/api/ui-settings', {'advance_payment': False})
    assert status == 200 and body['advance_payment'] is False, (status, body)
    status, body = call('PUT', '/api/ui-settings', {'advance_payment': True})
    assert status == 200, status
    print('PASS: CAP_NHAT lỗi trên máy ĐÃ có cài đặt -> quay về đúng cài đặt, dịch vụ vẫn ghi được')


def fresh_install_report():
    """CI: a FIRST install has only 1 verified backup, so the backup row must be KHÔNG ĐẠT
    (needs 3) with the reason and the action, and it must be the ONLY failing row."""
    report = sorted((DATA / 'nhatky').glob('kiem-tra-sau-cai-*.txt'), key=lambda p: p.stat().st_mtime)[-1]
    lines = report.read_text(encoding='utf-8-sig').splitlines()
    failed = [(line, lines[i + 1].strip()) for i, line in enumerate(lines) if line.startswith('[KHÔNG ĐẠT]')]
    assert len(failed) == 1, failed
    title, detail = failed[0]
    assert title.startswith('[KHÔNG ĐẠT] Sao lưu:'), title
    assert 'mới có 1 bản đã kiểm, cần ít nhất 3' in detail and '20:00' in detail, detail
    print('PASS: may moi cai -> chi muc sao luu KHONG DAT (moi 1 ban da kiem, can 3), co ly do va viec can lam')


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'login':
        page_check(); session(); print('PASS: đăng nhập quản trị')
    elif command == 'seed':
        seed()
    elif command == 'count':
        count()
    elif command == 'restore-test':
        restore_test()
    elif command == 'pg-set-password':
        pg_set_password()
    elif command == 'pg-accent-check':
        pg_accent_check()
    elif command == 'settings-set':
        settings_set()
    elif command == 'settings-check':
        settings_check()
    elif command == 'fresh-install-report':
        fresh_install_report()
    else:
        raise SystemExit(f'unknown command {command}')
