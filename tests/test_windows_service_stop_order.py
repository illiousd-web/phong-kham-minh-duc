"""Thứ tự thời gian dừng dịch vụ Windows phải luôn đúng:
Python tự dừng < WinSW cưỡng chế (stoptimeout) < mọi lần PowerShell chờ trạng thái Stopped.

Trước đây WinSW và PowerShell cùng 30 giây nên chạy đua: CI run 307 (main) và 308 (PR #53)
đỏ ở MinhDuc.Install.psm1 với lỗi WaitForStatus hết thời gian.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'deploy/windows/MinhDuc.Install.psm1'


def _read(path):
    return Path(path).read_text(encoding='utf-8-sig')


def _module_seconds(name):
    match = re.search(rf'^\$script:{name}\s*=\s*(\d+)\s*$', _read(MODULE), re.M)
    assert match, f'Thiếu $script:{name} trong MinhDuc.Install.psm1'
    return int(match.group(1))


def _graceful_seconds():
    tree = ast.parse(_read(ROOT / 'scripts/run_lan.py'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'run':
            for keyword in node.keywords:
                if keyword.arg == 'timeout_graceful_shutdown':
                    return keyword.value.value
    raise AssertionError('uvicorn.run trong scripts/run_lan.py thiếu timeout_graceful_shutdown')


def test_stop_timeouts_are_strictly_ordered():
    graceful = _graceful_seconds()
    winsw = _module_seconds('ServiceStopTimeoutSec')
    wait = _module_seconds('ServiceStopWaitSec')
    assert graceful < winsw < wait
    # Đủ khoảng trống để WinSW cưỡng chế xong trước khi PowerShell bỏ cuộc.
    assert wait - winsw >= 20


def test_winsw_xml_uses_shared_stop_timeout():
    text = _read(MODULE)
    assert '<stoptimeout>$($script:ServiceStopTimeoutSec) sec</stoptimeout>' in text
    assert not re.search(r'<stoptimeout>\d+ sec</stoptimeout>', text)


def test_no_stopped_wait_shorter_than_winsw_kill():
    winsw = _module_seconds('ServiceStopTimeoutSec')
    files = list((ROOT / 'deploy/windows').glob('*.ps1')) + [MODULE]
    files += list((ROOT / '.github/scripts').glob('*.ps1')) + [ROOT / '.github/workflows/clinic-tests.yml']
    pattern = re.compile(r"WaitForStatus\('Stopped',\s*(?:\(New-TimeSpan -Seconds (\d+)\)|\[TimeSpan\]::FromSeconds\((\d+)\))")
    short = []
    for path in files:
        for line_no, line in enumerate(_read(path).splitlines(), 1):
            match = pattern.search(line)
            if match and int(match.group(1) or match.group(2)) <= winsw:
                short.append(f'{path.relative_to(ROOT)}:{line_no}')
    assert not short, 'Chờ Stopped không dài hơn stoptimeout của WinSW: ' + ', '.join(short)
