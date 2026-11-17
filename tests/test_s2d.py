"""S2d imaging workflows: exclusively synthetic patients, pixels and signatures."""
from copy import deepcopy
from io import BytesIO
import json
import os
import re

from PIL import Image
from pypdf import PdfReader
import pytest

from app.main import db
from app.resources import LIMITS
from tests.test_s2c import actors as actors
from tests.test_workflows import prepare_visit
from tests.s2c_cases import signature_image


def pixels(color='white'):
    out=BytesIO(); Image.new('RGB',(320,180),color).save(out,format='JPEG'); return out.getvalue()


def make(clients, code='S2D-008'):
    _, vid=prepare_visit()
    d=clients['doctor']
    assert d.put(f'/api/visits/{vid}/clinical',json={'version':0,'diagnosis':'Chẩn đoán hình ảnh giả lập'}).status_code==200
    templates=d.get('/api/imaging/templates').json()
    t=next(x for x in templates if x['code']==code)
    o=d.post('/api/orders',json={'visit_id':vid,'category':t['category'],'name':t['name']})
    assert o.status_code==201,o.text
    oid=o.json()['id']
    r=d.post(f'/api/orders/{oid}/imaging-reports',json={'template_code':code})
    assert r.status_code==201,r.text
    return oid,r.json()['id'],t


def fill(d,rid,t):
    data={'version':0,'descriptions':[re.sub(r'…+|\.{3,}','1','\n'.join(row[1])) or 'Không khảo sát rõ.' for row in t['content']['rows']],
          'request':re.sub(r'…+|\.{3,}','trái',t['content']['yc']),
          'conclusion':re.sub(r'…+|\.{3,}','1',t['content']['kl'] or 'Kết luận giả lập.'),'advice':re.sub(r'…+|\.{3,}','1',t['content'].get('dan') or '')}
    r=d.put(f'/api/imaging/reports/{rid}',json=data)
    assert r.status_code==200,r.text
    return data


def sign(clients, ids, rid, kind):
    d=clients['doctor']; a=clients['admin']
    assert a.put(f'/api/users/{ids["doctor"]}/signature',files={'file':('fake.png',signature_image(),'image/png')}).status_code==200
    endpoint=f'/api/document-signatures/{kind}/{rid}'
    state=d.get(endpoint)
    assert state.status_code==200,state.text
    r=d.post(endpoint,json={'password':os.environ['DEMO_PASSWORD'],'content_hash':state.json()['content_hash']})
    assert r.status_code==200,r.text


def test_migration_seeds_28_once_and_preserves_content(actors):
    from app.s2d_migration import migrate_s2d, ROOT
    source=json.loads((ROOT/'data/danh_muc_goc/mau_ket_qua_28.json').read_text(encoding='utf-8'))
    with db(True) as c:
        migrate_s2d(c);migrate_s2d(c)
        rows=c.execute('SELECT * FROM imaging_templates ORDER BY code').fetchall()
        assert len(rows)==28
        assert sum(x['category']=='ultrasound' for x in rows)==12
        assert sum(x['category']=='xray' for x in rows)==16
        assert [json.loads(x['content']) for x in rows]==source


def test_admin_can_only_toggle_template(actors):
    clients,_=actors; path='/api/imaging/templates/S2D-001'
    assert clients['doctor'].put(path,json={'active':False}).status_code==403
    assert clients['admin'].put(path,json={'active':False,'name':'Đổi nội dung'}).status_code==422
    try:
        assert clients['admin'].put(path,json={'active':False}).status_code==200
        assert not any(x['code']=='S2D-001' for x in clients['doctor'].get('/api/imaging/templates').json())
        assert len(clients['admin'].get('/api/imaging/templates').json())==28
    finally:
        assert clients['admin'].put(path,json={'active':True}).status_code==200


def test_drafts_and_incomplete_fields_block_print_and_sign(actors):
    clients,_=actors;d=clients['doctor']
    oid,rid,t=make(clients)
    saved=d.get(f'/api/imaging/reports/{rid}').json()
    assert saved['descriptions']==['']*len(t['content']['rows'])
    assert saved['conclusion']==(t['content']['kl'] or '')
    assert d.get(f'/api/imaging/reports/{rid}/form').status_code==422
    assert d.get(f'/api/document-signatures/ultrasound/{rid}').status_code==422
    values=fill(d,rid,t); values['version']=1; values['descriptions'][0]='Còn …… mm'
    assert d.put(f'/api/imaging/reports/{rid}',json=values).status_code==200
    for route in (f'/api/imaging/reports/{rid}/form',f'/api/document-signatures/ultrasound/{rid}',f'/api/forms/ultrasound/{oid}'):
        r=d.get(route)
        assert r.status_code==422,r.text
        assert t['content']['rows'][0][0] in r.json()['detail']
    post=d.post(f'/api/document-signatures/ultrasound/{rid}',json={'password':os.environ['DEMO_PASSWORD'],'content_hash':'0'*64})
    assert post.status_code==422
    values['version']=2;values['descriptions'][0]='Không khảo sát rõ.';values['conclusion']=''
    assert d.put(f'/api/imaging/reports/{rid}',json=values).status_code==200
    assert 'Kết luận' in d.get(f'/api/imaging/reports/{rid}/form').json()['detail']


def test_images_type_size_limit_permissions_and_audit(actors):
    clients,_=actors;d=clients['doctor'];_,rid,_=make(clients)
    path=f'/api/imaging/reports/{rid}/images'
    assert d.post(path,files={'file':('fake.jpg',b'not an image','image/jpeg')}).status_code==415
    assert d.post(path,files={'file':('huge.jpg',b'x'*(LIMITS.upload_bytes+1),'image/jpeg')}).status_code==413
    assert clients['doctor2'].post(path,files={'file':('fake.jpg',pixels(),'image/jpeg')}).status_code==403
    ids=[]
    for color in ('white','blue'):
        r=d.post(path,files={'file':('fake.jpg',pixels(color),'image/jpeg')})
        assert r.status_code==201,r.text
        ids.append(r.json()['id'])
    assert d.post(path,files={'file':('third.jpg',pixels(),'image/jpeg')}).status_code==409
    assert clients['doctor2'].get(path+'/'+str(ids[0])).status_code==403
    assert d.get(path+'/'+str(ids[0])).content==pixels()
    assert clients['technician'].get(path+'/'+str(ids[0])).status_code==200
    from tests.test_workflows import client
    assert client.delete(path+'/'+str(ids[0]),headers=d.headers).status_code==200
    with db() as c:
        events={x['event'] for x in c.execute("SELECT event FROM audit_log WHERE object_type='imaging_report' AND object_id=?",(rid,))}
        assert {'imaging_image_uploaded','imaging_image_deleted'} <= events


def test_signed_content_images_and_correction_reference(actors,monkeypatch):
    from app.imaging import model, report, print_model
    from app.document_signatures import valid_signature
    clients,ids=actors;d=clients['doctor'];oid,rid,t=make(clients)
    data=fill(d,rid,t)
    assert d.post(f'/api/imaging/reports/{rid}/images',files={'file':('fake.jpg',pixels(),'image/jpeg')}).status_code==201
    sign(clients,ids,rid,'ultrasound')
    data['version']=1
    assert d.put(f'/api/imaging/reports/{rid}',json=data).status_code==409
    assert d.post(f'/api/imaging/reports/{rid}/images',files={'file':('fake.jpg',pixels(),'image/jpeg')}).status_code==409
    with db() as c:
        original=model(c,report(c,rid))
        assert valid_signature(c,'ultrasound',rid,models=[original])
        changed=deepcopy(original);changed['conclusion']='Đổi kết luận giả lập'
        assert valid_signature(c,'ultrasound',rid,models=[changed]) is None
        changed['conclusion']=original['conclusion']
        assert valid_signature(c,'ultrasound',rid,models=[changed])
        changed['images'][0]['sha256']='f'*64
        assert valid_signature(c,'ultrasound',rid,models=[changed]) is None
    # External file changes must be detected even though signed API writes are blocked.
    from app.main import FILES
    path=FILES/original['images'][0]['key']
    saved_bytes=path.read_bytes()
    try:
        path.write_bytes(pixels('red'))
        changed_pdf=d.get(f'/api/imaging/reports/{rid}/form')
        assert changed_pdf.status_code==200
        assert 'cần ký lại' in PdfReader(BytesIO(changed_pdf.content)).pages[0].extract_text()
        with db() as c:
            assert print_model(c,report(c,rid))['signature'] is None
    finally:
        path.write_bytes(saved_bytes)
    import app.forms as forms
    monkeypatch.setattr(forms,'WATERMARK','')
    with db() as c:
        assert print_model(c,report(c,rid))['signature']
    assert 'BẢN THỬ NGHIỆM' not in PdfReader(BytesIO(d.get(f'/api/imaging/reports/{rid}/form').content)).pages[0].extract_text()
    correction=d.post(f'/api/imaging/reports/{rid}/corrections',json={'reason':'Đính chính kết luận giả lập'})
    assert correction.status_code==201,correction.text
    new=correction.json()['id']
    v=d.get(f'/api/imaging/reports/{new}').json()
    assert v['replaces_id']==rid and len(v['images'])==1
    assert d.put(f'/api/imaging/reports/{new}',json={'version':0,'descriptions':v['descriptions'],'conclusion':'Kết luận đính chính giả lập','advice':v['advice']}).status_code==200
    sign(clients,ids,new,'ultrasound')
    with db() as c:
        m=print_model(c,report(c,rid))
        assert m['signature'] and m['successor']==f'Đã có phiếu đính chính số MD-HA-{new:06d}'
    response=d.get(f'/api/imaging/reports/{rid}/form')
    assert response.status_code==200,response.text
    pdf=PdfReader(BytesIO(response.content))
    assert f'Đã có phiếu đính chính số MD-HA-{new:06d}' in pdf.pages[0].extract_text()
    for path in (f'/api/forms/ultrasound/{oid}',f'/api/orders/{oid}/forms/result',f'/api/print/result/{oid}'):
        assert d.get(path).status_code==200,path
    from docx import Document
    from zipfile import ZipFile
    word=d.get(f'/api/imaging/reports/{rid}/form?fmt=docx')
    assert word.status_code==200,word.text
    doc=Document(BytesIO(word.content))
    assert f'Đã có phiếu đính chính số MD-HA-{new:06d}' in '\n'.join(p.text for p in doc.paragraphs)
    with ZipFile(BytesIO(word.content)) as archive:
        assert signature_image() in [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]



@pytest.mark.parametrize('code',[f'S2D-{i:03d}' for i in range(1,29)])
def test_all_templates_print_one_a4_including_longest_with_two_images(actors,code,tmp_path,request):
    clients,_=actors;d=clients['doctor'];_,rid,t=make(clients,code)
    fill(d,rid,t)
    if code=='S2D-008':
        previous=clients['admin'].get('/api/clinic-profile').json()
        request.addfinalizer(lambda:clients['admin'].put('/api/clinic-profile',json=previous))
        assert clients['admin'].put('/api/clinic-profile',json={'governing_body':'Đơn vị giả lập','name':'CƠ SỞ GIẢ LẬP','address':'Địa chỉ giả lập','phone':'0000000000','email':'demo@example.invalid'}).status_code==200
        for color in ('blue','white'):
            assert d.post(f'/api/imaging/reports/{rid}/images',files={'file':('fake.jpg',pixels(color),'image/jpeg')}).status_code==201
    r=d.get(f'/api/imaging/reports/{rid}/form')
    assert r.status_code==200,r.text
    pdf=PdfReader(BytesIO(r.content))
    assert len(pdf.pages)==1
    assert abs(float(pdf.pages[0].mediabox.width)-595.276)<1
    assert abs(float(pdf.pages[0].mediabox.height)-841.89)<1
    assert t['name'] in pdf.pages[0].extract_text()
    for label,_ in t['content']['rows']:
        assert ' '.join(label.split()) in ' '.join(pdf.pages[0].extract_text().split())
    if code=='S2D-008':
        assert len(pdf.pages[0].images)==3 # Logo plus two synthetic images.
        (tmp_path/'longest.pdf').write_bytes(r.content)


def test_sqlite_upgrade_preserves_existing_signatures():
    import sqlite3
    from app.s2c_migration import migrate_s2c
    from app.s2d_migration import migrate_s2d
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.executescript('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY); CREATE TABLE users(id INTEGER PRIMARY KEY); CREATE TABLE visits(id INTEGER PRIMARY KEY); INSERT INTO users VALUES(1); INSERT INTO visits VALUES(1);')
    migrate_s2c(c)
    c.execute('INSERT INTO document_signatures(document_kind,document_id,visit_id,signed_by,signed_at,content_hash,image,username) VALUES(?,?,?,?,?,?,?,?)',
              ('rx',1,1,1,'2026-01-01','a'*64,signature_image(),'fake-user'))
    original=tuple(c.execute('SELECT * FROM document_signatures').fetchone())
    migrate_s2d(c);migrate_s2d(c)
    assert tuple(c.execute('SELECT * FROM document_signatures').fetchone())==original
    with pytest.raises(sqlite3.IntegrityError):
        c.execute('UPDATE document_signatures SET username=?',('No change permitted',))
    c.close()


def test_correction_after_visit_closed_does_not_reopen_visit(actors):
    clients,ids=actors;d=clients['doctor'];oid,rid,t=make(clients,'S2D-013')
    fill(d,rid,t);sign(clients,ids,rid,'xray')
    with db(True) as c:
        vid=c.execute('SELECT visit_id FROM orders WHERE id=?',(oid,)).fetchone()['visit_id']
        c.execute("UPDATE visits SET status='completed' WHERE id=?",(vid,))
    correction=d.post(f'/api/imaging/reports/{rid}/corrections',json={'reason':'Đính chính sau đóng lượt'})
    assert correction.status_code==201,correction.text
    new=correction.json()['id']
    r=d.get(f'/api/imaging/reports/{new}').json()
    assert d.put(f'/api/imaging/reports/{new}',json={'version':0,'descriptions':r['descriptions'],'conclusion':'Kết luận đính chính sau đóng lượt','advice':r['advice']}).status_code==200
    sign(clients,ids,new,'xray')
    with db() as c:
        assert c.execute('SELECT status FROM visits WHERE id=?',(vid,)).fetchone()['status']=='completed'
