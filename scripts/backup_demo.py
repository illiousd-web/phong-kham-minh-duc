"""Consistent SQLite backup + attachment archive for LOCAL DEMO only.

Usage:
    python scripts/backup_demo.py create
    python scripts/backup_demo.py verify backups/filename.zip
No automatic upload, remote sync or restoration over an existing database.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=Path(os.environ.get('CLINIC_DB_PATH',ROOT/'data'/'minh_duc_demo.sqlite3'))
UPLOADS=Path(os.environ.get('CLINIC_UPLOAD_DIR',str(DB.parent/'attachments')))
BACKUPS=ROOT/'backups'

def digest(data:bytes)->str:return hashlib.sha256(data).hexdigest()

def create(out:Path|None=None)->Path:
    if not DB.is_file():raise RuntimeError('Chưa có cơ sở dữ liệu để sao lưu: '+str(DB))
    BACKUPS.mkdir(parents=True,exist_ok=True)
    if out is None:
        out=BACKUPS/('MinhDuc_demo_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.zip')
    if out.exists():raise RuntimeError('Tệp sao lưu đã tồn tại, không ghi đè')
    with tempfile.TemporaryDirectory(prefix='md-backup-') as td:
        snap=Path(td)/'database.sqlite3'
        src=sqlite3.connect(DB);dest=sqlite3.connect(snap)
        try:src.backup(dest)
        finally:dest.close();src.close()
        chk=sqlite3.connect(snap)
        try:
            if chk.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Bản sao lưu SQLite không đạt integrity_check')
        finally:chk.close()
        items={'database.sqlite3':snap.read_bytes()}
        if UPLOADS.is_dir():
            for file in UPLOADS.rglob('*'):
                if file.is_file() and not file.is_symlink():
                    rel=file.relative_to(UPLOADS)
                    if '..' not in rel.parts:items['attachments/'+rel.as_posix()]=file.read_bytes()
        manifest={'created_at_utc':datetime.now(timezone.utc).isoformat(),
                  'application':'MinhDuc local demo','archive_sha256_by_path':{k:digest(v) for k,v in items.items()}}
        with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
            for name,raw in items.items():z.writestr(name,raw)
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
    return out

def verify(path:Path)->dict:
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP bị lỗi CRC')
        names=set(z.namelist());m=json.loads(z.read('manifest.json'))
        for name,sha in m['archive_sha256_by_path'].items():
            if name not in names or digest(z.read(name))!=sha:raise RuntimeError('Bản sao lưu hỏng hoặc sai hash: '+name)
        with tempfile.TemporaryDirectory(prefix='md-backup-verify-') as td:
            sql=Path(td)/'snapshot.sqlite3'
            sql.write_bytes(z.read('database.sqlite3'))
            c=sqlite3.connect(sql)
            try:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite trong sao lưu không nhất quán')
                tables=c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            finally:c.close()
    return {'verified':True,'files':len(m['archive_sha256_by_path']),'tables':tables,'manifest_created_at':m['created_at_utc']}

def main():
    pa=argparse.ArgumentParser(description=__doc__)
    sub=pa.add_subparsers(dest='command',required=True)
    cp=sub.add_parser('create');cp.add_argument('--out',type=Path)
    vp=sub.add_parser('verify');vp.add_argument('archive',type=Path)
    args=pa.parse_args()
    try:
        if args.command=='create':
            a=create(args.out);print('Sao lưu thử nghiệm:',a);print('Kiểm tra:',verify(a))
        else:print('Kiểm tra bản sao:',verify(args.archive))
    except Exception as ex:
        print('LỖI:',ex,file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(main())
