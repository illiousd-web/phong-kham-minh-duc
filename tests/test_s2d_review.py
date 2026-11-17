"""PR 42 review regressions; synthetic identities and generated pixels only."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import re
import sqlite3
from threading import Barrier

from docx import Document
from pypdf import PdfReader
import pytest

from app.main import db
from tests.test_s2c import actors as actors
from tests.test_s2d import make, fill, sign, pixels


def document_text(response, fmt):
    assert response.status_code==200,response.text
    if fmt=='pdf':
        return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    doc=Document(BytesIO(response.content))
    return '\n'.join([p.text for p in doc.paragraphs]+[
        cell.text for table in doc.tables for row in table.rows for cell in row.cells])


@pytest.mark.parametrize('code,wrong',[('S2D-001','xray'),('S2D-013','ultrasound')])
@pytest.mark.parametrize('fmt',['pdf','docx'])
def test_export_rejects_mismatched_imaging_kind(actors,code,wrong,fmt):
    clients,_=actors
    oid,_,_=make(clients,code)
    response=clients['doctor'].get(f'/api/forms/{wrong}/{oid}?fmt={fmt}')
    assert response.status_code==422
    assert response.json()['detail']=='Loại phiếu không khớp chỉ định'


@pytest.mark.parametrize('code,kind',[('S2D-001','ultrasound'),('S2D-013','xray')])
@pytest.mark.parametrize('with_image',[False,True])
def test_pdf_word_identity_and_continuous_matching_headings(actors,code,kind,with_image,monkeypatch):
    clients,_=actors;d=clients['doctor']
    oid,rid,t=make(clients,code)
    fill(d,rid,t)
    with db(True) as c:
        c.execute('''UPDATE patients SET full_name=?,date_of_birth=?,sex=?,address=?
            WHERE id=(SELECT patient_id FROM visits WHERE id=?)''',
            ('Người bệnh định danh giả lập','1992-03-04','Nữ','Địa chỉ định danh giả lập',
             c.execute('SELECT visit_id FROM orders WHERE id=?',(oid,)).fetchone()[0]))
        patient=c.execute('SELECT p.* FROM patients p JOIN visits v ON v.patient_id=p.id JOIN orders o ON o.visit_id=v.id WHERE o.id=?',(oid,)).fetchone()
    # The current patient table has no BHYT input yet. Supply the documented
    # print-context field without adding an unrelated patient-schema feature.
    import app.main as main
    original=main.form_context
    def insured_context(*args,**kwargs):
        context=original(*args,**kwargs)
        context['patient']['health_insurance_number']='FAKE-BHYT-420001'
        return context
    monkeypatch.setattr(main,'form_context',insured_context)
    if with_image:
        assert d.post(f'/api/imaging/reports/{rid}/images',files={'file':('fake.jpg',pixels(),'image/jpeg')}).status_code==201
    expected=['A. YÊU CẦU CHIẾU/CHỤP' if kind=='xray' else 'A. YÊU CẦU KIỂM TRA',
              'B. KẾT QUẢ CHIẾU/CHỤP' if kind=='xray' else 'B. KẾT QUẢ SIÊU ÂM — Mô tả']
    if with_image:
        expected+=['C. HÌNH ẢNH X-QUANG' if kind=='xray' else 'C. HÌNH ẢNH SIÊU ÂM']
    expected+=['D. KẾT LUẬN' if with_image else 'C. KẾT LUẬN']
    for fmt in ('pdf','docx'):
        text=document_text(d.get(f'/api/imaging/reports/{rid}/form?fmt={fmt}'),fmt)
        for value in (patient['full_name'],patient['code'],'04/03/1992','Nữ',patient['address'],
                      'FAKE-BHYT-420001','Chẩn đoán hình ảnh giả lập'):
            assert value in text,(fmt,value,text)
        actual=[line for line in text.splitlines() if re.match(r'^[A-D]\. ',line)]
        assert len(actual)==len(expected),(fmt,actual)
        assert all(line.startswith(heading) for line,heading in zip(actual,expected)),(fmt,actual)


def test_sqlite_signed_images_cannot_be_replaced_with_recursive_triggers_off(actors):
    clients,ids=actors;d=clients['doctor']
    _,rid,t=make(clients);fill(d,rid,t)
    response=d.post(f'/api/imaging/reports/{rid}/images',files={'file':('fake.jpg',pixels(),'image/jpeg')})
    assert response.status_code==201
    iid=response.json()['id']
    _,draft,_=make(clients)
    sign(clients,ids,rid,'ultrasound')
    with db(True) as c:
        c.execute('PRAGMA recursive_triggers=OFF')
        assert c.execute('PRAGMA recursive_triggers').fetchone()[0]==0
        original=dict(c.execute('SELECT * FROM imaging_images WHERE id=?',(iid,)).fetchone())
        for verb in ('INSERT OR REPLACE INTO','REPLACE INTO'):
            for target in (rid,draft):
                values={**original,'report_id':target,'file_key':'fake-replacement.jpg'}
                with pytest.raises(sqlite3.IntegrityError):
                    c.execute(f'{verb} imaging_images('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))
                assert dict(c.execute('SELECT * FROM imaging_images WHERE id=?',(iid,)).fetchone())==original
        for sql,args in [('UPDATE imaging_images SET report_id=? WHERE id=?',(draft,iid)),
                         ('UPDATE imaging_images SET file_key=? WHERE id=?',('fake-replacement.jpg',iid)),
                         ('DELETE FROM imaging_images WHERE id=?',(iid,))]:
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(sql,args)
        assert dict(c.execute('SELECT * FROM imaging_images WHERE id=?',(iid,)).fetchone())==original
    text=document_text(d.get(f'/api/imaging/reports/{rid}/form'),'pdf')
    assert 'cần ký lại' not in text


def test_last_content_editor_is_result_author_and_signer_is_approver(actors):
    clients,ids=actors;d=clients['doctor']
    oid,rid,t=make(clients,'S2D-013')
    values=fill(d,rid,t)
    with db() as c:
        assert c.execute('SELECT updated_by FROM imaging_reports WHERE id=?',(rid,)).fetchone()[0]==ids['doctor']
    assert clients['technician'].put(f'/api/imaging/reports/{rid}',json={**values,'version':1,'conclusion':'Kết luận do kỹ thuật viên giả lập nhập'}).status_code==200
    sign(clients,ids,rid,'xray')
    with db() as c:
        row=c.execute('SELECT created_by,updated_by FROM imaging_reports WHERE id=?',(rid,)).fetchone()
        assert row['created_by']==ids['doctor']
        assert row['updated_by']==ids['technician']
        row=c.execute('SELECT result_by,approved_by FROM orders WHERE id=?',(oid,)).fetchone()
        assert row['result_by']==ids['technician']
        assert row['approved_by']==ids['doctor']


def test_concurrent_image_uploads_leave_exactly_two_images(actors):
    clients,_=actors;d=clients['doctor'];_,rid,_=make(clients)
    path=f'/api/imaging/reports/{rid}/images'
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


def test_review_upgrade_of_existing_v19_is_idempotent_and_preserves_signed_snapshot(actors):
    from app.s2d_migration import migrate_s2d
    clients,ids=actors;_,signed,t=make(clients);fill(clients['doctor'],signed,t)
    sign(clients,ids,signed,'ultrasound')
    _,draft,_=make(clients)
    with db(True) as c:
        snapshot=c.execute('SELECT snapshot FROM imaging_reports WHERE id=?',(signed,)).fetchone()[0]
        c.execute('DROP TRIGGER s2d_image_no_replace')
        c.execute('ALTER TABLE imaging_reports DROP COLUMN updated_by')
        migrate_s2d(c);migrate_s2d(c)
        assert c.execute('SELECT snapshot FROM imaging_reports WHERE id=?',(signed,)).fetchone()[0]==snapshot
        assert c.execute('SELECT updated_by FROM imaging_reports WHERE id=?',(draft,)).fetchone()[0]==ids['doctor']
        assert c.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='s2d_image_no_replace'").fetchone()
