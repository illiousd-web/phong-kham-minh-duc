#!/bin/sh
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
echo 'Mo http://127.0.0.1:8000 - Chi dung du lieu gia lap'
exec .venv/bin/python scripts/run_demo.py
