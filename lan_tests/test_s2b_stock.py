"""Same S2b acceptance contracts on real PostgreSQL transactions."""
from .conftest import db, IDS
from tests.s2b_cases import (check_cost_and_report, check_concurrent_receipts, check_permissions,
                             check_legacy_cost, check_report_period_boundaries, owner_sessions)


def test_s2b_fefo_cost_balance_privacy_exports_and_legacy_cost(clients, visit):
    owner = owner_sessions(clients)()
    _, first, issue, disp = check_cost_and_report(clients, IDS, visit, db, owner)
    check_permissions(clients, owner, first, issue, disp)
    check_legacy_cost(clients, db, owner)
    check_report_period_boundaries(clients, db, owner)
    owner.close()


def test_s2b_two_sessions_get_distinct_receipt_numbers(clients):
    check_concurrent_receipts(clients, owner_sessions(clients))
