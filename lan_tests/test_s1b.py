"""S1b runs together with S1a's real PostgreSQL immutable triggers."""
import json,secrets
from .conftest import IDS,db
from tests.s1_result_cases import check_text_versions


def test_text_result_conflict_history_and_cancellation(clients):
    check_text_versions(clients,IDS)


def test_controlled_and_numeric_guards_with_postgresql_snapshots(clients,visit):
    d,a=clients['doctor'],clients['admin']
    old=a.get('/api/prescription-settings').json()
    with db() as c:prior=dict(c.execute('SELECT practice_license,practice_scopes FROM users WHERE id=?',(IDS['doctor'],)).fetchone())
    try:
        assert a.put('/api/prescription-settings',json={**old,'clinic_facility_code':'ZZ001'}).status_code==200
        with db(True) as c:
            c.execute('UPDATE users SET practice_license=?,practice_scopes=? WHERE id=?',('GP-GIA-LAP','["Nội"]',IDS['doctor']))
            c.execute('UPDATE visits SET diagnosis=? WHERE id=?',('Giả lập S1',visit))
        line={'name':'Giả lập S1 LAN '+secrets.token_hex(4),'ingredient':'Hoạt chất giả lập','strength':'5mg','unit':'viên','quantity':'2','dose':'1','frequency':'1','days':'2','route':'Uống','timing':'sau ăn'}
        for changed,expected in [({'quantity':'abc'},422),({'days':'0'},422),({'timing':''},422),({'ingredient':'mOrPhIn','strength':'10mg/ml'},422),({'ingredient':'Diazepam','strength':'5mg'},422),({'ingredient':'Tramadol','strength':'50mg'},422),({'ingredient':'Codein + Hoạt chất giả lập','strength':'101mg + 5mg','brand_name':'Phối hợp giả lập'},422),({'ingredient':'Codein + Hoạt chất giả lập','strength':'10mg + 5mg','brand_name':'Phối hợp giả lập'},200)]:
            created=d.post('/api/clinical-prescriptions',json={'visit_id':visit,'items':[{**line,**changed}]});assert created.status_code==201,created.text
            rid=created.json()['id']
            result=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0});assert result.status_code==expected,result.text
            if expected==200:
                with db() as c:
                    snapshot=c.execute('SELECT snapshot FROM clinical_prescriptions WHERE id=?',(rid,)).fetchone()[0]
                    assert json.loads(snapshot)['items'][0]['controlled_label']
                cancelled=d.post(f'/api/clinical-prescriptions/{rid}/cancel',json={'version':1,'reason':'Lý do hủy giả lập S1'})
                assert cancelled.status_code==200,cancelled.text
                with db() as c:assert c.execute('SELECT snapshot FROM clinical_prescriptions WHERE id=?',(rid,)).fetchone()[0]==snapshot
    finally:
        a.put('/api/prescription-settings',json=old)
        with db(True) as c:c.execute('UPDATE users SET practice_license=?,practice_scopes=? WHERE id=?',(prior['practice_license'],prior['practice_scopes'],IDS['doctor']))
