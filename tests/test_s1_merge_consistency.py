"""Only equivalent catalog aliases may be used in prescription drafts."""
import json
import secrets

import pytest

from app.main import db
from app.m6 import fold
from tests.test_administrative import context


def catalog_pair(source_strength='500mg', target_strength='500 mg',
                 source_ingredient='Hoạt chất giả lập', target_ingredient='Hoạt chất giả lập', **fields):
    suffix = secrets.token_hex(6)
    ids = []
    with db(True) as c:
        for label, strength, ingredient in [('Nguồn', source_strength, source_ingredient), ('Đích', target_strength, target_ingredient)]:
            name = label + ' giả lập ' + suffix
            c.execute('INSERT INTO drugs(name,name_key,strength,strength_key,ingredient,ingredient_key,brand_name,brand_key,dosage_form,route,unit) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (name, fold(name), strength, fold(strength), ingredient, fold(ingredient), 'Nhãn gốc giả lập', fold('Nhãn gốc giả lập'), fields.get(('source_' if label=='Nguồn' else 'target_')+'dosage_form','Viên nén'), fields.get(('source_' if label=='Nguồn' else 'target_')+'route','Uống'), fields.get(('source_' if label=='Nguồn' else 'target_')+'unit','viên')))
            ids.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
        source = dict(c.execute('SELECT * FROM drugs WHERE id=?', (ids[0],)).fetchone())
    return ids, source


def prescription_body(clients, ids, source, **changes):
    r = clients['reception']
    p = r.post('/api/patients', json={'full_name': 'Người giả lập '+secrets.token_hex(5), 'date_of_birth': '1990-01-01', 'sex': 'Nữ', 'phone': '0900000000'})
    assert p.status_code == 201, p.text
    v = r.post('/api/visits', json={'patient_id': p.json()['id'], 'doctor_id': ids['doctor'], 'service_id': 1})
    assert v.status_code == 201, v.text
    line = dict(name=source['name'], strength=source['strength'], ingredient=source['ingredient'],
                brand_name='Nhãn trên đơn giả lập', dose='1', frequency='1', days='1', route='Uống', unit='viên')
    line.update(changes)
    return dict(visit_id=v.json()['id'], items=[line])


@pytest.mark.parametrize('left,right', [('500mg','500 mg'), ('0,5 g','0.5g')])
def test_merge_equivalent_strength_spacing_and_decimal(left, right):
    clients, _ = context()
    (a,b), _ = catalog_pair(left, right)
    response = clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id': b})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('kwargs,message', [
    ({'target_strength': '250 mg'}, 'khác hàm lượng'),
    ({'target_strength': '0.5 g'}, 'khác hàm lượng'),
    ({'target_ingredient': 'Hoạt chất khác giả lập'}, 'khác hoạt chất'),
])
def test_merge_rejects_different_strength_or_ingredient(kwargs, message):
    clients, _ = context()
    (a,b), _ = catalog_pair(**kwargs)
    response = clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id': b})
    assert response.status_code == 422, response.text
    assert message in response.json()['detail']
    with db() as c:
        assert c.execute('SELECT merged_into FROM drugs WHERE id=?', (a,)).fetchone()[0] is None


def test_merge_source_without_ingredient_is_rejected():
    clients, _ = context()
    (a,b), _ = catalog_pair(source_ingredient='')
    response = clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id': b})
    assert response.status_code == 422
    assert 'thuốc nguồn chưa có hoạt chất' in response.json()['detail']


def test_save_equivalent_alias_keeps_content_and_does_not_overwrite_target():
    clients, ids = context()
    (a,b), source = catalog_pair()
    body = prescription_body(clients, ids, source, ingredient='HOẠT CHẤT GIẢ LẬP')
    assert clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id': b}).status_code == 200
    with db() as c:
        before = dict(c.execute('SELECT * FROM drugs WHERE id=?', (b,)).fetchone())
    result = clients['doctor'].post('/api/clinical-prescriptions', json=body)
    assert result.status_code == 201, result.text
    with db() as c:
        row = c.execute('SELECT * FROM clinical_prescription_items WHERE prescription_id=?', (result.json()['id'],)).fetchone()
        assert row['drug_id'] == b
        content = json.loads(row['content'])
        for key, value in body['items'][0].items():
            assert content[key] == value
        assert dict(c.execute('SELECT * FROM drugs WHERE id=?', (b,)).fetchone()) == before


@pytest.mark.parametrize('changes', [{'target_strength':'250 mg'}, {'target_ingredient':'Hoạt chất khác giả lập'}])
def test_legacy_inconsistent_alias_rejected_on_save_and_lock(changes):
    clients, ids = context()
    (a,b), source = catalog_pair(**changes)
    body = prescription_body(clients, ids, source)
    saved = clients['doctor'].post('/api/clinical-prescriptions', json=body)
    assert saved.status_code == 201, saved.text
    rid = saved.json()['id']
    with db(True) as c:
        c.execute("UPDATE drugs SET merged_into=?,review_status='inactive' WHERE id=?", (b,a))
        target = dict(c.execute('SELECT * FROM drugs WHERE id=?', (b,)).fetchone())
    expected = f"Dòng 1: thuốc đã gộp sang {target['name']} {target['strength']}, chọn lại từ danh mục"
    result = clients['doctor'].put(f'/api/clinical-prescriptions/{rid}', json={**body, 'version':0})
    assert result.status_code == 422, result.text
    assert result.json()['detail'] == expected
    locked = clients['doctor'].post(f'/api/clinical-prescriptions/{rid}/lock', json={'version':0})
    assert locked.status_code == 422, locked.text
    assert {'row':1, 'field':'name', 'message':expected} in locked.json()['detail']['errors']
    with db() as c:
        assert c.execute('SELECT drug_id FROM clinical_prescription_items WHERE prescription_id=?', (rid,)).fetchone()[0] == a


@pytest.mark.parametrize('changes,message', [
    ({'target_dosage_form':'Dung dịch'}, 'khác dạng bào chế'),
    ({'target_route':'Tiêm'}, 'khác đường dùng'),
    ({'target_unit':'ống'}, 'khác đơn vị tính'),
    ({'source_dosage_form':''}, 'thuốc nguồn chưa có dạng bào chế'),
    ({'target_dosage_form':''}, 'thuốc đích chưa có dạng bào chế'),
    ({'source_route':'  '}, 'thuốc nguồn chưa có đường dùng'),
    ({'target_unit':''}, 'thuốc đích chưa có đơn vị tính'),
    ({'target_ingredient':''}, 'thuốc đích chưa có hoạt chất'),
])
def test_merge_requires_matching_complete_form_route_unit(changes, message):
    clients, _ = context()
    (a,b), _ = catalog_pair(**changes)
    response = clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id':b})
    assert response.status_code == 422, response.text
    assert message in response.json()['detail']


def test_merge_complete_fields_ignore_case_and_whitespace():
    clients, _ = context()
    (a,b), _ = catalog_pair(target_ingredient=' HOẠT CHẤT   GIẢ LẬP ',
                            target_dosage_form=' VIÊN   NÉN ', target_route=' UỐNG ', target_unit=' VIÊN ')
    response = clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id':b})
    assert response.status_code == 200, response.text


def test_save_alias_rejects_different_line_route():
    clients, ids = context()
    (a,b), source = catalog_pair()
    body = prescription_body(clients, ids, source, route='Tiêm')
    assert clients['admin'].post(f'/api/drugs/{a}/merge', json={'keep_id':b}).status_code == 200
    response = clients['doctor'].post('/api/clinical-prescriptions', json=body)
    assert response.status_code == 422, response.text
    assert 'Dòng 1: thuốc đã gộp sang' in response.json()['detail']
