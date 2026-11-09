"""C3c: Quản lý → Lượt khám tra được lượt cũ đã thu đủ (SQLite). Chỉ dữ liệu giả lập."""
import pytest

from tests.test_workflows import client, token
from tests import manager_visits_cases as cases

USERS = {'manager': 'quanly', 'admin': 'quantri', 'reception': 'letan', 'doctor': 'bs_noi',
         'technician': 'kythuat', 'nurse': 'dieuduong', 'pharmacy': 'duoc', 'cashier': 'thungan'}


@pytest.fixture(scope='module')
def headers():
    return {role: token(user) for role, user in USERS.items()}


@pytest.fixture(scope='module')
def get(headers):
    return lambda role, path: client.get(path, headers=headers[role] if role else {})


@pytest.fixture(scope='module')
def post(headers):
    return lambda role, path, body: client.post(path, headers=headers[role], json=body)


@pytest.fixture(scope='module')
def doctor_id(headers):
    return next(x['id'] for x in client.get('/api/staff', headers=headers['reception']).json() if x['username'] == 'bs_noi')


def test_old_settled_visit_found_by_name_and_day(get, post, doctor_id):
    cases.old_settled_visit_is_found(get, post, 1, doctor_id)


def test_money_and_status_filters(get, post):
    cases.money_filters_are_exact(get, post)


def test_pagination(get, post):
    cases.pagination_is_exact(get, post)


def test_only_manager(get, post, doctor_id):
    target, _, _ = cases.old_settled_visit_is_found(get, post, 1, doctor_id)
    cases.only_manager_may_read(get, target)
