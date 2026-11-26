"""Q2 trên PostgreSQL thật: quyền bị thu hồi trước giao dịch ghi thì không ghi được."""
from .conftest import IDS, SERVICE, client_for, db
from tests.q2_cases import check_write_rechecks_current_roles


def test_q2_payment_settlement_waiver_reopen_and_account_recheck_roles_at_write(clients):
    anon = client_for()
    try:
        check_write_rechecks_current_roles(clients, anon, db, IDS['doctor'], SERVICE)
    finally:
        anon.close()
