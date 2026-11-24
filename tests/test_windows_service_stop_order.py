"""Thứ tự thời gian dừng dịch vụ Windows phải luôn đúng:
Python tự dừng < WinSW cưỡng chế (stoptimeout) < mọi lần PowerShell chờ trạng thái Stopped
< mọi lần chờ tiến trình con có gọi Stop-MinhDucService.

Trước đây WinSW và PowerShell cùng 30 giây nên chạy đua: CI run 307 (main) và 308 (PR #53)
đỏ ở MinhDuc.Install.psm1 với lỗi WaitForStatus hết thời gian.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'deploy/windows/MinhDuc.Install.psm1'
# Chờ Python thoát sau khi dịch vụ dừng (Wait-MinhDucVenvPythonExit) và thăm HTTPS trước đó.
PYTHON_EXIT_MAX = 58
HTTPS_PROBE = 15
MIN_GRACEFUL = 60  # xuất báo cáo cả năm, in phiếu nhiều ảnh cần chạy xong


def _read(path):
    return Path(path).read_text(encoding='utf-8-sig')


def _winsw_seconds():
    match = re.search(r'^\$script:ServiceStopTimeoutSec\s*=\s*(\d+)\s*$', _read(MODULE), re.M)
    assert match, 'Thiếu $script:ServiceStopTimeoutSec trong MinhDuc.Install.psm1'
    return int(match.group(1))


def _stop_wait_seconds():
    match = re.search(r'function Get-MinhDucServiceStopWait \{\s*return New-TimeSpan -Seconds (\d+)\s*\}', _read(MODULE))
    assert match, 'Thiếu hàm Get-MinhDucServiceStopWait trả số giây cố định'
    return int(match.group(1))


def _graceful_seconds():
    tree = ast.parse(_read(ROOT / 'scripts/run_lan.py'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'run':
            for keyword in node.keywords:
                if keyword.arg == 'timeout_graceful_shutdown':
                    return keyword.value.value
    raise AssertionError('uvicorn.run trong scripts/run_lan.py thiếu timeout_graceful_shutdown')


def _powershell_files():
    files = list((ROOT / 'deploy/windows').glob('*.ps1')) + [MODULE]
    files += list((ROOT / '.github/scripts').glob('*.ps1')) + list((ROOT / 'tests').glob('*.ps1'))
    return files + [ROOT / '.github/workflows/clinic-tests.yml']


def test_stop_timeouts_are_strictly_ordered():
    graceful = _graceful_seconds()
    winsw = _winsw_seconds()
    wait = _stop_wait_seconds()
    assert graceful >= MIN_GRACEFUL
    assert graceful < winsw < wait
    # Đủ khoảng trống để WinSW cưỡng chế xong trước khi PowerShell bỏ cuộc.
    assert winsw - graceful >= 20
    assert wait - winsw >= 20


def test_winsw_xml_uses_shared_stop_timeout():
    text = _read(MODULE)
    assert '<stoptimeout>$($script:ServiceStopTimeoutSec) sec</stoptimeout>' in text
    assert not re.search(r'<stoptimeout>\d+ sec</stoptimeout>', text)


def test_every_stopped_wait_is_longer_than_winsw_kill():
    winsw = _winsw_seconds()
    pattern = re.compile(r"WaitForStatus\(\s*'Stopped'\s*,\s*([^)]*\)?)\s*\)", re.S)
    literal = re.compile(r'(?:New-TimeSpan\s+-Seconds\s+|FromSeconds\()\s*(\d+)')
    bad = []
    for path in _powershell_files():
        text = _read(path)
        for match in pattern.finditer(text):
            arg = match.group(1)
            line = text.count('\n', 0, match.start()) + 1
            if 'Get-MinhDucServiceStopWait' in arg:
                continue
            seconds = literal.search(arg)
            if not seconds or int(seconds.group(1)) <= winsw:
                bad.append(f'{path.relative_to(ROOT)}:{line}')
    assert not bad, 'Chờ Stopped phải dùng Get-MinhDucServiceStopWait hoặc số giây > stoptimeout: ' + ', '.join(bad)


def test_workers_that_stop_the_service_wait_long_enough():
    worst = _stop_wait_seconds() + PYTHON_EXIT_MAX + HTTPS_PROBE
    checked = 0
    for path in (ROOT / '.github/scripts').glob('*.ps1'):
        text = _read(path)
        # Tiến trình con dừng dịch vụ trực tiếp, hoặc chạy lại bài diễn tập có dừng dịch vụ.
        if 'Stop-MinhDucService' not in text and 'Test-S2f2dMaintenanceRecovery.ps1' not in text:
            continue
        for match in re.finditer(r'\$worker\.WaitForExit\((\d+)\)', text):
            checked += 1
            line = text.count('\n', 0, match.start()) + 1
            assert int(match.group(1)) / 1000 > worst, f'{path.relative_to(ROOT)}:{line} chờ tiến trình con ngắn hơn {worst} giây'
    assert checked >= 2
