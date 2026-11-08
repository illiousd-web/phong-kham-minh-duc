"""Encrypted, consistent PostgreSQL + attachment backups and empty-target restore.

Run as service account on encrypted storage. All app writers and this backup
share one DB advisory lock. A successful backup is published by atomic rename.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from urllib.parse import urlsplit, unquote
import psycopg
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from app.config import DATABASE_URL, DATA, LAN
from app.database import LOCK_ID

MAGIC = b'MDCLINIC1'
CHUNK = 1024*1024


def key_bytes(path):
    key = Path(path).read_bytes()
    if len(key) != 32:
        raise ValueError('Backup key must be exactly 32 random bytes')
    return key


def checksum(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(CHUNK), b''):
            h.update(block)
    return h.hexdigest()


def crypt_file(source, target, key, decrypt=False):
    """Bounded-memory AES-256-GCM; decrypted output is temporary until verified."""
    with source.open('rb') as inp, target.open('wb') as out:
        if decrypt:
            if inp.read(len(MAGIC)) != MAGIC:
                raise ValueError('Invalid backup format')
            nonce = inp.read(12)
            inp.seek(-16, 2); tag = inp.read(16)
            remaining = inp.tell()-16-len(MAGIC)-12
            inp.seek(len(MAGIC)+12)
            ctx = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        else:
            nonce = secrets.token_bytes(12)
            out.write(MAGIC+nonce)
            ctx = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
            remaining = source.stat().st_size
        ctx.authenticate_additional_data(MAGIC)
        while remaining > 0:
            block = inp.read(min(CHUNK, remaining))
            if not block:
                raise ValueError('Truncated backup')
            out.write(ctx.update(block)); remaining -= len(block)
        out.write(ctx.finalize())
        if not decrypt:
            out.write(ctx.tag)
        out.flush(); os.fsync(out.fileno())
    target.chmod(0o600)


def pg_env(url):
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise ValueError('Backup URL must be a plain local PostgreSQL URL; use PGSSLMODE for TLS')
    env = os.environ.copy()
    env.update(PGHOST=parts.hostname or 'localhost', PGPORT=str(parts.port or 5432),
               PGUSER=unquote(parts.username or ''), PGPASSWORD=unquote(parts.password or ''),
               PGDATABASE=unquote(parts.path.lstrip('/')))
    return env


def pg_tool(name, args, url):
    tool = os.getenv('CLINIC_'+name.upper(), name)
    result = subprocess.run([tool,*args], env=pg_env(url), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Do not echo connection strings or potentially sensitive dump errors.
        raise RuntimeError(f'{name} failed (exit {result.returncode}); inspect local PostgreSQL/service logs')


@contextmanager
def maintenance_lock(url):
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("SET lock_timeout='60s'")
        c.execute('SELECT pg_advisory_lock(%s)', (LOCK_ID,))
        try:
            yield c
        finally:
            c.execute('SELECT pg_advisory_unlock(%s)', (LOCK_ID,))


def backup(destination, key_path):
    key = key_bytes(key_path)
    keep=int(os.getenv('CLINIC_BACKUP_KEEP','30'))
    if keep < 2:
        raise ValueError('Retention must keep at least 2 backups')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Temp plaintext stays beside encrypted backups on the same protected volume.
    with tempfile.TemporaryDirectory(prefix='.backup-', dir=destination) as temp:
        root = Path(temp)
        uploads = Path(os.getenv('CLINIC_UPLOAD_DIR', str(DATA/'attachments')))
        with maintenance_lock(DATABASE_URL):
            pg_tool('pg_dump', ['--format=custom','--no-owner','--no-acl','--file',str(root/'database.dump')], DATABASE_URL)
            if uploads.exists():
                if any(p.is_symlink() for p in uploads.rglob('*')):
                    raise ValueError('Attachment storage must not contain symlinks')
                shutil.copytree(uploads, root/'attachments', symlinks=False)
            else:
                (root/'attachments').mkdir()
            manifest = {'format':1, 'created_at':datetime.now(timezone.utc).isoformat(),
                        'files':{str(f.relative_to(root)):checksum(f) for f in sorted(root.rglob('*')) if f.is_file()}}
        (root/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False))
        archive=root/'payload.tar'
        with tarfile.open(archive,'w') as tar:
            for name in ('database.dump','attachments','manifest.json'):
                tar.add(root/name, arcname=name)
        name = 'minhduc-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.mdbackup'
        pending=root/'encrypted.tmp'
        crypt_file(archive,pending,key)
        target=destination/name
        os.replace(pending,target)
    # Only prune files produced by this tool, after a new backup succeeds.
    for old in sorted(destination.glob('minhduc-*.mdbackup'), key=lambda p:p.stat().st_mtime, reverse=True)[keep:]:
        old.unlink()
    return target


def unpack_verified(source, key_path, root):
    archive=root/'payload.tar'
    crypt_file(source,archive,key_bytes(key_path),decrypt=True)
    with tarfile.open(archive) as tar:
        for item in tar.getmembers():
            path=Path(item.name)
            if path.is_absolute() or '..' in path.parts or item.issym() or item.islnk() or not (item.isfile() or item.isdir()):
                raise ValueError('Unsafe archive member')
            if path.parts[0] not in ('database.dump','attachments','manifest.json'):
                raise ValueError('Unexpected archive member')
        tar.extractall(root, filter='data')
    manifest=json.loads((root/'manifest.json').read_text())
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}-{'payload.tar','manifest.json'}
    if manifest['format'] != 1 or actual != set(manifest['files']):
        raise ValueError('Backup manifest mismatch')
    for name, digest in manifest['files'].items():
        if checksum(root/name) != digest:
            raise ValueError('Backup checksum mismatch')
    return manifest


def restore(source, key_path, url, uploads):
    # No in-place overwrites: operator must create a separate empty target.
    uploads = uploads.resolve()
    uploads.parent.mkdir(parents=True,exist_ok=True)
    if uploads.exists() and any(uploads.iterdir()):
        raise ValueError('Restore attachment destination must be empty')
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=uploads.parent) as temp:
        root=Path(temp)
        unpack_verified(source,key_path,root)
        with maintenance_lock(url) as c:
            if c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]:
                raise ValueError('Restore database must be empty; never overwrite the running clinic')
            # Stage files first; do not expose restored state before both pieces exist.
            staged=root/'attachments'
            pg_tool('pg_restore',['--single-transaction','--exit-on-error','--no-owner','--no-acl','--dbname',unquote(urlsplit(url).path.lstrip('/')),str(root/'database.dump')],url)
            if uploads.exists():
                uploads.rmdir()
            os.replace(staged,uploads)
            # Restored browser tokens must not become valid again.
            c.execute('DELETE FROM sessions')
            c.execute('INSERT INTO audit_log(event,object_type,created_at) VALUES(%s,%s,%s)',
                      ('backup_restored','system',datetime.now(timezone.utc).isoformat()))
    return uploads


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['keygen','backup','verify','restore'])
    parser.add_argument('--key',type=Path,required=True)
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--file',type=Path)
    parser.add_argument('--target-url-env', default='CLINIC_RESTORE_DATABASE_URL')
    parser.add_argument('--target-uploads',type=Path)
    args=parser.parse_args()
    if not LAN:
        parser.error('Requires CLINIC_MODE=lan')
    if args.command=='keygen':
        with os.fdopen(os.open(args.key,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
            f.write(secrets.token_bytes(32))
        args.key.chmod(0o600)
        print('Backup key created. Store a separate offline copy.')
    elif args.command=='backup':
        if not args.directory:parser.error('--directory is required')
        print(backup(args.directory,args.key))
    elif args.command=='verify':
        if not args.file:parser.error('--file is required')
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            result=unpack_verified(args.file,args.key,Path(tmp))
            print('Authenticated backup and checksums verified:',result['created_at'])
    else:
        if not args.file or not args.target_uploads:parser.error('--file and --target-uploads required')
        restore(args.file,args.key,os.environ[args.target_url_env],args.target_uploads)
        print('Restored into separate empty destination; sessions revoked. Validate before switching server configuration.')


if __name__=='__main__':
    main()
