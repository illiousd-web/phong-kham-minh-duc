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
