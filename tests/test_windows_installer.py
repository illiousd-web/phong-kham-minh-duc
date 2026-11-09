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
    assert c['CLINIC_BACKUP_KEEP'] == '30' and c['CLINIC_WORKERS'] == '1' and c['CLINIC_POOL_MAX'] == '4'
    assert app_pw not in json.dumps(report) and owner_pw not in json.dumps(report)
    # owner.env is a full LAN config (migration imports app.config) with the owner URL.
    assert o['CLINIC_ORIGIN'] == c['CLINIC_ORIGIN'] and o['CLINIC_DATABASE_URL'].startswith('postgresql://clinic_owner:')


def test_second_run_never_changes_existing_passwords_or_values(tmp_path):
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg/bin')
    first_c, first_o = clinic.read_text(), owner.read_text()
    # Administrator tuned a value; a re-run must keep it.
    clinic.write_text(first_c.replace('CLINIC_BACKUP_KEEP=30', 'CLINIC_BACKUP_KEEP=20'))
    report = install_env.write_configs(clinic, owner, '192.168.1.10', 24, '/data', '/pg/bin')
    assert report['new_password_roles'] == [] and not report['clinic_env_created']
    c = install_env.read_env(clinic)
    assert c['CLINIC_BACKUP_KEEP'] == '20'
    assert c['CLINIC_DATABASE_URL'] == install_env.read_env(tmp_path / 'clinic.env')['CLINIC_DATABASE_URL']
    assert install_env.read_env(owner)['CLINIC_DATABASE_URL'] in first_o


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
        'backup_state': {'last_success_utc': (NOW - timedelta(hours=2)).isoformat()}, 'backup_count': 1,
        'disk_free_gib': 120.5, 'memory': {'total_mib': 7900, 'available_mib': 3000},
        'pagefile': {'auto': True, 'detail': 'Windows tự quản lý'}, 'env_acl_ok': True, 'env_acl_detail': 'ok',
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
    ({'firewall': {'exists': True, 'enabled': True, 'scoped': False}}, 'Tường lửa'),
    ({'backup_task': {}}, 'Lịch sao lưu'),
    ({'backup_state': {'last_success_utc': (NOW - timedelta(hours=50)).isoformat()}}, 'Bản sao lưu'),
    ({'backup_state': {}, 'backup_newest_utc': None}, 'Bản sao lưu'),
    ({'disk_free_gib': 12}, 'Ổ dữ liệu'),
    ({'memory': {'total_mib': 4096, 'available_mib': 2000}}, 'RAM'),
    ({'pagefile': {'auto': False, 'detail': 'Cố định 512 MB'}}, 'page file'),
    ({'env_acl_ok': False}, 'Tệp cấu hình'),
    ({'external_declared': True, 'backup_state': {'last_success_utc': NOW.isoformat(),
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
    for name in ('CAI_DAT.bat', 'CAI_MAY_TRAM.bat', 'CAP_NHAT.bat', 'KIEM_TRA.bat'):
        text = (WIN / name).read_text()
        assert 'RunAs' in text and '-ExecutionPolicy Bypass' in text


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
