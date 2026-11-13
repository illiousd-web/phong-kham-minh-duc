"""S1b API regressions; synthetic patients/drugs, public-source ingredient probes."""
import secrets
import pytest
from tests.test_administrative import context
from app.main import db


@pytest.fixture
def prescription():
    clients, ids = context()
    r,d = clients['reception'],clients['doctor']
    p=r.post('/api/patients',json={'full_name':'Giả lập S1 '+secrets.token_hex(5),'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':p,'doctor_id':ids['doctor'],'service_id':1}).json()['id']
    with db(True) as c:
        c.execute('UPDATE users SET practice_license=?,practice_scopes=? WHERE id=?',('GP-GIA-LAP','["Nội"]',ids['doctor']))
        c.execute('UPDATE visits SET diagnosis=? WHERE id=?',('Chẩn đoán giả lập',vid))
    line={'name':'Thuốc giả lập S1 '+secrets.token_hex(6),'ingredient':'Hoạt chất giả lập','strength':'5 mg','unit':'viên','quantity':'2','dose':'1','frequency':'1','days':'2','route':'Uống','timing':'sau ăn'}
    return d,vid,line


def create(d,vid,line):
    response=d.post('/api/clinical-prescriptions',json={'visit_id':vid,'items':[line]})
    assert response.status_code==201,response.text
    return response.json()['id']


@pytest.mark.parametrize('field,value', [('quantity','abc'),('quantity','-10'),('quantity','0'),('days','0'),('days','-1'),('days','31'),('dose','abc'),('dose','0'),('dose','-1'),('frequency','abc'),('frequency','0'),('frequency','-1'),('unit',''),('strength',''),('timing','')])
def test_invalid_line_cannot_lock(prescription,field,value):
    d,vid,line=prescription
    rid=create(d,vid,{**line,field:value})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==422,response.text
    assert any(e['field']==field for e in response.json()['detail']['errors'])



def test_positive_comma_quantity_and_printed_dose_unit(prescription):
    import io
    from docx import Document
    import pymupdf
    d,vid,line=prescription
    rid=create(d,vid,{**line,'quantity':'1,5','dose':'0,75','frequency':'1','days':'2'})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==200,response.text
    for fmt in ('docx','pdf'):
        response=d.get(f'/api/clinical-prescriptions/{rid}/form?fmt={fmt}')
        assert response.status_code==200,response.text
        if fmt=='docx':
            document=Document(io.BytesIO(response.content))
            text=' '.join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        else:
            with pymupdf.open(stream=response.content,filetype='pdf') as document:text=' '.join(page.get_text() for page in document)
        assert '0,75 viên' in text


def test_manual_quantity_requires_reason_but_flexible_units_only_warn(prescription):
    d,vid,line=prescription
    for change,expected in [({'quantity':'10'},422),({'quantity':'10','quantity_acknowledged':True,'quantity_reason':'ngắn'},422),({'quantity':'10','quantity_acknowledged':True,'quantity_reason':'Lý do giả lập đủ dài'},200),({'quantity':'10','unit':'chai','dose_unit':'ml'},200),({'quantity':'2,4'},200)]:
        rid=create(d,vid,{**line,**change})
        response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
        assert response.status_code==expected,response.text
