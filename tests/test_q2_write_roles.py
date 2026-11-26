"""Q2 trên SQLite: quyền bị thu hồi trước giao dịch ghi thì không ghi được."""
from fastapi.testclient import TestClient

from app.main import app, db
from tests.q2_cases import check_write_rechecks_current_roles
from tests.test_m0 import RoleClient


def test_q2_payment_settlement_waiver_reopen_and_account_recheck_roles_at_write():
    names = {'admin': 'quantri', 'reception': 'letan', 'cashier': 'thungan'}
    clients = {key: RoleClient(value) for key, value in names.items()}
    doctor_id = next(x['id'] for x in clients['reception'].get('/api/staff').json() if x['username'] == 'bs_noi')
    check_write_rechecks_current_roles(clients, TestClient(app), db, doctor_id, 1)
