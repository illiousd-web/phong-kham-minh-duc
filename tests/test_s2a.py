"""S2a SQLite API and document contracts."""
from io import BytesIO
import json
import sqlite3
import zipfile

from docx import Document
from pypdf import PdfReader

from app.main import db, DB, form_context
from tests.test_m0 import RoleClient
from tests.test_workflows import prepare_visit
from tests.s2a_cases import PROFILE, signature_image, check_pharmacy_allergies, check_profile_and_signatures


def actors():
    names = dict(reception='letan', doctor='bs_noi', doctor2='bs_san', cashier='thungan', pharmacy='duoc',
                 manager='quanly', admin='quantri', technician='kythuat', nurse='dieuduong')
    clients = {key: RoleClient(name) for key, name in names.items()}
    with db() as c:
        ids = {key: c.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()[0] for key, name in names.items()}
    return clients, ids


def test_pharmacy_allergies_only_adds_data_to_pharmacy():
    clients, ids = actors()
    check_pharmacy_allergies(clients, ids, 1, db)


def test_admin_profile_private_signature_validation_and_audit():
    clients, ids = actors()
    check_profile_and_signatures(clients, ids, db)


def test_profile_in_all_nine_docx_pdf_templates_and_both_export_routes():
    from app.forms import generate_docx, generate_pdf, TEMPLATE_BY_TYPE, CLINIC
    clients, ids = actors()
    _, vid = prepare_visit()
    before = clients['admin'].get('/api/clinic-profile').json()
    try:
        assert clients['admin'].put('/api/clinic-profile', json=PROFILE).status_code == 200
        with db() as c:
            ctx = form_context(c, 'intake', vid)
        ctx.update(order={'id': 1, 'category': 'lab', 'name': 'Dịch vụ giả lập', 'status': 'approved', 'created_at': ctx['visit']['created_at']},
                   rx={'id': 1, 'drug_lines': 'Thuốc giả lập | 1 | Giả lập', 'created_at': ctx['visit']['created_at']})
        for kind in TEMPLATE_BY_TYPE:
            document = Document(BytesIO(generate_docx(kind, ctx)))
            headers = '\n'.join(cell.text for section in document.sections for header in (section.header, section.first_page_header) for table in header.tables for row in table.rows for cell in row.cells)
            text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(generate_pdf(kind, ctx))).pages)
            # Page 33's prescription header omits the governing body; other frames retain it.
            expected={k:v for k,v in PROFILE.items() if kind!='rx' or k!='governing_body'}
            for value in expected.values():
                assert value in headers and value in text, (kind, value)
            assert CLINIC not in headers and CLINIC not in text
            # Template assets remain unchanged; S2a inserts no signature image.
            with zipfile.ZipFile(BytesIO(generate_docx(kind, ctx))) as archive:
                assert len([name for name in archive.namelist() if name.startswith('word/media/')]) == 1
        for route in (f'/api/forms/intake/{vid}', f'/api/visits/{vid}/forms/reception'):
            response = clients['reception'].get(route)
            assert response.status_code == 200
            assert PROFILE['email'] in '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    finally:
        clients['admin'].put('/api/clinic-profile', json=before)


def test_sqlite_backup_restores_profile_signature_bytes_and_audit(tmp_path, monkeypatch):
    from scripts import backup_demo
    clients, ids = actors()
    before = clients['admin'].get('/api/clinic-profile').json()
    payload = signature_image()
    try:
        clients['admin'].put('/api/clinic-profile', json=PROFILE)
        assert clients['admin'].put(f'/api/users/{ids["doctor"]}/signature', files={'file': ('fake.png', payload, 'image/png')}).status_code == 200
        monkeypatch.setattr(backup_demo, 'DB', DB)
        monkeypatch.setattr(backup_demo, 'BACKUPS', tmp_path)
        backup = backup_demo.create(tmp_path/'demo.zip')
        assert backup_demo.verify(backup)['verified']
        with zipfile.ZipFile(backup) as archive:
            restored = tmp_path/'restored.sqlite3'
            restored.write_bytes(archive.read('database.sqlite3'))
        with sqlite3.connect(restored) as c:
            assert c.execute('SELECT name FROM clinic_profile').fetchone()[0] == PROFILE['name']
            assert c.execute('SELECT image FROM user_signatures WHERE user_id=?', (ids['doctor'],)).fetchone()[0] == payload
            assert json.loads(c.execute("SELECT details FROM audit_log WHERE event='user_signature_changed' ORDER BY id DESC LIMIT 1").fetchone()[0])['bytes'] == len(payload)
    finally:
        clients['admin'].put('/api/clinic-profile', json=before)
        with db(True) as c:
            c.execute('DELETE FROM user_signatures WHERE user_id=?', (ids['doctor'],))


def test_audit_failure_rolls_back_profile_and_signature_replacement():
    from fastapi.testclient import TestClient
    from app.main import app
    clients, ids = actors()
    admin = clients['admin']
    before = admin.get('/api/clinic-profile').json()
    path = f'/api/users/{ids["doctor"]}/signature'
    image = signature_image()
    assert admin.put(path, files={'file': ('fake.png', image, 'image/png')}).status_code == 200
    with db(True) as c:
        stored = tuple(c.execute('SELECT * FROM user_signatures WHERE user_id=?', (ids['doctor'],)).fetchone())
        c.execute("""CREATE TRIGGER s2a_test_audit_failure BEFORE INSERT ON audit_log
          WHEN NEW.event IN ('clinic_profile_changed','user_signature_changed')
          BEGIN SELECT RAISE(ABORT,'Giả lập lỗi ghi audit S2a'); END""")
    try:
        with TestClient(app, raise_server_exceptions=False) as failing:
            assert failing.put('/api/clinic-profile', headers=admin.headers, json=PROFILE).status_code == 500
            assert failing.put(path, headers=admin.headers, files={'file': ('fake.jpg', signature_image('JPEG'), 'image/jpeg')}).status_code == 500
        assert admin.get('/api/clinic-profile').json() == before
        with db() as c:
            assert tuple(c.execute('SELECT * FROM user_signatures WHERE user_id=?', (ids['doctor'],)).fetchone()) == stored
        assert admin.get(path).content == image
    finally:
        with db(True) as c:
            c.execute('DROP TRIGGER s2a_test_audit_failure')
            c.execute('DELETE FROM user_signatures WHERE user_id=?', (ids['doctor'],))
