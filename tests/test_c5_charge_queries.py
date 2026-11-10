"""Tối ưu đọc phải tương đương view, không có công thức giá mới."""
import re
from app.charge_queries import PRICE_INPUTS
from app.manual_price_migration import VIEW
from app import main
from tests.test_workflows import prepare_visit
from tests.charge_query_cases import check_prices


def test_price_query_covers_every_input_of_effective_view():
    assert set(re.findall(r'\b(?:FROM|JOIN)\s+(\w+)',VIEW,re.I))-{'charges'}==set(PRICE_INPUTS)


def test_price_query_matches_view_and_expected_amounts_sqlite():
    _,visit=prepare_visit()
    with main.db(True) as c:
        actor=c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        check_prices(c,visit,actor,main.NOW())
