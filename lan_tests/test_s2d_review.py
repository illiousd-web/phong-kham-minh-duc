"""S2d review checks against PostgreSQL, including real concurrent writes."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
import secrets

import psycopg
import pytest
from PIL import Image

from app.database import db
from tests.s2c_cases import new_visit, signature_image
from .conftest import IDS, PASSWORDS, SERVICE


def pixels(color='white'):
    out=BytesIO()
    Image.new('RGB',(320,180),color).save(out,format='JPEG')
    return out.getvalue()


def make_report(clients,category='xray',creator='doctor'):
    vid=new_visit(clients,IDS,SERVICE)
    tag=secrets.token_hex(6)
    response=clients['admin'].post('/api/catalog/services',json={'name':'Hình ảnh rà soát giả lập '+tag,'category':category,'price':1000})
    assert response.status_code==201,response.text
    order=clients['doctor'].post('/api/orders',json={'visit_id':vid,'category':category,'service_id':response.json()['id'],'request_key':tag})
    assert order.status_code==201,order.text
    oid=order.json()['id']
    created=clients[creator].post(f'/api/orders/{oid}/imaging-reports',json={'template_code':'S2D-013' if category=='xray' else 'S2D-001'})
    assert created.status_code==201,created.text
    return oid,created.json()['id']


def sign_report(clients,rid,kind='xray'):
    d=clients['doctor']
    assert clients['admin'].put(f'/api/users/{IDS["doctor"]}/signature',files={'file':('fake.png',signature_image(),'image/png')}).status_code==200
    endpoint=f'/api/document-signatures/{kind}/{rid}'
    state=d.get(endpoint)
    assert state.status_code==200,state.text
    response=d.post(endpoint,json={'password':PASSWORDS['doctor'],'content_hash':state.json()['content_hash']})
    assert response.status_code==200,response.text


def test_postgres_upsert_cannot_move_or_replace_signed_image(clients):
    _,rid=make_report(clients)
    _,draft=make_report(clients)
    tech=clients['technician']
    assert tech.put(f'/api/imaging/reports/{rid}',json={'version':0,'descriptions':['Không khảo sát rõ.'],'conclusion':'Kết luận giả lập'}).status_code==200
    upload=tech.post(f'/api/imaging/reports/{rid}/images',files={'file':('fake.jpg',pixels(),'image/jpeg')})
    assert upload.status_code==201,upload.text
    iid=upload.json()['id']
    sign_report(clients,rid)
    with db() as c:
        original=dict(c.execute('SELECT * FROM imaging_images WHERE id=?',(iid,)).fetchone())
    for target in (rid,draft):
        values={**original,'report_id':target,'file_key':'fake-replacement.jpg'}
        with pytest.raises(psycopg.errors.CheckViolation):
            with db(True) as c:
                c.execute('INSERT INTO imaging_images('+','.join(values)+') VALUES('+','.join('?' for _ in values)+') ON CONFLICT(id) DO UPDATE SET report_id=excluded.report_id,file_key=excluded.file_key',tuple(values.values()))
    for sql,args in [('UPDATE imaging_images SET report_id=? WHERE id=?',(draft,iid)),
                     ('UPDATE imaging_images SET file_key=? WHERE id=?',('fake-replacement.jpg',iid)),
                     ('DELETE FROM imaging_images WHERE id=?',(iid,))]:
        with pytest.raises(psycopg.errors.CheckViolation):
            with db(True) as c:
                c.execute(sql,args)
    with db() as c:
        assert dict(c.execute('SELECT * FROM imaging_images WHERE id=?',(iid,)).fetchone())==original
    state=clients['doctor'].get(f'/api/document-signatures/xray/{rid}')
    assert state.status_code==200,state.text
    assert state.json()['signed_by']==IDS['doctor']


def test_postgres_last_editor_result_by_and_approver_are_distinct(clients):
    oid,rid=make_report(clients)
    with db() as c:
        assert c.execute('SELECT created_by,updated_by FROM imaging_reports WHERE id=?',(rid,)).fetchone()=={'created_by':IDS['doctor'],'updated_by':IDS['doctor']}
    assert clients['technician'].put(f'/api/imaging/reports/{rid}',json={'version':0,'descriptions':['Không khảo sát rõ.'],'conclusion':'Kỹ thuật viên giả lập nhập'}).status_code==200
    sign_report(clients,rid)
    with db() as c:
        assert c.execute('SELECT updated_by FROM imaging_reports WHERE id=?',(rid,)).fetchone()[0]==IDS['technician']
        assert c.execute('SELECT result_by,approved_by FROM orders WHERE id=?',(oid,)).fetchone()=={'result_by':IDS['technician'],'approved_by':IDS['doctor']}


def test_postgres_concurrent_uploads_cannot_exceed_two_images(clients):
    _,rid=make_report(clients)
    d=clients['technician'];path=f'/api/imaging/reports/{rid}/images'
    assert d.post(path,files={'file':('first.jpg',pixels(),'image/jpeg')}).status_code==201
    start=Barrier(2)
    def upload(color):
        start.wait(timeout=10)
        return d.post(path,files={'file':('fake.jpg',pixels(color),'image/jpeg')}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(upload,['red','blue']))
    assert sorted(statuses)==[201,409]
    with db() as c:
        assert c.execute('SELECT COUNT(*) FROM imaging_images WHERE report_id=?',(rid,)).fetchone()[0]==2
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='imaging_image_uploaded' AND object_id=?",(rid,)).fetchone()[0]==2


def test_postgres_review_upgrade_preserves_existing_signed_snapshot(clients):
    from app.s2d_migration import migrate_s2d
    _,signed=make_report(clients)
    assert clients['technician'].put(f'/api/imaging/reports/{signed}',json={'version':0,'descriptions':['Không khảo sát rõ.'],'conclusion':'Kết luận trước nâng cấp giả lập'}).status_code==200
    sign_report(clients,signed)
    _,draft=make_report(clients)
    with db(True) as c:
        before=c.execute('SELECT snapshot FROM imaging_reports WHERE id=?',(signed,)).fetchone()[0]
        c.execute('ALTER TABLE imaging_reports DROP COLUMN updated_by')
        migrate_s2d(c,postgres=True);migrate_s2d(c,postgres=True)
        assert c.execute('SELECT snapshot FROM imaging_reports WHERE id=?',(signed,)).fetchone()[0]==before
        assert c.execute('SELECT updated_by FROM imaging_reports WHERE id=?',(draft,)).fetchone()[0]==IDS['doctor']
