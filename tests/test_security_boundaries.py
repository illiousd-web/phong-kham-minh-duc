"""Security boundaries for the loopback-only synthetic demo."""
import getpass
import warnings

import pytest
from fastapi.testclient import TestClient
from app.main import app
from scripts import run_demo


@pytest.mark.parametrize('host', ['attacker.example', 'localhost.attacker.example'])
def test_reject_untrusted_host(host):
    with TestClient(app) as client:
        assert client.get('/api/health', headers={'Host': host}).status_code == 400


@pytest.mark.parametrize('host', ['localhost:8000', '127.0.0.1:8000'])
def test_accept_loopback_host(host):
    with TestClient(app) as client:
        assert client.get('/api/health', headers={'Host': host}).status_code == 200


def test_reject_remote_client_even_with_local_host():
    with TestClient(app, client=('192.0.2.10', 1234)) as client:
        assert client.get('/api/health', headers={'Host': 'localhost'}).status_code == 403


def test_launcher_refuses_password_echo_fallback(monkeypatch):
    monkeypatch.delenv('DEMO_PASSWORD', raising=False)

    def insecure_prompt(*args):
        warnings.warn('No secure terminal', getpass.GetPassWarning)
        pytest.fail('Password must not be read after the warning')

    monkeypatch.setattr(getpass, 'getpass', insecure_prompt)
    with pytest.raises(SystemExit, match='DEMO_PASSWORD'):
        run_demo.main()


def test_launcher_keeps_loopback_and_disables_proxy_headers(monkeypatch):
    # conftest supplies a random password; never hard-code a credential here.
    def launch(command, **kwargs):
        assert command[command.index('--host') + 1] == '127.0.0.1'
        assert '--no-proxy-headers' in command
        assert kwargs['env']['DEMO_PASSWORD']
        return 0

    monkeypatch.setattr(run_demo.subprocess, 'call', launch)
    assert run_demo.main() == 0
