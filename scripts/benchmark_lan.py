"""Reproducible synthetic benchmark; creates/removes its own local PG container.

Never accepts a clinic database URL or existing patient directory. Linux/Docker
measurement is not a measurement of Windows 11 or the clinic's i3 CPU.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlsplit
import httpx
import psutil
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
IMAGE='postgres:17-bookworm@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994'
DOCKER=['docker','--host=unix:///var/run/docker.sock']
MIB=1048576


def docker(*args):
    result=subprocess.run([*DOCKER,*args],capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Benchmark Docker command failed (details omitted to protect generated credentials)')
    return result.stdout.strip()


def pg_options(source=ROOT):
    result=[]
    profile=source/'deploy/postgresql/minhduc-8gb.conf'
    if not profile.exists():return result
    for line in profile.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            name,value=line.split('=',1)
            # Container must listen on its bridge to reach the localhost-only
            # published port. Production profile stays loopback-only natively.
            if name.strip()=='listen_addresses':continue
            result+=['-c',name.strip()+'='+value.strip().strip("'")]
    return result


def seed(url):
    from app.auth import pw_hash
    from app.database import PGConnection,record_factory
    from app.migrations import migrate_v050
    passwords={role:secrets.token_urlsafe(24) for role in ('reception','doctor','cashier','doctor2')}
    with psycopg.connect(url,row_factory=record_factory) as c:
        c.execute((ROOT/'schema.postgresql.sql').read_text())
        migrate_v050(PGConnection(c),postgres=True)
        from app.manual_price_migration import migrate_manual_prices
        migrate_manual_prices(PGConnection(c),postgres=True)
        for i,(role,password) in enumerate(passwords.items(),1):
            salt=secrets.token_hex(16)
            c.execute('INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(%s,%s,%s,%s,%s)',(i,'fake_'+role,'Nhân viên giả lập '+role,salt,pw_hash(password,salt)))
            c.execute('INSERT INTO user_roles VALUES(%s,%s)',(i,'doctor' if role=='doctor2' else role))
        c.execute('SELECT setval(pg_get_serial_sequence(%s,%s),4)',('users','id'))
        c.execute("INSERT INTO service_catalog(name,price) VALUES('Khám giả lập benchmark',150000)")
        for i in range(1000):
            pid=c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES(%s,%s,'Chưa rõ',%s) RETURNING id",('FAKE'+str(i),'Người giả lập '+str(i),'2026-11-08')).fetchone()[0]
            vid=c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(%s,2,1,%s) RETURNING id",(pid,'2026-11-08')).fetchone()[0]
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(%s,'Giả lập',150000,%s)",(vid,'2026-11-08'))
    return passwords


def size_tree(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


class Monitor:
    def __init__(self,pid,folder=None,interval=.1):
        self.pid=pid;self.folder=folder;self.interval=interval;self.stop=threading.Event();self.samples=[]
        self.thread=threading.Thread(target=self.run,daemon=True)
    def run(self):
        while not self.stop.is_set():
            rss=uss=cpu=read=write=0;count=0
            try:
                parent=psutil.Process(self.pid)
                for process in [parent,*parent.children(recursive=True)]:
                    try:
                        rss+=process.memory_info().rss
                        try:uss+=process.memory_full_info().uss
                        except (psutil.Error,AttributeError):pass
                        times=process.cpu_times();cpu+=times.user+times.system
                        io=process.io_counters();read+=io.read_bytes;write+=io.write_bytes;count+=1
                    except psutil.Error:pass
            except psutil.Error:pass
            self.samples.append({'t':time.monotonic(),'rss':rss,'uss':uss,'cpu':cpu,'read':read,'write':write,'count':count,'disk':size_tree(self.folder) if self.folder and self.folder.exists() else 0})
            self.stop.wait(self.interval)
    def start(self):self.thread.start()
    def finish(self):
        self.stop.set();self.thread.join()
        s=self.samples or [dict(rss=0,uss=0,cpu=0,read=0,write=0,disk=0,count=0)]
        return {'rss_peak_mib':round(max(x['rss'] for x in s)/MIB,2),'uss_peak_mib':round(max(x['uss'] for x in s)/MIB,2),
                'rss_median_mib':round(statistics.median(x['rss'] for x in s)/MIB,2),
                'cpu_seconds':round(max(x['cpu'] for x in s)-s[0]['cpu'],3),'disk_read_mib':round((max(x['read'] for x in s)-s[0]['read'])/MIB,2),
                'disk_write_mib':round((max(x['write'] for x in s)-s[0]['write'])/MIB,2),
                'scratch_peak_mib':round(max(x['disk'] for x in s)/MIB,2),'process_count_peak':max(x['count'] for x in s)}


def percentile(values,p):return round(sorted(values)[min(len(values)-1,int((len(values)-1)*p))],2)


def pg_memory(container):
    command = r"""for status in /proc/[0-9]*/status; do
      base=${status%status}
      read name < "${base}comm" 2>/dev/null || continue
      [ "$name" = postgres ] || continue
      rss=$(awk '/^VmRSS:/{print $2}' "$status" 2>/dev/null)
      private=$(awk '/^Private_Clean:|^Private_Dirty:/{s+=$2} END{print s+0}' "${base}smaps_rollup" 2>/dev/null)
      printf '%s %s\n' "${rss:-0}" "${private:-0}"
    done"""
    rows=docker('exec','--user','postgres',container,'sh','-c',command).splitlines()
    values=[list(map(int,row.split())) for row in rows if len(row.split())==2]
    return {'rss_sum_mib':round(sum(row[0] for row in values)/1024,2),
            'uss_sum_mib':round(sum(row[1] for row in values)/1024,2) if any(row[1] for row in values) else None,
            'process_count':len(values),'kind':'snapshot after workload while app pool remains open, not peak'}


def run_server(source,env,root,passwords,iterations,container):
    with (root/'server-output.log').open('w') as output:
        server=subprocess.Popen([sys.executable,'-m','scripts.run_lan'],cwd=source,env=env,stdout=output,stderr=output)
        monitor=Monitor(server.pid);monitor.start()
        clients={};latencies=[];pdf_times=[];errors=[];lock=threading.Lock()
        try:
            tls=ssl.create_default_context(cafile=str(root.parent/'certs/ca.crt'))
            origin=env['CLINIC_ORIGIN']
            with httpx.Client(verify=tls,trust_env=False,timeout=1) as probe:
                for _ in range(150):
                    if server.poll() is not None:raise RuntimeError('HTTPS benchmark server exited')
                    try:
                        if probe.get(origin+'/api/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise RuntimeError('HTTPS startup timeout')
            for role in ('reception','doctor','cashier','doctor2'):
                c=httpx.Client(base_url=origin,verify=tls,trust_env=False,timeout=20,headers={'Origin':origin,'X-Clinic-Request':'1'})
                r=c.post('/api/login',json={'username':'fake_'+role,'password':passwords[role]});assert r.status_code==200
                c.headers['X-CSRF-Token']=c.cookies['__Host-clinic-csrf'];clients[role]=c
            def request(role,method,path,body=None,pdf=False,expected=200):
                start=time.perf_counter();r=clients[role].request(method,path,json=body)
                elapsed=(time.perf_counter()-start)*1000
                with lock:
                    (pdf_times if pdf else latencies).append(elapsed)
                    if r.status_code!=expected:errors.append({'endpoint':path,'status':r.status_code,'expected':expected})
                return r
            # Warm all three independent sessions and database caches.
            for role in ('reception','doctor','cashier'):
                for _ in range(3):clients[role].get('/api/visits')
            start=time.monotonic()
            def worker(role):
                for i in range(iterations):
                    if role=='reception':
                        p=request(role,'POST','/api/patients',{'full_name':'Người giả lập tải đồng thời','date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'},expected=201).json()['id']
                        request(role,'POST','/api/visits',{'patient_id':p,'doctor_id':2,'service_id':1},expected=201)
                        request(role,'GET','/api/visits')
                    elif role=='doctor':
                        request(role,'PUT','/api/visits/1/clinical',{'version':i,'history':('Ghi chú giả lập '*180),'diagnosis':'Chỉ thử nghiệm'})
                        request(role,'GET','/api/visits')
                        if i%10==0:
                            r=request(role,'GET','/api/forms/visit/1?fmt=pdf',pdf=True)
                            if not r.content.startswith(b'%PDF-'):raise RuntimeError('Invalid PDF')
                    else:
                        request(role,'POST','/api/payments',{'visit_id':1,'amount':1000,'method':'cash','idempotency_key':secrets.token_hex(16)},expected=201)
                        request(role,'GET','/api/dues')
            with ThreadPoolExecutor(max_workers=3) as executor:list(executor.map(worker,('reception','doctor','cashier')))
            elapsed=time.monotonic()-start
            assert clients['doctor2'].get('/api/visits/1').status_code==403
            assert clients['cashier'].get('/api/forms/visit/1').status_code==403
            # Send a complete TLS payment request, disconnect before reading its
            # response, then retry the SAME key. Either initial outcome is safe.
            key=secrets.token_hex(16)
            body=json.dumps({'visit_id':1,'amount':1000,'method':'cash','idempotency_key':key}).encode()
            cash=clients['cashier'];parts=urlsplit(origin)
            raw=(f'POST /api/payments HTTP/1.1\r\nHost: {parts.netloc}\r\nOrigin: {origin}\r\nX-Clinic-Request: 1\r\nX-CSRF-Token: '+cash.cookies['__Host-clinic-csrf']+'\r\nCookie: __Host-clinic='+cash.cookies['__Host-clinic']+'; __Host-clinic-csrf='+cash.cookies['__Host-clinic-csrf']+f'\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()+body
            with socket.create_connection(('127.0.0.1',parts.port),timeout=5) as connection:
                with tls.wrap_socket(connection,server_hostname='127.0.0.1') as channel:channel.sendall(raw)
            retry=cash.post('/api/payments',content=body,headers={'Content-Type':'application/json'});assert retry.status_code==201
            with psycopg.connect(env['CLINIC_DATABASE_URL']) as c:
                assert c.execute('SELECT count(*) FROM payments WHERE idempotency_key=%s',(key,)).fetchone()[0]==1
            assert not errors,errors
            return {'requests':len(latencies),'latency_ms':{'p50':percentile(latencies,.5),'p95':percentile(latencies,.95),'max':round(max(latencies),2)},
                    'pdf_latency_ms':{'p95':percentile(pdf_times,.95),'max':round(max(pdf_times),2)},
                    'elapsed_seconds':round(elapsed,2),'requests_per_second':round((len(latencies)+len(pdf_times))/elapsed,2),
                    'postgres_memory_after_load':pg_memory(container),
                    'errors':errors,'disconnect_retry_single_payment':True,'permission_checks_passed':True,'resources':monitor.finish()}
        finally:
            if not monitor.stop.is_set():monitor.finish()
            for c in clients.values():c.close()
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--iterations',type=int,default=30)
    parser.add_argument('--baseline-ref',default='0058564')
    args=parser.parse_args()
    if not 10<=args.iterations<=100:parser.error('iterations must be 10..100')
    report={'baseline_ref':args.baseline_ref,'measurement_environment':{'os':platform.system(),'architecture':platform.machine(),'clinic_windows_hardware_tested':False,
            'cgroup_memory_max':Path('/sys/fs/cgroup/memory.max').read_text().strip() if Path('/sys/fs/cgroup/memory.max').exists() else None,
            'cgroup_cpu_max':Path('/sys/fs/cgroup/cpu.max').read_text().strip() if Path('/sys/fs/cgroup/cpu.max').exists() else None,
            'postgres_container_cpu_limit':2,'postgres_container_memory_mib':1536,'synthetic_patients_seeded':1000,'synthetic_attachment_mib':16,
            'notes':['Load generator is excluded from app RSS/USS. PostgreSQL memory is reported separately.','RSS sums shared pages; USS approximates private memory. PostgreSQL is sampled from its own /proc entries, not shared Docker cgroup stats.','Benchmark reduces disk reserve to 256 MiB only in disposable test workspace.']},'profiles':{}}
    with tempfile.TemporaryDirectory(prefix='minhduc-benchmark-') as temp:
        root=Path(temp);baseline=root/'baseline';baseline.mkdir()
        archive=subprocess.run(['git','archive',args.baseline_ref],cwd=ROOT,capture_output=True,check=True).stdout
        from io import BytesIO
        with tarfile.open(fileobj=BytesIO(archive)) as tar:tar.extractall(baseline,filter='data')
        subprocess.run([sys.executable,'-m','scripts.create_lan_certificate','--name','minhduc.internal','--ip','127.0.0.1','--output',str(root/'certs')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
        for label,source in [('baseline_v04',baseline),('resource_light',ROOT)]:
            folder=root/label;folder.mkdir();uploads=folder/'attachments';uploads.mkdir()
            for i in range(16):(uploads/(str(i)+'.pdf')).write_bytes(b'%PDF-1.5\n'+secrets.token_bytes(MIB-9))
            password=secrets.token_urlsafe(32);name='minhduc-bench-'+secrets.token_hex(6)
            try:
                docker('run','-d','--name',name,'--cpus','2','--memory','1536m','-e','POSTGRES_PASSWORD='+password,'-e','POSTGRES_USER=clinic','-e','POSTGRES_DB=clinic_bench','-p','127.0.0.1::5432',IMAGE,*pg_options(source))
                port=int(json.loads(docker('inspect','--format','{{json .NetworkSettings.Ports}}',name))['5432/tcp'][0]['HostPort'])
                url=f'postgresql://clinic:{password}@127.0.0.1:{port}/clinic_bench'
                for _ in range(100):
                    try:
                        with psycopg.connect(url,connect_timeout=1):pass
                        break
                    except psycopg.OperationalError:time.sleep(.1)
                else:raise RuntimeError('Disposable PostgreSQL did not start')
                passwords=seed(url)
                with socket.socket() as socket_probe:
                    socket_probe.bind(('127.0.0.1',0));webport=socket_probe.getsockname()[1]
                env=os.environ.copy();env.update(CLINIC_MODE='lan',CLINIC_DATABASE_URL=url,CLINIC_ORIGIN=f'https://127.0.0.1:{webport}',
                    CLINIC_BIND_IP='127.0.0.1',CLINIC_ALLOWED_CIDRS='127.0.0.1/32',CLINIC_DATA_DIR=str(folder),CLINIC_UPLOAD_DIR=str(uploads),
                    CLINIC_TLS_CERT=str(root/'certs/server.crt'),CLINIC_TLS_KEY=str(root/'certs/server.key'),CLINIC_MIN_FREE_MB='256',CLINIC_BACKUP_KEEP='7',PYTHONPATH='')
                result=run_server(source,env,folder,passwords,args.iterations,name)
                key=folder/'backup.key';key.write_bytes(secrets.token_bytes(32));key.chmod(0o600)
                with (folder/'backup-output.log').open('w') as output:
                    backup=subprocess.Popen([sys.executable,'-m','scripts.backup_lan','backup','--key',str(key),'--directory',str(folder/'backups')],cwd=source,env=env,stdout=output,stderr=output)
                    measure=Monitor(backup.pid,folder/'backups',interval=.01);measure.start()
                    if backup.wait(timeout=90):raise RuntimeError('Synthetic backup benchmark failed')
                    result['backup_resources']=measure.finish()
                with psycopg.connect(url) as c:
                    result['database_mib']=round(c.execute('SELECT pg_database_size(current_database())').fetchone()[0]/MIB,2)
                    result['wal_mib']=float(round(c.execute('SELECT sum(size) FROM pg_ls_waldir()').fetchone()[0]/MIB,2))
                    result['durability']={setting:c.execute(sql.SQL('SHOW {}').format(sql.Identifier(setting))).fetchone()[0] for setting in ('fsync','synchronous_commit','full_page_writes')}
                report['profiles'][label]=result
            finally:
                subprocess.run([*DOCKER,'rm','-fv',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
