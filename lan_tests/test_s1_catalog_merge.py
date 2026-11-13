from tests.s1_merge_cases import check_catalog_only_merge
from .conftest import db,IDS,SERVICE


def test_catalog_only_merge_keeps_locked_reference_and_resolves_chain(clients):
    check_catalog_only_merge(clients,IDS,db,SERVICE)
