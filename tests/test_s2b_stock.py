"""S2b warehouse business, privacy and concurrency acceptance on SQLite."""
from app.main import db
from tests.test_m0 import RoleClient
from tests.test_workflows import prepare_visit
from tests.s2b_cases import (check_cost_and_report, check_concurrent_receipts, check_permissions,
                             check_legacy_cost, check_report_period_boundaries, owner_sessions)


def actors():
    names = {'admin': 'quantri', 'manager': 'quanly', 'pharmacy': 'duoc', 'doctor': 'bs_noi'}
    return {key: RoleClient(value) for key, value in names.items()}


def test_s2b_fefo_cost_balance_privacy_exports_and_legacy_cost():
    clients = actors()
    factory = owner_sessions(clients)
    owner = factory()
    _, vid = prepare_visit()
    _, first, issue, disp = check_cost_and_report(clients, {}, vid, db, owner)
    check_permissions(clients, owner, first, issue, disp)
    check_legacy_cost(clients, db, owner)
    check_report_period_boundaries(clients, db, owner)
    owner.close()


def test_s2b_two_sessions_get_distinct_receipt_numbers():
    clients = actors()
    check_concurrent_receipts(clients, owner_sessions(clients))
