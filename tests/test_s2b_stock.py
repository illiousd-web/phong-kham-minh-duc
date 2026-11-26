"""S2b warehouse business, privacy and concurrency acceptance on SQLite."""
from app.main import db
from tests.test_m0 import RoleClient
from tests.test_workflows import prepare_visit
import pytest

from tests.s2b_cases import (check_issue_profit, check_return_profit, check_cost_and_report, check_concurrent_receipts, check_permissions,
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
    import secrets
    from tests.s2b_cases import med, receive, checked
    clients = actors()
    _, visit = prepare_visit()
    with owner_sessions(clients)() as owner:
        medicine = med(clients)
        receive(owner, medicine, 4, 1000)
        doctor, pharmacy, manager = clients['doctor'], clients['pharmacy'], clients['manager']
        row = checked(doctor.get(f'/api/visits/{visit}'))
        checked(doctor.put(f'/api/visits/{visit}/clinical', json={'version':row['version'],'diagnosis':'Giả lập'}))
        rx = checked(doctor.post('/api/prescriptions', json={'visit_id':visit,'items':[{'medicine_id':medicine,'quantity':4,'directions':'Giả lập'}]}), 201)
        disp = checked(pharmacy.post(f'/api/prescriptions/{rx["id"]}/dispense'), 201)
        item = disp['lots'][0]['id']
        with db() as c:
            charge = c.execute("SELECT charge_id FROM charge_sources WHERE source_type='dispense_item' AND source_id=?", (item,)).fetchone()[0]
        def reprice(value):
            return manager.post(f'/api/charges/{charge}/reprice', json={'amount':value,'reason':'Giá giả lập','request_key':secrets.token_hex(16)})
        assert reprice(1).status_code == 200
        for quantity in quantities:
            ret = checked(pharmacy.post(f'/api/dispensations/{disp["dispensation_id"]}/returns', json={'reason':'Trả thuốc giả lập','request_key':secrets.token_hex(16),'items':[{'dispensation_item_id':item,'quantity':quantity}]}), 201)
            checked(manager.post(f'/api/medication-returns/{ret["id"]}/review', json={'approve':True}))
        assert reprice(4000).status_code == 409


def test_h2_stock_report_reads_period_only_with_same_results():
    from tests.h2_cases import check_stock_report_reads_period_only
    clients = actors()
    _, visit = prepare_visit()
    with owner_sessions(clients)() as owner:
        check_stock_report_reads_period_only(clients, visit, db, owner)


def test_h2_utc_evening_and_missing_cost():
    from tests.h2_cases import check_utc_evening_and_missing_cost
    check_utc_evening_and_missing_cost(actors(), db)
