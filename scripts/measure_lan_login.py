"""Measure ten simultaneous Chromium sessions against a disposable LAN server.

Run with requirements-test.lock and CLINIC_TEST_DATABASE_URL pointing to a
local, synthetic PostgreSQL instance with CREATEDB (as for lan_tests).
Use CHROMIUM_PATH to select a browser binary.
"""
import argparse
import asyncio
import json
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from playwright.async_api import Error, async_playwright
import psutil
import psycopg
from psycopg import sql

from app.resources import LIMITS

BROWSERS = 10
TIMEOUT_MS = 10_000
SAMPLE_INTERVAL = 0.01


@contextmanager
def test_database():
    source = os.getenv('CLINIC_TEST_DATABASE_URL', '')
    parts = urlsplit(source)
    if parts.scheme not in ('postgres', 'postgresql') or parts.hostname not in ('127.0.0.1', 'localhost', '::1') or parts.query:
        raise ValueError('CLINIC_TEST_DATABASE_URL must identify a local test PostgreSQL instance')
    name = 'clinic_load_' + secrets.token_hex(6)
    with psycopg.connect(source, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            yield urlunsplit(parts._replace(path='/' + name))
        finally:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def seed_accounts(env):
    passwords = {f'load_{index:02d}': secrets.token_urlsafe(24) for index in range(BROWSERS)}
    env['CLINIC_LOAD_ACCOUNTS'] = json.dumps(passwords)
    subprocess.run([sys.executable, '-c', """
import json
import os
from app.accounts import AccountInput, create_account
from app.auth import pw_hash
from app.database import db, migrate
migrate()
with db(True) as conn:
    for username, password in json.loads(os.environ['CLINIC_LOAD_ACCOUNTS']).items():
        create_account(conn, AccountInput(username=username, password=password,
                       full_name='Nhân viên giả lập ' + username, roles=['reception']), pw_hash)
"""], check=True, env=env)
    del env['CLINIC_LOAD_ACCOUNTS']
    return passwords


@contextmanager
def lan_server(database_url, root):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'https://127.0.0.1:{port}'
    certs = root / 'certs'
    subprocess.run([sys.executable, '-m', 'scripts.create_lan_certificate',
                    '--name', 'minhduc.internal', '--ip', '127.0.0.1', '--output', str(certs)],
                   stdout=subprocess.DEVNULL, check=True)
    env = dict(os.environ, CLINIC_MODE='lan', CLINIC_DATABASE_URL=database_url,
               CLINIC_DATA_DIR=str(root), CLINIC_ORIGIN=origin, CLINIC_BIND_IP='127.0.0.1',
               CLINIC_ALLOWED_CIDRS='127.0.0.1/32', CLINIC_TLS_CERT=str(certs / 'server.crt'),
               CLINIC_TLS_KEY=str(certs / 'server.key'), CLINIC_UPLOAD_DIR=str(root / 'attachments'),
               CLINIC_MIN_FREE_MB='256', CLINIC_WORKERS='1', CLINIC_CONCURRENCY='48')
    passwords = seed_accounts(env)
    with (root / 'launcher.log').open('w') as log, subprocess.Popen(
        [sys.executable, '-m', 'scripts.run_lan'], env=env, stdout=log, stderr=log,
    ) as server:
        try:
            tls = ssl.create_default_context(cafile=str(certs / 'ca.crt'))
            for _ in range(100):
                if server.poll() is not None:
                    break
                try:
                    with urlopen(origin + '/api/health', context=tls, timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError('HTTPS startup timed out')
            if server.poll() is not None:
                raise RuntimeError('LAN launcher failed to start')
            # Remove the health probe from the connection count.
            time.sleep(0.1)
            yield origin, port, server.pid, passwords
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


@contextmanager
def sample_connections(pid, port):
    process = psutil.Process(pid)
    stop = threading.Event()
    peaks = []

    def sample():
        peak = 0
        while not stop.is_set():
            connections = process.net_connections(kind='tcp')
            peak = max(peak, sum(conn.laddr.port == port and conn.status == psutil.CONN_ESTABLISHED
                                 for conn in connections if conn.laddr))
            stop.wait(SAMPLE_INTERVAL)
        peaks.append(peak)

    thread = threading.Thread(target=sample)
    thread.start()
    try:
        yield peaks
    finally:
        stop.set()
        thread.join()


async def open_login(page, origin, username, password):
    try:
        await page.goto(origin, wait_until='domcontentloaded', timeout=TIMEOUT_MS)
        form = page.locator('[data-form="login"]')
        await form.locator('[name="username"]').fill(username, timeout=TIMEOUT_MS)
        await form.locator('[name="password"]').fill(password, timeout=TIMEOUT_MS)
    except Error:
        return False
    return True


async def submit_login(page):
    try:
        await page.locator('[data-form="login"] button').click(timeout=TIMEOUT_MS)
        await page.locator('body:not(.login-view) #workspace[aria-busy="false"]').wait_for(timeout=TIMEOUT_MS)
    except Error:
        return False
    return True


async def run_wave(contexts, origin, pid, port, passwords):
    pages = await asyncio.gather(*(context.new_page() for context in contexts))
    unavailable = Counter()

    def record(response):
        if response.status == 503:
            unavailable[urlsplit(response.url).path] += 1

    for page in pages:
        page.on('response', record)
    try:
        with sample_connections(pid, port) as peaks:
            ready = await asyncio.gather(*(open_login(page, origin, user, password)
                                           for page, (user, password) in zip(pages, passwords.items(), strict=True)))
            signed_in = await asyncio.gather(*(submit_login(page) for page, ok in zip(pages, ready, strict=True) if ok))
        return {'peak_server_tcp_connections': peaks[0], 'http_503': sum(unavailable.values()),
                'http_503_by_path': dict(unavailable), 'login_forms': sum(ready),
                'successful_logins': sum(signed_in)}
    finally:
        await asyncio.gather(*(page.close() for page in pages))


async def measure(origin, port, pid, passwords, rounds):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'),
                                                   args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            waves = []
            for _ in range(rounds):
                contexts = await asyncio.gather(*(browser.new_context(ignore_https_errors=True) for _ in passwords))
                try:
                    # Separate Chromium contexts have separate caches, cookies and socket pools.
                    cold = await run_wave(contexts, origin, pid, port, passwords)
                    await asyncio.gather(*(context.clear_cookies() for context in contexts))
                    # New pages in the same contexts can revalidate cached assets with ETags.
                    warm = await run_wave(contexts, origin, pid, port, passwords)
                    waves.append({'cold': cold, 'warm': warm})
                finally:
                    await asyncio.gather(*(context.close() for context in contexts))
            return {'chromium': browser.version, 'browsers': BROWSERS, 'waves': waves}
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=3, help='Pairs of cold and warm waves')
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    with tempfile.TemporaryDirectory(prefix='minhduc-login-load-') as root, test_database() as database_url:
        with lan_server(database_url, Path(root)) as (origin, port, pid, passwords):
            result = asyncio.run(measure(origin, port, pid, passwords, args.rounds))
    waves = [wave for pair in result['waves'] for wave in pair.values()]
    result.update(clinic_max_connections=LIMITS.max_connections,
                  peak_server_tcp_connections=max(w['peak_server_tcp_connections'] for w in waves),
                  http_503=sum(w['http_503'] for w in waves),
                  successful_logins=sum(w['successful_logins'] for w in waves),
                  expected_logins=BROWSERS * len(waves))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
