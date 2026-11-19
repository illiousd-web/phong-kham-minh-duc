import shutil
import subprocess
from pathlib import Path

import pytest


POWERSHELL = shutil.which('powershell.exe') or shutil.which('pwsh')


@pytest.mark.skipif(not POWERSHELL, reason='PowerShell required for service restart tests')
def test_certificate_renewal_service_restart():
    script = Path(__file__).with_name('Test-CertificateRestart.ps1')
    result = subprocess.run(
        [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
        capture_output=True, encoding='utf-8', errors='replace', timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS: certificate restart' in result.stdout
