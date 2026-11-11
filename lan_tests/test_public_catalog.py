from .conftest import db
from tests.test_public_catalog import check_public_lookup


def test_public_lookup_and_explicit_ethnicity_codes(clients):
    from app.ui_settings import settings_path
    from app.main import FILES
    path=settings_path(FILES);old=path.read_bytes() if path.exists() else None
    try:check_public_lookup(clients)
    finally:
        if old is None:path.unlink(missing_ok=True)
        else:path.write_bytes(old)
