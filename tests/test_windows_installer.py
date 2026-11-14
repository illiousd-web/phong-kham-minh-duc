"""Logic of the Windows installer helpers (no PostgreSQL, no Windows needed)."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

import pytest

from scripts import install_env, backup_job, install_health

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / 'deploy' / 'windows'
NOW = datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)


# ---------- install_env: configuration files ----------

def test_lan_network_from_ip_and_prefix():
    assert install_env.lan_network('192.168.1.10', 24) == '192.168.1.0/24'
    assert install_env.lan_network('10.20.30.40', '16') == '10.20.0.0/16'
    for ip, prefix in [('8.8.8.8', 24), ('192.168.1.10', 8), ('192.168.1.0', 24), ('192.168.1.255', 24), ('fe80::1', 64)]:
        with pytest.raises(ValueError):
            install_env.lan_network(ip, prefix)


def test_write_configs_creates_strong_unique_passwords(tmp_path):
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'q' / 'owner.env'
    report = install_env.write_configs(clinic, owner, '192.168.1.10', 24, 'C:\\ProgramData\\MinhDuc',
                                       'C:\\Program Files\\PostgreSQL\\17\\bin')
    assert report['clinic_env_created'] and report['owner_env_created']
    assert sorted(report['new_password_roles']) == ['clinic_app', 'clinic_owner']
    c, o = install_env.read_env(clinic), install_env.read_env(owner)
    app_pw = install_env.password_from_url(c['CLINIC_DATABASE_URL'], 'clinic_app')
    owner_pw = install_env.password_from_url(o['CLINIC_DATABASE_URL'], 'clinic_owner')
    assert len(app_pw) >= 40 and len(owner_pw) >= 40 and app_pw != owner_pw
    assert re.fullmatch(r'[A-Za-z0-9_\-]+', app_pw)  # no URL escaping needed
    assert c['CLINIC_ORIGIN'] == 'https://192.168.1.10:8443'
    assert c['CLINIC_ALLOWED_CIDRS'] == '192.168.1.0/24'
    assert c['CLINIC_UPLOAD_DIR'] == 'C:\\ProgramData\\MinhDuc\\attachments'
    assert c['CLINIC_PG_DUMP'] == 'C:\\Program Files\\PostgreSQL\\17\\bin\\pg_dump.exe'
    assert c['CLINIC_BACKUP_KEEP'] == '14' and c['CLINIC_OFFSITE_KEEP'] == '30'
    assert c['CLINIC_WORKERS'] == '1' and c['CLINIC_POOL_MAX'] == '4'
    assert app_pw not in json.dumps(report) and owner_pw not in json.dumps(report)
    # owner.env is a full LAN config (migration imports app.config) with the owner URL.
    assert o['CLINIC_ORIGIN'] == c['CLINIC_ORIGIN'] and o['CLINIC_DATABASE_URL'].startswith('postgresql://clinic_owner:')


def test_second_run_never_changes_existing_passwords_or_values(tmp_path):
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg/bin')
    first_c, first_o = clinic.read_text(), owner.read_text()
    # Administrator tuned a value; a re-run must keep it.
    clinic.write_text(first_c.replace('CLINIC_MIN_FREE_MB=10240', 'CLINIC_MIN_FREE_MB=12288'))
    report = install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg/bin')
    assert report['new_password_roles'] == [] and not report['clinic_env_created']
    c = install_env.read_env(clinic)
    assert c['CLINIC_MIN_FREE_MB'] == '12288'
    assert c['CLINIC_DATABASE_URL'] == install_env.read_env(tmp_path / 'clinic.env')['CLINIC_DATABASE_URL']
    assert install_env.read_env(owner)['CLINIC_DATABASE_URL'] in first_o


def _old_installer_files(tmp_path):
    """Configuration written by the first Windows installer (30 local backups)."""
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg')
    for path in (clinic, owner):
        path.write_text(path.read_text().replace('CLINIC_BACKUP_KEEP=14', 'CLINIC_BACKUP_KEEP=30'))
    return clinic, owner


def test_rerun_cai_dat_moves_old_install_to_14_local_keeping_passwords(tmp_path):
    clinic, owner = _old_installer_files(tmp_path)
    urls = (install_env.read_env(clinic)['CLINIC_DATABASE_URL'], install_env.read_env(owner)['CLINIC_DATABASE_URL'])
    report = install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg')
    assert report['managed_changed'] == ['CLINIC_BACKUP_KEEP'] and report['new_password_roles'] == []
    for path, url in zip((clinic, owner), urls):
        values = install_env.read_env(path)
        assert values['CLINIC_BACKUP_KEEP'] == '14' and values['CLINIC_OFFSITE_KEEP'] == '30'
        assert values['CLINIC_DATABASE_URL'] == url


def test_cap_nhat_managed_update_changes_only_policy_keys(tmp_path):
    clinic, owner = _old_installer_files(tmp_path)
    clinic.write_text(clinic.read_text().replace('CLINIC_OFFSITE_KEEP=30\n', ''))  # very old file without the key
    before = {p: p.read_text() for p in (clinic, owner)}
    assert install_env.main(['managed', str(clinic), str(owner)]) == 0
    for path in (clinic, owner):
        old_lines = [l for l in before[path].splitlines() if not l.startswith(('CLINIC_BACKUP_KEEP', 'CLINIC_OFFSITE_KEEP'))]
        new_lines = [l for l in path.read_text().splitlines() if not l.startswith(('CLINIC_BACKUP_KEEP', 'CLINIC_OFFSITE_KEEP'))]
        assert old_lines == new_lines, 'passwords, comments and other values must be untouched'
        values = install_env.read_env(path)
        assert values['CLINIC_BACKUP_KEEP'] == '14' and values['CLINIC_OFFSITE_KEEP'] == '30'
    # Second call: nothing to change, file not rewritten.
    stamp = clinic.stat().st_mtime_ns
    assert install_env.apply_managed(clinic) == [] and clinic.stat().st_mtime_ns == stamp
    assert install_env.apply_managed(tmp_path / 'missing.env') == []


def test_ip_change_is_reported_not_silently_applied(tmp_path):
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg')
    report = install_env.write_configs(clinic, owner, '192.168.1.20', 24, '/data', '/pg')
    assert report['ip_changed'] and report['configured_ip'] == '192.168.1.10'
    assert install_env.read_env(clinic)['CLINIC_BIND_IP'] == '192.168.1.10'


def test_missing_key_is_added_on_rerun(tmp_path):
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg')
    clinic.write_text('\n'.join(l for l in clinic.read_text().splitlines() if not l.startswith('CLINIC_OFFSITE_KEEP')))
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg')
    assert install_env.read_env(clinic)['CLINIC_OFFSITE_KEEP'] == '30'


def test_superuser_file_is_created_once(tmp_path):
    path = tmp_path / 'postgres.env'
    assert install_env.write_super(path) is True
    first = path.read_text()
    assert install_env.write_super(path) is False and path.read_text() == first


def test_cli_errors_are_vietnamese_and_exit_2(capsys):
    assert install_env.main(['cidr', '8.8.8.8', '24']) == 2
    assert 'IP nội bộ' in capsys.readouterr().err


def test_generated_env_is_accepted_by_app_loader(tmp_path):
    """The literal format must be readable by scripts.with_env and Run-Clinic.ps1."""
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, 'C:\\ProgramData\\MinhDuc', 'C:\\PG\\17\\bin')
    for line in clinic.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            assert re.fullmatch(r'[A-Z][A-Z0-9_]*=.*', line)


# ---------- backup_job: external drive and warnings ----------

def _marker(folder, ident):
    target = folder / backup_job.MARKER_DIR
    target.mkdir(parents=True)
    (target / backup_job.MARKER_FILE).write_text(json.dumps({'id': ident}))
    return target


def test_find_external_by_marker_not_by_letter(tmp_path, monkeypatch):
    usb_e, usb_f, data = tmp_path / 'E', tmp_path / 'F', tmp_path / 'data'
    data.mkdir()
    _marker(usb_e, 'other-clinic-drive')
    wanted = _marker(usb_f, 'abc123')
    real_stat = os.stat
    devices = {str(data): 1, str(wanted): 2}

    class Fake:
        def __init__(self, dev): self.st_dev = dev

    monkeypatch.setattr(backup_job.os, 'stat', lambda p: Fake(devices[str(p)]) if str(p) in devices else real_stat(p))
    assert backup_job.find_external([tmp_path / 'C', usb_e, usb_f], 'abc123', data) == wanted
    assert backup_job.find_external([usb_e], 'abc123', data) is None


def test_find_external_rejects_same_volume_as_data(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    _marker(tmp_path / 'same-ssd', 'abc123')
    # Same filesystem as the data folder: not an external copy.
    assert backup_job.find_external([tmp_path / 'same-ssd'], 'abc123', data) is None


def test_external_absent_more_than_three_days_warns():
    config = {'id': 'x', 'label': 'USB SaoLuu', 'declared_at': (NOW - timedelta(days=10)).isoformat()}
    ok = {'last_success_utc': (NOW - timedelta(hours=1)).isoformat()}
    assert backup_job.evaluate({**ok, 'external_last_copy_utc': (NOW - timedelta(days=2)).isoformat()}, config, NOW) == []
    warnings = backup_job.evaluate({**ok, 'external_last_copy_utc': (NOW - timedelta(days=4)).isoformat()}, config, NOW)
    assert len(warnings) == 1 and '4 ngày' in warnings[0] and 'USB SaoLuu' in warnings[0]
    # Never copied since declaration 10 days ago.
    assert '10 ngày' in backup_job.evaluate(ok, config, NOW)[0]
    # Declared yesterday, not copied yet: no alarm yet.
    fresh = {**config, 'declared_at': (NOW - timedelta(days=1)).isoformat()}
    assert backup_job.evaluate(ok, fresh, NOW) == []
    # No external drive declared: nothing to report.
    assert backup_job.evaluate(ok, None, NOW) == []


def test_backup_failure_and_stale_backup_warn():
    stale = backup_job.evaluate({'last_success_utc': (NOW - timedelta(hours=40)).isoformat()}, None, NOW)
    assert any('36 giờ' in w for w in stale)
    failed = backup_job.evaluate({'last_error': 'StorageLimitError: thiếu chỗ',
                                  'last_success_utc': (NOW - timedelta(hours=20)).isoformat()}, None, NOW)
    assert any('THẤT BẠI' in w for w in failed)


def test_alert_file_written_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_job.os, 'name', 'posix')
    alert = tmp_path / 'CANH BAO.txt'
    backup_job.publish_alert(alert, ['Ổ ngoài vắng mặt'], NOW)
    assert 'Ổ ngoài vắng mặt' in alert.read_text(encoding='utf-8-sig')
    backup_job.publish_alert(alert, [], NOW)
    assert not alert.exists()


# ---------- install_health: report ----------

def _good_facts():
    return {
        'service': {'status': 'Running', 'start': 'Automatic'},
        'postgres_service': {'status': 'Running', 'start': 'Automatic'},
        'pg_listeners': ['127.0.0.1'], 'db_ok': True, 'schema_version': 3,
        'https_health': True, 'login_page': True, 'origin': 'https://192.168.1.10:8443',
        'cert_not_after': (NOW + timedelta(days=300)).isoformat(),
        'firewall': {'exists': True, 'enabled': True, 'scoped': True, 'port': '8443', 'remote': '192.168.1.0/24'},
        'backup_task': {'exists': True, 'enabled': True, 'next_run': 'x', 'last_result': 0},
        'backup_state': {'last_success_utc': (NOW - timedelta(hours=2)).isoformat(), 'verified_count': 3}, 'backup_count': 3,
        'disk_free_gib': 120.5, 'memory': {'total_mib': 7900, 'available_mib': 3000},
        'pagefile': {'auto': True, 'detail': 'Windows tự quản lý'}, 'env_acl_ok': True, 'env_acl_detail': 'ok',
        'ui_settings': 'file',
    }


def test_health_all_pass():
    rows = install_health.evaluate(_good_facts(), NOW)
    assert len(rows) >= 13 and all(r['dat'] for r in rows), [r for r in rows if not r['dat']]


@pytest.mark.parametrize('change, title_part', [
    ({'service': {'status': 'Stopped', 'start': 'Automatic'}}, 'Dịch vụ web'),
    ({'pg_listeners': ['0.0.0.0']}, 'PostgreSQL chỉ nhận'),
    ({'db_ok': False, 'db_error': 'OperationalError'}, 'cơ sở dữ liệu'),
    ({'schema_version': 2}, 'cơ sở dữ liệu'),
    ({'login_page': False}, 'Trang đăng nhập'),
    ({'cert_not_after': (NOW + timedelta(days=10)).isoformat()}, 'Chứng chỉ'),
    ({'cert_not_after': (NOW + timedelta(days=59, hours=1)).isoformat()}, 'Chứng chỉ'),
    ({'firewall': {'exists': True, 'enabled': True, 'scoped': False}}, 'Tường lửa'),
    ({'backup_task': {}}, 'Lịch sao lưu'),
    ({'backup_state': {'last_success_utc': (NOW - timedelta(hours=50)).isoformat(), 'verified_count': 3}}, 'Sao lưu:'),
    ({'backup_state': {}, 'backup_newest_utc': None}, 'Sao lưu:'),
    ({'backup_state': {'last_success_utc': NOW.isoformat(), 'verified_count': 2}}, 'Sao lưu:'),
    ({'backup_state': {'last_success_utc': NOW.isoformat(), 'verified_count': 5, 'over_budget': True}}, 'Sao lưu:'),
    ({'backup_state': {'last_success_utc': NOW.isoformat(), 'verified_count': 4, 'corrupt': ['x']}}, 'Sao lưu:'),
    ({'disk_free_gib': 12}, 'Ổ dữ liệu'),
    ({'memory': {'total_mib': 4096, 'available_mib': 2000}}, 'RAM'),
    ({'pagefile': {'auto': False, 'detail': 'Cố định 512 MB'}}, 'page file'),
    ({'env_acl_ok': False}, 'Tệp cấu hình'),
    ({'ui_settings': 'missing'}, 'ui_settings.json'),
    ({'ui_settings': 'invalid'}, 'ui_settings.json'),
    ({'external_declared': True, 'backup_state': {'last_success_utc': NOW.isoformat(), 'verified_count': 3,
                                                   'external_last_copy_utc': (NOW - timedelta(days=4)).isoformat()}}, 'Ổ sao lưu ngoài'),
])
def test_health_each_failure_detected(change, title_part):
    facts = {**_good_facts(), **change}
    failed = [r['muc'] for r in install_health.evaluate(facts, NOW) if not r['dat']]
    assert len(failed) == 1 and title_part in failed[0], failed


def test_health_missing_windows_facts_fail_not_pass():
    rows = install_health.evaluate({}, NOW)
    assert not any(r['dat'] for r in rows)


def test_report_text_has_no_secrets(tmp_path):
    secret = 'S3cretPw_' + 'x' * 30
    facts = {**_good_facts(), 'CLINIC_DATABASE_URL': f'postgresql://clinic_app:{secret}@127.0.0.1/minhduc'}
    text = install_health.render(install_health.evaluate(facts, NOW), facts, now=NOW)
    assert secret not in text and 'postgresql://' not in text
    assert 'ĐẠT' in text and 'giờ Việt Nam' in text and '20:00' in text


def test_collect_without_services_reports_reasons(tmp_path):
    env = {'CLINIC_DATA_DIR': str(tmp_path), 'CLINIC_DATABASE_URL': 'postgresql://u:p@127.0.0.1:1/x',
           'CLINIC_ORIGIN': 'https://127.0.0.1:1', 'CLINIC_TLS_CERT': str(tmp_path / 'missing.crt')}
    facts = install_health.collect(env, timeout=2)
    assert facts['db_ok'] is False and facts['https_health'] is False and 'cert_error' in facts
    assert 'p@' not in json.dumps(facts)


# ---------- Windows files: encoding and safety ----------

def _windows_files(*patterns):
    return [p for pattern in patterns for p in sorted(WIN.glob(pattern))]


def test_powershell_files_are_utf8_with_bom():
    """Windows PowerShell 5.1 reads BOM-less scripts as ANSI: Vietnamese would break."""
    files = _windows_files('*.ps1', '*.psm1')
    assert files
    for path in files:
        data = path.read_bytes()
        text = data.decode('utf-8-sig')
        if any(ord(ch) > 127 for ch in text):
            assert data.startswith(b'\xef\xbb\xbf'), path.name


def test_batch_files_are_ascii_and_elevate():
    """cmd.exe parses .bat in the OEM code page; keep them ASCII and push text to PowerShell."""
    names = {p.name for p in _windows_files('*.bat')}
    assert {'CAI_DAT.bat', 'CAI_MAY_TRAM.bat', 'CAP_NHAT.bat', 'KIEM_TRA.bat'} <= names
    for path in _windows_files('*.bat'):
        path.read_bytes().decode('ascii')
    for name in ('CAI_DAT.bat', 'CAP_NHAT.bat', 'KIEM_TRA.bat', 'GIA_HAN_CHUNG_CHI.bat'):
        text = (WIN / name).read_text()
        assert 'RunAs' in text and '-ExecutionPolicy Bypass' in text


def test_workstation_installer_runs_on_windows7_without_powershell():
    """Windows 7 SP1 workstations: only cmd.exe built-ins, certutil and cscript."""
    bat = (WIN / 'CAI_MAY_TRAM.bat').read_text()
    vbs = (WIN / 'MayTram.vbs').read_bytes()
    vbs.decode('ascii')  # cscript reads ANSI; Vietnamese name is built with ChrW
    assert 'powershell' not in bat.lower() and 'pwsh' not in bat.lower()
    assert 'certutil -addstore -f Root' in bat and '-user' not in bat  # local machine Trusted Root
    assert 'certutil -hashfile' in bat and 'SHA256' in bat and 'VAN_TAY_CA=' in bat
    assert 'MayTram.vbs" elevate' in bat and 'MayTram.vbs" shortcut' in bat
    text = vbs.decode('ascii')
    assert '"runas"' in text and '--app=' in text and 'chrome.exe' in text and 'msedge.exe' in text
    assert 'ChrW(272) & ChrW(7913)' in text  # "Đứ" in "Phòng khám Minh Đức"
    cai_dat = (WIN / 'CaiDat.ps1').read_text(encoding='utf-8-sig')
    assert "'MayTram.vbs'" in cai_dat and 'CaiMayTram.ps1' not in cai_dat.replace("'CaiMayTram.ps1') -Force", '')
    assert 'ASCIIEncoding' in cai_dat.split('may-chu.txt')[1][:200]


def test_pinned_downloads_have_sha256_and_https():
    module = (WIN / 'MinhDuc.Install.psm1').read_text(encoding='utf-8-sig')
    pins = re.findall(r"Url\s*=\s*'([^']+)'\s*;\s*Sha256\s*=\s*'([0-9a-f]{64})'", module)
    urls = [u for u, _ in pins]
    assert any('python-3.12.10-amd64.exe' in u for u in urls)
    assert any('postgresql-17.' in u and 'windows-x64.exe' in u for u in urls)
    assert any('WinSW' in u and 'v2.12.0' in u for u in urls)
    assert all(u.startswith('https://') for u in urls)


def test_installer_never_prints_or_commits_secrets():
    text = '\n'.join(p.read_text(encoding='utf-8-sig') for p in _windows_files('*.ps1', '*.psm1'))
    assert 'ConvertFrom-SecureString' not in text
    assert not re.search(r'Write-(Host|Output)[^\n]*(MINHDUC_PG_SUPER_PASSWORD|\$superPassword|\$adminPlain)', text)
    gitignore = (ROOT / '.gitignore').read_text()
    for pattern in ('*.key', '*.crt', '.env.*', '*.zip'):
        assert pattern in gitignore
    assert 'clinic.env' in gitignore


def test_requirements_lock_is_fully_hashed_and_has_windows_tzdata():
    text = (ROOT / 'requirements.lock').read_text()
    requirements = [l for l in text.splitlines() if l and not l.startswith((' ', '#'))]
    assert requirements
    blocks = re.split(r'\n(?=[A-Za-z])', text.split('\n', 3)[-1])
    for block in blocks:
        if block.strip() and not block.startswith('#'):
            assert '--hash=sha256:' in block, block.splitlines()[0]
    assert any(l.startswith('tzdata==') and 'win32' in l for l in requirements)


# ---------- install_cert: certificate by LAN IP ----------

def test_certificate_created_checked_and_kept(tmp_path):
    from scripts import install_cert
    tls, ca_key = tmp_path / 'tls', tmp_path / 'quantri' / 'ca.key'
    fp = install_cert.create('192.168.1.10', tls, ca_key)
    assert len(fp) == 64 and fp == install_cert.fingerprint(tls / 'ca.crt')
    assert (tls / 'server.crt').exists() and (tls / 'server.key').exists() and ca_key.exists()
    assert not (tls / 'ca.key').exists(), 'CA private key must not sit next to the server files'
    ok, reason = install_cert.check(tls / 'server.crt', '192.168.1.10', 30)
    assert ok and 'còn' in reason
    ok, reason = install_cert.check(tls / 'server.crt', '192.168.1.20', 30)
    assert not ok and '192.168.1.10' in reason
    assert not install_cert.check(tls / 'server.crt', '192.168.1.10', 400)[0]
    assert install_cert.check(tmp_path / 'none.crt', '192.168.1.10', 30) == (False, 'chưa có chứng chỉ')
    # Re-creating keeps the previous files for manual rollback.
    install_cert.create('192.168.1.10', tls, ca_key)
    assert list(tls.glob('ca.crt.cu-*')) and list(ca_key.parent.glob('ca.key.cu-*'))


def test_powershell_no_drive_qualified_variable_in_strings():
    """"$Tong: ..." is parsed as a drive-qualified variable and breaks the whole script."""
    pattern = re.compile(r'\$(?!script:|env:|global:|using:|private:|local:)[A-Za-z_]\w*:(?!:)')
    for path in _windows_files('*.ps1', '*.psm1'):
        for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
            if not line.lstrip().startswith('#'):
                assert not pattern.search(line), f'{path.name}:{number}: dùng ${{ten}}: thay vì $ten:'


def test_runtime_text_io_declares_utf8():
    """Windows with a United States locale reads files as cp1252: Vietnamese text breaks startup."""
    pattern = re.compile(r'\.(read_text|write_text)\((?!.*encoding)')
    for path in [*sorted((ROOT / 'app').glob('*.py')), *sorted((ROOT / 'scripts').glob('*.py'))]:
        if path.name == 'benchmark_lan.py':
            continue  # Linux-only developer harness
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            assert not pattern.search(line), f'{path.name}:{number} thiếu encoding="utf-8"'


def test_report_file_has_single_crlf_line_endings(tmp_path, monkeypatch):
    facts_file = tmp_path / 'facts.json'
    facts_file.write_text(json.dumps(_good_facts()), encoding='utf-8')
    monkeypatch.setattr(install_health, 'collect', lambda env, state=None: {})
    out = tmp_path / 'bao-cao.txt'
    install_health.main(['--windows-facts', str(facts_file), '--output', str(out)])
    data = out.read_bytes()
    assert data.startswith(b'\xef\xbb\xbf') and b'\r\n' in data and b'\r\r\n' not in data


# ---------- Lệnh 1b: gia hạn chứng chỉ bằng CA hiện có, cảnh báo 60 ngày ----------

def _x509(path):
    from cryptography import x509
    return x509.load_pem_x509_certificate(Path(path).read_bytes())


def test_renew_keeps_ca_and_names_new_key_and_rollback(tmp_path):
    from scripts import install_cert
    tls, ca_key = tmp_path / 'tls', tmp_path / 'quantri' / 'ca.key'
    fp = install_cert.create('192.168.1.10', tls, ca_key)
    ca_before = (tls / 'ca.crt').read_bytes()
    old_cert, old_key = (tls / 'server.crt').read_bytes(), (tls / 'server.key').read_bytes()
    result = install_cert.renew(tls, ca_key)
    assert result['ca_fingerprint'] == fp and (tls / 'ca.crt').read_bytes() == ca_before, 'CA must not change'
    new, old = _x509(tls / 'server.crt'), _x509(tls / f"server.crt.cu-{result['stamp']}")
    assert (tls / 'server.key').read_bytes() != old_key and new.serial_number != old.serial_number
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID
    san = lambda c: c.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    assert list(san(new)) == list(san(old)) and new.issuer == _x509(tls / 'ca.crt').subject
    assert format(new.serial_number, 'X') == result['serial']
    # Issued by the same CA: verifies with the unchanged ca.crt.
    _x509(tls / 'ca.crt').public_key().verify(new.signature, new.tbs_certificate_bytes,
        __import__('cryptography.hazmat.primitives.asymmetric.padding', fromlist=['PKCS1v15']).PKCS1v15(),
        new.signature_hash_algorithm)
    assert install_cert.check(tls / 'server.crt', '192.168.1.10', 300)[0]
    # Failure path: rollback restores the previous certificate and key exactly.
    install_cert.rollback(tls, result['stamp'])
    assert (tls / 'server.crt').read_bytes() == old_cert and (tls / 'server.key').read_bytes() == old_key
    assert (tls / f"server.crt.loi-{result['stamp']}").exists()
    # Rolling back again is harmless: nothing saved any more, live pair untouched.
    assert install_cert.rollback(tls, result['stamp'])['restored'] == []
    assert (tls / 'server.crt').read_bytes() == old_cert


def test_renew_refuses_foreign_ca_key(tmp_path):
    from scripts import install_cert
    install_cert.create('192.168.1.10', tmp_path / 'a', tmp_path / 'a-key' / 'ca.key')
    install_cert.create('192.168.1.10', tmp_path / 'b', tmp_path / 'b-key' / 'ca.key')
    before = (tmp_path / 'a' / 'server.crt').read_bytes()
    with pytest.raises(ValueError, match='không khớp'):
        install_cert.renew(tmp_path / 'a', tmp_path / 'b-key' / 'ca.key')
    assert (tmp_path / 'a' / 'server.crt').read_bytes() == before and not list((tmp_path / 'a').glob('*.cu-*'))


def test_status_codes_distinguish_renewable_from_new_ca(tmp_path):
    from scripts import install_cert
    tls = tmp_path / 'tls'
    install_cert.create('192.168.1.10', tls, tmp_path / 'ca.key')
    assert install_cert.status(tls / 'server.crt', '192.168.1.10', 30)['code'] == 'ok'
    assert install_cert.status(tls / 'server.crt', '192.168.1.10', 400)['code'] == 'expiring'
    assert install_cert.status(tls / 'server.crt', '192.168.1.99', 30)['code'] == 'ip'
    assert install_cert.status(tmp_path / 'none', '192.168.1.10', 30)['code'] == 'missing'


def test_served_reads_certificate_from_running_tls_server(tmp_path):
    import socket, ssl, threading
    from scripts import install_cert
    tls = tmp_path / 'tls'
    install_cert.create('127.0.0.1', tls, tmp_path / 'ca.key')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls / 'server.crt', tls / 'server.key')
    listener = socket.create_server(('127.0.0.1', 0))
    port = listener.getsockname()[1]

    def serve():
        conn, _ = listener.accept()
        try:
            with context.wrap_socket(conn, server_side=True):
                pass
        except OSError:
            pass
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    result = install_cert.served(f'https://127.0.0.1:{port}', tls / 'ca.crt')
    thread.join(5); listener.close()
    assert result['serial'] == format(_x509(tls / 'server.crt').serial_number, 'X')


def test_backup_job_warns_on_desktop_when_certificate_under_60_days():
    ok = {'last_success_utc': (NOW - timedelta(hours=1)).isoformat()}
    assert backup_job.evaluate({**ok, 'cert_days_left': 60}, None, NOW) == []
    warnings = backup_job.evaluate({**ok, 'cert_days_left': 59}, None, NOW)
    assert len(warnings) == 1 and '59 ngày' in warnings[0] and 'GIA_HAN_CHUNG_CHI.bat' in warnings[0]


def test_backup_job_reads_certificate_expiry(tmp_path):
    from scripts import install_cert
    install_cert.create('192.168.1.10', tmp_path / 'tls', tmp_path / 'ca.key')
    days = backup_job.cert_days_left(tmp_path / 'tls' / 'server.crt', datetime.now(timezone.utc))
    assert 360 <= days <= 365
    assert backup_job.cert_days_left(tmp_path / 'none.crt', NOW) is None


def test_gia_han_bat_exists_elevates_and_ps_rolls_back():
    text = (WIN / 'GIA_HAN_CHUNG_CHI.bat').read_text()
    assert 'RunAs' in text and 'GiaHanChungChi.ps1' in text
    ps = (WIN / 'GiaHanChungChi.ps1').read_text(encoding='utf-8-sig')
    for needle in ("'prepare'", "'commit'", "'rollback'", "'served'", 'Restart-Service', 'Wait-Https'):
        assert needle in ps, needle


# ---------- Lệnh 1b: mật khẩu postgres nhập tay có dấu ----------

def test_postgres_password_file_written_utf8_not_ascii():
    text = (WIN / 'CaiDat.ps1').read_text(encoding='utf-8-sig')
    line = [l for l in text.splitlines() if 'MINHDUC_PG_SUPER_PASSWORD=' in l and 'SuperEnv' in l]
    assert line, 'postgres.env must be written from CaiDat.ps1'
    assert all('ASCII' not in l and 'Set-Content' not in l for l in line), line
    assert 'UTF8Encoding' in text


def test_accented_postgres_password_round_trips_into_connection_url(tmp_path):
    from urllib.parse import urlsplit, unquote
    from scripts import install_db
    password = 'Mật-khẩu Đức#1/2@phòng'
    (tmp_path / 'postgres.env').write_bytes(('MINHDUC_PG_SUPER_PASSWORD=' + password + '\r\n').encode('utf-8'))
    clinic = tmp_path / 'clinic.env'
    install_env.write_configs(clinic, tmp_path / 'owner.env', '192.168.1.10', 24, '/data', '/pg')

    class Args:
        clinic_env, owner_env, super_env = str(clinic), str(tmp_path / 'owner.env'), str(tmp_path / 'postgres.env')
    saved = dict(os.environ)
    try:
        urls = install_db.load(Args)
    finally:
        os.environ.clear(); os.environ.update(saved)
    parts = urlsplit(urls['super'])
    assert unquote(parts.password) == password and parts.username == 'postgres' and parts.hostname == '127.0.0.1'


def test_renew_writes_new_files_inside_tls_folder_not_a_private_temp_dir(tmp_path, monkeypatch):
    """Windows: files moved out of a mkdtemp folder keep a current-user-only ACL and the
    service account cannot read server.key. Renewal must not use tempfile folders."""
    import tempfile
    from scripts import install_cert
    install_cert.create('192.168.1.10', tmp_path / 'tls', tmp_path / 'ca.key')
    def forbidden(*args, **kwargs):
        raise AssertionError('renew() must not create a private temporary folder')
    monkeypatch.setattr(tempfile, 'TemporaryDirectory', forbidden)
    monkeypatch.setattr(tempfile, 'mkdtemp', forbidden)
    install_cert.renew(tmp_path / 'tls', tmp_path / 'ca.key')
    assert not list((tmp_path / 'tls').glob('server.*.moi-*'))


# ---------- Máy trạm Windows 7 / Chrome 109: chứng chỉ theo chính sách Chrome ----------

def test_certificates_meet_chrome_policy_for_new_and_renewed(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID
    from scripts import install_cert
    tls = tmp_path / 'tls'
    install_cert.create('192.168.1.10', tls, tmp_path / 'ca.key')
    paths = [tls / 'server.crt']
    install_cert.renew(tls, tmp_path / 'ca.key')
    paths.append(tls / 'server.crt')
    for path in paths:
        cert = _x509(path)
        assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days <= 398  # Chrome maximum lifetime
        assert isinstance(cert.public_key(), rsa.RSAPublicKey) and cert.public_key().key_size >= 2048
        assert isinstance(cert.signature_hash_algorithm, hashes.SHA256)
        ext = cert.extensions
        assert '192.168.1.10' in [str(a) for a in ext.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(x509.IPAddress)]
        assert ExtendedKeyUsageOID.SERVER_AUTH in ext.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
        assert ext.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca is False
    ca = _x509(tls / 'ca.crt')
    assert ca.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca is True
    assert ca.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value.key_cert_sign is True


# ---------- Sao lưu 14 bản: chỉ xóa sau khi bản mới đã kiểm, giữ tối thiểu 3 bản đã kiểm ----------

def _items(spec):
    """spec newest first: list of (size, verified)."""
    return [{'name': f'b{i:02d}', 'size': size, 'verified': verified, 'path': None, 'mtime': 100 - i}
            for i, (size, verified) in enumerate(spec)]


def test_plan_prune_keeps_count_and_never_the_newest():
    items = _items([(1, True)] * 20)
    deleted, over = backup_job.plan_prune(items, keep=14, budget_bytes=10 ** 9)
    assert [d['name'] for d in deleted] == [f'b{i:02d}' for i in range(19, 13, -1)] and not over


def test_plan_prune_budget_deletes_oldest_but_keeps_three_verified():
    items = _items([(10, True)] * 6)
    deleted, over = backup_job.plan_prune(items, keep=14, budget_bytes=25)
    assert len(deleted) == 3 and over, 'stop at 3 verified even though still over budget'
    assert [d['name'] for d in deleted] == ['b05', 'b04', 'b03']


def test_plan_prune_unverified_legacy_go_first_verified_protected():
    # newest verified, then 2 verified, then 5 unverified legacy (oldest)
    items = _items([(10, True), (10, True), (10, True)] + [(10, False)] * 5)
    deleted, over = backup_job.plan_prune(items, keep=14, budget_bytes=30)
    assert {d['name'] for d in deleted} == {'b03', 'b04', 'b05', 'b06', 'b07'} and not over
    # Only the new one is verified and budget is tiny: legacy may go, the new one stays.
    deleted, over = backup_job.plan_prune(_items([(10, True), (10, False), (10, False)]), keep=14, budget_bytes=5)
    assert [d['name'] for d in deleted] == ['b02', 'b01'] and over


def test_warnings_for_over_budget_and_unreadable_certificate():
    ok = {'last_success_utc': (NOW - timedelta(hours=1)).isoformat()}
    warnings = backup_job.evaluate({**ok, 'over_budget': True}, None, NOW)
    assert len(warnings) == 1 and 'ngân sách' in warnings[0] and '3 bản' in warnings[0]
    warnings = backup_job.evaluate({**ok, 'cert_unreadable': True, 'cert_days_left': None}, None, NOW)
    assert len(warnings) == 1 and 'Không đọc được chứng chỉ' in warnings[0]


def test_backup_job_reports_missing_certificate(tmp_path, monkeypatch):
    """Certificate missing must warn like an expiring one (state flag set by run())."""
    assert backup_job.cert_days_left(tmp_path / 'khong-co.crt', NOW) is None
    (tmp_path / 'hong.crt').write_text('not a certificate')
    assert backup_job.cert_days_left(tmp_path / 'hong.crt', NOW) is None


def test_external_drive_is_hidden_opt_in(monkeypatch):
    monkeypatch.delenv('CLINIC_EXTERNAL_BACKUP', raising=False)
    assert backup_job.external_enabled({'id': 'x'}) is False
    monkeypatch.setenv('CLINIC_EXTERNAL_BACKUP', '1')
    assert backup_job.external_enabled({'id': 'x'}) is True and backup_job.external_enabled(None) is False
    cai_dat = (WIN / 'CaiDat.ps1').read_text(encoding='utf-8-sig')
    question = cai_dat.index('Có ổ USB hoặc ổ cứng gắn ngoài')
    assert cai_dat.rfind("MINHDUC_SAO_LUU_NGOAI -eq '1'", 0, question) != -1, 'question only behind the hidden option'



# ---------- Gia hạn: từng giai đoạn và kiểm thử gây lỗi ----------

def _tls(tmp_path):
    from scripts import install_cert
    tls, ca_key = tmp_path / 'tls', tmp_path / 'ca.key'
    install_cert.create('192.168.1.10', tls, ca_key)
    return install_cert, tls, ca_key, (tls / 'server.crt').read_bytes(), (tls / 'server.key').read_bytes()


def test_prepare_writes_temp_pair_next_to_old_files_without_touching_live(tmp_path):
    install_cert, tls, ca_key, crt, key = _tls(tmp_path)
    result = install_cert.prepare(tls, ca_key, '20261109000000')
    assert sorted(Path(f).name for f in result['files']) == ['server.crt.moi-20261109000000', 'server.key.moi-20261109000000']
    assert all(Path(f).parent == tls for f in result['files'])
    assert (tls / 'server.crt').read_bytes() == crt and (tls / 'server.key').read_bytes() == key
    assert install_cert.verify_pair(tls, '20261109000000') == {'verified': True}


def test_fault_key_not_readable_aborts_before_swap(tmp_path, monkeypatch):
    """Lỗi 1: không đọc được khóa mới -> không thay gì, dọn tệp tạm."""
    import ssl
    install_cert, tls, ca_key, crt, key = _tls(tmp_path)
    def denied(self, *args, **kwargs):
        raise PermissionError(13, 'Permission denied (gia lap)')
    monkeypatch.setattr(ssl.SSLContext, 'load_cert_chain', denied)
    with pytest.raises(PermissionError):
        install_cert.renew(tls, ca_key, stamp='20261109000001')
    assert (tls / 'server.crt').read_bytes() == crt and (tls / 'server.key').read_bytes() == key
    assert not list(tls.glob('*.moi-*')) and not list(tls.glob('*.cu-*'))
    # The CLI stage also reports it as an error (exit 2), not a traceback.
    install_cert.prepare(tls, ca_key, '20261109000002')
    assert install_cert.main(['verify', '--tls-dir', str(tls), '--stamp', '20261109000002']) == 2


def test_fault_midway_swap_restores_exact_old_pair(tmp_path, monkeypatch):
    """Lỗi 2: hỏng giữa lúc thay (chứng chỉ mới + khóa cũ) -> khôi phục đúng từng byte."""
    install_cert, tls, ca_key, crt, key = _tls(tmp_path)
    stamp = '20261109000003'
    install_cert.prepare(tls, ca_key, stamp)
    monkeypatch.setenv('MINHDUC_TEST_LOI', 'loi-giua-thay')
    with pytest.raises(OSError, match='giữa lúc thay'):
        install_cert.commit(tls, stamp)
    assert (tls / 'server.crt').read_bytes() != crt and (tls / 'server.key').read_bytes() == key  # inconsistent state
    monkeypatch.delenv('MINHDUC_TEST_LOI')
    assert install_cert.rollback(tls, stamp)['restored'] == ['server.crt']
    assert (tls / 'server.crt').read_bytes() == crt and (tls / 'server.key').read_bytes() == key
    assert not list(tls.glob('*.moi-*'))


def test_fault_rollback_failure_is_reported_and_retry_works(tmp_path, monkeypatch):
    """Lỗi 3: khôi phục thất bại -> báo lỗi (không im lặng); chạy lại khôi phục được."""
    install_cert, tls, ca_key, crt, key = _tls(tmp_path)
    stamp = '20261109000004'
    install_cert.prepare(tls, ca_key, stamp)
    install_cert.commit(tls, stamp)
    monkeypatch.setenv('MINHDUC_TEST_LOI', 'khoi-phuc-loi')
    assert install_cert.main(['rollback', '--tls-dir', str(tls), '--stamp', stamp]) == 2
    assert (tls / 'server.crt').read_bytes() != crt
    monkeypatch.delenv('MINHDUC_TEST_LOI')
    assert install_cert.main(['rollback', '--tls-dir', str(tls), '--stamp', stamp]) == 0
    assert (tls / 'server.crt').read_bytes() == crt and (tls / 'server.key').read_bytes() == key


def test_rollback_before_commit_only_cleans_up(tmp_path):
    install_cert, tls, ca_key, crt, key = _tls(tmp_path)
    install_cert.prepare(tls, ca_key, '20261109000005')
    assert install_cert.rollback(tls, '20261109000005')['restored'] == []
    assert (tls / 'server.crt').read_bytes() == crt and not list(tls.glob('*.moi-*'))


def test_gia_han_script_reports_restore_only_after_https_check():
    ps = (WIN / 'GiaHanChungChi.ps1').read_text(encoding='utf-8-sig')
    for needle in ("'prepare'", "'verify'", "'commit'", "'rollback'", "'served'", 'Test-AccountCanRead', 'MINHDUC_TEST_LOI'):
        assert needle in ps, needle
    restored_banner = ps.index('ĐÃ TRẢ CHỨNG CHỈ CŨ')
    assert ps.rfind('$restoreOk', 0, restored_banner) != -1, 'banner must depend on the post-restore HTTPS check'
    assert 'KHÔI PHỤC CHỨNG CHỈ CŨ THẤT BẠI' in ps
    assert ps.index('$stamp =') < ps.index("'prepare'"), 'stamp exists before anything changes'


# ---------- Phản biện PR 8: đối chiếu SHA-256 thật, bản hỏng, ổ gần đầy, KIEM_TRA ----------

def _real_backup(directory, name, payload):
    import hashlib
    path = directory / name
    path.write_bytes(payload)
    marker = {'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    path.with_name(name + backup_job.VERIFIED_SUFFIX).write_text(json.dumps(marker), encoding='utf-8')
    return path


def test_list_backups_same_size_tampering_is_corrupt_not_verified(tmp_path):
    good = _real_backup(tmp_path, 'minhduc-1-good.mdbackup', b'A' * 4096)
    bad = _real_backup(tmp_path, 'minhduc-2-bad.mdbackup', b'B' * 4096)
    data = bytearray(bad.read_bytes())
    data[100] ^= 0xFF  # same size, different content
    bad.write_bytes(bytes(data))
    assert bad.stat().st_size == 4096
    status = {i['name']: (i['verified'], i['corrupt']) for i in backup_job.list_backups(tmp_path)}
    assert status[good.name] == (True, False)
    assert status[bad.name] == (False, True), 'same size but different SHA-256 must be corrupt'
    # A marker without SHA-256 (or unreadable) is "not verified", not "corrupt".
    legacy = tmp_path / 'minhduc-0-legacy.mdbackup'
    legacy.write_bytes(b'x')
    legacy.with_name(legacy.name + '.verified').write_text('{"size": 1}', encoding='utf-8')
    status = {i['name']: (i['verified'], i['corrupt']) for i in backup_job.list_backups(tmp_path)}
    assert status[legacy.name] == (False, False)


def _items3(spec):
    """spec newest first: list of (size, verified, corrupt)."""
    return [{'name': f'b{i:02d}', 'size': size, 'verified': v, 'corrupt': c, 'path': None, 'mtime': 100 - i}
            for i, (size, v, c) in enumerate(spec)]


def test_corrupt_backup_is_never_kept_instead_of_a_good_one():
    # newest good, a corrupt one in the middle, older good ones; keep=4 -> drop 2
    items = _items3([(10, True, False), (10, False, True), (10, True, False), (10, True, False),
                     (10, True, False), (10, True, False)])
    deleted, _ = backup_job.plan_prune(items, keep=4, budget_bytes=10 ** 9)
    assert [d['name'] for d in deleted] == ['b01', 'b05'], 'corrupt goes first, then the oldest good one'
    plan = backup_job.plan_space(items, 15)
    assert [d['name'] for d in plan] == ['b01', 'b05']


def test_plan_space_frees_oldest_verified_but_keeps_three():
    items = _items3([(10, True, False)] * 5)
    assert [d['name'] for d in backup_job.plan_space(items, 20)] == ['b04', 'b03']
    assert backup_job.plan_space(items, 21) is None, 'would need a 3rd deletion -> below 3 verified -> nothing'
    assert backup_job.plan_space(items, 0) == []


def test_plan_space_with_fewer_than_three_verified_deletes_none_of_them():
    items = _items3([(10, True, False), (10, True, False), (50, False, False)])
    assert [d['name'] for d in backup_job.plan_space(items, 40)] == ['b02'], 'unverified legacy may go'
    assert backup_job.plan_space(items, 60) is None, 'the 2 verified ones are all kept -> stop, delete nothing'
    deleted, over = backup_job.plan_prune(_items3([(10, True, False), (10, True, False)]), keep=14, budget_bytes=5)
    assert deleted == [] and over


def test_warnings_corrupt_and_space_freed():
    ok = {'last_success_utc': (NOW - timedelta(hours=1)).isoformat()}
    warnings = backup_job.evaluate({**ok, 'corrupt': ['minhduc-x.mdbackup']}, None, NOW)
    assert len(warnings) == 1 and 'HỎNG' in warnings[0] and 'SHA-256' in warnings[0]
    warnings = backup_job.evaluate({**ok, 'freed_for_space': ['a', 'b']}, None, NOW)
    assert len(warnings) == 1 and 'gần đầy' in warnings[0] and '2 bản' in warnings[0]
    warnings = backup_job.evaluate({**ok, 'over_budget': True}, None, NOW)
    assert 'ít hơn thì giữ tất cả' in warnings[0]


def test_health_backup_row_explains_reason_and_action():
    def row(state):
        facts = {**_good_facts(), 'backup_state': {'last_success_utc': NOW.isoformat(), **state}}
        return [r for r in install_health.evaluate(facts, NOW) if r['muc'].startswith('Sao lưu:')][0]
    fresh = row({'verified_count': 1})
    assert not fresh['dat'] and 'mới có 1 bản đã kiểm, cần ít nhất 3' in fresh['chi_tiet'] and '20:00' in fresh['chi_tiet']
    over = row({'verified_count': 6, 'over_budget': True})
    assert not over['dat'] and 'ngân sách' in over['chi_tiet'] and 'báo người hỗ trợ' in over['chi_tiet']
    assert row({'verified_count': 3})['dat']


# ---------- Phản biện PR 8: chứng chỉ thiếu/hỏng -> chế độ phục hồi từ ca.key ----------

def test_status_reports_damaged_certificate_or_key_as_recoverable(tmp_path):
    from scripts import install_cert
    tls, ca_key = tmp_path / 'tls', tmp_path / 'quantri' / 'ca.key'
    install_cert.create('192.168.1.10', tls, ca_key)
    ok = install_cert.status(tls / 'server.crt', '192.168.1.10', 30, tls / 'server.key')
    assert ok['code'] == 'ok'
    (tls / 'server.key').write_text('hong')
    assert install_cert.status(tls / 'server.crt', '192.168.1.10', 30, tls / 'server.key')['code'] == 'hong'
    (tls / 'server.crt').write_text('-----BEGIN CERTIFICATE-----\nhong\n-----END CERTIFICATE-----\n')
    assert install_cert.status(tls / 'server.crt', '192.168.1.10', 30)['code'] == 'hong'
    (tls / 'server.crt').unlink()
    assert install_cert.status(tls / 'server.crt', '192.168.1.10', 30)['code'] == 'missing'


def _recover(tmp_path, damage):
    import ssl
    from scripts import install_cert
    tls, ca_key = tmp_path / 'tls', tmp_path / 'quantri' / 'ca.key'
    install_cert.create('192.168.1.10', tls, ca_key)
    ca_before = (tls / 'ca.crt').read_bytes()
    damage(tls)
    stamp = '20261109000009'
    result = install_cert.prepare(tls, ca_key, stamp, ip='192.168.1.10')
    install_cert.verify_pair(tls, stamp)
    install_cert.commit(tls, stamp)
    assert (tls / 'ca.crt').read_bytes() == ca_before, 'CA unchanged: workstations need nothing'
    assert install_cert.status(tls / 'server.crt', '192.168.1.10', 300, tls / 'server.key')['code'] == 'ok'
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(tls / 'server.crt'), str(tls / 'server.key'))
    new = _x509(tls / 'server.crt')
    _x509(tls / 'ca.crt').public_key().verify(new.signature, new.tbs_certificate_bytes,
        __import__('cryptography.hazmat.primitives.asymmetric.padding', fromlist=['PKCS1v15']).PKCS1v15(),
        new.signature_hash_algorithm)
    return install_cert, tls, stamp, result


def test_recovery_when_certificate_missing_issues_from_existing_ca_key(tmp_path):
    def damage(tls):
        (tls / 'server.crt').unlink(); (tls / 'server.key').unlink()
    install_cert, tls, stamp, _ = _recover(tmp_path, damage)
    # Rollback of a recovery returns to "missing" (exact previous state), new pair kept as *.loi-.
    result = install_cert.rollback(tls, stamp)
    assert sorted(result['absent_before']) == ['server.crt', 'server.key']
    assert not (tls / 'server.crt').exists() and (tls / f'server.crt.loi-{stamp}').exists()


def test_recovery_when_certificate_damaged_never_reads_old_one(tmp_path):
    def damage(tls):
        (tls / 'server.crt').write_text('rac')
    install_cert, tls, stamp, _ = _recover(tmp_path, damage)
    assert (tls / f'server.crt.cu-{stamp}').read_text() == 'rac', 'damaged file kept for investigation'
    install_cert.rollback(tls, stamp)
    assert (tls / 'server.crt').read_text() == 'rac'


def test_recovery_without_ca_key_fails_cleanly(tmp_path):
    from scripts import install_cert
    tls, ca_key = tmp_path / 'tls', tmp_path / 'quantri' / 'ca.key'
    install_cert.create('192.168.1.10', tls, ca_key)
    (tls / 'server.crt').unlink()
    ca_key.unlink()
    with pytest.raises(OSError):
        install_cert.prepare(tls, ca_key, '20261109000010', ip='192.168.1.10')
    assert not list(tls.glob('*.moi-*'))


def test_gia_han_bat_prints_message_by_exit_code_without_unverified_claims():
    bat = (WIN / 'GIA_HAN_CHUNG_CHI.bat').read_text(encoding='ascii')
    assert '"%RC%"=="0"' in bat and '"%RC%"=="50"' in bat and '"%RC%"=="51"' in bat
    m50 = bat[bat.index('"%RC%"=="50"'):bat.index('"%RC%"=="51"')]
    assert 'DA TRA CHUNG CHI CU' in m50 and 'HTTPS da kiem lai: DAT' in m50
    m51 = bat[bat.index('"%RC%"=="51"'):]
    assert 'CO THE KHONG TRUY CAP DUOC' in m51 and 'GOI NGUOI HO TRO NGAY' in m51
    assert 'chung chi cu da duoc tra lai' not in bat, 'old blanket claim removed'
    ps = (WIN / 'GiaHanChungChi.ps1').read_text(encoding='utf-8-sig')
    assert 'bình thường' not in ps and 'vẫn tin cậy' not in ps, 'no claim beyond what was checked'
    assert 'CÓ THỂ KHÔNG TRUY CẬP ĐƯỢC' in ps and 'GỌI NGƯỜI HỖ TRỢ NGAY' in ps


def test_gia_han_recovery_mode_and_lost_ca_key_message():
    ps = (WIN / 'GiaHanChungChi.ps1').read_text(encoding='utf-8-sig')
    assert "$recovery = $state.code -in @('missing', 'hong')" in ps
    assert "if ($recovery) { $prepareArgs += @('--ip', $ip) }" in ps
    lost = ps[ps.index('if ($recovery) {\n            Stop-CaiDat'):]
    assert 'CÀI LẠI CA (CAI_MAY_TRAM.bat) cho MỌI máy trạm' in lost[:800]
    # The certificate itself is no longer required to exist before starting (recovery).
    assert "-not (Test-Path -LiteralPath $cert)" not in ps


def test_certificate_warnings_point_to_recovery_procedure():
    ok = {'last_success_utc': (NOW - timedelta(hours=1)).isoformat()}
    warning = backup_job.evaluate({**ok, 'cert_unreadable': True}, None, NOW)[0]
    assert 'GIA_HAN_CHUNG_CHI.bat' in warning and 'phục hồi' in warning and 'mọi máy trạm' in warning
    facts = {**_good_facts(), 'cert_not_after': None}
    row = [r for r in install_health.evaluate(facts, NOW) if r['muc'].startswith('Chứng chỉ')][0]
    assert not row['dat'] and 'GIA_HAN_CHUNG_CHI.bat' in row['chi_tiet'] and 'tự phục hồi' in row['chi_tiet']


# ---------- Phản biện PR 8: CAI_MAY_TRAM mã thoát certutil/cscript, kiểm .lnk, kiểm tay trên Windows 7 ----------

def test_workstation_bat_treats_every_nonzero_certutil_cscript_code_as_error():
    lines = (WIN / 'CAI_MAY_TRAM.bat').read_text(encoding='ascii').splitlines()
    tool_lines = [i for i, line in enumerate(lines)
                  if re.match(r'\s*(certutil|cscript)\b', line, re.I)]
    assert len(tool_lines) >= 6, tool_lines  # dump, decode, hashfile, addstore, elevate, shortcut
    for i in tool_lines:
        following = lines[i + 1].strip()
        assert re.match(r'(if %errorlevel% neq 0 \(|set "VBRC=%errorlevel%")', following, re.I), (lines[i], following)
    bat = '\n'.join(lines)
    # 'if errorlevel 1' misses negative HRESULT codes of certutil: never used right after certutil/cscript.
    assert 'for /f "skip=1 delims=" %%h in (\'certutil' not in bat, 'exit code of certutil inside for /f is lost'
    assert 'if not "%VBRC%"=="0"' in bat


def test_workstation_bat_checks_shortcut_file_and_manual_check_without_curl():
    bat = (WIN / 'CAI_MAY_TRAM.bat').read_text(encoding='ascii')
    assert 'if not exist "%PUBLIC%\\Desktop\\Ph*ng kh*m Minh *.lnk"' in bat
    vbs = (WIN / 'MayTram.vbs').read_text(encoding='ascii')
    assert 'If Not fso.FileExists(finalPath) Then' in vbs
    no_curl = bat[bat.index('where curl.exe'):bat.index('set "HTTP="')]
    assert '[CAN KIEM TAY]' in no_curl and '[DAT]' not in no_curl
    assert 'KHONG co canh bao chung chi' in no_curl and 'trang dang nhap' in no_curl
    assert 'CON MOT VIEC: kiem tay' in bat


def test_docs_no_self_disable_smart_app_control_and_new_acceptance_items():
    doc = (ROOT / 'docs' / 'CAI_DAT_TUNG_BUOC.md').read_text(encoding='utf-8')
    assert 'Smart App Control settings → Off' not in doc and 'chọn Off' not in doc
    assert 'không tự tắt Smart App Control' in doc and 'gọi người hỗ trợ' in doc
    for path in WIN.glob('*.ps*1'):
        text = path.read_text(encoding='utf-8-sig')
        assert 'chọn Off' not in text and 'Nên tắt Smart App Control' not in text, path.name
    checklist = doc[doc.index('## 9. Danh sách nghiệm thu'):]
    assert 'Windows 7 + Chrome 109' in checklist and 'không có cảnh báo chứng chỉ' in checklist
    assert 'gõ mật khẩu có dấu' in checklist
    assert 'thời gian một lần sao lưu' in checklist and 'độ trễ thao tác khám' in checklist


def test_collect_reports_ui_settings_state(tmp_path):
    env = {'CLINIC_DATA_DIR': str(tmp_path), 'CLINIC_DATABASE_URL': 'postgresql://u:p@127.0.0.1:1/x',
           'CLINIC_ORIGIN': 'https://127.0.0.1:1', 'CLINIC_UPLOAD_DIR': str(tmp_path / 'attachments')}
    target = tmp_path / 'caidat' / 'ui_settings.json'
    assert install_health.collect(env, timeout=1)['ui_settings'] == 'missing'
    target.parent.mkdir()
    target.write_text('{hỏng', encoding='utf-8')
    assert install_health.collect(env, timeout=1)['ui_settings'] == 'invalid'
    target.write_text('{"advance_payment": false, "addendum": true, "controlled_drugs": true}', encoding='utf-8')
    assert install_health.collect(env, timeout=1)['ui_settings'] == 'file'


def test_workstation_shortcut_overwrites_with_checked_bounded_retries():
    text = (WIN / 'MayTram.vbs').read_text(encoding='ascii')
    body = text[text.index('Function MakeShortcut'):]
    assert 'fso.MoveFile' not in body
    assert 'fso.DeleteFile finalPath' not in body
    assert body.index('fso.DeleteFile tmpPath, True') < body.index('shell.CreateShortcut(tmpPath)')
    lines = [line.strip() for line in body.splitlines()]
    for i, line in enumerate(lines):
        if line == 'sc.Save' or line.startswith(('fso.CopyFile ', 'fso.DeleteFile ')):
            assert lines[i - 1] == 'Err.Clear'
            assert lines[i + 1].startswith('If Err.Number ')
    retry = body[body.index('For attempt = 1 To 3'):body.index('    Next')]
    assert 'fso.CopyFile tmpPath, finalPath, True' in retry
    assert 'If Err.Number = 0 Then Exit For' in retry
    assert 'If attempt = 3 Then' in retry
    assert retry.index('Exit Function') < retry.index('WScript.Sleep 1000')
    assert 'MakeShortcut = 4' in retry
    assert '"LOI tao bieu tuong: " & Err.Description' in retry
