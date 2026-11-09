"""Maintainer tool: add PyPI SHA-256 hashes to a pinned requirements file.

Usage: python scripts/hash_lock.py requirements.lock
Every published file (wheel for each platform + sdist) of the pinned version is
hashed so `pip install --require-hashes` works on Windows and Linux alike.
Run only on a developer machine with Internet; review the diff before commit.
"""
import json
import re
import sys
import urllib.request

LINE = re.compile(r'^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+]+)\s*(;.*)?$')


def hashes(name, version):
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as response:
        data = json.load(response)
    found = sorted({item['digests']['sha256'] for item in data['urls'] if not item.get('yanked')})
    if not found:
        raise SystemExit(f'No files published for {name}=={version}')
    return found


def convert(text):
    out = []
    for raw in text.splitlines():
        line = raw.split(' \\')[0].strip()
        if line.startswith('--hash'):
            continue  # regenerated below from PyPI
        if not line or line.startswith('#'):
            out.append(raw)
            continue
        match = LINE.match(line)
        if not match:
            raise SystemExit(f'Unpinned or unsupported line: {raw}')
        name, version, marker = match.groups()
        head = f'{name}=={version}' + (f' {marker.strip()}' if marker else '')
        out.append(head + ' \\')
        digests = hashes(name, version)
        for index, digest in enumerate(digests):
            out.append(f'    --hash=sha256:{digest}' + (' \\' if index < len(digests) - 1 else ''))
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    path = sys.argv[1]
    source = open(path, encoding='utf-8').read()
    result = convert(source)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(result)
