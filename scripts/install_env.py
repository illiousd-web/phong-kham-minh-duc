"""Windows installer helper: create or merge protected LAN configuration files.

Standard library only: the installer calls it with the base Python before the
virtual environment exists. Existing values ALWAYS win, so running the
installer again never changes a password that is already in use. Secrets are
written to files only (ACLs are applied by the PowerShell caller) and are never
printed.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys

DB_NAME = 'minhduc'
OWNER_ROLE = 'clinic_owner'
APP_ROLE = 'clinic_app'
PORT = 8443
PRIVATE = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]


def new_password():
    """43 URL-safe characters (256 bits); no percent-encoding needed in URLs."""
    return secrets.token_urlsafe(32)


def lan_network(ip, prefix):
    """Return the clinic subnet for this server address, refusing public ranges."""
    address = ipaddress.ip_address(ip)
    if address.version != 4 or not any(address in n for n in PRIVATE):
        raise ValueError('Địa chỉ IP của máy chủ phải là IP nội bộ (10.x, 172.16-31.x hoặc 192.168.x).')
    prefix = int(prefix)
    if not 16 <= prefix <= 30:
        raise ValueError('Dải mạng LAN phải có độ dài tiền tố từ /16 đến /30.')
    network = ipaddress.ip_network(f'{ip}/{prefix}', strict=False)
    if address in (network.network_address, network.broadcast_address):
        raise ValueError('Địa chỉ IP không hợp lệ cho máy chủ.')
    return str(network)


def read_env(path):
    values = {}
    path = Path(path)
    if not path.exists():
        return values
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Dòng cấu hình không hợp lệ trong {path.name}')
        key, value = line.split('=', 1)
        values[key] = value
    return values


def write_env(path, values, header):
    """Write atomically; the caller restricts the ACL immediately afterwards."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = '\n'.join([f'# {line}' for line in header] + [f'{k}={v}' for k, v in values.items()]) + '\n'
    pending = path.with_name('.' + path.name + '.tmp')
    with open(pending, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, path)


def password_from_url(url, role):
    prefix = f'postgresql://{role}:'
    if url and url.startswith(prefix) and '@' in url:
        return url[len(prefix):url.index('@', len(prefix))]
    return None


def desired(ip, cidr, data_dir, pg_bin, app_password):
    data = data_dir.rstrip('\\/')
    sep = '\\' if '\\' in data or ':' in data[:3] else '/'
    join = lambda *parts: sep.join([data, *parts])
    pg_root = pg_bin.rstrip('\\/')
    pg_root = pg_root[:-4] if pg_root.lower().endswith(sep + 'bin') else pg_root
    return {
        'CLINIC_MODE': 'lan',
        'CLINIC_DATABASE_URL': f'postgresql://{APP_ROLE}:{app_password}@127.0.0.1:5432/{DB_NAME}',
        'CLINIC_DATA_DIR': data,
        'CLINIC_UPLOAD_DIR': join('attachments'),
        'CLINIC_BACKUP_DIR': join('backups'),
        'CLINIC_ORIGIN': f'https://{ip}:{PORT}',
        'CLINIC_BIND_IP': ip,
        'CLINIC_ALLOWED_CIDRS': cidr,
        'CLINIC_TLS_CERT': join('tls', 'server.crt'),
        'CLINIC_TLS_KEY': join('tls', 'server.key'),
        'CLINIC_PG_DUMP': sep.join([pg_root, 'bin', 'pg_dump.exe' if sep == '\\' else 'pg_dump']),
        'CLINIC_PG_RESTORE': sep.join([pg_root, 'bin', 'pg_restore.exe' if sep == '\\' else 'pg_restore']),
        'CLINIC_PG_LOG_DIR': sep.join([pg_root, 'data', 'log']),
        'CLINIC_WORKERS': '1', 'CLINIC_POOL_MIN': '1', 'CLINIC_POOL_MAX': '4',
        'CLINIC_THREAD_LIMIT': '8', 'CLINIC_CONCURRENCY': '48', 'CLINIC_EXPORT_SLOTS': '1',
        'CLINIC_EXPORT_MAX_MB': '10', 'CLINIC_UPLOAD_MAX_MB': '5', 'CLINIC_UPLOAD_TOTAL_MB': '2048',
        'CLINIC_MIN_FREE_MB': '10240', 'CLINIC_BACKUP_TOTAL_MB': '20480',
        'CLINIC_BACKUP_KEEP': '30', 'CLINIC_REQUIRE_OFFSITE': '0', 'CLINIC_OFFSITE_KEEP': '30',
    }


def merge(existing, wanted):
    """Existing keys win (never rotate secrets silently); missing keys are added."""
    result = dict(wanted)
    result.update(existing)
    return result


def write_configs(clinic_env, owner_env, ip, prefix, data_dir, pg_bin):
    cidr = lan_network(ip, prefix)
    old_clinic, old_owner = read_env(clinic_env), read_env(owner_env)
    report = {'clinic_env_created': not old_clinic, 'owner_env_created': not old_owner,
              'new_password_roles': [], 'ip_changed': False, 'cidr': cidr}
    app_password = password_from_url(old_clinic.get('CLINIC_DATABASE_URL'), APP_ROLE)
    if not app_password:
        app_password = new_password()
        report['new_password_roles'].append(APP_ROLE)
    clinic = merge(old_clinic, desired(ip, cidr, data_dir, pg_bin, app_password))
    if old_clinic and old_clinic.get('CLINIC_BIND_IP') not in (None, ip):
        report['ip_changed'] = True
        report['configured_ip'] = old_clinic['CLINIC_BIND_IP']
    owner_password = password_from_url(old_owner.get('CLINIC_DATABASE_URL'), OWNER_ROLE)
    if not owner_password:
        owner_password = new_password()
        report['new_password_roles'].append(OWNER_ROLE)
    owner = dict(clinic)
    owner.update({k: v for k, v in old_owner.items() if k != 'CLINIC_DATABASE_URL'})
    owner['CLINIC_DATABASE_URL'] = f'postgresql://{OWNER_ROLE}:{owner_password}@127.0.0.1:5432/{DB_NAME}'
    write_env(clinic_env, clinic, ['Minh Duc LAN - tao boi CAI_DAT. KHONG gui tep nay cho ai, KHONG dua len Git.',
                                   'Dang KEY=VALUE, khong dau nhay. Chay lai CAI_DAT khong doi mat khau da co.'])
    write_env(owner_env, owner, ['Tai khoan chu so huu CSDL, chi dung cho migration. Chi Administrators doc duoc.'])
    report['origin'] = clinic['CLINIC_ORIGIN']
    report['bind_ip'] = clinic['CLINIC_BIND_IP']
    return report


def write_super(path):
    """PostgreSQL superuser password file for unattended install (never overwrite)."""
    values = read_env(path)
    if values.get('MINHDUC_PG_SUPER_PASSWORD'):
        return False
    write_env(path, {'MINHDUC_PG_SUPER_PASSWORD': new_password()},
              ['Mat khau sieu quan tri PostgreSQL (postgres). Chi Administrators/SYSTEM doc duoc.'])
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('cidr')
    c.add_argument('ip'); c.add_argument('prefix')
    w = sub.add_parser('write')
    for name in ('--clinic-env', '--owner-env', '--ip', '--prefix', '--data-dir', '--pg-bin'):
        w.add_argument(name, required=True)
    s = sub.add_parser('super')
    s.add_argument('--file', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'cidr':
            print(lan_network(args.ip, args.prefix))
        elif args.command == 'super':
            print(json.dumps({'created': write_super(args.file)}))
        else:
            print(json.dumps(write_configs(args.clinic_env, args.owner_env, args.ip, args.prefix,
                                           args.data_dir, args.pg_bin), ensure_ascii=False))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
