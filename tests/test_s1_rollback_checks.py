"""The updater must not turn logged recovery failures into a success result."""
from pathlib import Path


def test_recovery_collects_all_failures_before_reporting_success():
    text=(Path(__file__).resolve().parents[1]/'deploy/windows/CapNhat.ps1').read_text(encoding='utf-8-sig')
    recovery=text[text.index('function Invoke-QuayVe {'):text.index('$exitCode = 0')]
    assert 'throw' in recovery, 'Không được chỉ Write-Loi rồi trở về thành công'
    assert 'SilentlyContinue' not in recovery, 'Không được nuốt lỗi dừng/khởi động dịch vụ'
    assert 'Get-FileHash' in recovery, 'Phải kiểm mã đã trả lại'
    assert 'Wait-Https' in recovery
