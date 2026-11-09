"""Operator-only LAN setup, never creates demo users or inventory."""
import argparse
import getpass
import os
import warnings
from app.config import LAN
from app.database import db, migrate
from app.accounts import AccountInput, create_account
from app.auth import pw_hash
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    sub.add_parser('rollback-manual-prices', help='Quay lui migration giá nhập tay nếu chưa có dữ liệu của chức năng này')
    user = sub.add_parser('create-admin')
    user.add_argument('--username', required=True)
    user.add_argument('--name', required=True)
    user.add_argument('--password-env', help='Unattended install only: read the password from this '
                      'environment variable (removed immediately), never from the command line')
    args = parser.parse_args()
    if not LAN:
        parser.error('This command requires CLINIC_MODE=lan')
    if args.command == 'migrate':
        migrate()
        print('Schema migration complete; no demo data created.')
        return
    if args.command == 'rollback-manual-prices':
        from app.manual_price_migration import migrate_manual_prices
        with db(True) as c:
            migrate_manual_prices(c, postgres=True, down=True)
        print('Đã quay lui migration giá nhập tay; dữ liệu cũ giữ nguyên.')
        return
    if args.password_env:
        password = os.environ.pop(args.password_env, '')
        if not password:
            parser.error('Password environment variable is empty')
    else:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('Mat khau rieng (>=12 ky tu): ')
            if password != getpass.getpass('Nhap lai: '):
                parser.error('Passwords do not match')
    data = AccountInput(username=args.username, full_name=args.name, password=password, roles=['admin'])
    with db(True) as c:
        uid = create_account(c, data, pw_hash)
        c.execute('INSERT INTO audit_log(user_id,event,object_type,object_id,created_at) VALUES(?,?,?,?,?)',
                  (uid,'operator_account_created','user',uid,datetime.now(timezone.utc).isoformat()))
    print('Created individual administrator account.')


if __name__ == '__main__':
    main()
