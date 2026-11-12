"""Real PostgreSQL contention, not mocked lock exceptions."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import psycopg
from app import database
from .conftest import URL, db


def held_lock(key, seconds, ready):
    with psycopg.connect(URL) as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (key,))
        ready.set()
        time.sleep(seconds)


def test_business_writer_waits_one_second_then_succeeds():
    ready = threading.Event()
    with ThreadPoolExecutor() as executor:
        holding = executor.submit(held_lock, database.LOCK_ID, 1, ready)
        assert ready.wait(3)
        start = time.monotonic()
        with db(True) as c:
            assert c.execute('SELECT 1').fetchone()[0] == 1
            assert c.execute('SHOW lock_timeout').fetchone()[0] == '0'
        assert .8 < time.monotonic() - start < 5
        holding.result()


def test_separate_backup_lock_rejects_write_immediately(clients):
    key = getattr(database, 'BACKUP_LOCK_ID', database.LOCK_ID + 1)
    assert key != database.LOCK_ID
    with psycopg.connect(URL) as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (key,))
        start = time.monotonic()
        result = clients['reception'].post('/api/patients', json={
            'full_name':'Người kiểm khóa giả lập', 'sex':'Nữ', 'date_of_birth':'1990-01-01', 'phone':'0900000000'})
        assert result.status_code == 503, result.text
        assert result.headers['Retry-After'] == '1'
        assert result.json()['detail'] == 'Đang sao lưu, thử lại sau 1 giây'
        assert time.monotonic() - start < 1


def test_large_icd_import_does_not_block_clinical_save(clients, visit, monkeypatch):
    import json
    from app import d0_sources
    raw = (d0_sources.ROOT / d0_sources.SOURCES['icd10'][0]).read_bytes()
    meta = json.dumps({'document_number':'Văn bản kiểm thử giả lập', 'document_date':None,
                       'source':'Tệp công khai do chủ dự án cung cấp', 'version':'S1-concurrency'})
    args = {'files':{'file':('ICD10_TT06_2026.csv', raw)}, 'data':{'metadata':meta,'preview':'true'}}
    preview = clients['admin'].post('/api/standards/icd10/import', **args)
    assert preview.status_code == 200, preview.text
    args['data'].update(preview='false', proof=preview.json()['fingerprint'])
    entered, release = threading.Event(), threading.Event()
    original = d0_sources.apply_rows
    def paused(*a, **kw):
        entered.set()
        assert release.wait(8)
        return original(*a, **kw)
    monkeypatch.setattr(d0_sources, 'apply_rows', paused)
    with ThreadPoolExecutor() as executor:
        importing = executor.submit(clients['admin'].post, '/api/standards/icd10/import', **args)
        try:
            assert entered.wait(5)
            start = time.monotonic()
            saved = clients['doctor'].put(f'/api/visits/{visit}/clinical', json={'version':0,'diagnosis':'Chẩn đoán giả lập đồng thời'})
            assert saved.status_code == 200, saved.text
            assert time.monotonic() - start < 2
        finally:
            release.set()
        imported = importing.result()
        assert imported.status_code == 200, imported.text
        assert imported.json()['imported'] == 15844


def test_busy_business_writer_has_clear_message_after_five_seconds(clients):
    with psycopg.connect(URL) as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (database.LOCK_ID,))
        start = time.monotonic()
        result = clients['reception'].post('/api/patients', json={
            'full_name':'Người kiểm chờ giả lập', 'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'})
        assert result.status_code == 503, result.text
        assert result.json()['detail'] == 'Hệ thống đang bận, vui lòng thử lại'
        assert 4.9 <= time.monotonic() - start < 6.5
