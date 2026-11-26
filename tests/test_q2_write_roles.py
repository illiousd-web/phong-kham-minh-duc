"""Q2 trên SQLite: quyền bị thu hồi trước giao dịch ghi thì không ghi được."""
import pytest
from fastapi.testclient import TestClient

from app.main import app, db
from tests.q2_cases import (
    CATALOG_WRITE_CASES,
    STOCK_WRITE_CASES,
    VISIT_WRITE_CASES,
    check_account_write_after_restriction,
    check_catalog_write_after_role_removed,
    check_stock_write_after_role_removed,
    check_visit_write_after_role_removed,
    check_write_after_session_revoked,
    check_write_rechecks_current_roles,
)
from tests.test_m0 import RoleClient


@pytest.fixture
def q2_context():
    names = {'admin': 'quantri', 'reception': 'letan', 'cashier': 'thungan'}
    clients = {key: RoleClient(value) for key, value in names.items()}
    doctor_id = next(x['id'] for x in clients['reception'].get('/api/staff').json() if x['username'] == 'bs_noi')
    anon = TestClient(app)
    try:
        yield clients, anon, doctor_id, 1
    finally:
        anon.close()


def test_q2_payment_settlement_waiver_reopen_and_account_recheck_roles_at_write(q2_context):
    clients, anon, doctor_id, service_id = q2_context
    check_write_rechecks_current_roles(clients, anon, db, doctor_id, service_id)


@pytest.mark.parametrize('operation', ['create', 'reset-password'])
@pytest.mark.parametrize('restriction', ['role', 'locked'])
def test_q2_account_write_after_admin_restricted(q2_context, operation, restriction):
    clients, anon, _, _ = q2_context
    check_account_write_after_restriction(clients['admin'], anon, db, operation, restriction)


@pytest.mark.parametrize('revocation', ['logout', 'password-reset'])
def test_q2_payment_after_session_revoked(q2_context, revocation):
    clients, anon, doctor_id, service_id = q2_context
    check_write_after_session_revoked(clients, anon, db, doctor_id, service_id, revocation)


@pytest.mark.parametrize('operation', VISIT_WRITE_CASES)
def test_q2_visit_write_after_role_removed(q2_context, operation):
    clients, anon, doctor_id, service_id = q2_context
    check_visit_write_after_role_removed(clients, anon, db, doctor_id, service_id, operation)


@pytest.mark.parametrize('operation', CATALOG_WRITE_CASES)
def test_q2_catalog_write_after_role_removed(q2_context, operation):
    clients, anon, _, _ = q2_context
    check_catalog_write_after_role_removed(clients['admin'], anon, db, operation)


@pytest.mark.parametrize('operation', STOCK_WRITE_CASES)
def test_q2_stock_write_after_role_removed(q2_context, operation):
    clients, anon, _, _ = q2_context
    check_stock_write_after_role_removed(clients['admin'], anon, db, operation)
