"""Đối chứng giá từng dòng trên PostgreSQL thật, gồm nhiều nguồn cùng một khoản."""
from .conftest import db,IDS
from app.main import NOW
from tests.charge_query_cases import check_prices


def test_price_query_matches_view_and_expected_amounts_postgresql(clients,visit):
    with db(True) as c:check_prices(c,visit,IDS['manager'],NOW())
