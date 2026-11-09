"""Windows installer helper for PostgreSQL roles, database, grants and rollback.

Connection URLs are read from ACL-protected files whose PATHS are given on the
command line (clinic.env, owner.env, postgres superuser file); passwords never
appear in arguments or output.
Nothing here prints a password. Existing roles keep their passwords unless the
caller states that the configuration file was created in this run
(--allow-password-reset), i.e. no running system can be using the old one.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, urlsplit, urlunsplit, unquote

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]


def parts(url):
    p = urlsplit(url)
    return p, unquote(p.username or ''), unquote(p.password or ''), unquote(p.path.lstrip('/'))


def with_db(url, name):
    p = urlsplit(url)
    return urlunsplit(p._replace(path='/' + name))


def can_login(url):
    try:
        with psycopg.connect(url, connect_timeout=5) as c:
            c.execute('SELECT 1')
        return True
    except psycopg.OperationalError:
        return False


def ensure(super_url, owner_url, app_url, allow_reset=False):
    """Create missing roles/database. Returns a JSON-able report, no secrets."""
    _, owner, owner_pw, db_name = parts(owner_url)
    _, app, app_pw, app_db = parts(app_url)
    if db_name != app_db:
        raise ValueError('Owner and runtime URLs must use the same database')
    report = {'created_roles': [], 'reset_roles': [], 'created_database': False}
    with psycopg.connect(super_url, autocommit=True, connect_timeout=10) as c:
        for role, password, flags in ((owner, owner_pw, 'LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'),
                                      (app, app_pw, 'LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT')):
            row = c.execute('SELECT rolsuper FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
            if row is None:
                c.execute(sql.SQL('CREATE ROLE {} ' + flags + ' PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
                report['created_roles'].append(role)
            elif row[0]:
                raise ValueError(f'Vai trò {role} đang là superuser; không dùng cho ứng dụng.')
        exists = c.execute('SELECT 1 FROM pg_database WHERE datname=%s', (db_name,)).fetchone()
        if not exists:
            # Explicit UTF8: a United States Windows locale would otherwise pick WIN1252
            # on some clusters and reject Vietnamese text.
            c.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(db_name), sql.Identifier(owner)))
            report['created_database'] = True
        encoding = c.execute('SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname=%s', (db_name,)).fetchone()[0]
        if encoding != 'UTF8':
            raise ValueError(f'CSDL {db_name} dùng bảng mã {encoding}, cần UTF8.')
        c.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db_name)))
        c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db_name), sql.Identifier(app)))
        for role, url, password in ((owner, owner_url, owner_pw), (app, app_url, app_pw)):
            if role in report['created_roles'] or can_login(url):
                continue
            if not allow_reset:
                raise ValueError(f'Không đăng nhập được bằng tài khoản {role} trong tệp cấu hình đang dùng. '
                                 'Không tự đổi mật khẩu; liên hệ người hỗ trợ.')
            c.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
            report['reset_roles'].append(role)
    for url in (owner_url, app_url):
        if not can_login(url):
            raise ValueError('Đã tạo tài khoản nhưng vẫn không đăng nhập được PostgreSQL.')
    return report


def grant(owner_url, app_role, db_name):
    """Apply the reviewed runtime grants (deploy/postgresql-roles.sql) as owner."""
    text = (ROOT / 'deploy' / 'postgresql-roles.sql').read_text(encoding='utf-8')
    text = text.replace('ON DATABASE minhduc', 'ON DATABASE ' + sql.Identifier(db_name).as_string(None))
    text = text.replace('clinic_app', sql.Identifier(app_role).as_string(None))
    with psycopg.connect(owner_url, autocommit=False, connect_timeout=10) as c:
        c.execute(text)


def fingerprint(url):
    """Schema fingerprint to decide whether an update touched the database."""
    with psycopg.connect(url, connect_timeout=10) as c:
        cols = c.execute("""SELECT table_name||'.'||column_name||':'||data_type||':'||is_nullable||':'||COALESCE(column_default,'')
                            FROM information_schema.columns WHERE table_schema='public' ORDER BY 1""").fetchall()
        cons = c.execute("""SELECT conrelid::regclass::text||':'||conname FROM pg_constraint c
                            JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' ORDER BY 1""").fetchall()
        idx = c.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1").fetchall()
        trg = c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1").fetchall()
        try:
            versions = c.execute('SELECT version FROM schema_migrations ORDER BY 1').fetchall()
        except psycopg.errors.UndefinedTable:
            versions = []
    digest = hashlib.sha256(json.dumps([cols, cons, idx, trg, versions], default=str).encode()).hexdigest()
    return {'sha256': digest, 'versions': [v[0] for v in versions]}


def admin_count(url):
    with psycopg.connect(url, connect_timeout=10) as c:
        try:
            return c.execute("""SELECT count(*) FROM users u JOIN user_roles r ON r.user_id=u.id
                                WHERE r.role='admin' AND u.active=1""").fetchone()[0]
        except psycopg.errors.UndefinedTable:
            return 0


def _step(name):
    """Mốc giữa các bước quay lui. Kiểm thử thay hàm này để chèn lỗi giả; chạy thật không làm gì."""


def rollback_database(super_url, owner_url, app_role, backup_file, key_file, uploads):
    """Put the database, attachments and UI settings back to a verified backup.

    The current database is RENAMED (kept for investigation), never dropped; the
    current attachment folder and ui_settings.json are renamed the same way.
    Every precondition is checked BEFORE the database is renamed. If any later
    step fails, everything is put back as it was (old database name, attachment
    folder and settings file) and the error is raised.
    """
    from scripts.backup_lan import unpack_verified, restore, SETTINGS_NAME  # needs CLINIC_* LAN config
    from app.ui_settings import settings_path
    import shutil
    import tempfile
    _, owner, _, db_name = parts(owner_url)
    uploads = Path(uploads).resolve()
    live_settings = settings_path(uploads)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    kept = f'{db_name}_loi_{stamp}'
    staged = uploads.with_name(uploads.name + f'.khoiphuc-{stamp}')
    staged_settings = live_settings.with_name(f'.ui_settings.khoiphuc-{stamp}.json')
    moved = uploads.with_name(uploads.name + f'.loi-{stamp}')
    old_settings = live_settings.with_name(f'ui_settings.loi-{stamp}.json')

    # 1. Kiểm mọi điều kiện trước khi đụng vào CSDL đang chạy.
    uploads.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.verify-', dir=uploads.parent) as temp:
        manifest = unpack_verified(Path(backup_file), key_file, Path(temp))  # giải mã + kiểm hash
    has_settings = SETTINGS_NAME in manifest['files']
    for path in (staged, staged_settings, moved, old_settings):
        if path.exists():
            raise ValueError(f'Đường dẫn tạm đã có sẵn, không ghi đè: {path.name}')
    for folder in {uploads.parent, live_settings.parent}:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.ghi-thu-') as probe:
            probe.write(b'ok')
            probe.flush()
    with psycopg.connect(super_url, autocommit=True, connect_timeout=10) as c:
        if not c.execute('SELECT 1 FROM pg_database WHERE datname=%s', (db_name,)).fetchone():
            raise ValueError(f'Không thấy CSDL {db_name}')
        if c.execute('SELECT 1 FROM pg_database WHERE datname=%s', (kept,)).fetchone():
            raise ValueError(f'CSDL {kept} đã có sẵn, không ghi đè')

    done = set()
    try:
        _step('rename')
        with psycopg.connect(super_url, autocommit=True, connect_timeout=10) as c:
            c.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()', (db_name,))
            c.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(sql.Identifier(db_name), sql.Identifier(kept)))
            done.add('renamed')
            _step('create')
            c.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(db_name), sql.Identifier(owner)))
            c.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db_name)))
            c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db_name), sql.Identifier(app_role)))
        _step('restore')
        # Cài đặt được khôi phục vào chỗ tạm, chưa đụng tệp đang dùng.
        restore(Path(backup_file), key_file, owner_url, staged, settings=staged_settings)
        _step('attachments')
        if uploads.exists():
            os.replace(uploads, moved)
            done.add('attachments_moved')
        os.replace(staged, uploads)
        done.add('attachments_swapped')
        _step('settings')
        if has_settings and staged_settings.exists():
            if live_settings.exists():
                os.replace(live_settings, old_settings)
                done.add('settings_moved')
            os.replace(staged_settings, live_settings)
            done.add('settings_swapped')
        _step('grant')
        grant(owner_url, app_role, db_name)
    except BaseException as error:
        problems = _undo_rollback(super_url, db_name, kept, done, uploads, staged, moved,
                                  live_settings, staged_settings, old_settings, shutil)
        if problems:
            raise RuntimeError('Quay lui lỗi và hoàn tác KHÔNG trọn vẹn: ' + '; '.join(problems)) from error
        raise
    return {'kept_database': kept,
            'kept_attachments': str(moved) if 'attachments_moved' in done else None,
            'settings': 'restored' if 'settings_swapped' in done else 'kept',
            'kept_settings': str(old_settings) if 'settings_moved' in done else None}


def _undo_rollback(super_url, db_name, kept, done, uploads, staged, moved, live_settings, staged_settings, old_settings, shutil):
    """Đưa mọi thứ về như trước khi quay lui. Trả danh sách lỗi (rỗng nếu hoàn tác trọn vẹn)."""
    problems = []

    def attempt(label, action):
        try:
            action()
        except Exception as error:  # noqa: BLE001 - gom lỗi để báo đủ, không bỏ dở hoàn tác
            problems.append(f'{label}: {type(error).__name__}')

    if 'settings_swapped' in done:
        attempt('bỏ cài đặt vừa khôi phục', lambda: os.replace(live_settings, staged_settings))
    if 'settings_moved' in done:
        attempt('trả cài đặt cũ', lambda: os.replace(old_settings, live_settings))
    if 'attachments_swapped' in done:
        attempt('bỏ thư mục đính kèm vừa khôi phục', lambda: os.replace(uploads, staged))
    if 'attachments_moved' in done:
        attempt('trả thư mục đính kèm cũ', lambda: os.replace(moved, uploads))
    attempt('dọn tệp tạm', lambda: staged_settings.unlink(missing_ok=True))
    if staged.exists():
        attempt('dọn thư mục tạm', lambda: shutil.rmtree(staged))
    if 'renamed' in done:
        def database_back():
            with psycopg.connect(super_url, autocommit=True, connect_timeout=10) as c:
                # Chỉ xóa CSDL MỚI tạo trong lần quay lui này; CSDL cũ đang mang tên kept.
                if c.execute('SELECT 1 FROM pg_database WHERE datname=%s', (db_name,)).fetchone():
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(db_name)))
                c.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(sql.Identifier(kept), sql.Identifier(db_name)))
        attempt('đổi tên CSDL cũ về', database_back)
    return problems


def load(args):
    """Read ACL-protected env files given by path; nothing secret on the command line."""
    from scripts.install_env import read_env
    clinic = read_env(args.clinic_env)
    if not clinic.get('CLINIC_DATABASE_URL'):
        raise ValueError('Thiếu tệp cấu hình clinic.env')
    os.environ.update(clinic)  # LAN config for app imports (rollback/restore)
    urls = {'app': clinic['CLINIC_DATABASE_URL'], 'uploads': clinic.get('CLINIC_UPLOAD_DIR', '')}
    if args.owner_env:
        urls['owner'] = read_env(args.owner_env)['CLINIC_DATABASE_URL']
    if args.super_env:
        values = read_env(args.super_env)
        password = values.get('MINHDUC_PG_SUPER_PASSWORD')
        if not password:
            raise ValueError('Thiếu mật khẩu siêu quản trị PostgreSQL')
        user = values.get('MINHDUC_PG_SUPER_USER', 'postgres')
        p = urlsplit(urls['app'])
        urls['super'] = urlunsplit(p._replace(netloc=f'{quote(user, safe="")}:{quote(password, safe="")}@{p.hostname}:{p.port or 5432}',
                                              path='/postgres'))
    return urls


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clinic-env', required=True)
    parser.add_argument('--owner-env')
    parser.add_argument('--super-env')
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('ensure'); e.add_argument('--allow-password-reset', action='store_true')
    sub.add_parser('grant')
    sub.add_parser('fingerprint')
    sub.add_parser('admin-count')
    r = sub.add_parser('rollback')
    r.add_argument('--file', required=True); r.add_argument('--key', required=True)
    args = parser.parse_args(argv)
    try:
        urls = load(args)
        _, app, _, db_name = parts(urls['app'])
        if args.command == 'ensure':
            result = ensure(urls['super'], urls['owner'], urls['app'], args.allow_password_reset)
        elif args.command == 'grant':
            grant(urls['owner'], app, db_name)
            # Post-migration step run by every CAI_DAT and CAP_NHAT version with the NEW
            # code: bring installer-managed policy (backup retention) up to date.
            from scripts.install_env import apply_managed
            changed = sorted(set(apply_managed(args.clinic_env)) | set(apply_managed(args.owner_env) if args.owner_env else set()))
            # Tệp cài đặt giao diện mặc định cho máy mới (không sửa tệp đã có).
            from app.ui_settings import settings_path, ensure_default_settings
            uploads = Path(urls['uploads']) if urls['uploads'] else Path(os.environ.get('CLINIC_DATA_DIR', '.')) / 'attachments'
            result = {'granted': True, 'managed_changed': changed, 'ui_settings': ensure_default_settings(settings_path(uploads))}
        elif args.command == 'fingerprint':
            result = fingerprint(urls['owner'])
        elif args.command == 'admin-count':
            result = {'admins': admin_count(urls['app'])}
        else:
            result = rollback_database(urls['super'], urls['owner'], app, args.file, args.key, urls['uploads'])
    except (ValueError, psycopg.Error, KeyError, OSError, RuntimeError) as error:
        # psycopg messages never contain the password; keep them to one line.
        message = str(error).splitlines()[0] if str(error) else ''
        print(f'LOI: {type(error).__name__}: {message}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
