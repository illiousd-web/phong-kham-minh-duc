"""Synthetic regression cases for PR 41 review items B and C."""
from io import BytesIO
import os
import secrets
import shutil
from zipfile import ZipFile

import pytest

from app.main import db
from tests.s2c_cases import document, image_count, signature_image, sign_current
from tests.test_s2c import actors as actors


@pytest.mark.parametrize('kind', ['rx', 'order', 'lab'])
def test_signature_ignores_watermark_logo_template_but_tracks_clinical_content(actors, tmp_path, monkeypatch, kind):
    import app.config as config
    import app.forms as legacy
    import app.s2c_forms as forms
    clients, ids = actors
    d = clients['doctor']
    templates = tmp_path/'templates'
    shutil.copytree(forms.TEMPLATE_DIR, templates)
    logo = tmp_path/'logo.png'
    logo.write_bytes(forms.LOGO.read_bytes())
    monkeypatch.setattr(forms, 'TEMPLATE_DIR', templates)
    monkeypatch.setattr(forms, 'LOGO', logo)
    monkeypatch.setattr(config, 'IN_DONG_THU_NGHIEM', True)
    warning = 'BẢN THỬ NGHIỆM - KHÔNG DÙNG CHO NGƯỜI BỆNH THẬT'
    monkeypatch.setattr(forms, 'WATERMARK', warning)
    monkeypatch.setattr(legacy, 'WATERMARK', warning)
    vid, oid, url, word_url = document(clients, ids, db, 1, kind)
    assert clients['admin'].put(f'/api/users/{ids["doctor"]}/signature', files={'file': ('fake.png', signature_image(), 'image/png')}).status_code == 200
    sign_current(d, kind, oid, os.environ['DEMO_PASSWORD'])
    assert image_count(d.get(url)) == 2
    monkeypatch.setattr(config, 'IN_DONG_THU_NGHIEM', False)
    monkeypatch.setattr(forms, 'WATERMARK', '')
    monkeypatch.setattr(legacy, 'WATERMARK', '')
    assert image_count(d.get(url)) == 2
    logo.write_bytes(signature_image('red'))
    assert image_count(d.get(url)) == 2
    template = templates/forms.TEMPLATES['rx' if kind == 'rx' else 'order' if kind == 'order' else 'biochemistry']
    template.write_bytes(template.read_bytes()+b'changed-test-template')
    assert image_count(d.get(url)) == 2
    word = d.get(word_url)
    assert word.status_code == 200
    with ZipFile(BytesIO(word.content)) as archive:
        assert signature_image() in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
    with db(True) as c:
        original = c.execute('SELECT diagnosis FROM visits WHERE id=?', (vid,)).fetchone()['diagnosis']
        c.execute('UPDATE visits SET diagnosis=? WHERE id=?', ('Chuyên môn thay đổi giả lập', vid))
    assert image_count(d.get(url)) == 1
    with db(True) as c:
        c.execute('UPDATE visits SET diagnosis=? WHERE id=?', (original, vid))
    assert image_count(d.get(url)) == 2


def test_rx_prescriber_and_visit_doctor_export_but_only_prescriber_signs(actors):
    from app.accounts import AccountInput, create_account
    from app.auth import pw_hash
    from tests.test_m0 import RoleClient
    clients, ids = actors
    a, b = clients['doctor'], clients['doctor2']
    name = 'test_c_'+secrets.token_hex(5)
    with db(True) as c:
        create_account(c, AccountInput(username=name, full_name='Bác sĩ C giả lập', password=os.environ['DEMO_PASSWORD'], roles=['doctor']), pw_hash)
    unrelated = RoleClient(name)
    _, oid, url, _ = document(clients, ids, db, 1, 'rx')
    with db(True) as c:
        c.execute('UPDATE prescriptions SET doctor_id=? WHERE id=?', (ids['doctor2'], oid))
    assert clients['admin'].put(f'/api/users/{ids["doctor2"]}/signature', files={'file': ('fake.png', signature_image(), 'image/png')}).status_code == 200
    endpoint = f'/api/document-signatures/rx/{oid}'
    state = b.get(endpoint)
    assert state.status_code == 200
    body = {'password':os.environ['DEMO_PASSWORD'], 'content_hash':state.json()['content_hash']}
    assert a.post(endpoint, json=body).status_code == 403
    assert unrelated.post(endpoint, json=body).status_code == 403
    assert b.post(endpoint, json=body).status_code == 200
    for reader in (a, b, clients['pharmacy']):
        assert image_count(reader.get(url)) == 2
        assert reader.get(url+'?fmt=pdf').status_code == 200
        word = reader.get(url+'?fmt=docx')
        assert word.status_code == 200
        with ZipFile(BytesIO(word.content)) as archive:
            assert signature_image() in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
    for suffix in ('', '?fmt=pdf', '?fmt=docx'):
        assert unrelated.get(url+suffix).status_code == 403
