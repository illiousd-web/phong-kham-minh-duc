"""H1 trên SQLite: báo cáo lọc kỳ trong SQL, kết quả không đổi, số câu SQL không tăng theo số lượt."""
from app.main import db
from tests.h1_cases import (check_reports_filter_in_sql_with_same_results, check_unpaid_matches_invoice,
                            check_refunds_and_waiver_match_reference)


def test_h1_reports_same_results_and_constant_queries():
    check_reports_filter_in_sql_with_same_results(db)
    check_unpaid_matches_invoice(db)


def test_h1_refunds_waiver_and_timestamp_formats():
    check_refunds_and_waiver_match_reference(db)
