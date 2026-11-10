from .conftest import IDS, SERVICE, db, client_for
from tests.administrative_cases import check_administrative, check_catalog, check_child, check_scopes


def test_patient_document_privacy_and_practitioner_prints(clients):
    with client_for('nurse') as nurse:
        check_administrative(dict(clients,nurse=nurse),IDS,db,SERVICE)


def test_patient_catalog_atomic_csv_excel(clients):
    check_catalog(clients,db)


def test_child_prescribing_vietnam_boundary(clients):
    with db(True) as c:
        c.execute("INSERT INTO medicines(name,base_unit,controlled) VALUES('Thuốc giả lập L1','viên',0)")
    check_child(clients,IDS,db,SERVICE)


def test_scope_warning_and_opt_in_block(clients):
    check_scopes(clients,IDS,db,SERVICE)
