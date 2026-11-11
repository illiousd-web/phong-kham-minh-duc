"""Ensure all test modules share a fresh fake-data database regardless of import order."""
import os
import secrets
import tempfile
from pathlib import Path

_DEMO_TEST_TMP = tempfile.TemporaryDirectory(prefix='minhduc_pytest_session_')
_ROOT = Path(_DEMO_TEST_TMP.name)
os.environ['CLINIC_DB_PATH'] = str(_ROOT/'database.sqlite3')
os.environ['CLINIC_UPLOAD_DIR'] = str(_ROOT/'attachments')

os.environ['DEMO_PASSWORD'] = secrets.token_urlsafe(32)

import pytest
@pytest.fixture(autouse=True)
def legacy_parallel_icd_mode(request):
    if request.node.path.name=='test_d0.py':return
    from app.main import init_db,db
    init_db()
    with db(True) as c:
        c.execute("INSERT INTO prescription_settings(key,value) VALUES('require_primary_icd10','false') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
