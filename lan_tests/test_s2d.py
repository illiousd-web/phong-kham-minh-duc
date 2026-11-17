"""S2d migration/signing on PostgreSQL, synthetic data only."""
import json
import secrets
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.database import db
from app.s2d_migration import migrate_s2d
from tests.s2c_cases import new_visit, signature_image
from .conftest import IDS, PASSWORDS, SERVICE


def test_postgres_migration_images_signing_and_correction(clients):
    with db(True) as c:
        migrate_s2d(c,postgres=True);migrate_s2d(c,postgres=True)
        assert c.execute('SELECT COUNT(*) FROM imaging_templates').fetchone()[0]==28
    vid=new_visit(clients,IDS,SERVICE)
    tag=secrets.token_hex(6)
    service=clients['admin'].post('/api/catalog/services',json={'name':'X-quang giả lập '+tag,'category':'xray','price':1000})
    assert service.status_code==201,service.text
    d=clients['doctor']
    o=d.post('/api/orders',json={'visit_id':vid,'category':'xray','service_id':service.json()['id'],'request_key':tag})
    assert o.status_code==201,o.text
    oid=o.json()['id']
    created=clients['technician'].post(f'/api/orders/{oid}/imaging-reports',json={'template_code':'S2D-013'})
    assert created.status_code==201,created.text
    rid=created.json()['id']
    assert rid is not None
    assert clients['doctor2'].get(f'/api/imaging/reports/{rid}').status_code==403
    assert clients['reception'].get(f'/api/imaging/reports/{rid}').status_code==403
    body={'version':0,'descriptions':['Không khảo sát rõ.'],'conclusion':'Kết luận X-quang giả lập','advice':'Lời dặn giả lập'}
    assert clients['technician'].put(f'/api/imaging/reports/{rid}',json=body).status_code==200
    assert clients['admin'].put(f'/api/users/{IDS["doctor"]}/signature',files={'file':('fake.png',signature_image(),'image/png')}).status_code==200
    endpoint=f'/api/document-signatures/xray/{rid}'
    state=d.get(endpoint)
    assert state.status_code==200,state.text
    assert clients['technician'].post(endpoint,json={'password':PASSWORDS['technician'],'content_hash':state.json()['content_hash']}).status_code==403
    result=d.post(endpoint,json={'password':PASSWORDS['doctor'],'content_hash':state.json()['content_hash']})
    assert result.status_code==200,result.text
    with db() as c:
        snapshot=json.loads(c.execute('SELECT snapshot FROM imaging_reports WHERE id=?',(rid,)).fetchone()['snapshot'])
        assert snapshot['conclusion']==body['conclusion']
    with pytest.raises(Exception,match='bất biến'):
        with db(True) as c:
            c.execute('UPDATE imaging_reports SET conclusion=? WHERE id=?',('Không được sửa',rid))
    assert d.put(f'/api/imaging/reports/{rid}',json={**body,'version':1}).status_code==409
    correction=d.post(f'/api/imaging/reports/{rid}/corrections',json={'reason':'Sửa nội dung giả lập'})
    assert correction.status_code==201,correction.text
    new=correction.json()['id']
    state=d.get(f'/api/document-signatures/xray/{new}')
    assert state.status_code==200,state.text
    assert d.post(f'/api/document-signatures/xray/{new}',json={'password':PASSWORDS['doctor'],'content_hash':state.json()['content_hash']}).status_code==200
    printed=d.get(f'/api/forms/xray/{oid}')
    assert printed.status_code==200,printed.text
    pdf=PdfReader(BytesIO(printed.content))
    assert len(pdf.pages)==1
    assert f'Đã có phiếu đính chính số MD-HA-{new:06d}' in pdf.pages[0].extract_text()
    assert len(pdf.pages[0].images)==2 # Logo and original signature.
