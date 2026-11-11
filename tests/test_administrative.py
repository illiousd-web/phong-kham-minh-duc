from tests.test_m0 import RoleClient
from app.main import db
from tests.administrative_cases import check_administrative, check_catalog, check_child, check_scopes


def context():
    names=dict(nurse='dieuduong',reception='letan',doctor='bs_noi',doctor2='bs_san',cashier='thungan',pharmacy='duoc',manager='quanly',admin='quantri',technician='kythuat')
    clients={k:RoleClient(v) for k,v in names.items()}
    with db() as c:ids={k:c.execute('SELECT id FROM users WHERE username=?',(v,)).fetchone()[0] for k,v in names.items()}
    return clients,ids


def test_patient_document_privacy_and_practitioner_prints():
    clients,ids=context();check_administrative(clients,ids,db,1)


def test_patient_catalog_atomic_csv_excel():
    clients,_=context();check_catalog(clients,db)


def test_child_prescribing_vietnam_boundary():
    clients,ids=context();check_child(clients,ids,db,1)


def test_scope_warning_and_opt_in_block():
    clients,ids=context();check_scopes(clients,ids,db,1)


def test_certificate_warning_30_day_boundary_in_vietnam():
    from datetime import datetime, timedelta, timezone
    from app.practitioners import certificate_warning
    now=datetime(2026,11,10,17,tzinfo=timezone.utc) # 11/11 in Vietnam
    assert certificate_warning('2026-12-11',now) is None
    assert certificate_warning('2026-12-10',now)=='Chứng thư số còn 29 ngày hết hạn'
    assert certificate_warning('2026-11-11',now)=='Chứng thư số còn 0 ngày hết hạn'
    assert certificate_warning('2026-11-10',now)=='Chứng thư số đã hết hạn'
    assert certificate_warning(None,now) is None


def test_patch_preserves_omitted_fields_and_redacts_audit():
    from tests.administrative_revision_cases import check_patch_preserves_administrative_and_private_audit
    clients, ids = context()
    check_patch_preserves_administrative_and_private_audit(clients, ids, db, 1)


def test_structured_address_in_word_and_pdf_patient_section():
    from tests.administrative_revision_cases import check_structured_address_print_position
    clients, ids = context()
    check_structured_address_print_position(clients, ids, db, 1)


def test_masked_short_documents_and_address_fallback():
    from app.administrative import masked_document
    from app.forms import format_patient_address
    for value in ('A', 'AB', 'ABC', 'ABCD'):
        assert masked_document(value) == '••••'
    assert masked_document('AB1234') == '••••1234'
    assert masked_document(None) is None
    assert format_patient_address({}) == '—'
    assert format_patient_address({'address': ' Địa chỉ cũ giả lập '}) == 'Địa chỉ cũ giả lập'
    assert format_patient_address({'address': 'Cũ', 'commune': ' Xã giả lập '}) == 'Cũ, Xã giả lập'
