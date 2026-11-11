from tests.test_administrative import context
from app.main import db

def test_existing_link_change_requires_reason_and_audits_old_new():
    a=context()[0]['admin']
    codes=a.get('/api/standards/shared_lab_codes?limit=2').json()['items']
    tid=a.get('/api/standards/links/lab-tests').json()['items'][0]['id']
    url='/api/standards/lab-tests/'+str(tid)
    assert a.put(url,json={'code':codes[0]['code']}).status_code==200
    assert a.put(url,json={'code':codes[1]['code']}).status_code==422
    assert a.put(url,json={'code':codes[1]['code'],'confirmed':True,'reason':'Sửa mã giả lập đúng'}).status_code==200
    with db() as c:
        import json
        x=json.loads(c.execute("SELECT details FROM audit_log WHERE event='lab_standard_linked' AND object_id=? ORDER BY id DESC LIMIT 1",(tid,)).fetchone()[0])
        assert x['old']==codes[0]['code'] and x['new']==codes[1]['code']
    assert a.put(url,json={'code':None,'confirmed':True,'reason':'Bỏ mã gắn sai giả lập'}).status_code==200
    assert any(x['id']==tid for x in a.get('/api/standards/links/lab-tests?status=unlinked').json()['items'])

def test_cross_province_link_requires_explicit_exception():
    a=context()[0]['admin']
    with db() as c:
        source=c.execute("SELECT code,parent_code FROM patient_catalog WHERE kind='commune' AND active=1 LIMIT 1").fetchone()
        province=c.execute("SELECT name FROM patient_catalog WHERE kind='province' AND code=?",(source['parent_code'],)).fetchone()[0]
        target=c.execute("SELECT code FROM official_addresses WHERE province_name<>? AND active=1 LIMIT 1",(province,)).fetchone()[0]
    body={'tms_code':source['code'],'official_code':target}
    assert a.put('/api/standards/geography/link',json=body).status_code==422
    assert a.put('/api/standards/geography/link',json={**body,'exception_confirmed':True,'reason':'Đối chiếu địa giới giả lập'}).status_code==200
    assert 'ngoại lệ khác tỉnh' in a.get('/api/audit?limit=1').text
