"""Windows installer helper for the clinic HTTPS certificate.

check  : exit 0 when the server certificate exists, matches the LAN IP and is
         valid for more than --days days; exit 1 otherwise (reason printed).
create : run scripts.create_lan_certificate into a fresh temporary folder,
         then place server.crt/server.key/ca.crt in --tls-dir and the CA
         private key in --ca-key (administrators only, never shared).
fingerprint : SHA-256 of ca.crt, shown on server and workstation for comparison.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def check(cert_path, ip, days):
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID
    path = Path(cert_path)
    if not path.exists():
        return False, 'chưa có chứng chỉ'
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    addresses = [str(a) for a in san.get_values_for_type(x509.IPAddress)]
    if str(ipaddress.ip_address(ip)) not in addresses:
        return False, f'chứng chỉ đang cấp cho IP {", ".join(addresses)}, khác IP máy hiện tại {ip}'
    left = cert.not_valid_after_utc - datetime.now(timezone.utc)
    if left <= timedelta(days=days):
        return False, f'chứng chỉ còn {left.days} ngày'
    return True, f'chứng chỉ hợp lệ, còn {left.days} ngày'


def fingerprint(ca_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    cert = x509.load_pem_x509_certificate(Path(ca_path).read_bytes())
    return cert.fingerprint(hashes.SHA256()).hex().upper()


def create(ip, tls_dir, ca_key, name='minhduc.internal'):
    from scripts import create_lan_certificate
    tls_dir, ca_key = Path(tls_dir), Path(ca_key)
    with tempfile.TemporaryDirectory(prefix='.tls-', dir=tls_dir.parent) as temp:
        out = Path(temp) / 'new'
        argv = sys.argv
        try:
            sys.argv = ['create_lan_certificate', '--name', name, '--ip', ip, '--output', str(out)]
            create_lan_certificate.main()
        finally:
            sys.argv = argv
        tls_dir.mkdir(parents=True, exist_ok=True)
        ca_key.parent.mkdir(parents=True, exist_ok=True)
        # Keep the previous files next to the new ones for manual rollback.
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        for name_ in ('server.crt', 'server.key', 'ca.crt'):
            old = tls_dir / name_
            if old.exists():
                os.replace(old, tls_dir / f'{name_}.cu-{stamp}')
            shutil.move(str(out / name_), str(tls_dir / name_))
        if ca_key.exists():
            os.replace(ca_key, ca_key.with_name(ca_key.name + f'.cu-{stamp}'))
        shutil.move(str(out / 'ca.key'), str(ca_key))
    return fingerprint(tls_dir / 'ca.crt')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('check'); c.add_argument('--cert', required=True); c.add_argument('--ip', required=True)
    c.add_argument('--days', type=int, default=30)
    n = sub.add_parser('create'); n.add_argument('--ip', required=True); n.add_argument('--tls-dir', required=True)
    n.add_argument('--ca-key', required=True)
    f = sub.add_parser('fingerprint'); f.add_argument('--ca', required=True)
    args = parser.parse_args(argv)
    if args.command == 'check':
        ok, reason = check(args.cert, args.ip, args.days)
        print(json.dumps({'ok': ok, 'reason': reason}, ensure_ascii=False))
        return 0 if ok else 1
    if args.command == 'create':
        print(json.dumps({'fingerprint': create(args.ip, args.tls_dir, args.ca_key)}))
        return 0
    print(json.dumps({'fingerprint': fingerprint(args.ca)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
