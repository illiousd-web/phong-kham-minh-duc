"""S1b migration 13, public TT18 files supplied and authorized by owner."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

FILES = {
 'TT18_2026_DUOC_CHAT_KIEM_SOAT.csv':(122,'27eefdbfcd095ab09ef69da83c92b23a62b0fd34c0d42ecf904fe46807d4b7cd'),
 'TT18_2026_GIOI_HAN_PHOI_HOP.csv':(62,'9019e0d8569c4e6ff81145ca0f3d3bfc2a804d1d1085620f0dd374e515e186f7'),
}


def source_rows(filename):
    raw=(Path(__file__).resolve().parents[1]/'data/danh_muc_goc'/filename).read_bytes()
    count, digest=FILES[filename]
    if hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('CSV TT18 sai SHA-256: '+filename)
    rows=list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    if len(rows)!=count:raise RuntimeError('CSV TT18 sai số dòng: '+filename)
    return rows


def migrate_controlled(c):
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=13').fetchone():return
    from .controlled_substances import aliases,key,flag_drug
    substances=source_rows('TT18_2026_DUOC_CHAT_KIEM_SOAT.csv')
    limits=source_rows('TT18_2026_GIOI_HAN_PHOI_HOP.csv')
    c.execute('''CREATE TABLE controlled_substances(source_key TEXT PRIMARY KEY,name TEXT NOT NULL,
      controlled_type TEXT NOT NULL,source_json TEXT NOT NULL,limits_json TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)''')
    c.execute('''CREATE TABLE controlled_substance_aliases(alias_key TEXT NOT NULL,substance_key TEXT NOT NULL REFERENCES controlled_substances(source_key),
      alias TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(alias_key,substance_key))''')
    for row in substances:
        source_key=row['phu_luc']+':'+row['stt']
        names = [x.strip() for x in row['ten_quoc_te'].split(';') if x.strip()]
        alternate = [x.strip() for x in row['ten_thong_dung_khac'].split(';') if x.strip()]
        all_aliases = {alias for name in names+alternate for alias in aliases(name)}
        keys = {key(alias) for alias in all_aliases}
        matched = [r for r in limits if key(r['duoc_chat']) in keys]
        kind = {'I':'N','II':'H','III':'precursor'}[row['phu_luc'].split(' ')[0]]
        c.execute('INSERT INTO controlled_substances VALUES(?,?,?,?,?,1)',(source_key,row['ten_quoc_te'],kind,json.dumps(row,ensure_ascii=False),json.dumps(matched,ensure_ascii=False)))
        for alias in sorted(all_aliases):
            c.execute('INSERT INTO controlled_substance_aliases VALUES(?,?,?,?) ON CONFLICT(alias_key,substance_key) DO NOTHING',(key(alias),source_key,alias,'public/rule'))
    stamp=datetime.now(timezone.utc).isoformat()
    for filename,(count,digest) in FILES.items():
        c.execute('''INSERT INTO catalog_imports(kind,document_number,document_date,source,version,fingerprint,mapping,created_at,row_count)
          VALUES(?,?,?,?,?,?,?,?,?)''',('controlled_substances' if count==122 else 'controlled_limits','TT 18/2026/TT-BYT','2026-06-01',filename,'2026-07-16',digest,'{}',stamp,count))
    def audit(conn,u,event,typ,obj,details):
        conn.execute('INSERT INTO audit_log(event,object_type,object_id,details,created_at) VALUES(?,?,?,?,?)',(event,typ,obj,details,stamp))
    for drug in c.execute('SELECT id,ingredient FROM drugs').fetchall():flag_drug(c,drug['id'],drug['ingredient'],None,audit)
    c.execute('INSERT INTO schema_migrations(version) VALUES(13)')
