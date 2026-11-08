"""End-to-end API/form-generation tests, all values are invented."""
import io
from docx import Document
from pypdf import PdfReader
from tests.test_workflows import client,token,prepare_visit


def test_documents_full_workflow_with_role_scope():
    patient,visit=prepare_visit('bs_noi')
    doc,rec,tec,pharm,unassigned=token('bs_noi'),token('letan'),token('kythuat'),token('duoc'),token('bs_san')
    diagnosis='Chẩn đoán giả lập A - không dùng điều trị'
    value={'chief_complaint':'Triệu chứng giả lập B', 'history':'Tiền sử giả lập',
           'vitals':'Mạch 74; huyết áp 110/70','diagnosis':diagnosis,
           'treatment':'Theo dõi mô phỏng','follow_up':'20/12/2026','version':0}
    assert client.put(f'/api/visits/{visit}/clinical',json=value,headers=doc).status_code==200
    # Reception print - doctor cannot print frontdesk form in this minimal role model.
    intake=client.get(f'/api/forms/intake/{visit}?fmt=docx',headers=rec)
    assert intake.status_code==200,intake.text
    assert intake.content[:2]==b'PK'
    assert 'application/vnd.openxmlformats' in intake.headers['content-type']
    assert 'DEMO' in intake.headers['content-disposition']
    assert client.get(f'/api/forms/intake/{visit}',headers=unassigned).status_code==403
    d=Document(io.BytesIO(intake.content))
    tt=' '.join([p.text for p in d.paragraphs]+[c.text for t in d.tables for row in t.rows for c in row.cells])
    assert 'Bệnh nhân mô phỏng Hồng' in tt
    assert f'MD-TD-{visit:06d}' in tt
    # Visiting doctor prints clinical PDF/DOCX + follow-up only for assigned record.
    for kind in ('visit','followup'):
        for fmt in ('docx','pdf'):
            x=client.get(f'/api/forms/{kind}/{visit}?fmt={fmt}',headers=doc)
            assert x.status_code==200,(kind,fmt,x.text[:200] if x.status_code!=200 else '')
            assert (x.content[:4]==b'%PDF') if fmt=='pdf' else x.content[:2]==b'PK'
    assert client.get(f'/api/forms/visit/{visit}',headers=unassigned).status_code==403
    clinical=client.get(f'/api/forms/visit/{visit}?fmt=pdf',headers=doc)
    text=''.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(clinical.content)).pages)
    assert diagnosis in text
    assert 'KHÔNG DÙNG CHO NGƯỜI BỆNH THẬT' in text
    # All 4 diagnostic types: order form and approved result form.
    for category in ('lab','ultrasound','xray','ecg'):
        n=client.post('/api/orders',json={'visit_id':visit,'category':category,'name':f'Dịch vụ kiểm thử {category}'},headers=doc)
        assert n.status_code==201,n.text
        oid=n.json()['id']
        assert client.get(f'/api/forms/{category}/{oid}',headers=doc).status_code==409
        assert client.get(f'/api/forms/order/{oid}?fmt=docx',headers=doc).status_code==200
        assert client.put(f'/api/orders/{oid}/result',json={'result_text':'Kết quả giả lập - không điều trị'},headers=tec).status_code==200
        assert client.post(f'/api/orders/{oid}/approve',headers=doc).status_code==200
        for fmt in ('docx','pdf'):
            res=client.get(f'/api/forms/{category}/{oid}?fmt={fmt}',headers=doc)
            assert res.status_code==200,(category,fmt,res.text if res.status_code!=200 else '')
            assert (res.content[:4]==b'%PDF') if fmt=='pdf' else res.content[:2]==b'PK'
        assert client.get(f'/api/forms/order/{oid}',headers=unassigned).status_code==403
        assert client.get(f'/api/forms/ultrasound/{oid}',headers=doc).status_code==422 if category!='ultrasound' else True
    r=client.post('/api/prescriptions',json={'visit_id':visit,'drug_lines':'Thuốc mô phỏng A | 2 viên | Dùng giả lập, không dùng thật',
                                           'instructions':'Chỉ để thử nghiệm','follow_up':'20/12/2026'},headers=doc)
    assert r.status_code==201,r.text
    rid=r.json()['id']
    for fmt in ('pdf','docx'):
        res=client.get(f'/api/forms/rx/{rid}?fmt={fmt}',headers=doc)
        assert res.status_code==200,res.text if res.status_code!=200 else ''
        assert 'attachment;' in res.headers['content-disposition']
    assert client.get(f'/api/forms/rx/{rid}',headers=pharm).status_code==200
    assert client.get(f'/api/forms/rx/{rid}',headers=unassigned).status_code==403
    assert client.get('/api/forms/invalid/1',headers=doc).status_code==404
    assert client.get(f'/api/forms/intake/{visit}?fmt=txt',headers=rec).status_code==422


def test_form_generation_does_not_mutate_saved_clinical_content():
    _,v=prepare_visit('bs_noi')
    d=token('bs_noi')
    before=client.get(f'/api/visits/{v}',headers=d).json()
    for _ in range(2):
        assert client.get(f'/api/forms/visit/{v}?fmt=pdf',headers=d).status_code==200
    after=client.get(f'/api/visits/{v}',headers=d).json()
    assert before['version']==after['version']==0
