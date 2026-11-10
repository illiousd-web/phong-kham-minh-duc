from .conftest import IDS, db
from tests.m0_cases import check_m0


def test_m0_postgres_permissions_audit_closing_and_daily_queue(clients):
    check_m0(clients, IDS, db)
