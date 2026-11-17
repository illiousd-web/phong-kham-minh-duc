"""Structured ultrasound/X-ray results extend existing orders and document signing."""
import hashlib
from io import BytesIO
import json
import re
import uuid
import warnings

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .resources import LIMITS, export_slot


class ReportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=0)
    descriptions: list[str] = Field(max_length=40)
    request: str | None = Field(default=None, max_length=2000)
    conclusion: str = Field(default='', max_length=3000)
    advice: str = Field(default='', max_length=2000)


class OpenInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    template_code: str = Field(max_length=20)


class CorrectInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=8, max_length=1000)


class ActiveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool


def template(c, code):
    r = c.execute('SELECT * FROM imaging_templates WHERE code=?', (code,)).fetchone()
    if not r:
        raise HTTPException(404, 'Không có mẫu kết quả')
    return {**dict(r), 'content':json.loads(r['content'])}


def report(c, rid):
    r = c.execute('SELECT * FROM imaging_reports WHERE id=?', (rid,)).fetchone()
    if not r:
        raise HTTPException(404, 'Không có phiếu hình ảnh')
    return dict(r)


def access(c, u, oid, *, kind=None, writing=False, correction=False):
    if not {'doctor','technician'}.intersection(u['roles']):
        raise HTTPException(403, 'Chỉ bác sĩ hoặc kỹ thuật viên được xem kết quả')
    o = c.execute('SELECT o.*,v.doctor_id,v.status AS visit_status FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?', (oid,)).fetchone()
    if o and kind is not None and kind != o['category']:
        raise HTTPException(422, 'Loại phiếu không khớp chỉ định')
    if not o or o['category'] not in ('ultrasound','xray'):
        raise HTTPException(404, 'Không có chỉ định siêu âm/X-quang')
    if 'technician' not in u['roles'] and o['doctor_id'] != u['id']:
        raise HTTPException(403, 'Không phải bác sĩ phụ trách')
    if o['status'] in ('cancelled','requested'):
        raise HTTPException(409, 'Chỉ định đã hủy hoặc chưa được duyệt')
    if writing and (o['visit_status']=='cancelled' or (o['visit_status']=='completed' and not correction)):
        raise HTTPException(409, 'Lượt khám đã kết thúc')
    return dict(o)


def editable(r):
    if r['snapshot']:
        raise HTTPException(409, 'Phiếu đã ký, phải lập phiếu đính chính')


def images(c, rid):
    return [dict(x) for x in c.execute('SELECT * FROM imaging_images WHERE report_id=? ORDER BY id', (rid,))]


def model(c, r):
    from .main import form_context, FILES
    from .practitioners import printed_name
    if r['snapshot']:
        m = json.loads(r['snapshot'])
    else:
        o = c.execute('SELECT * FROM orders WHERE id=?', (r['order_id'],)).fetchone()
        ctx = form_context(c, 'intake', o['visit_id'])
        t = template(c, r['template_code'])['content']
        from .d0 import diagnosis_text
        m = {'kind':o['category'], 'imaging':True, 'report_id':r['id'], 'order_id':o['id'],
             'number':f"MD-HA-{r['id']:06d}", 'template_name':t['n'], 'request':r['request'],
             'patient':ctx['patient'], 'diagnosis':diagnosis_text(ctx['visit']), 'profile':ctx['clinic_profile'],
             'sections':[[row[0], text] for row, text in zip(t['rows'], json.loads(r['descriptions']))],
             'conclusion':r['conclusion'], 'advice':r['advice'], 'stamp':r['updated_at'],
             'signer_name':printed_name(c, ctx['visit']['doctor_id']), 'actor':ctx['visit']['doctor_id'],
             'visit_id':o['visit_id'], 'replaces':f"MD-HA-{r['replaces_id']:06d}" if r['replaces_id'] else '',
             'reason':r['reason']}
    m['images'] = []
    for item in images(c, r['id']):
        path = FILES/item['file_key']
        if not path.is_file():
            raise HTTPException(409, 'Thiếu ảnh trên máy chủ, cần kiểm tra bản sao lưu')
        m['images'].append({'key':item['file_key'], 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    successor = c.execute('SELECT id FROM imaging_reports WHERE replaces_id=? AND snapshot IS NOT NULL', (r['id'],)).fetchone()
    m['successor'] = f"Đã có phiếu đính chính số MD-HA-{successor['id']:06d}" if successor else ''
    return m


def complete(m):
    missing = []
    for label, value in m['sections']+[('Kết luận',m['conclusion'])]:
        if not value.strip() or re.search(r'…|\.{3,}', value):
            missing.append(label)
    for label, value in [('Lời dặn',m['advice']), ('Yêu cầu',m['request'])]:
        if (label=='Yêu cầu' and not value.strip()) or re.search(r'…|\.{3,}', value):
            missing.append(label)
    if missing:
        raise HTTPException(422, 'Chưa hoàn tất: '+', '.join(missing))


def content(m):
    # Rendering decorations and filesystem keys never participate in signing.
    return {k:m[k] for k in ('kind','patient','diagnosis','profile','template_name','request','sections',
                             'conclusion','advice','stamp','signer_name','actor','replaces','reason')} | {
        'image_hashes':[x['sha256'] for x in m['images']]}


def print_model(c, r):
    from .document_signatures import valid_signature, signature_notice
    m = model(c, r)
    complete(m)
    m['signature'] = valid_signature(c, m['kind'], r['id'], models=[m])
    m['signature_notice'] = signature_notice(c, m['kind'], r['id'], m['signature'])
    return m


def install_imaging(app, db, principal, require, audit, now):
    @app.get('/api/imaging/templates')
    def catalog(category: str | None = None, u=Depends(principal)):
        require(u, 'admin','doctor','technician')
        with db() as c:
            rows = [dict(r) for r in c.execute('SELECT * FROM imaging_templates ORDER BY code')]
        return [{**r, 'content':json.loads(r['content'])} for r in rows if
                ('admin' in u['roles'] or r['active']) and (category is None or r['category']==category)]

    @app.put('/api/imaging/templates/{code}')
    def enable(code: str, data: ActiveInput, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            template(c, code)
            c.execute('UPDATE imaging_templates SET active=? WHERE code=?', (int(data.active),code))
            audit(c,u,'imaging_template_active','imaging_template',None,json.dumps({'code':code,'active':data.active}))
        return {'ok':True}

    @app.get('/api/orders/{oid}/imaging-reports')
    def listing(oid: int, u=Depends(principal)):
        with db() as c:
            o = access(c,u,oid)
            patient = c.execute('SELECT p.sex,p.full_name,p.code FROM patients p JOIN visits v ON v.patient_id=p.id WHERE v.id=?', (o['visit_id'],)).fetchone()
            rows = [dict(x) for x in c.execute('SELECT * FROM imaging_reports WHERE order_id=? ORDER BY id', (oid,))]
            return {'items':rows, 'sex':patient['sex'], 'patient_name':patient['full_name'], 'patient_code':patient['code'], 'category':o['category']}

    @app.post('/api/orders/{oid}/imaging-reports', status_code=201)
    def create(oid: int, data: OpenInput, u=Depends(principal)):
        with db(True) as c:
            o = access(c,u,oid,writing=True)
            if c.execute('SELECT 1 FROM imaging_reports WHERE order_id=?', (oid,)).fetchone():
                raise HTTPException(409, 'Chỉ định đã có phiếu, mở lại phiếu hiện có')
            if o['status']=='approved' or o['result_text'] or o['file_key']:
                raise HTTPException(409, 'Chỉ định đã có kết quả cũ, không ghi đè')
            t = template(c,data.template_code)
            if not t['active'] or t['category'] != o['category']:
                raise HTTPException(422, 'Mẫu không phù hợp hoặc đã tắt')
            stamp = now()
            c.execute('''INSERT INTO imaging_reports(order_id,template_code,descriptions,request,conclusion,advice,created_by,created_at,updated_at,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (oid,data.template_code,json.dumps(['']*len(t['content']['rows'])),t['content']['yc'],
                t['content']['kl'] or '',t['content'].get('dan') or '',u['id'],stamp,stamp,u['id']))
            rid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,u,'imaging_created','imaging_report',rid)
            return {'id':rid}

    @app.get('/api/imaging/reports/{rid}')
    def read(rid: int, u=Depends(principal)):
        with db('access') as c:
            r = report(c,rid)
            access(c,u,r['order_id'])
            audit(c,u,'imaging_viewed','imaging_report',rid)
            return {**r,'descriptions':json.loads(r['descriptions']), 'template':template(c,r['template_code']),
                    'images':[{'id':x['id'],'media_type':x['media_type']} for x in images(c,rid)]}

    @app.put('/api/imaging/reports/{rid}')
    def save(rid: int, data: ReportInput, u=Depends(principal)):
        with db(True) as c:
            r = report(c,rid)
            access(c,u,r['order_id'],writing=True,correction=bool(r['replaces_id']))
            editable(r)
            t = template(c,r['template_code'])['content']
            if data.version != r['version']:
                raise HTTPException(409, 'Phiếu đã được sửa, tải lại trước khi lưu')
            if len(data.descriptions) != len(t['rows']) or any(len(x)>5000 for x in data.descriptions):
                raise HTTPException(422, 'Số mục hoặc độ dài mô tả không phù hợp')
            new_request = data.request if data.request is not None else r['request']
            if (json.dumps(data.descriptions,ensure_ascii=False) == r['descriptions'] and new_request == r['request']
                    and data.conclusion == r['conclusion'] and data.advice == r['advice']):
                return {'version': r['version']}
            c.execute('UPDATE imaging_reports SET descriptions=?,request=?,conclusion=?,advice=?,version=version+1,updated_at=?,updated_by=? WHERE id=?',
                      (json.dumps(data.descriptions,ensure_ascii=False),data.request if data.request is not None else r['request'],data.conclusion,data.advice,now(),u['id'],rid))
            audit(c,u,'imaging_saved','imaging_report',rid)
        return {'version':data.version+1}

    @app.post('/api/imaging/reports/{rid}/corrections', status_code=201)
    def correct(rid: int, data: CorrectInput, u=Depends(principal)):
        with db(True) as c:
            r = report(c,rid)
            access(c,u,r['order_id'],writing=True,correction=True)
            if not r['snapshot']:
                raise HTTPException(409, 'Chỉ đính chính phiếu đã ký')
            if len(data.reason.strip())<8 or c.execute('SELECT 1 FROM imaging_reports WHERE replaces_id=?', (rid,)).fetchone():
                raise HTTPException(409, 'Thiếu lý do hoặc phiếu đã có đính chính')
            stamp = now()
            c.execute('''INSERT INTO imaging_reports(order_id,template_code,descriptions,request,conclusion,advice,created_by,created_at,updated_at,replaces_id,reason,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(r['order_id'],r['template_code'],r['descriptions'],r['request'],r['conclusion'],r['advice'],u['id'],stamp,stamp,rid,data.reason.strip(),u['id']))
            new = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for item in images(c,rid):
                c.execute('INSERT INTO imaging_images(report_id,file_key,sha256,media_type,created_by,created_at) VALUES(?,?,?,?,?,?)',
                          (new,item['file_key'],item['sha256'],item['media_type'],u['id'],stamp))
            audit(c,u,'imaging_corrected','imaging_report',new,str(rid)+': '+data.reason)
        return {'id':new}

    @app.post('/api/imaging/reports/{rid}/images', status_code=201)
    def upload(rid: int, file: UploadFile=File(...), u=Depends(principal)):
        require(u,'doctor','technician')
        from .main import FILES
        from .storage import check_upload
        raw = file.file.read(LIMITS.upload_bytes+1)
        if not raw or len(raw)>LIMITS.upload_bytes:
            raise HTTPException(413, 'Ảnh vượt dung lượng cho phép')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as im:
                    if im.format not in ('JPEG','PNG') or im.width*im.height>20_000_000:
                        raise ValueError()
                    fmt = im.format
                    im.verify()
                with Image.open(BytesIO(raw)) as im:
                    im.load()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(415, 'Chỉ nhận ảnh JPG/PNG hợp lệ') from None
        media = 'image/jpeg' if fmt=='JPEG' else 'image/png'
        if file.content_type != media:
            raise HTTPException(415, 'Loại tệp không khớp ảnh')
        key = 's2d-'+uuid.uuid4().hex+('.jpg' if fmt=='JPEG' else '.png')
        target = FILES/key
        try:
            with db(True) as c:
                r = report(c,rid)
                access(c,u,r['order_id'],writing=True,correction=bool(r['replaces_id']))
                editable(r)
                # db(True) holds the PostgreSQL writer lock / SQLite BEGIN IMMEDIATE
                # through commit: count and insert cannot race another upload.
                if c.execute('SELECT COUNT(*) FROM imaging_images WHERE report_id=?',(rid,)).fetchone()[0]>=2:
                    raise HTTPException(409, 'Mỗi phiếu tối đa 2 ảnh')
                check_upload(FILES,len(raw))
                FILES.mkdir(parents=True,exist_ok=True)
                import os
                with target.open('xb') as out:
                    out.write(raw); out.flush(); os.fsync(out.fileno())
                c.execute('INSERT INTO imaging_images(report_id,file_key,sha256,media_type,created_by,created_at) VALUES(?,?,?,?,?,?)',
                          (rid,key,hashlib.sha256(raw).hexdigest(),media,u['id'],now()))
                iid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute('UPDATE imaging_reports SET version=version+1, updated_by=? WHERE id=?', (u['id'], rid))
                audit(c,u,'imaging_image_uploaded','imaging_report',rid,str(iid))
        except Exception:
            # A lost commit acknowledgement must never delete a referenced file.
            if target.exists():
                with db(True) as c:
                    if not c.execute('SELECT 1 FROM imaging_images WHERE file_key=?',(key,)).fetchone():
                        target.unlink(missing_ok=True)
            raise
        return {'id':iid}

    @app.get('/api/imaging/reports/{rid}/images/{iid}')
    def picture(rid: int, iid: int, u=Depends(principal)):
        from .main import FILES
        with db('access') as c:
            r = report(c,rid)
            access(c,u,r['order_id'])
            item = c.execute('SELECT * FROM imaging_images WHERE id=? AND report_id=?',(iid,rid)).fetchone()
            if not item or not (FILES/item['file_key']).is_file():
                raise HTTPException(404, 'Không có ảnh')
            audit(c,u,'imaging_image_viewed','imaging_report',rid,str(iid))
            return Response((FILES/item['file_key']).read_bytes(),media_type=item['media_type'],headers={'Cache-Control':'no-store'})

    @app.delete('/api/imaging/reports/{rid}/images/{iid}')
    def delete_picture(rid: int, iid: int, u=Depends(principal)):
        from .main import FILES
        with db(True) as c:
            r = report(c,rid)
            access(c,u,r['order_id'],writing=True,correction=bool(r['replaces_id']))
            editable(r)
            item = c.execute('SELECT * FROM imaging_images WHERE id=? AND report_id=?',(iid,rid)).fetchone()
            if not item:
                raise HTTPException(404, 'Không có ảnh')
            key = item['file_key']
            c.execute('DELETE FROM imaging_images WHERE id=?',(iid,))
            c.execute('UPDATE imaging_reports SET version=version+1, updated_by=? WHERE id=?', (u['id'], rid))
            audit(c,u,'imaging_image_deleted','imaging_report',rid,str(iid))
        with db(True) as c:
            if not c.execute('SELECT 1 FROM imaging_images WHERE file_key=?',(key,)).fetchone():
                (FILES/key).unlink(missing_ok=True)
        return {'ok':True}

    @app.get('/api/imaging/reports/{rid}/form')
    @export_slot
    def form(rid: int, fmt: str='pdf', u=Depends(principal)):
        from .imaging_forms import render
        with db('access') as c:
            r = report(c,rid)
            access(c,u,r['order_id'])
            data = print_model(c,r)
            audit(c,u,'imaging_printed','imaging_report',rid,fmt)
            raw = render(data,fmt)
        return Response(raw,media_type='application/pdf' if fmt=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        headers={'Cache-Control':'no-store','Content-Disposition':f'inline; filename="{data["number"]}.{fmt}"'})
