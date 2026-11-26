"""Same S2b acceptance contracts on real PostgreSQL transactions."""
from .conftest import db, IDS
import pytest

from tests.s2b_cases import (check_lot_quantity_ceiling, check_issue_profit, check_return_profit, check_cost_and_report, check_concurrent_receipts, check_permissions,
                             check_legacy_cost, check_report_period_boundaries,
                             check_reprice_after_approved_return, owner_sessions)


def test_s2b_fefo_cost_balance_privacy_exports_and_legacy_cost(clients, visit):
    owner = owner_sessions(clients)()
    _, first, issue, disp = check_cost_and_report(clients, IDS, visit, db, owner)
    check_permissions(clients, owner, first, issue, disp)
    check_legacy_cost(clients, db, owner)
    check_report_period_boundaries(clients, db, owner)
    owner.close()


def test_s2b_two_sessions_get_distinct_receipt_numbers(clients):
    check_concurrent_receipts(clients, owner_sessions(clients))


@pytest.mark.parametrize('reason', ['internal', 'supplier_return', 'expired_disposal'])
def test_s2b_issue_cost_does_not_reduce_sales_profit(clients, reason):
    with owner_sessions(clients)() as owner:
        check_issue_profit(clients, db, owner, reason)


@pytest.mark.parametrize('half', [False, True], ids=['full', 'half'])
@pytest.mark.parametrize('approval_next_day', [False, True], ids=['same-day', 'next-day'])
def test_s2b_approved_return_reverses_original_cost_and_credit(clients, visit, half, approval_next_day):
    with owner_sessions(clients)() as owner:
        check_return_profit(clients, visit, db, owner, half, approval_next_day)


def test_t4_resent_stock_documents_are_not_duplicated(clients):
    from tests.s2b_cases import check_resent_documents_are_not_duplicated, check_missing_request_key_rejected
    factory = owner_sessions(clients)
    check_resent_documents_are_not_duplicated(clients, db, factory)
    with factory() as owner:
        check_missing_request_key_rejected(clients, owner)
def test_s2b_lot_quantity_ceiling(clients):
    with owner_sessions(clients)() as owner:
        check_lot_quantity_ceiling(clients, db, owner)


@pytest.mark.parametrize('quantities', [[1], [1, 1], [4]])
def test_reprice_denied_after_approved_return_with_zero_credit(clients, visit, quantities):
    with owner_sessions(clients)() as owner:
        check_reprice_after_approved_return(clients, visit, db, owner, quantities)



def test_h2_stock_report_reads_period_only_with_same_results(clients, visit):
    from tests.h2_cases import check_stock_report_reads_period_only
    with owner_sessions(clients)() as owner:
        check_stock_report_reads_period_only(clients, visit, db, owner)


def test_h2_utc_evening_and_missing_cost(clients):
    from tests.h2_cases import check_utc_evening_and_missing_cost
    check_utc_evening_and_missing_cost(clients, db)
