"""Resource controls must fail closed without weakening authentication/durability."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from app import resources,storage


def test_validated_resource_defaults_and_invalid_combinations(monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith(('CLINIC_WORKERS','CLINIC_POOL_','CLINIC_THREAD_','CLINIC_CONCURRENCY','CLINIC_EXPORT_')):monkeypatch.delenv(name)
    limits=resources.read_limits()
    assert (limits.workers,limits.pool_min,limits.pool_max,limits.export_slots)==(1,1,4,1)
    for name,value in [('CLINIC_WORKERS','0'),('CLINIC_POOL_MAX','-1'),('CLINIC_THREAD_LIMIT','bad'),('CLINIC_EXPORT_SLOTS','5')]:
        with monkeypatch.context() as patch:
            patch.setenv(name,value)
            with pytest.raises(RuntimeError):resources.read_limits()
    monkeypatch.setenv('CLINIC_POOL_MIN','6')
    with pytest.raises(RuntimeError):resources.read_limits()


def test_parallel_export_limit_releases_after_error(monkeypatch):
    monkeypatch.setattr(resources,'_exports',threading.BoundedSemaphore(1))
    entered=threading.Event();release=threading.Event()
    @resources.export_slot
    def slow():
        entered.set();assert release.wait(3)
        return Response(b'%PDF-test')
    with ThreadPoolExecutor(max_workers=1) as executor:
        first=executor.submit(slow);assert entered.wait(2)
        with pytest.raises(HTTPException) as error:slow()
        assert error.value.status_code==503
        release.set();assert first.result().body.startswith(b'%PDF')
    @resources.export_slot
    def failed():raise RuntimeError('simulated renderer failure')
    with pytest.raises(RuntimeError):failed()
    assert slow().status_code==200


def test_storage_guard_and_read_only_accounting(tmp_path,monkeypatch):
    original=tmp_path/'keep-patient-file';original.write_bytes(b'keep')
    monkeypatch.setattr(storage,'free_bytes',lambda path:0)
    with pytest.raises(storage.StorageLimitError):storage.check_upload(tmp_path,1)
    assert original.read_bytes()==b'keep'
    assert storage.tree_bytes(tmp_path)==4
    monkeypatch.setattr(storage,'free_bytes',lambda path:10**12)
    monkeypatch.setattr(storage,'LIMITS',replace(resources.LIMITS,upload_total_bytes=4))
    with pytest.raises(storage.StorageLimitError):storage.check_upload(tmp_path,1)
    assert original.read_bytes()==b'keep'


def test_multi_process_operational_logs_stay_bounded(tmp_path):
    import subprocess,sys
    code='''import logging,sys
from app.logging_config import LockedRotatingFileHandler
logger=logging.getLogger('fake_resource_test');logger.setLevel(logging.WARNING)
handler=LockedRotatingFileHandler(sys.argv[1],maxBytes=1024,backupCount=3,encoding='utf-8')
logger.addHandler(handler)
for i in range(80):logger.warning('Synthetic operation log %s %s',i,'x'*70)
handler.close()
'''
    path=tmp_path/'server.log'
    processes=[subprocess.Popen([sys.executable,'-c',code,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(3)]
    for process in processes:
        _,errors=process.communicate(timeout=15)
        assert process.returncode==0 and not errors,errors.decode()
    files=[p for p in tmp_path.glob('server.log*') if p.suffix!='.lock']
    assert len(files)<=4 and sum(p.stat().st_size for p in files)<=4*1024
