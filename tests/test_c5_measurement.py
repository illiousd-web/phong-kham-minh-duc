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


def test_chuan_bi_khong_cong_hai_thao_tac_va_loi_chuan_bi_van_khong_dat(monkeypatch):
    clock=[0.0];prepared=[]
    def prepare():clock[0]+=10;prepared.append(True)
    def action():clock[0]+=.1
    monkeypatch.setattr('scripts.do_hieu_nang.time.perf_counter',lambda:clock[0])
    result=measure('Một thao tác',action,prepare=prepare)
    assert len(prepared)==21 and result['sample_count']==20 and result['passed']
    assert abs(result['median_seconds']-.1)<1e-9
    def failed_prepare():raise TimeoutError('Không mở được màn hình chuẩn bị')
    failed=measure('Chuẩn bị lỗi',action,prepare=failed_prepare)
    assert not failed['passed'] and failed['sample_count']==0 and 'TimeoutError' in failed['errors'][0]


def test_loi_manifest_duoc_ghi_la_khong_dat_khong_co_so_khoi_phuc(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from scripts import backup_lan,do_hieu_nang
    monkeypatch.setenv('C5_BACKUP_KEY',str(tmp_path/'fake.key'))
    monkeypatch.setattr(backup_lan,'backup',lambda *args:tmp_path/'fake.mdbackup')
    def fail(*args):raise ValueError('Backup manifest mismatch')
    monkeypatch.setattr(backup_lan,'unpack_verified',fail)
    output=tmp_path/'result.json'
    do_hieu_nang.worker(SimpleNamespace(source=do_hieu_nang.ROOT,workspace=tmp_path/'worker',worker='backup',output=output))
    result=json.loads(output.read_text(encoding='utf-8'))
    assert not result['backup_verified'] and result['verified_files']==0
    assert result['verification_error']=='ValueError: Backup manifest mismatch'
    assert 'restore_seconds' not in result
