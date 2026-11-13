"""The updater must not turn logged recovery failures into a success result."""
from pathlib import Path


def test_recovery_collects_all_failures_before_reporting_success():
    text=(Path(__file__).resolve().parents[1]/'deploy/windows/CapNhat.ps1').read_text(encoding='utf-8-sig')
    recovery=text[text.index('function Invoke-QuayVe {'):text.index('$exitCode = 0')]
    assert 'throw' in recovery, 'Không được chỉ Write-Loi rồi trở về thành công'
    assert 'SilentlyContinue' not in recovery, 'Không được nuốt lỗi dừng/khởi động dịch vụ'
    assert 'Get-FileHash' in recovery, 'Phải kiểm mã đã trả lại'
    assert 'Wait-Https' in recovery


def test_windows_fault_drill_really_makes_rollback_cli_exit_23():
    import re
    root=Path(__file__).resolve().parents[1]
    drill=(root/'.github/scripts/Test-S1RecoveryFailures.ps1').read_text(encoding='utf-8-sig')
    needle=re.search(r'^\s*\$needle = "([^"]+)"',drill,re.M).group(1)
    cli=root/'scripts/install_db.py'
    source=cli.read_text(encoding='utf-8')
    assert needle in source, 'Mốc chèn lỗi phải có thật trong CLI rollback'
    injected=source.replace(needle,'            return 23  # CI rollback failure\n'+needle)
    namespace={'__name__':'s1_fake_fault_cli','__file__':str(cli)}
    exec(compile(injected,str(cli),'exec'),namespace)
    namespace['load']=lambda args:{'app':'synthetic','owner':'synthetic','super':'synthetic','uploads':'synthetic'}
    namespace['parts']=lambda url:('127.0.0.1','synthetic','synthetic','synthetic')
    def forbidden(*args): raise AssertionError('Không được gọi khôi phục thật khi đã chèn return 23')
    namespace['rollback_database']=forbidden
    assert namespace['main'](['--clinic-env','synthetic','rollback','--file','synthetic','--key','synthetic'])==23
