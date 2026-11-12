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


def test_single_service_limit_checks_final_addition():
    from tests.d0_isolation import service
    from tests.d0_cases import upload
    import secrets
    a=context()[0]['admin'];sid=service(db);suffix=secrets.token_hex(6)
    code_a,code_b='FAKE-A-'+suffix,'FAKE-B-'+suffix
    upload(a,'tech_catalog',[{'code':code_a,'name':'Kỹ thuật giả lập A '+suffix},{'code':code_b,'name':'Kỹ thuật giả lập B '+suffix}])
    url='/api/standards/services/'+str(sid)
    assert a.put(url,json={'codes':[code_a]}).status_code==200
    response=a.put(url,json={'mode':'add','codes':[code_b],'package':False,'confirmed':True,'reason':'Thêm mã giả lập đã kiểm'})
    assert response.status_code==422,response.text
    with db() as c:assert [x[0] for x in c.execute('SELECT tech_code FROM service_tech_codes WHERE service_id=?',(sid,))]==[code_a]


def test_retained_pl02_revalidates_final_pl01_and_review_key():
    from tests.d0_isolation import service
    from app.d0_sources import seed_sources
    import json
    a=context()[0]['admin'];sid=service(db)
    with db(True) as c:
        seed_sources(c,'2026-11-12T00:00:00+00:00')
        pair=c.execute('''SELECT l.pl02_id,l.pl01_code FROM tech_pl02_links l JOIN tech_catalog_pl02 p ON p.id=l.pl02_id WHERE p.active=1 AND l.needs_review=0 AND NOT EXISTS(SELECT 1 FROM tech_pl02_links bad WHERE bad.pl02_id=l.pl02_id AND bad.needs_review=1) LIMIT 1''').fetchone()
        assert pair
        pid=str(pair['pl02_id']);code_a=pair['pl01_code']
        linked={r[0] for r in c.execute('SELECT pl01_code FROM tech_pl02_links WHERE pl02_id=?',(pid,))}
        others=[r[0] for r in c.execute('SELECT code FROM tech_catalog WHERE active=1 ORDER BY code') if r[0] not in linked][:2]
        assert len(others)==2
    code_b,code_c=others;url='/api/standards/services/'+str(sid)
    assert a.put(url,json={'codes':[code_a],'pl02_ids':[pid]}).status_code==200
    change={'codes':[code_b],'confirmed':True,'reason':'Đối chiếu mã giả lập mới','removed_codes':[code_a]}
    assert a.put(url,json=change).status_code==422
    with db() as c:
        assert c.execute('SELECT tech_code FROM service_tech_codes WHERE service_id=?',(sid,)).fetchone()[0]==code_a
        assert str(c.execute('SELECT pl02_id FROM service_pl02_codes WHERE service_id=?',(sid,)).fetchone()[0])==pid
    assert a.put(url,json={**change,'exception_confirmed':True}).status_code==422
    # Simulate unverified fragments on this retained source row, without changing source codes.
    with db(True) as c:c.execute('UPDATE tech_pl02_links SET needs_review=1 WHERE pl02_id=?',(pid,))
    assert a.put(url,json=change).status_code==422
    assert a.put(url,json={**change,'exception_confirmed':True}).status_code==200
    assert a.put(url,json={'codes':[code_b]}).status_code==200 # same reviewed pair, no prompt again
    change_c={**change,'codes':[code_c],'removed_codes':[code_b]}
    assert a.put(url,json=change_c).status_code==422 # B review cannot authorize C
    assert a.put(url,json={**change_c,'exception_confirmed':True}).status_code==200
    assert a.put(url,json={**change,'removed_codes':[code_c]}).status_code==200 # reuse B review after changing away and back
    with db() as c:
        review=c.execute("SELECT details FROM audit_log WHERE event='pl02_relationship_review_reason' AND object_id=? ORDER BY id LIMIT 1",(int(pid),)).fetchone()
        assert review and json.loads(review[0])=={'codes':[code_b],'reason':change['reason']}
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='pl02_relationship_reviewed' AND object_id=?",(int(pid),)).fetchone()[0]==2
        audit=json.loads(c.execute("SELECT details FROM audit_log WHERE event='service_standard_linked' AND object_id=? AND details LIKE ? ORDER BY id LIMIT 1",(sid,'%'+change['reason']+'%')).fetchone()[0])
        assert audit['old']==[code_a] and audit['new']==[code_b]
        assert list(map(str,audit['old_pl02_ids']))==[pid] and audit['pl02_ids']==[pid]
