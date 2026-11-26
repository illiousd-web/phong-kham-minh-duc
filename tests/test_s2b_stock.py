"""S2b warehouse business, privacy and concurrency acceptance on SQLite."""
from app.main import db
from tests.test_m0 import RoleClient
from tests.test_workflows import prepare_visit
import pytest

from tests.s2b_cases import (check_lot_quantity_ceiling, check_issue_profit, check_return_profit, check_cost_and_report, check_concurrent_receipts, check_permissions,
                             check_legacy_cost, check_report_period_boundaries,
                             check_reprice_after_approved_return, owner_sessions)


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


@pytest.mark.parametrize('reason', ['internal', 'supplier_return', 'expired_disposal'])
def test_s2b_issue_cost_does_not_reduce_sales_profit(reason):
    clients = actors()
    with owner_sessions(clients)() as owner:
        check_issue_profit(clients, db, owner, reason)


@pytest.mark.parametrize('half', [False, True], ids=['full', 'half'])
@pytest.mark.parametrize('approval_next_day', [False, True], ids=['same-day', 'next-day'])
def test_s2b_approved_return_reverses_original_cost_and_credit(half, approval_next_day):
    clients = actors()
    _, visit = prepare_visit()
    with owner_sessions(clients)() as owner:
        check_return_profit(clients, visit, db, owner, half, approval_next_day)


@pytest.mark.parametrize('quantities', [[1], [1, 1], [4]])
def test_reprice_denied_after_approved_return_with_zero_credit(quantities):
    clients = actors()
    _, visit = prepare_visit()
    with owner_sessions(clients)() as owner:
        check_reprice_after_approved_return(clients, visit, db, owner, quantities)


def test_s2b_lot_quantity_ceiling():
    clients = actors()
    with owner_sessions(clients)() as owner:
        check_lot_quantity_ceiling(clients, db, owner)


def test_t4_resent_stock_documents_are_not_duplicated():
    from tests.s2b_cases import check_resent_documents_are_not_duplicated, check_missing_request_key_rejected
    clients = actors()
    factory = owner_sessions(clients)
    check_resent_documents_are_not_duplicated(clients, db, factory)
    with factory() as owner:
        check_missing_request_key_rejected(clients, owner)



def test_t2_stock_revenue_uses_effective_price_across_periods():
    from tests.s2b_cases import check_reprice_revenue_periods
    clients = actors()
    clients['cashier'] = RoleClient('thungan')
    _, visit = prepare_visit()
    with owner_sessions(clients)() as owner:
        check_reprice_revenue_periods(clients, visit, db, owner)


def test_t2_two_reprices_multiple_returns_and_full_return():
    from tests.s2b_cases import check_reprice_twice_and_return_all
    clients = actors()
    _, visit = prepare_visit()
    with owner_sessions(clients)() as owner:
        check_reprice_twice_and_return_all(clients, visit, db, owner)
