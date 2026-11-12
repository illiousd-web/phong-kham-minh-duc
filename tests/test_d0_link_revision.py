from tests.test_administrative import context
from app.main import db

def test_existing_link_change_requires_reason_and_audits_old_new():
    a=context()[0]['admin']
    from tests.d0_isolation import lab
    from tests.d0_cases import upload
    upload(a,'shared_lab_codes',[{'code':'9000001','name':'Chỉ số mã giả lập A'},{'code':'9000002','name':'Chỉ số mã giả lập B'}])
    codes=a.get('/api/standards/shared_lab_codes?limit=2').json()['items']
    assert len(codes)==2
    tid=lab(a)
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
    import secrets
    from tests.d0_cases import upload
    suffix=secrets.token_hex(6);pc='FAKE-P-'+suffix;cc='FAKE-C-'+suffix;target='FAKE-O-'+suffix
    with db(True) as c:
        c.execute("INSERT INTO patient_catalog(kind,code,name,parent_code) VALUES('province',?,?, '')",(pc,'Tỉnh giả lập A '+suffix))
        c.execute("INSERT INTO patient_catalog(kind,code,name,parent_code) VALUES('commune',?,?,?)",(cc,'Xã giả lập '+suffix,pc))
    upload(a,'official_addresses',[{'code':target,'name':'Xã đối chiếu giả lập '+suffix,'province_name':'Tỉnh giả lập B '+suffix,'province_code':'FAKE-B-'+suffix,'kind':'commune'}])
    source={'code':cc}
    body={'tms_code':source['code'],'official_code':target}
    assert a.put('/api/standards/geography/link',json=body).status_code==422
    assert a.put('/api/standards/geography/link',json={**body,'exception_confirmed':True,'reason':'Đối chiếu địa giới giả lập'}).status_code==200
    assert 'ngoại lệ khác tỉnh' in a.get('/api/audit?limit=1').text
