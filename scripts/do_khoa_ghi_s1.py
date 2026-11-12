"""Measure acquired-lock-to-commit time through real APIs on disposable synthetic C5.

Never uses the clinic database. The C5 generator refuses existing databases.
No production instrumentation or patient data are logged. Run with
CLINIC_PERF_SOURCE_DATABASE_URL pointing to a local disposable PostgreSQL server.
"""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=20)
    args = parser.parse_args()
    if args.samples < 20:
        parser.error('Cần ít nhất 20 mẫu cho p95')
    source = os.environ['CLINIC_PERF_SOURCE_DATABASE_URL']
    name = 'clinic_perf_test_' + secrets.token_hex(6)
    url = urlunsplit(urlsplit(source)._replace(path='/'+name))
    with tempfile.TemporaryDirectory(prefix='s1-lock-c5-') as temporary:
        data = Path(temporary)/name
        os.environ.update(CLINIC_MODE='lan', CLINIC_DATABASE_URL=url, CLINIC_DATA_DIR=str(data),
            CLINIC_UPLOAD_DIR=str(data/'attachments'), CLINIC_ORIGIN='https://127.0.0.1:58443',
            CLINIC_ALLOWED_CIDRS='127.0.0.1/32', CLINIC_BIND_IP='127.0.0.1', CLINIC_MIN_FREE_MB='256')
        from scripts.tao_du_lieu_gia import generate, CONFIRM
        import psycopg
        from psycopg import sql
        try:
            manifest = generate(source, name, data, CONFIRM)
            from app import database
            database.migrate()
            from app.main import app
            from fastapi.testclient import TestClient
            credentials = json.loads((data/'credentials.json').read_text())
            clients = {}
            for role in ('doctor','admin','cashier'):
                c = TestClient(app, base_url=os.environ['CLINIC_ORIGIN'], client=('127.0.0.1',1234))
                c.headers.update({'Origin':os.environ['CLINIC_ORIGIN'],'X-Clinic-Request':'1'})
                r = c.post('/api/login', json={k:credentials[role][k] for k in ('username','password')})
                assert r.status_code == 200, r.text
                c.headers['X-CSRF-Token'] = c.cookies['__Host-clinic-csrf']
                clients[role] = c
            doctor, admin, cashier = (clients[r] for r in ('doctor','admin','cashier'))
            def ok(r):
                assert r.status_code in (200,201), (r.status_code,r.text)
                return r.json()
            ok(admin.put('/api/standards/settings',json={'require_primary_icd10':False}))
            ok(admin.put('/api/practitioners/'+str(manifest['roles']['doctor']),json={'practice_license':'GP-GIA-LAP-C5','practice_scopes':['Nội']}))
            ok(admin.put('/api/prescription-settings',json={'clinic_facility_code':'ZZ001','clinic_name':'Cơ sở giả lập C5'}))
            vid = manifest['doctor_visit']
            label = ContextVar('s1_lock_measurement', default=None)
            samples = {k:[] for k in ('clinical_save','payment','prescription_lock','icd10_import')}
            actual_pool = database.pool()
            class Cursor:
                def __init__(self, cursor, owner): self.cursor,self.owner=cursor,owner
                def fetchone(self):
                    row=self.cursor.fetchone()
                    if row[0]: self.owner.started=time.perf_counter()
                    return row
                def __getattr__(self,key): return getattr(self.cursor,key)
            class Connection:
                def __init__(self, raw): self.raw,self.started=raw,None
                def __getattr__(self,key): return getattr(self.raw,key)
                def execute(self, query, params=()):
                    result=self.raw.execute(query,params)
                    if isinstance(query,str) and query=='SELECT pg_try_advisory_xact_lock(%s)':
                        return Cursor(result,self)
                    return result
                @contextmanager
                def transaction(self):
                    with self.raw.transaction(): yield
                    if self.started is not None and label.get():
                        samples[label.get()].append(time.perf_counter()-self.started)
            class Pool:
                @contextmanager
                def connection(self):
                    with actual_pool.connection() as c: yield Connection(c)
            database.pool=lambda:Pool()
            def measure(key, action):
                token=label.set(key)
                try: return ok(action())
                finally: label.reset(token)
            from app.d0_sources import ROOT,SOURCES
            raw=(ROOT/SOURCES['icd10'][0]).read_bytes()
            meta=json.dumps({'document_number':'Đo giả lập C5','document_date':None,'source':'Tệp công khai chủ dự án cung cấp','version':'s1-lock-c5'})
            upload={'files':{'file':('ICD10_TT06_2026.csv',raw)},'data':{'metadata':meta,'preview':'true'}}
            proof=ok(admin.post('/api/standards/icd10/import',**upload))['fingerprint']
            upload['data'].update(preview='false',proof=proof)
            for i in range(args.samples):
                version=ok(doctor.get(f'/api/visits/{vid}'))['version']
                measure('clinical_save',lambda:doctor.put(f'/api/visits/{vid}/clinical',json={'version':version,'diagnosis':'Chẩn đoán giả lập C5'}))
                measure('payment',lambda:cashier.post('/api/payments',json={'visit_id':vid,'amount':1,'method':'cash','idempotency_key':secrets.token_hex(16)}))
                rx=ok(doctor.post('/api/clinical-prescriptions',json={'visit_id':vid,'items':[{'name':'Thuốc giả lập C5 S1','ingredient':'Chất giả lập C5','dose':'1','frequency':'1','days':'1','route':'Uống','unit':'viên'}]}))['id']
                measure('prescription_lock',lambda:doctor.post(f'/api/clinical-prescriptions/{rx}/lock',json={'version':0}))
                measure('icd10_import',lambda:admin.post('/api/standards/icd10/import',**upload))
                print(f'Mẫu {i+1}/{args.samples}',flush=True)
            result={'synthetic_only':True,'platform':'Linux cục bộ; chưa đại diện Windows/i3','dataset':manifest['counts'],'attachments':manifest['attachments'],
                'measurement':'Từ lúc lấy được khóa ghi nghiệp vụ/danh mục đến sau COMMIT; không gồm thời gian chờ khóa, parse CSV hay mạng',
                'operations':{k:{'n':len(v),'p50_ms':round(statistics.median(v)*1000,3),'p95_ms':round(sorted(v)[math.ceil(.95*len(v))-1]*1000,3)} for k,v in samples.items()}}
            assert all(len(v)==args.samples for v in samples.values()), {k:len(v) for k,v in samples.items()}
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(result,ensure_ascii=False),flush=True)
            for c in clients.values(): c.close()
        finally:
            from app import database
            if database._pool: database._pool.close()
            with psycopg.connect(source,autocommit=True) as c:
                c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


if __name__ == '__main__': main()
