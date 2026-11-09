"""TLS of the real LAN launcher is usable by Chrome 109 (last Chrome for Windows 7).

Chrome 109 negotiates with its own BoringSSL (not the Windows 7 SChannel stack),
so the server must offer TLS 1.2/1.3 with ECDHE + AES-GCM/ChaCha20, which
scripts.run_lan does. Set MINHDUC_EXPECT_CHROMIUM_MAJOR=109 (CI job
browser-chromium-109) to prove the test really ran on that browser version.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from .conftest import ROOT


@pytest.fixture(scope='module')
def https_server(request):
    # The import-browser tests reuse this fixture in a separate module. Each
    # module must get new certificates: the generator refuses to overwrite keys.
    certdir = ROOT / ('certs-tls-compat-' + request.module.__name__.rsplit('.', 1)[-1])
    subprocess.run([sys.executable, '-m', 'scripts.create_lan_certificate', '--name', 'minhduc.internal',
                    '--ip', '127.0.0.1', '--output', str(certdir)], check=True)
    env = os.environ.copy()
    env.update(CLINIC_TLS_CERT=str(certdir / 'server.crt'), CLINIC_TLS_KEY=str(certdir / 'server.key'))
    log = ROOT / 'https-tls-compat.log'
    with log.open('w') as output:
        server = subprocess.Popen([sys.executable, '-m', 'scripts.run_lan'], env=env, stdout=output, stderr=output)
        origin = urlsplit(env['CLINIC_ORIGIN'])
        try:
            for _ in range(150):
                if server.poll() is not None:
                    pytest.fail(log.read_text())
                try:
                    with socket.create_connection((origin.hostname, origin.port), timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail('HTTPS server did not start')
            yield env['CLINIC_ORIGIN'], certdir
        finally:
            server.terminate()
            server.wait(10)


def _handshake(origin, cafile, **context_options):
    parts = urlsplit(origin)
    context = ssl.create_default_context(cafile=str(cafile))
    for key, value in context_options.items():
        if key == 'ciphers':
            context.set_ciphers(value)
        else:
            setattr(context, key, value)
    with socket.create_connection((parts.hostname, parts.port), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname=parts.hostname) as tls:
            return tls.version(), tls.cipher()[0]


def test_server_accepts_chrome109_tls12_suites_and_refuses_old_tls(https_server):
    origin, certdir = https_server
    ca = certdir / 'ca.crt'
    # Chrome 109 TLS 1.2 suites (ECDHE-RSA with AES-GCM or ChaCha20); one is enough to connect.
    for suite in ('ECDHE-RSA-AES128-GCM-SHA256', 'ECDHE-RSA-AES256-GCM-SHA384', 'ECDHE-RSA-CHACHA20-POLY1305'):
        version, cipher = _handshake(origin, ca, maximum_version=ssl.TLSVersion.TLSv1_2, ciphers=suite)
        assert version == 'TLSv1.2' and cipher == suite
    assert _handshake(origin, ca)[0] == 'TLSv1.3'
    with pytest.raises(ssl.SSLError):
        _handshake(origin, ca, minimum_version=ssl.TLSVersion.TLSv1, maximum_version=ssl.TLSVersion.TLSv1_1)


def test_chromium_negotiates_modern_tls_with_clinic_server(https_server):
    origin, certdir = https_server
    cert = x509.load_pem_x509_certificate((certdir / 'server.crt').read_bytes())
    spki = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    pin = base64.b64encode(hashlib.sha256(spki).digest()).decode()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + pin])
        try:
            version = browser.version
            expected = os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR')
            if expected:
                assert version.split('.')[0] == expected, version
            page = browser.new_page()
            response = page.goto(origin + '/')
            details = response.security_details()
            assert response.status == 200 and details['protocol'] in ('TLS 1.2', 'TLS 1.3'), details
            evidence = Path('test_evidence/lan')
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / f'tls-chromium-{version.split(".")[0]}.json').write_text(
                json.dumps({'chromium': version, 'protocol': details['protocol']}), encoding='utf-8')
        finally:
            browser.close()
