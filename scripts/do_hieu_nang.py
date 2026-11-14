"""C5: đo trước/sau cùng dữ liệu qua HTTPS và Chromium; không dùng dữ liệu thật."""
import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import secrets
import socket
import ssl
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
import psutil
import psycopg
from psycopg import sql

from scripts.ui_wait import wait_for_login

ROOT=Path(__file__).resolve().parents[1]
MIB=1024**2
JOB_HANDLE=None


def windows_limits():
    """Job 8 GiB, hai CPU logic cho cả trình đo và mọi tiến trình con mới."""
    if os.name!='nt':
        return {'applied':False,'reason':'Đây là lượt đo cục bộ Linux, không giả là Windows/i3'}
    import ctypes as ct
    from ctypes import wintypes as w
    class Basic(ct.Structure):
        _fields_=[('PerProcessUserTimeLimit',ct.c_longlong),('PerJobUserTimeLimit',ct.c_longlong),
                  ('LimitFlags',w.DWORD),('MinimumWorkingSetSize',ct.c_size_t),('MaximumWorkingSetSize',ct.c_size_t),
                  ('ActiveProcessLimit',w.DWORD),('Affinity',ct.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
    class IO(ct.Structure):
        _fields_=[(name,ct.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class Extended(ct.Structure):
        _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ct.c_size_t),
                  ('JobMemoryLimit',ct.c_size_t),('PeakProcessMemoryUsed',ct.c_size_t),('PeakJobMemoryUsed',ct.c_size_t)]
    kernel=ct.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ct.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ct.c_int,ct.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.GetCurrentProcess.restype=w.HANDLE
    cpus=psutil.Process().cpu_affinity()[:2]
    limits=Extended();limits.BasicLimitInformation.LimitFlags=0x200|0x10|0x2000
    limits.BasicLimitInformation.Affinity=sum(1<<n for n in cpus);limits.JobMemoryLimit=8*1024**3
    global JOB_HANDLE
    JOB_HANDLE=kernel.CreateJobObjectW(None,None)
    if not JOB_HANDLE or not kernel.SetInformationJobObject(JOB_HANDLE,9,ct.byref(limits),ct.sizeof(limits)):
        raise ct.WinError(ct.get_last_error())
    if not kernel.AssignProcessToJobObject(JOB_HANDLE,kernel.GetCurrentProcess()):
        raise ct.WinError(ct.get_last_error())
    psutil.Process().cpu_affinity(cpus)
    return {'applied':True,'logical_cpus':cpus,'job_commit_limit_mib':8192,
            'note':'Giới hạn nhóm tiến trình, không thay RAM/cache toàn máy; không coi là đo trên i3 vật lý'}


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


@contextmanager
def postgres_cluster(bin_path, root):
    if os.name=='nt':
        # initdb tự bỏ quyền Administrators. Thư mục tempfile của Python khi
        # chạy elevated có thể chỉ cấp quyền qua nhóm đó; cấp rõ cho đúng
        # tài khoản đang chạy, chỉ trên thư mục giả lập mới, trước khi tạo con.
        subprocess.run(['icacls',str(root),'/grant:r',psutil.Process().username()+':(OI)(CI)F','/Q'],
                       check=True,stdout=subprocess.DEVNULL)
    password=secrets.token_urlsafe(32);pw=root/'pg-password.txt';pw.write_text(password,encoding='utf-8');pw.chmod(0o600)
    binary=lambda name:str(bin_path/(name+('.exe' if os.name=='nt' else '')))
    data=root/'postgres';port=free_port()
    subprocess.run([binary('initdb'),'-D',str(data),'-U','c5_owner','--pwfile',str(pw),'-A','scram-sha-256','--encoding=UTF8','--locale=C'],check=True,stdout=subprocess.DEVNULL)
    options=f'-h 127.0.0.1 -p {port} -c shared_buffers=256MB -c work_mem=4MB -c max_connections=32'
    subprocess.run([binary('pg_ctl'),'-D',str(data),'-l',str(root/'postgres.log'),'-o',options,'-w','start'],check=True,stdout=subprocess.DEVNULL)
    try:
        yield f'postgresql://c5_owner:{password}@127.0.0.1:{port}/postgres',int((data/'postmaster.pid').read_text(encoding='utf-8').splitlines()[0])
    finally:
        subprocess.run([binary('pg_ctl'),'-D',str(data),'-m','fast','-w','stop'],check=True,stdout=subprocess.DEVNULL)


class Memory:
    def __init__(self, app_pid, pg_pid):
        self.roots={'service':app_pid,'postgres':pg_pid};self.peaks={'service':0,'postgres':0};self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)

    def run(self):
        while not self.stop.is_set():
            for label,pid in self.roots.items():
                if not pid:continue
                try:
                    root=psutil.Process(pid);total=0
                    for process in [root]+root.children(recursive=True):
                        try:
                            memory=process.memory_info()
                            total+=max(memory.rss,getattr(memory,'peak_wset',0))
                        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                    self.peaks[label]=max(self.peaks[label],total)
                except psutil.NoSuchProcess:pass
            self.stop.wait(.05)

    def __enter__(self):self.thread.start();return self

    def __exit__(self,*args):self.stop.set();self.thread.join()

    def result(self):
        return {key+suffix:number for key,value in self.peaks.items()
                for suffix,number in [('_peak_bytes',value),('_peak_mib',round(value/MIB,3)),('_peak_mb',round(value/1000000,3))]}


def measure(label, action, *, samples=20, prepare=lambda:None):
    values=[];errors=[]
    try:
        prepare();action()  # Một lần làm nóng, không đưa vào mẫu.
        for _ in range(samples):
            prepare()  # Mở màn hình trước đó; không cộng hai thao tác vào một.
            started=time.perf_counter();action();values.append(time.perf_counter()-started)
    except Exception as error:
        # Baseline có thể chậm/hỏng: ghi lại, không biến timeout thành mẫu đạt.
        errors.append(type(error).__name__+': '+str(error)[:240])
    result={'samples_seconds':values,'sample_count':len(values),'errors':errors,
            'median_seconds':statistics.median(values) if values else None,
            'p95_seconds':sorted(values)[math.ceil(.95*len(values))-1] if values else None,
            'max_seconds':max(values) if values else None}
    result['passed']=not errors and len(values)==samples and result['median_seconds']<=1.5 and result['p95_seconds']<=3
    print(label+': '+json.dumps({k:v for k,v in result.items() if k!='samples_seconds'},ensure_ascii=False),flush=True)
    return result


def migrate_profile_schema(c):
    """Only prepare the current schema; measurement and limits stay unchanged."""
    from app.m0_migration import migrate_m0
    from app.administrative_migration import migrate_administrative
    from app.patient_catalog import migrate_public_catalog
    from app.m6_migration import migrate_m6
    from app.m5_migration import migrate_m5
    from app.d0_migration import migrate_d0
    from app.d0_source_migration import migrate_source_catalogs
    from app.s1_migration import migrate_s1
    from app.controlled_migration import migrate_controlled
    from app.order_result_migration import migrate_result_versions
    for _ in range(2):
        migrate_m0(c);migrate_administrative(c);migrate_public_catalog(c)
        migrate_m6(c,postgres=True);migrate_m5(c,postgres=True);migrate_d0(c,postgres=True);migrate_source_catalogs(c,postgres=True)
        migrate_s1(c)
        migrate_controlled(c);migrate_result_versions(c,postgres=True)


def database_state(url):
    with psycopg.connect(url) as c:
        tables=[r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        counts={table:c.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] for table in tables}
        money=c.execute('SELECT (SELECT COALESCE(SUM(amount),0) FROM effective_charges), (SELECT COALESCE(SUM(amount),0) FROM payments)').fetchone()
        stock=list(c.execute('SELECT id,quantity FROM stock_lots ORDER BY id'))
    return {'tables':counts,'money':[int(x) for x in money],'stock':[list(x) for x in stock]}


def files_state(root):
    return {str(p.relative_to(root)).replace(os.sep,'/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def query_probes(url, since, output):
    """Đối chứng JIT cùng SQL/dữ liệu trên chính máy Windows, không đổi cấu hình DB."""
    tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    from app.charge_queries import DUES_SQL,orders_sql
    def query_in(name,prefix):
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        return next(n.value for n in ast.walk(function) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith(prefix))
    queries={'dues':(DUES_SQL,(since,)),
             # The before probe uses the populated pre-S1 schema. API measurements
             # after migration use the normal atomic content+version query.
             'orders':(orders_sql(include_versions=False),()),
             'payments':(query_in('list_payments','SELECT m.id,'),())}
    report={}
    with psycopg.connect(url) as c:
        report['jit_available']=c.execute('SELECT pg_jit_available()').fetchone()[0]
        report['postgres_version']=c.execute('SELECT version()').fetchone()[0]
        for label,(query,args) in queries.items():
            results=None;report[label]={};query=query.replace('?','%s')
            for setting in ('on','off'):
                c.execute('SET LOCAL jit = '+setting)
                first=c.execute(query,args).fetchall()
                if results is None:results=first
                assert first==results, 'JIT làm đổi kết quả '+label
                samples=[]
                for _ in range(5):
                    started=time.perf_counter();actual=c.execute(query,args).fetchall();samples.append(time.perf_counter()-started)
                    assert actual==results
                plan=c.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query,args).fetchone()[0]
                value={'median_seconds':statistics.median(samples),'max_seconds':max(samples),
                       'samples_seconds':samples,'rows':len(first),'jit':plan[0].get('JIT'),
                       'execution_ms':plan[0]['Execution Time'],'plan':plan}
                report[label][setting]=value
                print('C5 SQL '+label+' JIT '+setting+': '+json.dumps({k:v for k,v in value.items() if k!='plan'}),flush=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def worker(args):
    # Nạp đúng mã trước/sau trong tiến trình riêng, tránh config/app cache lẫn nhau.
    sys.path.insert(0,str(args.source))
    from scripts import backup_lan
    root=args.workspace;root.mkdir(parents=True,exist_ok=True)
    if args.worker=='backup':
        key=Path(os.environ['C5_BACKUP_KEY'])
        started=time.perf_counter();target=backup_lan.backup(root/'backups',key)
        saved=time.perf_counter()
        result={'backup_seconds':saved-started,'backup_path':str(target),
                'verified_files':0,'backup_verified':False}
        try:
            with tempfile.TemporaryDirectory(dir=root) as temp:
                manifest=backup_lan.unpack_verified(target,key,Path(temp))
            result.update(verified_files=len(manifest['files']),backup_verified=True)
        except ValueError as error:
            # Ghi lỗi của mã trước C5 để vẫn đo được bản sau. Tuyệt đối không
            # gọi restore hoặc coi backup này là đạt khi kiểm manifest thất bại.
            result['verification_error']=type(error).__name__+': '+str(error)
        result.update(verify_seconds=time.perf_counter()-saved,backup_verify_seconds=time.perf_counter()-started)
    else:
        started=time.perf_counter()
        backup_lan.restore(Path(os.environ['C5_BACKUP']),Path(os.environ['C5_BACKUP_KEY']),os.environ['C5_RESTORE_URL'],root/'attachments')
        result={'restore_seconds':time.perf_counter()-started}
    args.output.write_text(json.dumps(result),encoding='utf-8')


def run_profile(source, label, env, data, manifest, pg_pid, output):
    from playwright.sync_api import sync_playwright,expect
    import base64
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    credentials=json.loads((data/'credentials.json').read_text(encoding='utf-8'))
    result={'screens':{},'source':str(source),'errors':[],'restored_exact':False,'passed':False}
    profile=data/label;profile.mkdir()
    log=(profile/'service.log').open('w',encoding='utf-8')
    app=subprocess.Popen([sys.executable,'-m','scripts.run_lan'],cwd=source,env=env,stdout=log,stderr=log)
    cert=x509.load_pem_x509_certificate(Path(env['CLINIC_TLS_CERT']).read_bytes())
    pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    try:
        with Memory(app.pid,pg_pid) as memory:
            for _ in range(150):
                if app.poll() is not None:raise RuntimeError('Dịch vụ kiểm thử không khởi động: '+(profile/'service.log').read_text(encoding='utf-8')[-1000:])
                try:
                    httpx.get(env['CLINIC_ORIGIN']+'/api/health',verify=ssl.create_default_context(cafile=str(data/'certs/ca.crt')),trust_env=False,timeout=1).raise_for_status();break
                except (httpx.HTTPError,OSError):time.sleep(.1)
            else:raise RuntimeError('Dịch vụ kiểm thử chưa sẵn sàng')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or None,headless=True,
                    args=['--no-sandbox','--disable-dev-shm-usage','--ignore-certificate-errors-spki-list='+pin])
                result['browser_version']=browser.version
                pages={}
                def settled(page):
                    expect(page.locator('#workspace')).to_have_attribute('aria-busy','false')
                    assert 'Không thể tải trang:' not in page.locator('#workspace').inner_text()
                def go(page,where):
                    page.locator(f'#navigation [data-page="{where}"]').click()
                    expect(page.locator('#workspace')).to_have_attribute('data-page',where);settled(page)
                for role,value in credentials.items():
                    context=browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000})
                    page=context.new_page();page.set_default_timeout(15000);pages[role]=page
                    page.on('pageerror',lambda error:result['errors'].append(str(error)))
                    page.goto(env['CLINIC_ORIGIN']);page.locator('[name="username"]').fill(value['username']);page.locator('[name="password"]').fill(value['password'])
                    page.locator('[data-form="login"] button').click();wait_for_login(page)
                    where={'technician':'lab'}.get(role,role)
                    result['screens']['hang_cho_'+role]=measure('Hàng chờ '+role,lambda page=page,where=where:go(page,where))
                # Ngoài khoảng đo: chứng minh tốc độ không đến từ việc cắt mất hàng chờ.
                result['queue_coverage']={}
                for role in ('technician','reception','doctor','nurse'):
                    path='/orders' if role=='technician' else '/visits'
                    rows=pages[role].evaluate("async path=>await api(path)",path)
                    status='ordered' if role=='technician' else None
                    ids=[row['id'] for row in rows if row['status']==status or (status is None and row['status'] not in ('completed','cancelled'))]
                    expected=manifest['active_visits']*(4 if role=='technician' else 1)
                    key='lab' if role=='technician' else role
                    badge=pages[role].evaluate("async key=>(await api('/queue-counts'))[key]",key)
                    result['queue_coverage'][role]={'actual':len(ids),'badge':badge,'expected':expected,'unique':len(set(ids))==len(ids)}
                    if label=='after' and (len(ids)!=expected or badge!=expected or len(set(ids))!=len(ids)):
                        result['errors'].append('Hàng chờ '+role+' thiếu hoặc trùng việc')
                doctor=pages['doctor'];visit=manifest['doctor_visit']
                def clinical():
                    doctor.locator(f'[data-action="pick"][data-kind="visit"][data-id="{visit}"]').click();settled(doctor)
                    expect(doctor.locator('[data-form="clinical"] [name="diagnosis"]')).to_have_value('Chẩn đoán giả lập C5')
                result['screens']['phieu_kham']=measure('Mở phiếu khám',clinical,prepare=lambda:go(doctor,'doctor'))
                reception=pages['reception']
                def patient_search():
                    go(reception,'reception');reception.locator('#search-patients').fill(manifest['patient_query'])
                    with reception.expect_response(lambda r:'/api/patients?' in r.url):reception.locator('[data-form="patient-search"] button.btn').click()
                    settled(reception);expect(reception.locator('#workspace')).to_contain_text(manifest['patient_query'])
                result['screens']['tim_benh_nhan']=measure('Tìm bệnh nhân',patient_search)
                manager=pages['manager'];today=datetime.fromisoformat(manifest['today']);end=today.replace(day=1)-timedelta(days=1);begin=end.replace(day=1)
                def month():
                    go(manager,'manager');manager.get_by_role('tab',name='Lượt khám',exact=True).click();settled(manager)
                    manager.locator('[name="vs_from"]').fill(begin.strftime('%d/%m/%Y'));manager.locator('[name="vs_to"]').fill(end.strftime('%d/%m/%Y'))
                    manager.locator('[name="vs_q"]').fill('');manager.locator('[name="vs_money"]').select_option('')
                    with manager.expect_response(lambda r:'/api/manager/visits?' in r.url) as response:
                        manager.locator('[data-form="mgr-visit-search"] button').click()
                    assert response.value.status==200 and response.value.json()['total']>0;settled(manager)
                result['screens']['tra_cuu_thang']=measure('Tra cứu lượt khám trọn tháng',month)
                def pdf():
                    with doctor.expect_download() as download:doctor.locator('[data-form="clinical"] [data-kind="visit"][data-format="pdf"]').click()
                    path=profile/'phieu-kham.pdf';download.value.save_as(str(path))
                    import pymupdf
                    with pymupdf.open(path) as doc:assert len(doc)>0 and 'Chẩn đoán giả lập C5' in ''.join(p.get_text() for p in doc)
                def prepare_pdf():
                    go(doctor,'doctor');clinical()
                result['screens']['in_pdf']=measure('In PDF phiếu khám',pdf,prepare=prepare_pdf)
                browser.close()
            # Đóng phiên đo và dừng app giả lập trước khi chụp trạng thái nguồn.
            # Request GET cũ có thể còn ghi last_seen/nhật ký sau browser.close;
            # không so snapshot trước request với backup sau request rồi báo sai.
            app.terminate()
            try:app.wait(timeout=15)
            except subprocess.TimeoutExpired:app.kill();app.wait()
            for _ in range(200):
                with psycopg.connect(env['CLINIC_DATABASE_URL']) as c:
                    remaining=c.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='c5-service'").fetchone()[0]
                if not remaining:break
                time.sleep(.05)
            else:raise RuntimeError('Phiên dịch vụ giả lập chưa đóng, chưa đo backup')
            before=database_state(env['CLINIC_DATABASE_URL']);attachments=files_state(data/'attachments')
            cmd=[sys.executable,str(ROOT/'scripts/do_hieu_nang.py'),'--source',str(source),'--workspace',str(profile)]
            subprocess.run(cmd+['--worker','backup','--output',str(profile/'backup.json')],env=env,check=True,timeout=960)
            backup=json.loads((profile/'backup.json').read_text(encoding='utf-8'));result.update(backup)
            result['restored_exact']=False
            if not backup['backup_verified']:
                result['errors'].append(backup['verification_error'])
            else:
                assert backup['verified_files']==manifest['attachments']+2
                target=manifest['database_name']+'_restore_'+label
                with psycopg.connect(os.environ['CLINIC_PERF_SOURCE_DATABASE_URL'],autocommit=True) as c:
                    c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
                restore_url=urlunsplit(urlsplit(env['CLINIC_DATABASE_URL'])._replace(path='/'+target))
                try:
                    restore_env={**env,'C5_BACKUP':backup['backup_path'],'C5_RESTORE_URL':restore_url}
                    subprocess.run(cmd+['--worker','restore','--workspace',str(profile/'restored'),'--output',str(profile/'restore.json')],env=restore_env,check=True,timeout=960)
                    result.update(json.loads((profile/'restore.json').read_text(encoding='utf-8')))
                    restored=database_state(restore_url)
                    expected={**before,'tables':dict(before['tables'])}
                    # Hợp đồng restore đã có: hủy mọi phiên trình duyệt và ghi
                    # đúng một sự kiện backup_restored; mọi dữ liệu nghiệp vụ giữ nguyên.
                    expected['tables']['sessions']=0;expected['tables']['audit_log']+=1
                    result['restore_checks']={'source':before,'expected':expected,'restored':restored}
                    assert restored==expected,('Khôi phục không khớp số dòng/tiền/kho',expected,restored)
                    with psycopg.connect(restore_url) as c:
                        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='backup_restored'").fetchone()[0]==1
                    assert files_state(profile/'restored/attachments')==attachments,'Tệp khôi phục không khớp SHA-256'
                    result['restored_exact']=True
                finally:
                    with psycopg.connect(os.environ['CLINIC_PERF_SOURCE_DATABASE_URL'],autocommit=True) as c:
                        c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
            result.update(memory.result())
            assert result['service_peak_bytes']>0 and result['postgres_peak_bytes']>0, 'Chưa lấy được số đo RAM của dịch vụ/PostgreSQL'
    finally:
        app.terminate()
        try:app.wait(timeout=15)
        except subprocess.TimeoutExpired:app.kill();app.wait()
        log.close()
        if sys.exc_info()[1] is not None:
            result['errors'].append('Đo bị dừng: '+type(sys.exc_info()[1]).__name__)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    result['passed']=all(x['passed'] for x in result['screens'].values()) and result['backup_verified'] and result['backup_verify_seconds']<=900 and result['service_peak_bytes']<=500000000 and not result['errors'] and result['restored_exact']
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def benchmark(args,source_url,pg_pid,temporary,limits):
    from scripts.tao_du_lieu_gia import generate,CONFIRM
    name='clinic_perf_test_'+secrets.token_hex(6);data=temporary/name
    manifest=generate(source_url,name,data,CONFIRM)
    url=urlunsplit(urlsplit(source_url)._replace(path='/'+name))
    (data/'backup.key').write_bytes(secrets.token_bytes(32))
    baseline=temporary/'baseline';baseline.mkdir()
    with (temporary/'baseline.tar').open('wb') as handle:subprocess.run(['git','archive',args.baseline_ref],cwd=ROOT,stdout=handle,check=True)
    with tarfile.open(temporary/'baseline.tar') as archive:archive.extractall(baseline,filter='data')
    subprocess.run([sys.executable,'-m','scripts.create_lan_certificate','--name','minhduc.internal','--ip','127.0.0.1','--output',str(data/'certs')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    env={**os.environ,'CLINIC_MODE':'lan','CLINIC_DATABASE_URL':url,'CLINIC_DATA_DIR':str(data),'CLINIC_UPLOAD_DIR':str(data/'attachments'),
         'CLINIC_ORIGIN':f'https://127.0.0.1:{free_port()}','CLINIC_BIND_IP':'127.0.0.1','CLINIC_ALLOWED_CIDRS':'127.0.0.1/32',
         'CLINIC_TLS_CERT':str(data/'certs/server.crt'),'CLINIC_TLS_KEY':str(data/'certs/server.key'),'CLINIC_MIN_FREE_MB':'256',
         'CLINIC_WORKERS':'1','CLINIC_POOL_MAX':'4','CLINIC_BACKUP_KEEP':'14','PYTHONPATH':'',
         'C5_BACKUP_KEY':str(data/'backup.key'),'PGAPPNAME':'c5-service'}
    for key in ('CLINIC_BACKUP_OFFSITE_DIR','CLINIC_REQUIRE_OFFSITE','DEMO_PASSWORD'):env.pop(key,None)
    os.environ['CLINIC_PERF_SOURCE_DATABASE_URL']=source_url
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report={'environment':{'os':platform.platform(),'logical_cpus':psutil.cpu_count(),'host_memory_mib':round(psutil.virtual_memory().total/MIB),
                         'limits':limits,'postgres_rss_note':'Tổng RSS/peak working set các tiến trình PostgreSQL; có thể đếm lặp vùng nhớ chia sẻ',
                         'service_rss_note':'Tổng dịch vụ và tiến trình con; không gồm trình duyệt/trình đo/pg_dump'},
            'baseline_ref':args.baseline_ref,'dataset':manifest,'profiles':{}}
    print('C5 môi trường: '+json.dumps(report['environment'],ensure_ascii=False),flush=True)
    print('C5 dữ liệu: '+json.dumps(manifest,ensure_ascii=False),flush=True)
    try:
        since=datetime.now(timezone(timedelta(hours=7))).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat(timespec='seconds')
        report['query_probes']=query_probes(url,since,args.output.parent/'query-probes.json')
        for label,source in [('before',baseline),('after',ROOT)]:
            if label == 'after':
                # M0 migration is deliberately applied only AFTER the old-code profile.
                # Same populated C5 database, no regenerated or reduced dataset.
                from app.m6_migration import TABLES
                from app.m5_migration import TABLES as M5_TABLES, FRAMEWORK
                from app.d0_migration import TABLES as D0_TABLES
                from app.d0_source_migration import TABLES as SOURCE_TABLES
                from app.d0_sources import SOURCES
                from app.database import PGConnection, record_factory
                old_state = database_state(url)
                with psycopg.connect(url, row_factory=record_factory) as con:
                    legacy_result_count = con.execute("SELECT COUNT(*) FROM orders WHERE result_text<>''").fetchone()[0]
                    started = time.perf_counter()
                    migrate_profile_schema(PGConnection(con))
                    migration_seconds = time.perf_counter() - started
                    assert con.execute('SELECT COUNT(*) FROM patients WHERE allergies IS NOT NULL').fetchone()[0] == 0
                new_state = database_state(url)
                expected_state = {**old_state, 'tables': dict(old_state['tables'])}
                expected_state['tables']['schema_migrations'] += 10  # versions 5–14, including S1a + S1b
                expected_state['tables'].update({name: 0 for name in TABLES+M5_TABLES+D0_TABLES+SOURCE_TABLES})
                expected_state['tables']['lab_tests'] = sum(len(v) for v in FRAMEWORK.values())
                expected_state['tables']['audit_log'] += 7  # D0 plus one TT18 source-seed audit
                expected_state['tables']['catalog_imports'] = 7
                expected_state['tables']['controlled_substances'] = 122
                expected_state['tables']['controlled_substance_aliases'] = 202  # exact two SHA-pinned TT18 files
                expected_state['tables']['order_result_versions'] = legacy_result_count
                for kind,spec in SOURCES.items():expected_state['tables'][kind]=spec[1]
                expected_state['tables']['tech_catalog_pl01']=19438
                expected_state['tables']['tech_pl02_links']=8252 # exact fragments in the SHA-256-pinned public PL02
                expected_state['tables']['patient_catalog'] = 3411
                assert new_state == expected_state, 'Migration M0 làm đổi dữ liệu C5'
                report['m0_migration'] = {'seconds': migration_seconds, 'preserved': True,
                    'visits': new_state['tables']['visits'], 'patients': new_state['tables']['patients']}
            print('C5 profile: '+label,flush=True)
            report['profiles'][label]=run_profile(source,label,env,data,manifest,pg_pid,args.output.parent/(label+'.json'))
            value=report['profiles'][label]
            print('C5 '+label+' tổng kết: '+json.dumps({k:value[k] for k in
                  ('backup_seconds','verify_seconds','backup_verify_seconds','restore_seconds','service_peak_mb','postgres_peak_mb','backup_verified','restored_exact','queue_coverage','passed')
                  if k in value},ensure_ascii=False),flush=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0 if report['profiles']['after']['passed'] else 1
    finally:
        with psycopg.connect(source_url,autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def main():
    parser=argparse.ArgumentParser(description='Đo C5 trên PostgreSQL giả lập mới, HTTPS và Chromium')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-ref',default='2fd1e9c9f811cd0d62f689ef7b18355c3f738113')
    parser.add_argument('--pg-bin',type=Path)
    parser.add_argument('--pg-pid',type=int)
    parser.add_argument('--worker',choices=['backup','restore'])
    parser.add_argument('--source',type=Path)
    parser.add_argument('--workspace',type=Path)
    args=parser.parse_args()
    if args.worker:worker(args);return 0
    limits=windows_limits()
    with tempfile.TemporaryDirectory(prefix='minhduc-c5-') as temporary:
        root=Path(temporary)
        if args.pg_bin:
            os.environ['PATH']=str(args.pg_bin)+os.pathsep+os.environ['PATH']
            with postgres_cluster(args.pg_bin,root) as (source,pid):return benchmark(args,source,pid,root,limits)
        return benchmark(args,os.environ['CLINIC_PERF_SOURCE_DATABASE_URL'],args.pg_pid,root,limits)


if __name__=='__main__':
    raise SystemExit(main())
