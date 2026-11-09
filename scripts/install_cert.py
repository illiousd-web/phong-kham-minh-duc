"""Windows installer helper for the clinic HTTPS certificate.

check  : exit 0 when the server certificate exists, matches the LAN IP and is
         valid for more than --days days; exit 1 otherwise (reason printed).
create : run scripts.create_lan_certificate into a fresh temporary folder,
         then place server.crt/server.key/ca.crt in --tls-dir and the CA
         private key in --ca-key (administrators only, never shared).
fingerprint : SHA-256 of ca.crt, shown on server and workstation for comparison.
renew  : issue a NEW server certificate (new key, same names/IPs) signed by the
         EXISTING clinic CA, so workstations do not need CAI_MAY_TRAM again.
         Stages for GIA_HAN_CHUNG_CHI: prepare (write *.moi-<stamp> next to the
         old files) -> caller sets/checks the service ACL -> verify -> commit
         (old files become *.cu-<stamp>). `rollback --stamp` works from any stage.
served : read the certificate the running HTTPS service presents (verified
         against ca.crt) to prove the service picked up the renewed one.
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


RENEW_WARNING_DAYS = 60


def status(cert_path, ip, days):
    """code: ok | missing | ip (needs a new CA + workstation reinstall) | expiring (renewable)."""
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID
    path = Path(cert_path)
    if not path.exists():
        return {'ok': False, 'code': 'missing', 'reason': 'chưa có chứng chỉ'}
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    addresses = [str(a) for a in san.get_values_for_type(x509.IPAddress)]
    left = cert.not_valid_after_utc - datetime.now(timezone.utc)
    if str(ipaddress.ip_address(ip)) not in addresses:
        return {'ok': False, 'code': 'ip', 'days_left': left.days,
                'reason': f'chứng chỉ đang cấp cho IP {", ".join(addresses)}, khác IP máy hiện tại {ip}'}
    if left <= timedelta(days=days):
        return {'ok': False, 'code': 'expiring', 'days_left': left.days, 'reason': f'chứng chỉ còn {left.days} ngày'}
    return {'ok': True, 'code': 'ok', 'days_left': left.days, 'reason': f'chứng chỉ hợp lệ, còn {left.days} ngày'}


def check(cert_path, ip, days):
    result = status(cert_path, ip, days)
    return result['ok'], result['reason']


def days_left(cert_path, now=None):
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    return (cert.not_valid_after_utc - (now or datetime.now(timezone.utc))).days


PAIR = ('server.crt', 'server.key')
TEST_FAULT = 'MINHDUC_TEST_LOI'  # test-only fault injection (CI), never set in production


def _new_stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')


def _temp(tls_dir, name, stamp):
    return Path(tls_dir) / f'{name}.moi-{stamp}'


def prepare(tls_dir, ca_key_path, stamp, valid_days=365):
    """Write the new pair next to the old files as server.crt/.key.moi-<stamp>.

    Files are created inside tls_dir so they inherit that folder's ACL (never a
    private temporary folder). Nothing in use is touched.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID
    tls_dir = Path(tls_dir)
    ca_cert = x509.load_pem_x509_certificate((tls_dir / 'ca.crt').read_bytes())
    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    if ca_key.public_key().public_numbers() != ca_cert.public_key().public_numbers():
        raise ValueError('Khóa CA (ca.key) không khớp chứng chỉ gốc ca.crt đang phát cho máy trạm.')
    now = datetime.now(timezone.utc)
    if ca_cert.not_valid_after_utc - now < timedelta(days=30):
        raise ValueError('Chứng chỉ gốc (CA) sắp hết hạn: phải tạo CA mới và cài lại mọi máy trạm.')
    old = x509.load_pem_x509_certificate((tls_dir / 'server.crt').read_bytes())
    san = old.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    not_after = min(now + timedelta(days=valid_days), ca_cert.not_valid_after_utc - timedelta(days=1))
    cert = (x509.CertificateBuilder().subject_name(old.subject).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(list(san)), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=None, decipher_only=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _temp(tls_dir, 'server.key', stamp).write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    _temp(tls_dir, 'server.crt', stamp).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return {'stamp': stamp, 'not_after': not_after.isoformat(), 'serial': format(cert.serial_number, 'X'),
            'ca_fingerprint': fingerprint(tls_dir / 'ca.crt'),
            'files': [str(_temp(tls_dir, n, stamp)) for n in PAIR]}


def verify_pair(tls_dir, stamp):
    """The prepared files are readable and the key matches the certificate."""
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(_temp(tls_dir, 'server.crt', stamp)), str(_temp(tls_dir, 'server.key', stamp)))
    return {'verified': True}


def commit(tls_dir, stamp):
    """Swap: in-use files become *.cu-<stamp>, prepared files become live."""
    tls_dir = Path(tls_dir)
    for index, name in enumerate(PAIR):
        if not _temp(tls_dir, name, stamp).exists():
            raise ValueError(f'Không thấy tệp đã chuẩn bị {name}.moi-{stamp}')
    for index, name in enumerate(PAIR):
        os.replace(tls_dir / name, tls_dir / f'{name}.cu-{stamp}')
        os.replace(_temp(tls_dir, name, stamp), tls_dir / name)
        if index == 0 and os.environ.get(TEST_FAULT) == 'loi-giua-thay':
            raise OSError('Lỗi giả lập giữa lúc thay tệp (kiểm thử)')
    return {'committed': stamp}


def renew(tls_dir, ca_key_path, valid_days=365, stamp=None):
    """prepare + verify + commit (used by CAI_DAT); on any error the old pair is restored."""
    stamp = stamp or _new_stamp()
    try:
        result = prepare(tls_dir, ca_key_path, stamp, valid_days)
        verify_pair(tls_dir, stamp)
        commit(tls_dir, stamp)
    except Exception:
        rollback(tls_dir, stamp)
        raise
    return result


def rollback(tls_dir, stamp):
    """Return to the pair that was live before <stamp>, from any stage.

    Before commit: removes the prepared files, live files untouched. Mid-commit or
    after: each file saved as *.cu-<stamp> goes back; the replaced one is kept as
    *.loi-<stamp> for investigation.
    """
    if os.environ.get(TEST_FAULT) == 'khoi-phuc-loi':
        raise OSError('Lỗi giả lập khi khôi phục (kiểm thử)')
    tls_dir = Path(tls_dir)
    restored = []
    for name in PAIR:
        saved = tls_dir / f'{name}.cu-{stamp}'
        if saved.exists():
            current = tls_dir / name
            if current.exists():
                os.replace(current, tls_dir / f'{name}.loi-{stamp}')
            os.replace(saved, current)
            restored.append(name)
        _temp(tls_dir, name, stamp).unlink(missing_ok=True)
    for name in PAIR:
        if not (tls_dir / name).exists():
            raise ValueError(f'Thiếu {name} sau khi khôi phục')
    return {'restored': restored}


def served(origin, ca_file, timeout=10):
    """Certificate actually presented by the HTTPS service, verified with the clinic CA."""
    import socket
    import ssl
    from urllib.parse import urlsplit
    parts = urlsplit(origin)
    context = ssl.create_default_context(cafile=str(ca_file))
    with socket.create_connection((parts.hostname, parts.port or 443), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=parts.hostname) as tls:
            peer = tls.getpeercert()
    return {'serial': peer['serialNumber'].upper().lstrip('0'), 'not_after': peer['notAfter']}


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
    r = sub.add_parser('renew'); r.add_argument('--tls-dir', required=True); r.add_argument('--ca-key', required=True)
    pr = sub.add_parser('prepare'); pr.add_argument('--tls-dir', required=True); pr.add_argument('--ca-key', required=True)
    pr.add_argument('--stamp', required=True)
    for cmd in ('verify', 'commit', 'rollback'):
        x = sub.add_parser(cmd); x.add_argument('--tls-dir', required=True); x.add_argument('--stamp', required=True)
    s = sub.add_parser('served'); s.add_argument('--origin', required=True); s.add_argument('--ca', required=True)
    args = parser.parse_args(argv)
    if args.command == 'check':
        result = status(args.cert, args.ip, args.days)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['ok'] else 1
    try:
        if args.command == 'renew':
            print(json.dumps(renew(args.tls_dir, args.ca_key)))
            return 0
        if args.command == 'prepare':
            print(json.dumps(prepare(args.tls_dir, args.ca_key, args.stamp)))
            return 0
        if args.command in ('verify', 'commit', 'rollback'):
            action = {'verify': verify_pair, 'commit': commit, 'rollback': rollback}[args.command]
            print(json.dumps(action(args.tls_dir, args.stamp)))
            return 0
        if args.command == 'served':
            print(json.dumps(served(args.origin, args.ca)))
            return 0
    except (ValueError, OSError) as error:  # ssl.SSLError is an OSError
        print(f'LOI: {error}', file=sys.stderr)
        return 2
    if args.command == 'create':
        print(json.dumps({'fingerprint': create(args.ip, args.tls_dir, args.ca_key)}))
        return 0
    print(json.dumps({'fingerprint': fingerprint(args.ca)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
