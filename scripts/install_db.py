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


def rollback_database(super_url, owner_url, app_role, backup_file, key_file, uploads):
    """Put the database and attachments back to a verified backup.

    The current database is RENAMED (kept for investigation), never dropped; the
    current attachment folder is renamed the same way.
    """
    from scripts.backup_lan import unpack_verified, restore  # needs CLINIC_* LAN config
    import tempfile
    _, owner, _, db_name = parts(owner_url)
    uploads = Path(uploads)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    # Fail before touching anything if the backup cannot be authenticated.
    with tempfile.TemporaryDirectory(prefix='.verify-', dir=uploads.parent) as temp:
        unpack_verified(Path(backup_file), key_file, Path(temp))
    kept = f'{db_name}_loi_{stamp}'
    with psycopg.connect(super_url, autocommit=True, connect_timeout=10) as c:
        c.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()', (db_name,))
        c.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(sql.Identifier(db_name), sql.Identifier(kept)))
        c.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
            sql.Identifier(db_name), sql.Identifier(owner)))
        c.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db_name)))
        c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db_name), sql.Identifier(app_role)))
    staged = uploads.with_name(uploads.name + f'.khoiphuc-{stamp}')
    restore(Path(backup_file), key_file, owner_url, staged)
    moved = None
    if uploads.exists():
        moved = uploads.with_name(uploads.name + f'.loi-{stamp}')
        os.replace(uploads, moved)
    os.replace(staged, uploads)
    grant(owner_url, app_role, db_name)
    return {'kept_database': kept, 'kept_attachments': str(moved) if moved else None}


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
            result = {'granted': True}
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
