"""H1 trên PostgreSQL thật: cùng kết quả với bản cũ, số câu SQL không tăng theo số lượt."""
from .conftest import db
from tests.h1_cases import check_reports_filter_in_sql_with_same_results, check_unpaid_matches_invoice


def test_h1_reports_same_results_and_constant_queries():
    check_reports_filter_in_sql_with_same_results(db)
    check_unpaid_matches_invoice(db)
