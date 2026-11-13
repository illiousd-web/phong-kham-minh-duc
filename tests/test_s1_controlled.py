import pytest
from tests.test_s1_prescription import prescription, create

@pytest.mark.parametrize('ingredient,strength', [('Morphin','10mg/ml'),('Diazepam','5mg'),('Tramadol','50mg'),('mOrPhIn','10mg/ml')])
def test_controlled_ingredient_without_manual_flag_is_blocked(prescription,ingredient,strength):
    d,vid,line=prescription
    rid=create(d,vid,{**line,'ingredient':ingredient,'strength':strength})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==422,response.text
    assert 'chưa hỗ trợ' in response.text


def test_public_tt18_counts_and_limits():
    from collections import Counter
    from app.controlled_migration import source_rows
    from app.main import db
    substances=source_rows('TT18_2026_DUOC_CHAT_KIEM_SOAT.csv')
    limits=source_rows('TT18_2026_GIOI_HAN_PHOI_HOP.csv')
    assert Counter(r['phu_luc'].split()[0] for r in substances)=={'I':42,'II':72,'III':8}
    assert Counter(r['phu_luc'].split()[0] for r in limits)=={'IV':13,'V':43,'VI':6}
    with db() as c:
        assert c.execute('SELECT COUNT(*) FROM controlled_substances').fetchone()[0]==122
        rows=c.execute("SELECT row_count FROM catalog_imports WHERE document_number='TT 18/2026/TT-BYT' ORDER BY row_count").fetchall()
        assert [r[0] for r in rows]==[62,122]


@pytest.mark.parametrize('strength,status', [('10 mg + 5 mg',200),('101 mg + 5 mg',422),('không rõ + 5 mg',422),('10 mg/ml + 5 mg',422)])
def test_codein_combination_threshold_and_snapshot(prescription,strength,status):
    from app.main import db
    d,vid,line=prescription
    rid=create(d,vid,{**line,'ingredient':'cOdEiN + Hoạt chất giả lập','brand_name':'Nhãn giả lập phối hợp','strength':strength})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==status,response.text
    if status==200:
        with db() as c:
            import json
            payload=json.loads(c.execute('SELECT snapshot FROM clinical_prescriptions WHERE id=?',(rid,)).fetchone()[0])
            assert payload['items'][0]['controlled_label']=='thuốc dạng phối hợp có chứa chất kiểm soát'
            assert c.execute('SELECT controlled_type FROM drugs WHERE id=?',(payload['items'][0]['drug_id'],)).fetchone()[0]=='N'
    else:assert 'chưa hỗ trợ' in response.text


def test_fuzzy_requires_explicit_reason(prescription):
    d,vid,line=prescription
    row={**line,'ingredient':'Morphinn'}
    rid=create(d,vid,row)
    assert d.get(f'/api/clinical-prescriptions/{rid}').json()['items'][0]['controlled_warning']
    assert d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0}).status_code==422
    saved=d.put(f'/api/clinical-prescriptions/{rid}',json={'visit_id':vid,'version':0,'items':[{**row,'controlled_acknowledged':True,'controlled_reason':'Đã rà soát tên giả lập'}]})
    assert saved.status_code==200,saved.text
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':1})
    assert response.status_code==200,response.text


def test_alias_admin_only_and_audit(prescription):
    from tests.test_administrative import context
    from app.main import db
    c,_=context();a=c['admin']
    rows=a.get('/api/controlled-substances').json()['items']
    substance=next(x for x in rows if x['name']=='MORPHINE')
    import secrets
    alias='Tên khác giả lập '+secrets.token_hex(4)
    body={'substance_key':substance['source_key'],'alias':alias}
    assert c['doctor'].post('/api/controlled-substances/aliases',json=body).status_code==403
    result=a.post('/api/controlled-substances/aliases',json=body)
    assert result.status_code==201,result.text
    with db() as conn:assert conn.execute("SELECT 1 FROM audit_log WHERE event='controlled_alias_added'").fetchone()
    d,vid,line=prescription
    rid=create(d,vid,{**line,'ingredient':alias})
    assert d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0}).status_code==422


def test_every_source_name_variant_is_matched_and_all_limits_preserved():
    import json,re
    from app.main import db
    from app.controlled_migration import source_rows
    from app.controlled_substances import matches
    with db() as c:
        for source in source_rows('TT18_2026_DUOC_CHAT_KIEM_SOAT.csv'):
            for name in re.split('[;/]',source['ten_quoc_te']):
                assert matches(c,name.strip()),name
        assert sum(len(json.loads(r['limits_json'])) for r in c.execute('SELECT limits_json FROM controlled_substances'))==62


@pytest.mark.parametrize('ingredient,strength,blocked', [
    ('Codeine + Ethylmorphine','10 mg + 10 mg',True),
    ('Diazepam + Alprazolam','1 mg + 1 mg',True),
    ('Codeine + Paracetamol','10 mg + 500 mg',False),
])
def test_only_controlled_components_never_receive_combination_label(prescription, ingredient, strength, blocked):
    from app.main import db
    from app.controlled_substances import assess, LABEL
    d,vid,line=prescription
    row={**line,'ingredient':ingredient,'strength':strength,'brand_name':'Phối hợp giả lập'}
    with db() as c: result=assess(c,row)
    message='Đơn thuốc N/H chưa hỗ trợ: thuốc chỉ gồm chất kiểm soát'
    if blocked:
        assert message in result['errors']
        assert result['label']==''
    else:
        assert result['errors']==[] and result['label']==LABEL
    rid=create(d,vid,row)
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==(422 if blocked else 200),response.text
    if blocked: assert message in response.text
