"""S2c print, signing, range-import and migration regression tests."""
from datetime import date
from io import BytesIO
import os
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader
import pymupdf
import pytest

from app.main import db, form_context
from app.s2c_forms import from_context, from_m6, laboratory, render, order_checks
from scripts.build_s2c_assets import catalog_items
from tests.s2c_cases import check_signing, document, image_count, signature_image
from tests.test_s2a import actors as get_actors


@pytest.fixture(scope='module')
def actors():
    result=get_actors()
    with db() as c:
        prior=[dict(r) for r in c.execute('SELECT * FROM user_signatures')]
    yield result
    with db(True) as c:
        c.execute('DELETE FROM user_signatures')
        for row in prior:
            c.execute('INSERT INTO user_signatures(user_id,image,media_type,uploaded_at,uploaded_by) VALUES(?,?,?,?,?)',
                      tuple(row[k] for k in ('user_id','image','media_type','uploaded_at','uploaded_by')))


@pytest.mark.parametrize('kind', ['rx', 'order', 'lab', 'clinical_rx', 'lab_report'])
def test_password_identity_image_invalidation_and_audit(actors, kind):
    clients, ids = actors
    check_signing(clients, ids, db, 1, os.environ['DEMO_PASSWORD'], kind)


def test_stale_content_hash_missing_image_and_audit_rollback(actors):
    clients, ids = actors
    d = clients['doctor']
    vid, oid, url, _ = document(clients, ids, db, 1, 'order')
    endpoint = f'/api/document-signatures/order/{oid}'
    body = dict(password=os.environ['DEMO_PASSWORD'], content_hash=d.get(endpoint).json()['content_hash'])
    with db(True) as c:
        c.execute('UPDATE visits SET chief_complaint=? WHERE id=?', ('Đã sửa giả lập', vid))
    assert d.post(endpoint, json=body).status_code == 409
    body['content_hash'] = d.get(endpoint).json()['content_hash']
    with db(True) as c:
        c.execute('DELETE FROM user_signatures WHERE user_id=?', (ids['doctor'],))
    assert d.post(endpoint, json=body).status_code == 409
    assert clients['admin'].put(f'/api/users/{ids["doctor"]}/signature', files={'file': ('fake.png', signature_image(), 'image/png')}).status_code == 200
    with db(True) as c:
        c.execute("CREATE TRIGGER s2c_test_audit_failure BEFORE INSERT ON audit_log WHEN NEW.event='document_signed' BEGIN SELECT RAISE(ABORT,'Lỗi giả lập'); END")
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as failing:
            assert failing.post(endpoint, json=body, headers=d.headers).status_code == 500
        assert image_count(d.get(url)) == 1
        with db() as c:
            assert not c.execute('SELECT 1 FROM document_signatures WHERE document_kind=? AND document_id=?', ('order', oid)).fetchone()
    finally:
        with db(True) as c:
            c.execute('DROP TRIGGER s2c_test_audit_failure')


@pytest.mark.parametrize('kind', ['rx', 'clinical_rx'])
def test_under_72_months_without_weight_blocked_on_every_print_route(actors, kind):
    clients, ids = actors
    d = clients['doctor']
    born = date.today().replace(year=date.today().year-5).isoformat()
    vid, oid, url, word_url = document(clients, ids, db, 1, kind)
    # Simulate a historical pediatric record with missing weight; do not change save/lock gates.
    with db(True) as c:
        c.execute('UPDATE patients SET date_of_birth=? WHERE id=(SELECT patient_id FROM visits WHERE id=?)', (born, vid))
    routes = [url, word_url]
    if kind == 'rx':
        routes += [f'/api/prescriptions/{oid}/forms/prescription?format={fmt}' for fmt in ('pdf', 'docx')]
    for route in routes:
        response = d.get(route)
        assert response.status_code == 422 and 'cân nặng' in response.text
    assert d.get(f'/api/document-signatures/{kind}/{oid}').status_code == 422
    with db(True) as c:
        c.execute('UPDATE visits SET weight_kg=? WHERE id=?', (18.5, vid))
    assert image_count(d.get(url)) == 1


def test_all_three_complete_lab_groups_and_five_medicines_fit_one_a4(actors, tmp_path):
    clients, ids = actors
    vid, _, _, _ = document(clients, ids, db, 1, 'rx')
    with db() as c:
        ctx = form_context(c, 'intake', vid)
    ctx['clinic_profile'] = dict(name='CƠ SỞ GIẢ LẬP', governing_body='Đơn vị giả lập', address='Địa chỉ giả lập', phone='0000000000', email='demo@example.invalid')
    ctx['rx'] = {'id': 1, 'created_at': ctx['visit']['created_at'], 'instructions': 'Lời dặn giả lập',
                 'drug_lines': '\n'.join('Thuốc giả lập – 5 mg | 20 viên | 1 viên · Uống · sau ăn · 10 ngày' for _ in range(5))}
    ctx['order'] = dict(id=1, category='lab', name='Glucose', status='ordered', created_at=ctx['visit']['created_at'])
    ctx['orders'] = [ctx['order']]
    models = [from_context('rx', ctx), from_context('order', ctx)]
    items = []
    for x in catalog_items():
        refs = x['references']
        ref = ' · '.join((r['sex']+' '+(r['normal_value'] or ' – '.join(v for v in (r['lower_value'], r['upper_value']) if v is not None))).strip() for r in refs)
        items.append(dict(x, reference_text=ref, value='123.4', display_value='123,4', flag='H', note=''))
    p = dict(id=1, patient=ctx['patient'], clinic_profile=ctx['clinic_profile'], diagnosis='Chẩn đoán giả lập', status='approved',
             items=items, approver_name='Người duyệt giả lập', sample_at='2026-11-16T08:00:00+07:00', result_at='2026-11-16T09:00:00+07:00')
    models += [laboratory(p, g) for g in ('biochemistry', 'hematology', 'urine')]
    for model in models:
        for signed in (False, True):
            if signed:
                model['signature'] = dict(image=signature_image(), signed_at='2026-11-16T03:04:00+00:00', username='fake-doctor')
            pdf = render(model, 'pdf')
            assert image_count(type('Response', (), {'status_code': 200, 'content': pdf})()) == (2 if signed else 1)
            text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
            assert 'CƠ SỞ GIẢ LẬP' in text and 'Chẩn đoán giả lập' in text
            docx = render(model, 'docx')
            from tests.print_pagination_cases import word_as_pdf
            converted = word_as_pdf(docx)
            if converted is not None:
                assert len(PdfReader(BytesIO(converted)).pages) == 1, model['kind']
            doc = Document(BytesIO(docx))
            assert abs(doc.sections[0].page_width.pt-595.276) < 1
            with ZipFile(BytesIO(docx)) as archive:
                assert len([n for n in archive.namelist() if n.startswith('word/media/')]) == (2 if signed else 1)
            # Preserve reviewable output outside Git (pytest tmp directory).
            (tmp_path/(model['kind']+('-signed' if signed else '')+'.pdf')).write_bytes(pdf)


def test_abnormal_values_bold_arrows_in_pdf_and_word():
    p = dict(id=1, patient=dict(full_name='Giả lập', sex='Nam', date_of_birth='1990-01-01'), status='approved', items=[
        dict(name='Cao giả lập', group_name='hematology', reference_text='10 – 20', unit='g/L', display_value='25', flag='H'),
        dict(name='Thấp giả lập', group_name='hematology', reference_text='10 – 20', unit='g/L', display_value='5', flag='L'),
        dict(name='Bình thường giả lập', group_name='hematology', reference_text='10 – 20', unit='g/L', display_value='15', flag='')])
    m = laboratory(p, 'hematology')
    with pymupdf.open(stream=render(m, 'pdf'), filetype='pdf') as pdf:
        spans = [s for b in pdf[0].get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans']]
        for value in ('25 ↑', '5 ↓'):
            assert any(value in s['text'] and 'Bold' in s['font'] for s in spans)
        assert any(s['text'] == '15' and 'Bold' not in s['font'] for s in spans)
    doc = Document(BytesIO(render(m, 'docx')))
    cells = [c for t in doc.tables for r in t.rows for c in r.cells]
    for value in ('25 ↑', '5 ↓'):
        assert any(c.text == value and all(run.bold for run in c.paragraphs[0].runs) for c in cells)


def test_order_boxes_follow_real_orders_only_and_preserve_arbitrary_names():
    m = dict(orders=[dict(category='lab', name='Glucose, CTM giả lập'), dict(category='ultrasound', name='Siêu âm bụng giả lập')])
    checks = order_checks(m)
    labs = checks[0][1]
    assert '☒ CTM' in labs and '☒ Glucose' in labs and '☐ HCV' in labs
    assert any(x.startswith('☒ 2. Siêu âm') for x in checks[1:])
    assert any(x.startswith('☐ 3. X-quang') for x in checks[1:])
    assert 'Glucose, CTM giả lập' in checks[-1]
    checks=order_checks(dict(orders=[dict(category='lab',name='Fasting glucose culture giả lập'),dict(category='procedure',name='Nội soi dạ dày giả lập')]))
    assert '☐ GOT, GPT' in checks[0][1] and '☐ Ure, Creatinin' in checks[0][1]
    assert any(x.startswith('☐ 4. Nội soi tai mũi họng') for x in checks[1:])
    assert any(x.startswith('☒ 6. Dịch vụ khác') for x in checks[1:])


def test_opt_in_excel_same_headers_exact_numbers_sexes_and_preview_import(actors):
    from app.m5_import import workbook, parse
    from app.m5 import evaluate
    clients, _ = actors
    a = clients['admin']
    path = Path('data/danh_muc_goc/chi_so_xet_nghiem_minh_duc.xlsx')
    raw = path.read_bytes()
    w = load_workbook(BytesIO(raw))
    empty = load_workbook(BytesIO(workbook()))
    assert w.sheetnames == empty.sheetnames == ['ChiSo', 'ThamChieu']
    for sheet in w.sheetnames:
        assert [c.value for c in w[sheet][1]] == [c.value for c in empty[sheet][1]]
    rows = parse(raw)
    assert len(rows) == 78
    items = {x['test']['code']: x['test'] for x in rows}
    for code, ranges in {'biochemistry-CRE': [('Nữ','53','110'),('Nam','62','120')],
                         'biochemistry-UA': [('Nữ','150','360'),('Nam','180','420')],
                         'hematology-RBC': [('Nam','4.0','5.8'),('Nữ','3.9','5.4')],
                         'hematology-HGB': [('Nam','140','160'),('Nữ','125','145')],
                         'hematology-HCT': [('Nam','0.38','0.50'),('Nữ','0.35','0.47')]}.items():
        assert [(r['sex'],r['lower_value'],r['upper_value']) for r in items[code]['references']] == ranges
    assert items['biochemistry-GLU']['unit'] == 'mmol/L'
    assert items['biochemistry-CPEPTIDE']['unit'] == 'mmol/L'
    assert items['biochemistry-CRP']['unit'] == 'mg/dl'
    assert items['urine-PH']['references'][0]['normal_value'] == '(phiếu mẫu ghi 5.0)'
    assert items['urine-SG']['references'][0]['normal_value'] == '(phiếu mẫu ghi 1.010)'
    ph=items['urine-PH']
    assert evaluate(ph,ph['references'],'5.0','Nữ',360)['flag']==''  # Descriptive source text does not invent a range.
    assert items['biochemistry-HBA1C']['references'][0]['normal_value'] == '< 6.5'
    test = items['biochemistry-HBA1C']
    assert evaluate(test, test['references'], '6.5', 'Nữ', 360)['flag'] == 'H'
    assert evaluate(test, test['references'], '6.4', 'Nữ', 360)['flag'] == ''
    files = {'file': (path.name, raw, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    assert a.post('/api/lab/catalog-import', files=files, data={'preview': 'false'}).status_code == 422
    before = len(a.get('/api/lab/catalog').json())
    preview = a.post('/api/lab/catalog-import', files=files, data={'preview': 'true'})
    assert preview.status_code == 200, preview.text
    assert preview.json()['count'] == 78
    assert len(a.get('/api/lab/catalog').json()) == before
    committed = a.post('/api/lab/catalog-import', files=files, data={'preview': 'false', 'fingerprint': preview.json()['fingerprint']})
    assert committed.status_code == 200 and committed.json()['count'] == 78


def test_migration_idempotent_reversible_empty_and_preserves_signing_history(actors):
    from app.s2c_migration import migrate_s2c
    with db(True) as c:
        before = c.execute('SELECT COUNT(*) FROM document_signatures').fetchone()[0]
        migrate_s2c(c)
        assert c.execute('SELECT COUNT(*) FROM document_signatures').fetchone()[0] == before
        assert before > 0
        with pytest.raises(ValueError, match='đã có bản ký'):
            migrate_s2c(c, down=True)


def test_overflow_preserves_all_prescription_rows_without_rejection():
    p = dict(full_name='Giả lập', sex='Nam', date_of_birth='1990-01-01', contact_phone='', escort_name='', weight_kg=None)
    value = dict(patient=p, clinic_profile={}, encounter={'diagnosis': 'Giả lập'}, prescriber={'name':'Giả lập'},
                 advice=dict(lifestyle_advice='', follow_up_advice='', purchase_advice=''), items=[], created_at=None, locked_at=None)
    m = from_m6(value, 'draft')
    m['rows'] = [[f'DRUG_{i:03d} '+ 'Tên thuốc giả lập '*20, '10 viên', 'Cách dùng giả lập '*30] for i in range(30)]
    from tests.print_pagination_cases import word_text
    raw = render(m, 'pdf')
    reader = PdfReader(BytesIO(raw))
    assert len(reader.pages) > 1
    for text in ('\n'.join(p.extract_text() for p in reader.pages), word_text(render(m, 'docx'))):
        assert all(f'DRUG_{i:03d}' in text for i in range(30))


def test_empty_migration_down_up_keeps_source_rows_and_never_imports_ranges(tmp_path):
    import sqlite3
    from app.s2c_migration import migrate_s2c
    # Work on a disposable copy; never remove signing history from the source database.
    with db() as source, sqlite3.connect(tmp_path/'migration.sqlite3') as c:
        source.backup(c)
        c.execute('DELETE FROM document_signatures')
        c.commit()
        before = [tuple(r) for r in c.execute('SELECT * FROM visits ORDER BY id')]
        references = c.execute('SELECT COUNT(*) FROM lab_reference_ranges').fetchone()[0]
        migrate_s2c(c, down=True)
        migrate_s2c(c, down=True)
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='document_signatures'").fetchone()
        migrate_s2c(c)
        migrate_s2c(c)
        assert c.execute('SELECT COUNT(*) FROM document_signatures').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM lab_reference_ranges').fetchone()[0] == references
        assert c.execute('SELECT * FROM visits ORDER BY id').fetchall() == before
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
