"""Catalog merges must never rewrite historical prescription evidence."""
import json
import secrets


def check_catalog_only_merge(clients, ids, db, service):
    from app.m6 import fold
    suffix=secrets.token_hex(6)
    names=['Thuốc gộp giả lập '+x+' '+suffix for x in 'ABC']
    with db(True) as c:
        drugs=[]
        for i,name in enumerate(names):
            c.execute('INSERT INTO drugs(name,name_key,strength_key,toxic,controlled_type) VALUES(?,?,?, ?,?)',
                      (name,fold(name),'',int(i==0),'N' if i==0 else ''))
            drugs.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
    a,b,z=drugs
    r,d,admin=clients['reception'],clients['doctor'],clients['admin']
    p=r.post('/api/patients',json={'full_name':'Người gộp giả lập '+suffix,'date_of_birth':'1990-01-01','sex':'Nữ','phone':'0900000000'})
    assert p.status_code==201,p.text
    v=r.post('/api/visits',json={'patient_id':p.json()['id'],'doctor_id':ids['doctor'],'service_id':service})
    assert v.status_code==201,v.text
    line={'name':names[0],'ingredient':'Hoạt chất giả lập','dose':'1','frequency':'1','days':'1','route':'Uống','unit':'viên'}
    body={'visit_id':v.json()['id'],'items':[line]}
    locked=d.post('/api/clinical-prescriptions',json=body);draft=d.post('/api/clinical-prescriptions',json=body)
    assert locked.status_code==draft.status_code==201
    rid=locked.json()['id'];draft_id=draft.json()['id'];snapshot=json.dumps({'synthetic_only':True})
    with db(True) as c:
        c.execute("UPDATE clinical_prescriptions SET status='locked',snapshot=? WHERE id=?",(snapshot,rid))
        before=dict(c.execute('SELECT * FROM clinical_prescription_items WHERE prescription_id=?',(rid,)).fetchone())
    assert admin.post(f'/api/drugs/{a}/merge',json={'keep_id':b}).status_code==200
    with db() as c:
        assert dict(c.execute('SELECT * FROM clinical_prescription_items WHERE prescription_id=?',(rid,)).fetchone())==before
        assert c.execute('SELECT snapshot FROM clinical_prescriptions WHERE id=?',(rid,)).fetchone()[0]==snapshot
        from app.m6 import current_drug
        assert current_drug(c,a)['id']==b
        assert c.execute('SELECT toxic,controlled_type FROM drugs WHERE id=?',(b,)).fetchone()[0]==1
        assert c.execute('SELECT controlled_type FROM drugs WHERE id=?',(b,)).fetchone()[0]=='N'
        assert c.execute("SELECT user_id FROM audit_log WHERE event='drug_merged' AND object_id=?",(str(a),)).fetchone()[0]==ids['admin']
    assert admin.post(f'/api/drugs/{b}/merge',json={'keep_id':a}).status_code==422
    saved=d.put(f'/api/clinical-prescriptions/{draft_id}',json={**body,'version':0})
    assert saved.status_code==200,saved.text
    with db() as c: assert c.execute('SELECT drug_id FROM clinical_prescription_items WHERE prescription_id=?',(draft_id,)).fetchone()[0]==b
    assert admin.post(f'/api/drugs/{b}/merge',json={'keep_id':z}).status_code==200
    with db() as c:
        assert current_drug(c,a)['id']==z
        assert c.execute('SELECT drug_id FROM clinical_prescription_items WHERE prescription_id=?',(rid,)).fetchone()[0]==a
    assert admin.post(f'/api/drugs/{z}/merge',json={'keep_id':a}).status_code==422
    from fastapi import HTTPException
    import pytest
    try:
        with db(True) as c: c.execute('UPDATE drugs SET merged_into=? WHERE id=?',(a,z))
        with db() as c:
            with pytest.raises(HTTPException) as error: current_drug(c,a)
            assert error.value.status_code==422 and 'vòng' in str(error.value.detail)
    finally:
        with db(True) as c: c.execute('UPDATE drugs SET merged_into=NULL WHERE id=?',(z,))
