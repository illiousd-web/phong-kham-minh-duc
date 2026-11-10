"""C5 tạo dữ liệu trong database mới; lần hai không được chạm dữ liệu lần đầu."""
import secrets
from urllib.parse import urlsplit,urlunsplit
import psycopg
from psycopg import sql
import pytest
import pymupdf
from .conftest import SOURCE
from scripts.tao_du_lieu_gia import generate,CONFIRM
from scripts.do_hieu_nang import query_probes


def test_c5_du_lieu_lien_ket_va_khong_ghi_de_csdl_co_san(tmp_path):
    name='clinic_perf_test_'+secrets.token_hex(6)
    source=urlunsplit(urlsplit(SOURCE)._replace(path='/postgres'))
    url=urlunsplit(urlsplit(SOURCE)._replace(path='/'+name))
    try:
        result=generate(source,name,tmp_path/name,CONFIRM,visits=60,patients=45,attachments=6)
        assert result['counts']['visits']==60 and result['counts']['orders']==240
        assert result['counts']['prescriptions']==60 and result['attachments']==6
        probes=query_probes(url,'2024-01-01T00:00:00+00:00',tmp_path/'query-probes.json')
        assert probes['orders']['on']['rows']==probes['orders']['off']['rows']==100
        assert probes['dues']['on']['rows']==probes['dues']['off']['rows']==60
        with psycopg.connect(url) as c:
            assert c.execute('SELECT COUNT(*) FROM orders WHERE file_key IS NOT NULL').fetchone()[0]==6
            for key, in c.execute('SELECT file_key FROM orders WHERE file_key IS NOT NULL'):
                path=tmp_path/name/'attachments'/key
                assert path.stat().st_size==64*1024
                with pymupdf.open(path) as document:
                    assert len(document)==1 and not document.is_repaired
            assert c.execute("SELECT MIN(quantity) FROM stock_lots").fetchone()[0] >= 0
            assert c.execute('''SELECT COUNT(*) FROM visits v JOIN patients p ON p.id=v.patient_id
                WHERE p.created_at>v.created_at''').fetchone()[0]==0
            assert c.execute('''SELECT COUNT(*) FROM audit_log a LEFT JOIN patients p ON p.id=a.object_id
                WHERE a.event='patient_created' AND p.id IS NULL''').fetchone()[0]==0
            assert c.execute("INSERT INTO service_catalog(name,price) VALUES('Kiểm chuỗi giả lập C5',1000) RETURNING id").fetchone()[0]>5
            before=c.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
        # Đích khác trên đĩa nhưng cùng tên DB: CREATE DATABASE phải từ chối,
        # kể cả người chạy biết đúng mã xác nhận và tên hợp lệ.
        with pytest.raises(psycopg.errors.DuplicateDatabase):
            generate(source,name,tmp_path/'lan-hai'/name,CONFIRM,visits=60,patients=45,attachments=6)
        assert not (tmp_path/'lan-hai'/name).exists()
        with psycopg.connect(url) as c:
            assert c.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]==before
            assert c.execute('SELECT COUNT(*) FROM visits').fetchone()[0]==60
    finally:
        with psycopg.connect(SOURCE,autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
