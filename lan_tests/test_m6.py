from .conftest import IDS,SERVICE,db
from tests.m6_cases import check_m6


def test_m6_clinical_prescription_end_to_end(clients):
    check_m6(clients,IDS,db,SERVICE)


def test_replacement_atomic_chain_and_allergy_acknowledgement(clients):
    from tests.m6_followup_cases import check_followup
    check_followup(clients,IDS,db,SERVICE)
