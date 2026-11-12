from .conftest import db,IDS,SERVICE
from tests.d0_source_cases import check_source_api

def test_public_sources_postgresql_import_and_rules(clients):check_source_api(clients,IDS,db,SERVICE)
