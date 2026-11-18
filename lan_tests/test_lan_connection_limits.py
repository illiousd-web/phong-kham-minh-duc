"""Run admission and cache regression checks through the HTTPS LAN launcher."""
import asyncio
import os
import ssl
from contextlib import ExitStack
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from app.resources import LIMITS, read_limits
from .conftest import PASSWORDS
from .test_tls_chrome_compat import https_server as https_server


def test_static_cache_revalidates_with_etag(https_server):
    origin, certdir = https_server
    tls = ssl.create_default_context(cafile=str(certdir / 'ca.crt'))
    with httpx.Client(base_url=origin, verify=tls, trust_env=False) as client:
        asset = client.get('/assets/app.js')
        assert asset.status_code == 200
        assert asset.headers['cache-control'] == 'no-cache'
        validated = client.get('/assets/app.js', headers={'If-None-Match': asset.headers['etag']})
        assert validated.status_code == 304 and validated.content == b''
        assert validated.headers['etag'] == asset.headers['etag']
        assert validated.headers['cache-control'] == asset.headers['cache-control']

        for path in ('/', '/api/health', '/assets/missing.js'):
            assert client.get(path).headers['cache-control'] == 'no-store', path


def test_60_parallel_asset_requests_while_business_api_is_at_capacity(https_server):
    origin, certdir = https_server
    address = urlsplit(origin)
    tls = ssl.create_default_context(cafile=str(certdir / 'ca.crt'))
    headers = {'Origin': origin, 'X-Clinic-Request': '1'}
    login_request = (
        f'POST /api/login HTTP/1.1\r\nHost: {address.netloc}\r\nOrigin: {origin}\r\n'
        'X-Clinic-Request: 1\r\nContent-Type: application/json\r\nContent-Length: 2\r\n'
        'Expect: 100-continue\r\nConnection: close\r\n\r\n'
    ).encode('ascii')

    async def check():
        async with httpx.AsyncClient(base_url=origin, verify=tls, trust_env=False, headers=headers,
                                     limits=httpx.Limits(max_connections=60, max_keepalive_connections=0)) as client:
            with ExitStack() as connections:
                async def hold_login():
                    reader, writer = await asyncio.open_connection(address.hostname, address.port, ssl=tls)
                    connections.callback(writer.close)
                    writer.write(login_request)
                    await writer.drain()
                    # Uvicorn sends this only once the app starts reading the admitted request body.
                    interim = await reader.readuntil(b'\r\n\r\n')
                    assert interim.startswith(b'HTTP/1.1 100 '), interim
                    return reader, writer

                active = await asyncio.gather(*(hold_login() for _ in range(LIMITS.concurrency)))
                busy = await client.post('/api/login', json={})
                assert busy.status_code == 503
                assert busy.headers['x-content-type-options'] == 'nosniff'
                assert busy.headers['x-frame-options'] == 'DENY'
                assert busy.headers['referrer-policy'] == 'no-referrer'
                index = await client.get('/')
                assert index.status_code == 200 and index.headers['content-type'].startswith('text/html')
                assert '<html' in index.text
                head = await client.head('/')
                assert head.status_code == 200 and head.content == b''
                assert (await client.get('/api/health')).status_code == 200

                assets = await asyncio.gather(*(client.get('/assets/app.js') for _ in range(60)))
                assert [response.status_code for response in assets] == [200] * 60
                assert (await client.post('/api/login', json={})).status_code == 503

                async def finish_login(reader, writer):
                    writer.write(b'{}')
                    await writer.drain()
                    response = await reader.read()
                    assert response.startswith(b'HTTP/1.1 422 '), response

                await asyncio.gather(*(finish_login(reader, writer) for reader, writer in active))
                assert (await client.post('/api/login', json={})).status_code == 422

    asyncio.run(asyncio.wait_for(check(), timeout=30))


def test_lan_launcher_uses_validated_connection_limit(https_server, monkeypatch):
    from scripts import run_lan

    _, certdir = https_server
    monkeypatch.setenv('CLINIC_TLS_CERT', str(certdir / 'server.crt'))
    monkeypatch.setenv('CLINIC_TLS_KEY', str(certdir / 'server.key'))
    calls = []
    monkeypatch.setattr(run_lan.uvicorn, 'run', lambda app, **kwargs: calls.append(kwargs))
    monkeypatch.delenv('CLINIC_MAX_CONNECTIONS', raising=False)
    for value, expected in ((None, 200), ('100', 100), ('500', 500)):
        if value is not None:
            monkeypatch.setenv('CLINIC_MAX_CONNECTIONS', value)
        monkeypatch.setattr(run_lan, 'LIMITS', read_limits())
        run_lan.main()
        assert calls[-1]['limit_concurrency'] == expected
    for invalid in ('99', '501', 'many'):
        monkeypatch.setenv('CLINIC_MAX_CONNECTIONS', invalid)
        with pytest.raises(RuntimeError, match='CLINIC_MAX_CONNECTIONS'):
            read_limits()


@pytest.mark.parametrize('failure', [503, 'network', 401])
def test_boot_checks_session_again_on_retry(https_server, failure):
    origin, _ = https_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'),
                                             args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            context = browser.new_context(ignore_https_errors=True)
            login = context.request.post(origin + '/api/login', headers={'Origin': origin, 'X-Clinic-Request': '1'},
                                         data={'username': 'test_reception', 'password': PASSWORDS['reception']})
            assert login.ok
            session = next(cookie for cookie in context.cookies() if cookie['name'] == '__Host-clinic')
            page = context.new_page()

            def fail_once(route):
                if failure == 'network':
                    route.abort()
                else:
                    route.fulfill(status=failure, json={'detail': 'Lỗi kiểm thử'})

            page.route('**/api/me', fail_once, times=1)
            page.goto(origin)
            login_form = page.locator('[data-form="login"]')
            retry = page.get_by_role('button', name='Thử lại', exact=True)
            if failure == 401:
                expect(login_form).to_be_visible()
                expect(retry).to_have_count(0)
                return

            expect(page.get_by_role('alert')).to_contain_text('Hệ thống đang bận, vui lòng thử lại')
            expect(login_form).to_have_count(0)
            assert session in context.cookies()
            with page.expect_response(lambda response: response.url == origin + '/api/me') as result:
                retry.click()
            assert result.value.status == 200
            expect(page.locator('.account-trigger')).to_be_visible()
            expect(retry).to_have_count(0)
            assert session in context.cookies()
        finally:
            browser.close()


def test_boot_finishes_the_unauthenticated_session_request(https_server):
    origin, _ = https_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'),
                                             args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            page = browser.new_page(ignore_https_errors=True)
            with page.expect_event('requestfinished', lambda request: request.url == origin + '/api/me') as result:
                page.goto(origin, wait_until='networkidle')
            assert result.value.response().status == 401
            expect(page.locator('[data-form="login"]')).to_be_visible()
        finally:
            browser.close()
