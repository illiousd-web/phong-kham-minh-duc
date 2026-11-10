"""Ngưỡng C5 phải dựa trên đủ 20 mẫu và P95, không biến lỗi/timeout thành đạt."""
from scripts.do_hieu_nang import measure


def test_p95_nearest_rank_va_khong_dung_mau_tot_nhat(monkeypatch):
    samples=[1.0]*18+[2.0,9.0]
    counter=iter(value for i,elapsed in enumerate(samples) for value in (20*i,20*i+elapsed))
    monkeypatch.setattr('scripts.do_hieu_nang.time.perf_counter',lambda:next(counter))
    result=measure('Giả lập P95',lambda:None)
    assert result['sample_count']==20 and result['median_seconds']==1
    assert result['p95_seconds']==2 and result['max_seconds']==9
    assert result['passed']


def test_timeout_hoac_loi_khong_duoc_coi_la_mau_dat():
    def fail():raise TimeoutError('Hết thời gian giả lập')
    result=measure('Giả lập lỗi',fail)
    assert not result['passed'] and result['sample_count']==0
    assert result['median_seconds'] is None and result['p95_seconds'] is None
    assert 'TimeoutError' in result['errors'][0]
