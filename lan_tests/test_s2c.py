"""PostgreSQL parity for password-confirmed S2c signing and invalidation triggers."""
import pytest
from app.database import db
from tests.s2c_cases import check_signing
from .conftest import IDS, PASSWORDS, SERVICE


@pytest.mark.parametrize('kind', ['rx', 'order', 'lab', 'clinical_rx', 'lab_report'])
def test_s2c_signatures_with_postgres(clients, kind):
    check_signing(clients, IDS, db, SERVICE, PASSWORDS['doctor'], kind)
