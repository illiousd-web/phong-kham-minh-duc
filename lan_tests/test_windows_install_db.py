"""Installer database helpers against a real disposable PostgreSQL server.

Covers: role/database creation, idempotent re-run without password change,
refusal to rotate passwords in use, grants, admin detection, the nightly job
(backup + verify + external copy) and the update rollback (restore).
"""
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
import pytest

from lan_tests.conftest import SOURCE
from scripts import install_db, install_env, backup_job

def _server_uses_trust():
    """True when the test server accepts a wrong password (pg_hba 'trust')."""
    p = urlsplit(SOURCE)
    wrong = urlunsplit(p._replace(netloc=f'{p.username}:sai-{secrets.token_hex(8)}@{p.hostname}:{p.port or 5432}'))
    try:
        with psycopg.connect(wrong, connect_timeout=5):
            return True
    except psycopg.OperationalError:
        return False


if _server_uses_trust():
    pytest.skip('PostgreSQL kiểm thử đang dùng chế độ trust (chấp nhận mọi mật khẩu): không kiểm được '
                'việc từ chối mật khẩu sai của bộ cài. Dùng máy chủ kiểm thử xác thực scram-sha-256.',
                allow_module_level=True)

SUFFIX = secrets.token_hex(4)
DB = f'minhduc_inst_{SUFFIX}'
OWNER = f'inst_owner_{SUFFIX}'
APP = f'inst_app_{SUFFIX}'


def url(role, password, db):
    p = urlsplit(SOURCE)
    return urlunsplit(p._replace(netloc=f'{role}:{password}@{p.hostname}:{p.port or 5432}', path='/' + db))


@pytest.fixture(scope='module')
def creds():
    data = {'owner': secrets.token_urlsafe(32), 'app': secrets.token_urlsafe(32)}
    yield data
    with psycopg.connect(SOURCE, autocommit=True) as c:
        for row in c.execute("SELECT datname FROM pg_database WHERE datname LIKE %s", (DB + '%',)).fetchall():
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(row[0])))
        for role in (APP, OWNER):
            c.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))


def owner_url(creds):
    return url(OWNER, creds['owner'], DB)


def app_url(creds):
    return url(APP, creds['app'], DB)


def test_ensure_creates_least_privilege_roles_and_utf8_database(creds):
    report = install_db.ensure(SOURCE, owner_url(creds), app_url(creds))
    assert sorted(report['created_roles']) == sorted([OWNER, APP]) and report['created_database']
    with psycopg.connect(SOURCE) as c:
        for role in (OWNER, APP):
            flags = c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
            assert flags == (False, False, False, False)
        enc, owner = c.execute('SELECT pg_encoding_to_char(encoding), pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (DB,)).fetchone()
        assert enc == 'UTF8' and owner == OWNER


def test_rerun_is_noop_and_keeps_passwords(creds):
    report = install_db.ensure(SOURCE, owner_url(creds), app_url(creds))
    assert report == {'created_roles': [], 'reset_roles': [], 'created_database': False}


def test_password_in_use_is_never_rotated_without_permission(creds):
    wrong = url(APP, 'not-the-password-' + secrets.token_hex(8), DB)
    with pytest.raises(ValueError, match='Không tự đổi mật khẩu'):
        install_db.ensure(SOURCE, owner_url(creds), wrong)
    assert install_db.can_login(app_url(creds))


def test_reset_only_when_config_was_just_created(creds):
    new = secrets.token_urlsafe(32)
    report = install_db.ensure(SOURCE, owner_url(creds), url(APP, new, DB), allow_reset=True)
    assert report['reset_roles'] == [APP]
    creds['app'] = new
    assert install_db.can_login(app_url(creds))


def _lan_env(tmp, creds):
    env = {'CLINIC_MODE': 'lan', 'CLINIC_DATABASE_URL': app_url(creds), 'CLINIC_DATA_DIR': str(tmp),
           'CLINIC_UPLOAD_DIR': str(tmp / 'attachments'), 'CLINIC_ORIGIN': 'https://127.0.0.1:58443',
           'CLINIC_ALLOWED_CIDRS': '192.168.10.0/24,127.0.0.1/32', 'CLINIC_BIND_IP': '127.0.0.1'}
    return env


def test_migrate_grant_and_admin_detection(creds, tmp_path, monkeypatch):
    import subprocess, sys
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, **_lan_env(tmp_path, creds), 'CLINIC_DATABASE_URL': owner_url(creds)}
    result = subprocess.run([sys.executable, '-m', 'scripts.manage', 'migrate'], cwd=root, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    install_db.grant(owner_url(creds), APP, DB)
    assert install_db.admin_count(app_url(creds)) == 0
    with psycopg.connect(app_url(creds)) as c:
        assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] >= 3
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute('DELETE FROM audit_log')
    env = {**os.environ, **_lan_env(tmp_path, creds), 'MINHDUC_TEST_ADMIN_PW': secrets.token_urlsafe(18)}
    result = subprocess.run([sys.executable, '-m', 'scripts.manage', 'create-admin', '--username', 'quantri.test',
                             '--name', 'Quản trị kiểm thử', '--password-env', 'MINHDUC_TEST_ADMIN_PW'],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert env['MINHDUC_TEST_ADMIN_PW'] not in result.stdout + result.stderr
    assert install_db.admin_count(app_url(creds)) == 1
    before = install_db.fingerprint(owner_url(creds))
    subprocess.run([sys.executable, '-m', 'scripts.manage', 'migrate'], cwd=root, check=True, capture_output=True,
                   env={**os.environ, **_lan_env(tmp_path, creds), 'CLINIC_DATABASE_URL': owner_url(creds)})
    assert install_db.fingerprint(owner_url(creds)) == before, 'Re-running migration must not change the schema'


def test_cli_reads_secrets_from_files_only(creds, tmp_path):
    clinic, owner, sup = tmp_path / 'clinic.env', tmp_path / 'owner.env', tmp_path / 'postgres.env'
    env = _lan_env(tmp_path, creds)
    install_env.write_env(clinic, env, ['test'])
    install_env.write_env(owner, {**env, 'CLINIC_DATABASE_URL': owner_url(creds)}, ['test'])
    assert install_db.main(['--clinic-env', str(clinic), '--owner-env', str(owner), 'fingerprint']) == 0
    assert install_db.main(['--clinic-env', str(clinic), 'admin-count']) == 0
    install_env.write_env(sup, {'MINHDUC_PG_SUPER_PASSWORD': 'wrong-' + secrets.token_hex(6)}, ['test'])
    # Wrong superuser password: clean error, exit 2, no traceback/secret.
    assert install_db.main(['--clinic-env', str(clinic), '--owner-env', str(owner), '--super-env', str(sup), 'ensure']) == 2


JOB = """import json,sys
from pathlib import Path
import scripts.backup_job as b
marker=Path(sys.argv[1])
b.find_external=(lambda roots,ident,data: marker if ident=='usb-1' and marker.exists() else None)
sys.exit(b.main(sys.argv[2:]))
"""


def run_job(env, marker, args):
    import subprocess, sys
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', JOB, str(marker), *args], cwd=root, env=env,
                            capture_output=True, text=True)
    return result


def test_grant_cli_moves_old_install_to_7_local_30_external(creds, tmp_path):
    clinic, owner = tmp_path / 'clinic.env', tmp_path / 'owner.env'
    env = {**_lan_env(tmp_path, creds), 'CLINIC_BACKUP_KEEP': '30', 'CLINIC_OFFSITE_KEEP': '30'}
    install_env.write_env(clinic, env, ['test'])
    install_env.write_env(owner, {**env, 'CLINIC_DATABASE_URL': owner_url(creds)}, ['test'])
    saved = dict(os.environ)
    try:
        assert install_db.main(['--clinic-env', str(clinic), '--owner-env', str(owner), 'grant']) == 0
    finally:
        os.environ.clear(); os.environ.update(saved)
    for path, url in ((clinic, app_url(creds)), (owner, owner_url(creds))):
        values = install_env.read_env(path)
        assert values['CLINIC_BACKUP_KEEP'] == '7' and values['CLINIC_OFFSITE_KEEP'] == '30'
        assert values['CLINIC_DATABASE_URL'] == url, 'passwords must be kept'
    assert install_db.can_login(app_url(creds))


def test_nightly_job_backup_verify_external_copy_and_rollback(creds, tmp_path):
    env = {**os.environ, **_lan_env(tmp_path, creds), 'CLINIC_MIN_FREE_MB': '256', 'CLINIC_BACKUP_KEEP': '30'}
    key = tmp_path / 'backup.key'
    key.write_bytes(secrets.token_bytes(32))
    (tmp_path / 'attachments').mkdir()
    (tmp_path / 'attachments' / 'ket-qua-gia-lap.pdf').write_bytes(b'%PDF-1.4 synthetic')
    with psycopg.connect(owner_url(creds)) as c:
        c.execute("INSERT INTO service_catalog(name,price) VALUES('Dịch vụ trước cập nhật',100000)")
    usb = tmp_path / 'usb'
    marker = usb / backup_job.MARKER_DIR
    marker.mkdir(parents=True)
    (marker / backup_job.MARKER_FILE).write_text(json.dumps({'id': 'usb-1'}))
    config = tmp_path / 'external.json'
    config.write_text(json.dumps({'id': 'usb-1', 'label': 'USB thử', 'declared_at': '2026-11-01T00:00:00+00:00'}))
    state = tmp_path / 'backup-status.json'
    alert = tmp_path / 'alert.txt'
    args = ['--key', str(key), '--directory', str(tmp_path / 'backups'), '--state', str(state),
            '--external-config', str(config), '--alert-file', str(alert)]
    result = run_job(env, marker, args)
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads(state.read_text(encoding='utf-8'))
    assert saved['last_success_utc'] and saved['external_present'] and saved['warnings'] == []
    assert len(list(marker.glob('minhduc-*.mdbackup'))) == 1 and not alert.exists()
    assert not [p for p in marker.iterdir() if p.suffix == '.key'], 'Key must never be copied to the external drive'
    # Drive unplugged: local backup still verified; warning only after 3 days.
    result = run_job(env, tmp_path / 'unplugged', args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state.read_text(encoding='utf-8'))['external_present'] is False
    assert len(list((tmp_path / 'backups').glob('minhduc-*.mdbackup'))) == 2
    # Broken key: job reports failure (exit 1) and writes the alert; old backups stay.
    bad = tmp_path / 'bad.key'
    bad.write_bytes(b'short')
    result = run_job(env, marker, [*args[:1], str(bad), *args[2:]])
    assert result.returncode == 1 and alert.exists()
    assert 'THẤT BẠI' in alert.read_text(encoding='utf-8-sig')
    assert len(list((tmp_path / 'backups').glob('minhduc-*.mdbackup'))) == 2
    backup_file = sorted((tmp_path / 'backups').glob('minhduc-*.mdbackup'))[0]
    # Simulate a failed update that changed data/schema, then roll back via the CLI.
    with psycopg.connect(owner_url(creds)) as c:
        c.execute("INSERT INTO service_catalog(name,price) VALUES('Dữ liệu sau cập nhật lỗi',1)")
        c.execute('CREATE TABLE update_probe(id int)')
    (tmp_path / 'attachments' / 'tep-moi.pdf').write_bytes(b'%PDF new')
    clinic, owner, sup = tmp_path / 'clinic.env', tmp_path / 'owner.env', tmp_path / 'postgres.env'
    lan = {k: v for k, v in env.items() if k.startswith('CLINIC_')}
    install_env.write_env(clinic, lan, ['test'])
    install_env.write_env(owner, {**lan, 'CLINIC_DATABASE_URL': owner_url(creds)}, ['test'])
    source = urlsplit(SOURCE)
    install_env.write_env(sup, {'MINHDUC_PG_SUPER_USER': source.username,
                                'MINHDUC_PG_SUPER_PASSWORD': source.password}, ['test'])
    import subprocess, sys
    result = subprocess.run([sys.executable, '-m', 'scripts.install_db', '--clinic-env', str(clinic), '--owner-env',
                             str(owner), '--super-env', str(sup), 'rollback', '--file', str(backup_file), '--key', str(key)],
                            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['kept_database'].startswith(DB + '_loi_')
    assert creds['app'] not in result.stdout + result.stderr
    with psycopg.connect(app_url(creds)) as c:
        names = [r[0] for r in c.execute('SELECT name FROM service_catalog ORDER BY id')]
        assert 'Dịch vụ trước cập nhật' in names and 'Dữ liệu sau cập nhật lỗi' not in names
        assert c.execute("SELECT to_regclass('public.update_probe')").fetchone()[0] is None
        assert install_db.admin_count(app_url(creds)) == 1
    assert sorted(p.name for p in (tmp_path / 'attachments').iterdir()) == ['ket-qua-gia-lap.pdf']
    assert (Path(report['kept_attachments']) / 'tep-moi.pdf').exists()
