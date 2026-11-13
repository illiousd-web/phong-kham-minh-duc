from tests.test_administrative import context
from app.main import db
from tests.s1_merge_cases import check_catalog_only_merge


def test_catalog_only_merge_keeps_locked_reference_and_resolves_chain():
    clients,ids=context()
    check_catalog_only_merge(clients,ids,db,1)
