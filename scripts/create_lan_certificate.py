"""Create a clinic-specific offline CA and HTTPS certificate. No public ACME."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True, help='Internal DNS name, e.g. minhduc.internal')
    parser.add_argument('--ip', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.ip)
    if not address.is_private or address.is_unspecified or address.is_multicast:
        parser.error('Use a private LAN IP')
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Minh Duc LAN Pilot CA')])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True,path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True,key_cert_sign=True,crl_sign=True,
                          content_commitment=False,key_encipherment=False,data_encipherment=False,
                          key_agreement=False,encipher_only=None,decipher_only=None), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,args.name)]))
            .issuer_name(ca_name).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(args.name),x509.IPAddress(address)]),critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,content_commitment=False,
                            data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,
                            encipher_only=None,decipher_only=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
            # Python 3.13+ verifies with VERIFY_X509_STRICT, which rejects certificates without these identifiers.
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    for name, key in [('ca.key',ca_key),('server.key',server_key)]:
        path=args.output/name
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        path.chmod(0o600)
    for name, item in [('ca.crt',ca),('server.crt',cert)]:
        (args.output/name).write_bytes(item.public_bytes(serialization.Encoding.PEM))
    print('Created internal certificates. Distribute only ca.crt to clients. Store ca.key offline.')


if __name__ == '__main__':
    main()
