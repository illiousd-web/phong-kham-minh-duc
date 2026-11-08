"""v0.4.1: bắt buộc trường hồ sơ, ngày dd/mm/yyyy, nhãn tiếng Việt trên biểu mẫu,
phiếu kết quả có bảng chỉ số và tên người thực hiện / người duyệt. Dữ liệu đều giả lập."""
import io
import subprocess
import sys

from cryptography import x509
from pypdf import PdfReader

from app.labels import lab_rows, parse_day, show_day
from tests.test_workflows import client, token, prepare_visit

ENGLISH_CODES = ('waiting', 'in_progress', 'pending_review', 'approved', 'ordered', 'draft')


def pdf_text(response):
    assert response.status_code == 200, response.text
    return ' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(response.content)).pages)


def test_patient_requires_survey_fields_and_normalises_input():
    r = token('letan')
    base = {'full_name': '  Bệnh nhân   mô phỏng Ngày  ', 'sex': 'Nam', 'date_of_birth': '05/11/1992', 'phone': '0912 345 678'}
    for missing in ('sex', 'date_of_birth', 'phone'):
        body = {k: v for k, v in base.items() if k != missing}
        assert client.post('/api/patients', headers=r, json=body).status_code == 422, missing
    assert client.post('/api/patients', headers=r, json={**base, 'sex': 'Chưa rõ'}).status_code == 422
    assert client.post('/api/patients', headers=r, json={**base, 'date_of_birth': '31/02/1992'}).status_code == 422
    assert client.post('/api/patients', headers=r, json={**base, 'phone': '123'}).status_code == 422
    created = client.post('/api/patients', headers=r, json=base)
    assert created.status_code == 201, created.text
    saved = client.get(f"/api/patients/{created.json()['id']}", headers=r).json()
    assert saved['full_name'] == 'Bệnh nhân mô phỏng Ngày'
    assert saved['date_of_birth'] == '1992-11-05'
    assert saved['phone'] == '0912345678'


def test_follow_up_accepts_vietnamese_dates_only():
    _, visit = prepare_visit('bs_noi')
    doc = token('bs_noi')
    ok = client.put(f'/api/visits/{visit}/clinical', headers=doc, json={'version': 0, 'follow_up': '05/12/2026'})
    assert ok.status_code == 200
    assert client.get(f'/api/visits/{visit}', headers=doc).json()['follow_up'] == '2026-12-05'
    bad = client.put(f'/api/visits/{visit}/clinical', headers=doc, json={'version': 1, 'follow_up': '7 ngày'})
    assert bad.status_code == 422


def test_doctor_sees_patient_sex_and_birth_date_on_visit():
    _, visit = prepare_visit('bs_noi')
    v = client.get(f'/api/visits/{visit}', headers=token('bs_noi')).json()
    assert v['patient_sex'] == 'Nữ' and v['patient_dob'] == '1995-04-21'
    cashier_view = client.get(f'/api/visits/{visit}', headers=token('thungan')).json()
    assert 'patient_dob' not in cashier_view and 'diagnosis' not in cashier_view


def test_printed_forms_use_vietnamese_status_and_lab_table():
    _, visit = prepare_visit('bs_noi')
    doc, tech, rec = token('bs_noi'), token('kythuat'), token('letan')
    assert client.put(f'/api/visits/{visit}/clinical', headers=doc, json={
        'version': 0, 'diagnosis': 'Chẩn đoán giả lập', 'vitals': 'Mạch 80 l/p; HA 150/95 mmHg',
        'follow_up': '2026-12-20'}).status_code == 200
    order = client.post('/api/orders', headers=doc, json={'visit_id': visit, 'category': 'lab', 'name': 'Sinh hóa giả lập'}).json()['id']
    pending = pdf_text(client.get(f'/api/forms/visit/{visit}?fmt=pdf', headers=doc))
    assert 'Chờ thực hiện' in pending and '20/12/2026' in pending
    result = 'Glucose | 9,2 | mmol/L | 3,9–5,6 | H\nUre | 5,1 | mmol/L | 2,5–7,5\nMẫu lấy lúc đói\nKết luận: Tăng glucose máu (giả lập)'
    assert client.put(f'/api/orders/{order}/result', headers=tech, json={'result_text': result}).status_code == 200
    assert client.post(f'/api/orders/{order}/approve', headers=doc).status_code == 200
    lab = pdf_text(client.get(f'/api/forms/lab/{order}?fmt=pdf', headers=doc))
    for expected in ('Glucose', '9,2', 'mmol/L', '3,9–5,6', 'Ure', 'Mẫu lấy lúc đói',
                     'Tăng glucose máu', 'NGƯỜI THỰC HIỆN', 'NGƯỜI DUYỆT', 'Kỹ thuật viên', 'BS Nội', 'Đã duyệt'):
        assert expected in lab, expected
    old_print = pdf_text(client.get(f'/api/print/result/{order}', headers=doc))
    assert 'Glucose' in old_print and 'Kỹ thuật viên' in old_print
    texts = [lab, old_print,
             pdf_text(client.get(f'/api/forms/intake/{visit}?fmt=pdf', headers=rec)),
             pdf_text(client.get(f'/api/forms/order/{order}?fmt=pdf', headers=doc)),
             pdf_text(client.get(f'/api/print/intake/{visit}', headers=rec)),
             pdf_text(client.get(f'/api/print/order/{order}', headers=doc))]
    for text in texts:
        for code in ENGLISH_CODES:
            assert code not in text, code


def test_lab_rows_never_drop_lines():
    rows, notes, conclusion = lab_rows('A | 1 | g/L | 1–2\n\nghi chú tự do\nB|2\nKL: bình thường\nC | 1 | 2 | 3 | 4 | 5 | 6')
    assert [r[0] for r in rows] == ['A', 'B', 'C'] and notes == ['ghi chú tự do'] and conclusion == 'bình thường'
    assert rows[2][4] == '4 | 5 | 6'
    assert parse_day('5/1/2027') == '2027-01-05' and parse_day('') is None
    # 18:30 UTC ngày 08/11 là 01:30 sáng 09/11 giờ Việt Nam.
    assert show_day('2026-11-08T18:30:00+00:00') == '09/11/2026' and show_day('2027-01-01') == '01/01/2027'


def test_lan_certificate_has_key_identifiers_for_python_313(tmp_path):
    out = tmp_path / 'certs'
    subprocess.run([sys.executable, '-m', 'scripts.create_lan_certificate', '--name', 'minhduc.internal',
                    '--ip', '192.168.10.5', '--output', str(out)], check=True, capture_output=True)
    ca = x509.load_pem_x509_certificate((out / 'ca.crt').read_bytes())
    server = x509.load_pem_x509_certificate((out / 'server.crt').read_bytes())
    ca_ski = ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest
    aki = server.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value.key_identifier
    assert aki == ca_ski
    server.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
    server.extensions.get_extension_for_class(x509.KeyUsage)
