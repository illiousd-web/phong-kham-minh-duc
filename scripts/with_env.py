"""Load a protected literal environment file and run one Python module.

Usage: python -m scripts.with_env /etc/minhduc/clinic.env scripts.run_lan
No shell evaluation, no printing of configuration or secrets.
"""
import os
from pathlib import Path
import re
import runpy
import sys


def main():
    if len(sys.argv)<3:
        raise SystemExit(__doc__)
    for line in Path(sys.argv[1]).read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*=.*',line):
            raise SystemExit('Invalid environment file entry')
        key,value=line.split('=',1)
        os.environ[key]=value
    module=sys.argv[2]
    sys.argv=[module,*sys.argv[3:]]
    runpy.run_module(module,run_name='__main__')


if __name__=='__main__':main()
