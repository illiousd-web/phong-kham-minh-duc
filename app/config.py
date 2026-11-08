"""Fail-closed configuration for the synthetic LAN pilot."""
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

MODE = os.getenv('CLINIC_MODE', 'demo')
if MODE not in ('demo', 'lan'):
    raise RuntimeError('CLINIC_MODE must be demo or lan')
LAN = MODE == 'lan'
DATABASE_URL = os.getenv('CLINIC_DATABASE_URL', '')
ORIGIN = os.getenv('CLINIC_ORIGIN', '')
DATA = Path(os.getenv('CLINIC_DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data'))).resolve()
NETWORKS = []
HOSTS = ['127.0.0.1', 'localhost', 'testserver']
if LAN:
    if not DATABASE_URL.startswith(('postgresql://', 'postgres://')):
        raise RuntimeError('LAN requires CLINIC_DATABASE_URL (PostgreSQL)')
    parsed = urlsplit(ORIGIN)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise RuntimeError('CLINIC_ORIGIN must be an exact HTTPS origin without a trailing slash')
    HOSTS = [parsed.hostname]
    for item in os.getenv('CLINIC_ALLOWED_CIDRS', '').split(','):
        if item.strip():
            network = ipaddress.ip_network(item.strip(), strict=True)
            private_ranges = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '::1/128', 'fc00::/7')]
            if not any(network.version == n.version and network.subnet_of(n) for n in private_ranges):
                raise RuntimeError('Only explicit private LAN/loopback networks are accepted')
            NETWORKS.append(network)
    if not NETWORKS:
        raise RuntimeError('Set CLINIC_ALLOWED_CIDRS to the clinic subnet and proxy loopback')


def client_allowed(host):
    if not LAN:
        return host in ('127.0.0.1', '::1', 'testclient')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in NETWORKS)
