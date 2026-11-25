"""Run the financial self-review contract on PostgreSQL."""
from tests.test_self_review import (
    manager_setup as manager_setup,
    test_controlled_return_cannot_be_self_reviewed as test_controlled_return_cannot_be_self_reviewed,
    test_financial_review_rechecks_manager_after_authentication as test_financial_review_rechecks_manager_after_authentication,
    test_financial_self_review as test_financial_self_review,
    test_self_review_after_own_manager_change as test_self_review_after_own_manager_change,
    test_waiver_sql_matches_previous_period_filter as test_waiver_sql_matches_previous_period_filter,
)
