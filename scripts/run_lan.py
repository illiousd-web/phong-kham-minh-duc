"""Start the HTTPS-only LAN pilot on one explicit private interface."""
import ipaddress
import os
from pathlib import Path
import ssl
from urllib.parse import urlsplit
import uvicorn
from app.config import LAN, ORIGIN, client_allowed
from app.resources import LIMITS
from app.logging_config import server_logging


def main():
    if not LAN:
        raise SystemExit('Set CLINIC_MODE=lan; this launcher never starts demo mode')
    bind = os.environ.get('CLINIC_BIND_IP', '')
    try:
        address = ipaddress.ip_address(bind)
    except ValueError:
        raise SystemExit('Set CLINIC_BIND_IP to the server private LAN IP (not 0.0.0.0)')
    if address.is_unspecified or address.is_multicast or not address.is_private or not client_allowed(bind):
        raise SystemExit('Bind address must be inside CLINIC_ALLOWED_CIDRS')
    origin = urlsplit(ORIGIN)
    cert = Path(os.environ['CLINIC_TLS_CERT']).resolve()
    key = Path(os.environ['CLINIC_TLS_KEY']).resolve()
    # Validate key pair and TLS configuration before launching workers.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID
    from datetime import datetime, timezone
    certificate = x509.load_pem_x509_certificate(cert.read_bytes())
    san = certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    names = san.get_values_for_type(x509.DNSName) + [str(i) for i in san.get_values_for_type(x509.IPAddress)]
    if origin.hostname not in names or certificate.not_valid_after_utc <= datetime.now(timezone.utc):
        raise SystemExit('Certificate must be unexpired and match CLINIC_ORIGIN')
    uvicorn.run('app.main:app', host=bind, port=origin.port or 443,
                workers=LIMITS.workers, proxy_headers=False, server_header=False, access_log=False,
                ssl_certfile=str(cert), ssl_keyfile=str(key), ssl_version=ssl.PROTOCOL_TLS_SERVER,
                ssl_ciphers='ECDHE+AESGCM:ECDHE+CHACHA20',
                limit_concurrency=LIMITS.concurrency, timeout_keep_alive=2,
                log_config=server_logging())


if __name__ == '__main__':
    main()
