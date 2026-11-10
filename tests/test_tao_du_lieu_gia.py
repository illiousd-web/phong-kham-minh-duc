"""Chặn nhầm CSDL/thư mục đang dùng trước khi mở bất kỳ kết nối ghi nào."""
from pathlib import Path
import pytest
from scripts.tao_du_lieu_gia import CONFIRM, validate


@pytest.mark.parametrize('name', ['minhduc', 'clinic', 'clinic_test_source', 'clinic_perf_test_prod', 'clinic_perf_test_123456789abc_restore'])
def test_tu_choi_ten_csdl_khong_phai_dich_c5(name, tmp_path):
    with pytest.raises(ValueError, match='Chỉ nhận tên'):
        validate('postgresql://user@127.0.0.1/postgres', name, tmp_path/name, CONFIRM)


def test_bat_buoc_xac_nhan_va_loopback_va_thu_muc_moi(tmp_path):
    name='clinic_perf_test_123456789abc'
    with pytest.raises(ValueError, match='xác nhận'):
        validate('postgresql://user@127.0.0.1/postgres', name, tmp_path/name, '')
    with pytest.raises(ValueError, match='loopback'):
        validate('postgresql://user@192.168.1.10/postgres', name, tmp_path/name, CONFIRM)
    with pytest.raises(ValueError, match='Nguồn không được'):
        validate('postgresql://user@127.0.0.1/'+name, name, tmp_path/name, CONFIRM)
    with pytest.raises(ValueError, match='CSDL phòng khám đang dùng'):
        validate('postgresql://user@127.0.0.1/minhduc', name, tmp_path/name, CONFIRM)
    (tmp_path/name).mkdir()
    (tmp_path/name/'giu-nguyen.txt').write_text('Giữ nguyên dữ liệu cũ')
    with pytest.raises(ValueError, match='không ghi đè'):
        validate('postgresql://user@127.0.0.1/postgres', name, tmp_path/name, CONFIRM)
    assert (tmp_path/name/'giu-nguyen.txt').read_text() == 'Giữ nguyên dữ liệu cũ'
