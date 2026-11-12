"""End-to-end form generation/authorization tests using ONLY synthetic patients."""
from __future__ import annotations
import io
import os
import tempfile
from pathlib import Path
import pytest
import fitz
from docx import Document
from fastapi.testclient import TestClient
from app import main as mod

@pytest.fixture
def ctx(tmp_path,monkeypatch):
    from app import database
    monkeypatch.setattr(mod,'DB',tmp_path/'db.sqlite3')
    monkeypatch.setattr(database,'DB',tmp_path/'db.sqlite3')
    monkeypatch.setattr(mod,'FILES',tmp_path/'uploads')
    mod.init_db()
    client=TestClient(mod.app)
    def role(name):
        x=client.post('/api/login',json={'username':name,'password':os.environ['DEMO_PASSWORD']})
        assert x.status_code==200,x.text
        return {'Authorization':'Bearer '+x.json()['access_token']}
    h={name:role(name) for name in ('letan','bs_noi','bs_san','kythuat','duoc','thungan')}
    p=client.post('/api/patients',headers=h['letan'],json={'full_name':'Bệnh nhân mô phỏng Trần Ngọc A','sex':'Nữ',
       'date_of_birth':'1991-09-20','phone':'0000000000','citizen_id':'000000000567','address':'Địa chỉ giả lập'}).json()
    doc=next(x['id'] for x in client.get('/api/staff',headers=h['letan']).json() if x['username']=='bs_noi')
    v=client.post('/api/visits',headers=h['letan'],json={'patient_id':p['id'],'doctor_id':doc,'service_id':1}).json()['id']
    clinical={'chief_complaint':'Triệu chứng mô phỏng','history':'Bệnh sử giả lập','vitals':'Mạch 72 lần/phút (giả lập)',
      'diagnosis':'Chẩn đoán giả lập, không có giá trị y khoa','treatment':'Lời dặn chỉ dành cho kiểm thử',
      'follow_up':'2026-12-01','version':0}
    r=client.put(f'/api/visits/{v}/clinical',headers=h['bs_noi'],json=clinical)
    assert r.status_code==200,r.text
    return client,h,p,v


def content_as_text(r,fmt):
    assert r.status_code==200, r.text[:900]
    assert r.headers['cache-control']=='no-store'
    if fmt=='pdf':
        assert r.content[:5]==b'%PDF-'
        pdf=fitz.open(stream=r.content,filetype='pdf')
        return '\n'.join(page.get_text() for page in pdf)
    assert r.content[:2]==b'PK'
    d=Document(io.BytesIO(r.content))
    text='\n'.join(p.text for p in d.paragraphs)
    text+='\n'+'\n'.join(c.text for t in d.tables for row in t.rows for c in row.cells)
    return text

@pytest.mark.parametrize('fmt',['pdf','docx'])
@pytest.mark.parametrize('kind,who',[
    ('reception','letan'),('clinical','bs_noi'),('followup','bs_noi')
])
def test_visit_forms(ctx,kind,who,fmt):
    c,h,p,v=ctx
    r=c.get(f'/api/visits/{v}/forms/{kind}?format={fmt}',headers=h[who])
    text=content_as_text(r,fmt)
    assert 'Trần Ngọc A' in text, (kind,fmt,text[:500])
    if kind=='clinical':assert 'Triệu chứng mô phỏng' in text
    if kind=='followup':assert '2026-12-01' in text or '01/12/2026' in text

@pytest.mark.parametrize('kind',['lab','ultrasound','xray','ecg'])
def test_result_forms_clinical_permissions(ctx,kind):
    c,h,p,v=ctx
    o=c.post('/api/orders',headers=h['bs_noi'],json={'visit_id':v,'category':kind,'name':'Dịch vụ giả lập '+kind})
    assert o.status_code==201,o.text
    oid=o.json()['id']
    assert c.get(f'/api/orders/{oid}/forms/result',headers=h['bs_noi']).status_code==409
    assert c.get(f'/api/orders/{oid}/forms/order',headers=h['bs_san']).status_code==403
    assert c.get(f'/api/orders/{oid}/forms/order',headers=h['thungan']).status_code==403
    for fmt in ('pdf','docx'):
        t=content_as_text(c.get(f'/api/orders/{oid}/forms/order?format={fmt}',headers=h['bs_noi']),fmt)
        assert 'Dịch vụ giả lập' in t
    res=c.put(f'/api/orders/{oid}/result',headers=h['kythuat'],json={'version':0,'result_text':'Kết quả thử nghiệm '+kind})
    assert res.status_code==200
    assert c.get(f'/api/orders/{oid}/forms/result',headers=h['bs_noi']).status_code==409
    assert c.post(f'/api/orders/{oid}/approve',headers=h['bs_noi']).status_code==200
    for fmt in ('pdf','docx'):
        t=content_as_text(c.get(f'/api/orders/{oid}/forms/result?format={fmt}',headers=h['bs_noi']),fmt)
        assert 'Trần Ngọc A' in t
        assert 'Kết quả thử nghiệm' in t

@pytest.mark.parametrize('fmt',['pdf','docx'])
def test_prescription_draft_print_and_scope(ctx,fmt):
    c,h,p,v=ctx
    rx=c.post('/api/prescriptions',headers=h['bs_noi'],json={
       'visit_id':v,'drug_lines':'Thuốc giả lập A | 3 viên | hướng dẫn chỉ thử nghiệm\nVật tư giả lập B | 2 cái | thử nghiệm',
       'instructions':'CHỈ MÔ PHỎNG – KHÔNG CÓ HƯỚNG DẪN ĐIỀU TRỊ', 'follow_up':'2026-12-01'})
    assert rx.status_code==201,rx.text
    rid=rx.json()['id']
    assert c.get(f'/api/prescriptions/{rid}/forms/prescription',headers=h['bs_san']).status_code==403
    assert c.get(f'/api/prescriptions/{rid}/forms/prescription',headers=h['letan']).status_code==403
    text=content_as_text(c.get(f'/api/prescriptions/{rid}/forms/prescription?format={fmt}',headers=h['bs_noi']),fmt)
    assert 'Thuốc giả lập' in text
    assert 'Trần Ngọc A' in text
    assert 'ĐƠN NHÁP' in text or 'NHÁP' in text or 'THỬ NGHIỆM' in text


def test_invalid_format_and_scope(ctx):
    c,h,p,v=ctx
    assert c.get(f'/api/visits/{v}/forms/clinical?format=exe',headers=h['bs_noi']).status_code==422
    assert c.get(f'/api/visits/{v}/forms/clinical',headers=h['bs_san']).status_code==403
    assert c.get(f'/api/visits/{v}/forms/reception',headers=h['bs_noi']).status_code==403
    assert c.get(f'/api/visits/{v}/forms/clinical').status_code==401
    assert c.get('/api/orders/10000/forms/result',headers=h['bs_noi']).status_code==404


def test_respects_persisted_data_not_unsaved_browser_fields(ctx):
    c,h,p,v=ctx
    t=content_as_text(c.get(f'/api/visits/{v}/forms/clinical',headers=h['bs_noi']),'pdf')
    assert 'Chẩn đoán giả lập' in t
    from app.main import DB
    import sqlite3
    with sqlite3.connect(DB) as con:
        assert con.execute("SELECT diagnosis FROM visits WHERE id=?",(v,)).fetchone()[0] in t
