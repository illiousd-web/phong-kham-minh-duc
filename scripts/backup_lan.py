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
from app.resources import LIMITS
from app.storage import tree_bytes, require_space, free_bytes, StorageLimitError
from app.ui_settings import FILE_NAME as SETTINGS_NAME, settings_path, load_settings, parse_settings, serialize, write_settings, DEFAULTS as SETTINGS_DEFAULTS

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


def encrypt_archive(members,target,key):
    """Stream TAR directly into GCM: no attachment copy or plaintext TAR file."""
    nonce=secrets.token_bytes(12)
    ctx=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    ctx.authenticate_additional_data(MAGIC)
    with target.open('xb') as output:
        output.write(MAGIC+nonce)
        class Writer:
            def write(self,block):
                output.write(ctx.update(block))
                return len(block)
        with tarfile.open(fileobj=Writer(),mode='w|') as tar:
            for path,name in members:tar.add(path,arcname=name)
        output.write(ctx.finalize());output.write(ctx.tag)
        output.flush();os.fsync(output.fileno())
    target.chmod(0o600)


def copy_offsite(source,directory):
    """Publish encrypted copy only after byte verification. Never copy the key."""
    directory=Path(directory).resolve()
    if directory==source.parent.resolve() or directory.is_relative_to(source.parent.resolve()):
        raise ValueError('Offsite destination must be separate from local backups')
    # A network/USB destination must already be mounted. Never create a missing
    # mount directory and accidentally treat the local SSD as the offline device.
    if not directory.is_dir():raise ValueError('Offsite destination is not available')
    if free_bytes(directory)<source.stat().st_size+256*1024*1024:
        raise StorageLimitError('Offsite destination lacks space for a verified copy and 256 MiB reserve')
    pending=directory/('.'+source.name+'.partial')
    try:
        with source.open('rb') as inp,pending.open('xb') as out:
            shutil.copyfileobj(inp,out,CHUNK);out.flush();os.fsync(out.fileno())
        if checksum(source)!=checksum(pending):raise ValueError('Offsite copy checksum mismatch')
        os.replace(pending,directory/source.name)
    finally:pending.unlink(missing_ok=True)


def space_required(destination):
    """Free bytes backup() demands before it starts (same formula as its require_space)."""
    uploads=Path(os.getenv('CLINIC_UPLOAD_DIR',str(DATA/'attachments')))
    with psycopg.connect(DATABASE_URL,connect_timeout=10) as c:
        estimate=c.execute('SELECT pg_database_size(current_database())').fetchone()[0]+tree_bytes(uploads)
    return LIMITS.min_free_bytes+2*estimate+64*1024*1024


def backup(destination, key_path, prune=True, enforce_budget=True):
    """prune/enforce_budget=False: caller (Windows scripts.backup_job) verifies the new
    file first and only then applies retention and the size budget."""
    key=key_bytes(key_path)
    keep=int(os.getenv('CLINIC_BACKUP_KEEP','7'))
    if not 2<=keep<=30:raise ValueError('Retention must keep 2 to 30 backups')
    offsite=os.getenv('CLINIC_BACKUP_OFFSITE_DIR','')
    required=os.getenv('CLINIC_REQUIRE_OFFSITE','0')
    if required not in ('0','1'):raise ValueError('CLINIC_REQUIRE_OFFSITE must be 0 or 1')
    if required=='1' and not offsite:raise ValueError('An encrypted off-server backup destination is required')
    destination=destination.resolve()
    destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    uploads=Path(os.getenv('CLINIC_UPLOAD_DIR',str(DATA/'attachments')))
    with tempfile.TemporaryDirectory(prefix='.backup-',dir=destination) as temp:
        root=Path(temp)
        with maintenance_lock(DATABASE_URL) as c:
            estimate=c.execute('SELECT pg_database_size(current_database())').fetchone()[0]+tree_bytes(uploads)
            require_space(destination,2*estimate+64*1024*1024)
            current=sum(p.stat().st_size for p in destination.glob('minhduc-*.mdbackup'))
            if enforce_budget and current+estimate>LIMITS.backup_total_bytes:
                raise StorageLimitError('Kho backup đạt ngân sách dung lượng. Giữ bản tốt cũ; quản trị kiểm tra bản ngoài máy trước khi giải phóng chỗ.')
            pg_tool('pg_dump',['--format=custom','--no-owner','--no-acl','--file',str(root/'database.dump')],DATABASE_URL)
            files={'database.dump':checksum(root/'database.dump')}
            # iterators avoid constructing a list of every attachment in RAM.
            if uploads.exists():
                for path in uploads.rglob('*'):
                    if path.is_symlink():raise ValueError('Attachment storage must not contain symlinks')
                    if path.is_file():files['attachments/'+str(path.relative_to(uploads)).replace(os.sep,'/')]=checksum(path)
            # Cài đặt giao diện đang có hiệu lực (tệp thiếu/hỏng thì là mặc định, đã ghi cảnh báo).
            settings,settings_source=load_settings(settings_path(uploads))
            (root/SETTINGS_NAME).write_bytes(serialize(settings))
            files[SETTINGS_NAME]=checksum(root/SETTINGS_NAME)
            manifest={'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'files':files,'ui_settings_source':settings_source}
            (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            if not uploads.exists():(root/'attachments').mkdir()
            name='minhduc-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.mdbackup'
            pending=root/'encrypted.tmp'
            encrypt_archive([(root/'database.dump','database.dump'),
                             (uploads if uploads.exists() else root/'attachments','attachments'),
                             (root/SETTINGS_NAME,SETTINGS_NAME),
                             (root/'manifest.json','manifest.json')],pending,key)
            if enforce_budget and current+pending.stat().st_size>LIMITS.backup_total_bytes:raise StorageLimitError('Bản backup mới vượt ngân sách dung lượng')
            target=destination/name
            os.replace(pending,target)
    # A failed offsite copy leaves the new local backup AND all old good copies.
    # This permits manual recovery and never prunes the only known good backup.
    if offsite:
        offsite_keep=int(os.getenv('CLINIC_OFFSITE_KEEP','30'))
        if not 2<=offsite_keep<=90:raise ValueError('Offsite retention must keep 2 to 90 backups')
        copy_offsite(target,offsite)
        for old in sorted(Path(offsite).glob('minhduc-*.mdbackup'),key=lambda p:p.stat().st_mtime,reverse=True)[offsite_keep:]:old.unlink()
    if prune:
        for old in sorted(destination.glob('minhduc-*.mdbackup'),key=lambda p:p.stat().st_mtime,reverse=True)[keep:]:old.unlink()
    return target


def unpack_verified(source, key_path, root):
    archive=root/'payload.tar'
    crypt_file(source,archive,key_bytes(key_path),decrypt=True)
    with tarfile.open(archive) as tar:
        for item in tar.getmembers():
            path=Path(item.name)
            if path.is_absolute() or '..' in path.parts or item.issym() or item.islnk() or not (item.isfile() or item.isdir()):
                raise ValueError('Unsafe archive member')
            if path.parts[0] not in ('database.dump','attachments','manifest.json',SETTINGS_NAME):
                raise ValueError('Unexpected archive member')
        tar.extractall(root, filter='data')
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}-{'payload.tar','manifest.json'}
    if manifest['format'] != 1 or actual != set(manifest['files']):
        raise ValueError('Backup manifest mismatch')
    for name, digest in manifest['files'].items():
        if checksum(root/name) != digest:
            raise ValueError('Backup checksum mismatch')
    return manifest


def restore(source, key_path, url, uploads, settings=None):
    """settings: nơi ghi ui_settings.json; mặc định cạnh thư mục tệp đính kèm đích,
    đúng chỗ ứng dụng đọc khi CLINIC_UPLOAD_DIR chuyển sang đích này."""
    # No in-place overwrites: operator must create a separate empty target.
    uploads = uploads.resolve()
    settings = Path(settings).resolve() if settings else uploads.parent/SETTINGS_NAME
    uploads.parent.mkdir(parents=True,exist_ok=True)
    if uploads.exists() and any(uploads.iterdir()):
        raise ValueError('Restore attachment destination must be empty')
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=uploads.parent) as temp:
        root=Path(temp)
        manifest=unpack_verified(source,key_path,root)
        restored_settings=None
        if SETTINGS_NAME in manifest['files']:
            try:restored_settings=parse_settings((root/SETTINGS_NAME).read_bytes())
            except ValueError:
                print('CẢNH BÁO: cài đặt giao diện trong bản sao không hợp lệ; ghi giá trị mặc định.')
                restored_settings=dict(SETTINGS_DEFAULTS)
        else:
            print('CẢNH BÁO: bản sao cũ chưa có cài đặt giao diện; ứng dụng sẽ dùng mặc định. Vào Cài đặt kiểm tra lại.')
        with maintenance_lock(url) as c:
            if c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]:
                raise ValueError('Restore database must be empty; never overwrite the running clinic')
            if settings.exists():
                raise ValueError('Restore settings destination already exists; never overwrite live settings')
            # Stage files first; do not expose restored state before both pieces exist.
            staged=root/'attachments'
            pg_tool('pg_restore',['--single-transaction','--exit-on-error','--no-owner','--no-acl','--dbname',unquote(urlsplit(url).path.lstrip('/')),str(root/'database.dump')],url)
            if uploads.exists():
                uploads.rmdir()
            os.replace(staged,uploads)
            if restored_settings is not None:write_settings(settings,restored_settings)
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
    parser.add_argument('--target-settings',type=Path,help='mặc định: cạnh --target-uploads, tên ui_settings.json')
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
        restore(args.file,args.key,os.environ[args.target_url_env],args.target_uploads,args.target_settings)
        print('Restored into separate empty destination; sessions revoked. Validate before switching server configuration.')


if __name__=='__main__':
    main()
