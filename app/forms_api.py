"""Authenticated, role-scoped demo document export endpoints."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from .resources import export_slot
from .administrative import redact_document
from .practitioners import printed_name
from .forms import generate_docx, generate_pdf, TEMPLATE_BY_TYPE


def mount_forms(app, db, principal, require, audit):
    router=APIRouter(prefix='/api')

    def get_visit(c, vid):
        r=c.execute('''SELECT v.id AS visit_id,v.doctor_id,v.status AS visit_status,v.created_at,
             v.chief_complaint,v.history,v.vitals,v.diagnosis,v.treatment,v.follow_up,
             v.weight_kg,v.escort_name,v.escort_relationship,v.escort_phone,
             p.document_number,p.ethnicity,p.occupation,p.workplace,p.province,p.commune,p.address_detail,
             p.full_name,p.code,p.date_of_birth,p.sex,p.phone,p.citizen_id,p.address,
             u.full_name AS doctor_name
             FROM visits v JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=v.doctor_id
             WHERE v.id=?''',(vid,)).fetchone()
        if not r:raise HTTPException(404,'Không có lượt khám')
        result=redact_document(dict(r))
        result['doctor_name']=printed_name(c,result['doctor_id'])
        return result

    def ensure_assigned(u,c,vid):
        v=get_visit(c,vid)
        if 'doctor' not in u['roles'] or v['doctor_id']!=u['id']:
            raise HTTPException(403,'Không có quyền xuất biểu mẫu này')
        return v

    def response(kind,ctx,fmt):
        if fmt not in ('docx','pdf'):raise HTTPException(422,'Chỉ hỗ trợ pdf hoặc docx')
        k={'reception':'intake','clinical':'visit'}.get(kind,kind)
        patient={key:ctx.get(key) for key in ('full_name','code','date_of_birth','sex','phone','citizen_id','address','document_number','ethnicity','occupation','workplace','province','commune','address_detail')}
        visit={key:ctx.get(key) for key in ('chief_complaint','history','vitals','diagnosis','treatment','follow_up','created_at','weight_kg','escort_name','escort_relationship','escort_phone')}
        visit.update(id=ctx['visit_id'],doctor_id=ctx['doctor_id'],status=ctx['visit_status'])
        payload={'patient':patient,'visit':visit,'doctor_name':ctx['doctor_name'],
                 'service_label':'Khám ngoại trú (mô phỏng)','orders':ctx.get('orders',[]),'addenda':ctx.get('addenda',[])}
        if 'order_id' in ctx:
            payload['order']={'id':ctx['order_id'],'name':ctx['order_name'],'category':ctx['category'],
                              'status':ctx['order_status'],'result_text':ctx['result_text'],
                              'created_at':ctx['order_created_at'],'file_name':ctx.get('file_name'),
                              'approved_by_name':ctx.get('approved_by_name'),'result_by_name':ctx.get('result_by_name')}
        if 'rx_id' in ctx:
            payload['rx']={'id':ctx['rx_id'],'drug_lines':ctx['drug_lines'],'instructions':ctx['instructions'],
                           'follow_up':ctx.get('follow_up'),'created_at':ctx['rx_created_at']}
        if fmt=='docx':
            b=generate_docx(k,payload);mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        else:
            b=generate_pdf(k,payload);mime='application/pdf'
        fid=ctx.get('order_id') or ctx.get('rx_id') or ctx.get('visit_id') or 'sample'
        filename=f'Minh_Duc_{kind}_{fid}.{fmt}'
        return Response(content=b,media_type=mime,headers={
            'Content-Disposition':f'attachment; filename="{filename}"',
            'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'
        })

    @router.get('/visits/{visit_id}/forms/{kind}')
    @export_slot
    def visit_form(visit_id:int,kind:str,format:str='pdf',u=Depends(principal)):
        if kind not in ('reception','clinical','followup'):
            raise HTTPException(404,'Biểu mẫu không tồn tại')
        with db(True) as c:
            if kind=='reception':
                require(u,'reception','admin')
                ctx=get_visit(c,visit_id)
            else:
                require(u,'doctor')
                ctx=ensure_assigned(u,c,visit_id)
            if kind=='followup' and not ctx.get('follow_up'):
                raise HTTPException(409,'Chưa có ngày hẹn tái khám')
            if kind=='clinical':ctx['addenda']=[dict(x) for x in c.execute("SELECT * FROM visit_addenda WHERE visit_id=? AND status='approved' ORDER BY id",(visit_id,))]
            for appendix in ctx.get('addenda',[]):appendix['author_name']=printed_name(c,appendix['created_by'])
            result=response(kind,ctx,format)
            audit(c,u,'demo_form_exported','visit',visit_id,f'{kind}.{format}')
            return result

    @router.get('/orders/{order_id}/forms/{kind}')
    @export_slot
    def order_form(order_id:int,kind:str,format:str='pdf',u=Depends(principal)):
        if kind not in ('order','result'):raise HTTPException(404,'Biểu mẫu không tồn tại')
        require(u,'doctor','technician')
        with db(True) as c:
            o=c.execute('''SELECT o.*,a.full_name AS approved_by_name
              FROM orders o LEFT JOIN users a ON a.id=o.approved_by
              WHERE o.id=?''',(order_id,)).fetchone()
            if not o:raise HTTPException(404,'Không có chỉ định')
            ctx=get_visit(c,o['visit_id'])
            if 'doctor' in u['roles'] and ctx['doctor_id']!=u['id'] and 'technician' not in u['roles']:
                raise HTTPException(403,'Không phải bác sĩ phụ trách')
            if kind=='order':
                if 'doctor' not in u['roles'] or ctx['doctor_id']!=u['id']:
                    raise HTTPException(403,'Chỉ bác sĩ phụ trách được xuất phiếu chỉ định')
                render_kind='order'
            else:
                if o['status']!='approved':raise HTTPException(409,'Kết quả chưa duyệt')
                render_kind=o['category']
            ctx['approved_by_name']=printed_name(c,o['approved_by'])
            ctx['result_by_name']=printed_name(c,o['result_by'])
            ctx.update(order_id=o['id'],order_name=o['name'],category=o['category'],
                       order_status=o['status'],result_text=o['result_text'],
                       order_created_at=o['created_at'],approved_by_name=ctx['approved_by_name'],file_name=o['file_name'])
            result=response(render_kind,ctx,format)
            audit(c,u,'demo_form_exported','order',order_id,f'{render_kind}.{format}')
            return result

    @router.get('/prescriptions/{rx_id}/forms/prescription')
    @export_slot
    def rx_form(rx_id:int,format:str='pdf',u=Depends(principal)):
        require(u,'doctor','pharmacy')
        with db(True) as c:
            rx=c.execute('SELECT * FROM prescriptions WHERE id=?',(rx_id,)).fetchone()
            if not rx:raise HTTPException(404,'Không có đơn nháp')
            ctx=get_visit(c,rx['visit_id'])
            if 'doctor' in u['roles'] and ctx['doctor_id']!=u['id'] and 'pharmacy' not in u['roles']:
                raise HTTPException(403,'Không phải bác sĩ phụ trách')
            ctx.update(rx_id=rx_id,drug_lines=rx['drug_lines'],instructions=rx['instructions'],rx_created_at=rx['created_at'],follow_up=rx['follow_up'])
            result=response('rx',ctx,format)
            audit(c,u,'demo_form_exported','prescription',rx_id,'rx.'+format)
            return result

    app.include_router(router)
