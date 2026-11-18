"""Run admission and cache regression checks through the HTTPS LAN launcher."""
import asyncio
import ssl
from contextlib import ExitStack
from urllib.parse import urlsplit

import httpx

from app.resources import LIMITS
from .test_tls_chrome_compat import https_server as https_server


def test_static_cache_is_fresh_then_revalidates_with_etag(https_server):
    origin, certdir = https_server
    tls = ssl.create_default_context(cafile=str(certdir / 'ca.crt'))
    with httpx.Client(base_url=origin, verify=tls, trust_env=False) as client:
        asset = client.get('/assets/app.js')
        assert asset.status_code == 200
        assert asset.headers['cache-control'] == 'private, max-age=300, must-revalidate'
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
                assert (await client.post('/api/login', json={})).status_code == 503
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
