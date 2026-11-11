from tests.test_administrative import context
from app.main import db
from tests.d0_source_cases import check_source_api

def test_public_sources_real_import_and_rules():
    clients,ids=context();check_source_api(clients,ids,db,1)
