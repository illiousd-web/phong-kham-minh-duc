"""C5 tạo dữ liệu trong database mới; lần hai không được chạm dữ liệu lần đầu."""
import secrets
from urllib.parse import urlsplit,urlunsplit
import psycopg
from psycopg import sql
import pytest
from .conftest import SOURCE
from scripts.tao_du_lieu_gia import generate,CONFIRM


def test_c5_du_lieu_lien_ket_va_khong_ghi_de_csdl_co_san(tmp_path):
    name='clinic_perf_test_'+secrets.token_hex(6)
    source=urlunsplit(urlsplit(SOURCE)._replace(path='/postgres'))
    url=urlunsplit(urlsplit(SOURCE)._replace(path='/'+name))
    try:
        result=generate(source,name,tmp_path/name,CONFIRM,visits=60,patients=45,attachments=6)
        assert result['counts']['visits']==60 and result['counts']['orders']==240
        assert result['counts']['prescriptions']==60 and result['attachments']==6
        with psycopg.connect(url) as c:
            assert c.execute('SELECT COUNT(*) FROM orders WHERE file_key IS NOT NULL').fetchone()[0]==6
            for key, in c.execute('SELECT file_key FROM orders WHERE file_key IS NOT NULL'):
                assert (tmp_path/name/'attachments'/key).read_bytes().startswith(b'%PDF-')
            assert c.execute("SELECT MIN(quantity) FROM stock_lots").fetchone()[0] >= 0
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
