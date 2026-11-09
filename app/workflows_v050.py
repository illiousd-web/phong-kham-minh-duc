"""v0.5 routes for billing, returns, controlled custody, care and immutable history."""
from datetime import date
import json
from typing import Literal
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field
from .domain import ensure_open,authorize_order,invoice,revision,status_refresh

class Reason(BaseModel):
    reason:str=Field(min_length=8,max_length=500)
class Key(Reason):
    request_key:str=Field(min_length=8,max_length=120)
class Reprice(Key):
    amount:int=Field(ge=0,le=2_000_000_000)
class UnitInput(BaseModel):
    name:str=Field(min_length=1,max_length=40)
    base_factor:int=Field(gt=0,le=1000)
class CareInput(BaseModel):
    content:str=Field(min_length=3,max_length=3000)
    request_key:str=Field(min_length=8,max_length=120)
class TaskInput(CareInput):
    nurse_id:int=Field(gt=0)
class Execution(BaseModel):
    content:str=Field(min_length=3,max_length=3000)
class ControlledApproval(Reason):
    register_ref:str=Field(min_length=4,max_length=120)
class ControlledReceipt(ControlledApproval):
    medicine_id:int=Field(gt=0)
    lot_number:str=Field(min_length=2,max_length=80)
    expiry_date:str
    quantity:int=Field(gt=0,le=10000)
    request_key:str=Field(min_length=8,max_length=120)
class ReturnItem(BaseModel):
    dispensation_item_id:int=Field(gt=0)
    quantity:int=Field(gt=0,le=10000)
class ReturnInput(Key):
    items:list[ReturnItem]=Field(min_length=1,max_length=60)
class Review(BaseModel):
    approve:bool


def install_v050(app,db,principal,require,audit,visit_access,now):
    def nurse_scope(c,u,vid):
        v=visit_access(c,u,vid,clinical=False)
        if 'doctor' in u['roles'] and v['doctor_id']==u['id']:return v
        if 'nurse' in u['roles'] and c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=? AND active=1',(vid,u['id'])).fetchone():return v
        raise HTTPException(403,'Không được phân công hồ sơ này')

    @app.post('/api/orders/{oid}/authorize')
    def authorize(oid:int,u=Depends(principal)):
        require(u,'doctor','nurse')
        with db(True) as c:return authorize_order(c,oid,u,audit,now)

    @app.get('/api/visits/{vid}/settlement')
    def settlement(vid:int,u=Depends(principal)):
        require(u,'doctor','nurse','reception','cashier','pharmacy','manager','admin')
        with db() as c:
            v=visit_access(c,u,vid,clinical=False)
            if {'doctor','nurse'}.intersection(u['roles']) and not {'manager','admin','cashier','reception','pharmacy'}.intersection(u['roles']):nurse_scope(c,u,vid)
            if 'nurse' in u['roles'] and not {'doctor','cashier','reception','pharmacy','manager','admin'}.intersection(u['roles']):
                return {'clinical_status':v['status'],'version':v['version'],'billing':{'due':None,'refund_due':None},'payment_status':'restricted','dispensing_status':'restricted'}
            state=invoice(c,vid)
            rx=c.execute('SELECT id,status FROM prescriptions WHERE visit_id=?',(vid,)).fetchone()
            return {'clinical_status':v['status'],'version':v['version'],'billing':state,'payment_status':'unpriced' if state['unpriced_count'] else ('refund_due' if state['refund_due'] else ('due' if state['due'] else 'settled')),'dispensing_status':rx['status'] if rx else 'not_prescribed'}

    @app.post('/api/charges/{cid}/reprice')
    def reprice(cid:int,data:Reprice,u=Depends(principal)):
        require(u,'manager')
        with db(True) as c:
            prior=c.execute('SELECT * FROM charge_price_history WHERE request_key=?',(data.request_key,)).fetchone()
            if prior:
                if prior['charge_id']!=cid or prior['new_amount']!=data.amount or prior['reason']!=data.reason or prior['changed_by']!=u['id']:raise HTTPException(409,'Khóa đã dùng với nội dung khác')
                return {'id':prior['id'],'status':'already_recorded'}
            ch=c.execute('SELECT * FROM effective_charges WHERE id=?',(cid,)).fetchone()
            if not ch:raise HTTPException(404,'Không có khoản phí')
            if ch['original_amount'] is None:raise HTTPException(409,'Khoản giá nhập tay phải nhập lần đầu hoặc gửi đề nghị sửa giá để quản lý duyệt')
            if c.execute('SELECT 1 FROM charge_voids WHERE charge_id=?',(cid,)).fetchone():raise HTTPException(409,'Khoản đã hủy')
            if c.execute('SELECT 1 FROM charge_credits WHERE charge_id=?',(cid,)).fetchone():raise HTTPException(409,'Khoản đã có trả thuốc; cần đối soát trước')
            c.execute('INSERT INTO charge_pricing(charge_id,amount) VALUES(?,?) ON CONFLICT(charge_id) DO UPDATE SET amount=excluded.amount',(cid,data.amount))
            invoice(c,ch['visit_id'])
            c.execute('INSERT INTO charge_price_history(charge_id,previous_amount,new_amount,reason,changed_by,created_at,request_key) VALUES(?,?,?,?,?,?,?)',(cid,ch['amount'],data.amount,data.reason,u['id'],now(),data.request_key))
            rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,u,'charge_repriced','charge',cid,data.reason)
            return {'id':rid,'billing':invoice(c,ch['visit_id'])}

    @app.post('/api/adjustments/{aid}/reverse')
    def reverse_discount(aid:int,data:Reason,u=Depends(principal)):
        require(u,'manager')
        with db(True) as c:
            a=c.execute('SELECT * FROM adjustments WHERE id=?',(aid,)).fetchone()
            if not a or a['kind']!='discount' or a['status']!='approved':raise HTTPException(409,'Chỉ hoàn tác giảm phí đã duyệt')
            if c.execute('SELECT 1 FROM adjustment_reversals WHERE adjustment_id=?',(aid,)).fetchone():raise HTTPException(409,'Đã hoàn tác')
            c.execute('INSERT INTO adjustment_reversals(adjustment_id,reason,reversed_by,created_at) VALUES(?,?,?,?)',(aid,data.reason,u['id'],now()))
            audit(c,u,'discount_reversed','adjustment',aid,data.reason)
            return invoice(c,a['visit_id'])

    @app.post('/api/medicines/{mid}/units',status_code=201)
    def unit(mid:int,data:UnitInput,u=Depends(principal)):
        require(u,'manager','admin')
        with db(True) as c:
            med=c.execute('SELECT controlled FROM medicines WHERE id=?',(mid,)).fetchone()
            if not med:raise HTTPException(404,'Không có thuốc')
            if med['controlled'] and 'controlled_reviewer' not in u['roles']:raise HTTPException(403,'Thiếu quyền quản lý đơn vị thuốc kiểm soát')
            if c.execute('SELECT 1 FROM medicine_units WHERE medicine_id=? AND name=?',(mid,data.name)).fetchone():raise HTTPException(409,'Đơn vị đã có; không đổi hệ số lịch sử')
            c.execute('INSERT INTO medicine_units(medicine_id,name,base_factor) VALUES(?,?,?)',(mid,data.name,data.base_factor))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0];audit(c,u,'medicine_unit_created','medicine',mid,f'{data.name}={data.base_factor}')
            return {'id':uid}

    @app.get('/api/medicines/{mid}/units')
    def units(mid:int,u=Depends(principal)):
        require(u,'doctor','pharmacy','manager','admin')
        with db() as c:return [dict(x) for x in c.execute('SELECT * FROM medicine_units WHERE medicine_id=? ORDER BY id',(mid,))]

    @app.post('/api/prescriptions/{rid}/cancel')
    def cancel_rx(rid:int,data:Reason,u=Depends(principal)):
        require(u,'doctor','pharmacy')
        with db(True) as c:
            rx=c.execute('SELECT * FROM prescriptions WHERE id=?',(rid,)).fetchone()
            if not rx:raise HTTPException(404,'Không có đơn')
            if 'doctor' in u['roles'] and rx['doctor_id']!=u['id']:raise HTTPException(403,'Không được giao')
            if c.execute('SELECT 1 FROM prescription_items i JOIN medicines m ON m.id=i.medicine_id WHERE i.prescription_id=? AND m.controlled=1',(rid,)).fetchone():
                if not (('doctor' in u['roles'] and 'controlled_prescriber' in u['roles'] and rx['doctor_id']==u['id']) or ('pharmacy' in u['roles'] and 'controlled_pharmacy' in u['roles'])):raise HTTPException(403,'Thiếu quyền hủy đơn thuốc kiểm soát')
            if rx['status']!='draft':raise HTTPException(409,'Đơn đã xử lý; dùng quy trình trả thuốc nếu đã cấp')
            c.execute("UPDATE prescriptions SET status='cancelled' WHERE id=?",(rid,))
            c.execute('INSERT INTO prescription_cancellations(prescription_id,actor_id,reason,created_at) VALUES(?,?,?,?)',(rid,u['id'],data.reason,now()))
            audit(c,u,'rx_cancelled','prescription',rid,data.reason);return {'status':'cancelled'}

    @app.get('/api/dispensations/{did}/items')
    def dispensed_items(did:int,u=Depends(principal)):
        require(u,'pharmacy','cashier','manager')
        with db() as c:return [dict(x) for x in c.execute("SELECT i.*,m.name,l.lot_number,l.expiry_date,COALESCE((SELECT SUM(ri.quantity) FROM medication_return_items ri JOIN medication_returns r ON r.id=ri.return_id WHERE ri.dispensation_item_id=i.id AND r.status='approved'),0) AS returned FROM dispensation_items i JOIN medicines m ON m.id=i.medicine_id JOIN stock_lots l ON l.id=i.stock_lot_id WHERE i.dispensation_id=? ORDER BY i.id",(did,))]

    @app.post('/api/dispensations/{did}/returns',status_code=201)
    def request_return(did:int,data:ReturnInput,u=Depends(principal)):
        require(u,'pharmacy')
        if len({x.dispensation_item_id for x in data.items})!=len(data.items):raise HTTPException(422,'Trùng dòng trả')
        with db(True) as c:
            old=c.execute('SELECT * FROM medication_returns WHERE request_key=?',(data.request_key,)).fetchone()
            if old:
                existing=[(x['dispensation_item_id'],x['quantity']) for x in c.execute('SELECT * FROM medication_return_items WHERE return_id=? ORDER BY dispensation_item_id',(old['id'],))]
                if old['dispensation_id']!=did or old['requested_by']!=u['id'] or old['reason']!=data.reason or existing!=sorted((x.dispensation_item_id,x.quantity) for x in data.items):raise HTTPException(409,'Khóa trả thuốc đã dùng khác nội dung')
                return {'id':old['id'],'status':old['status']}
            if not c.execute('SELECT 1 FROM dispensations WHERE id=?',(did,)).fetchone():raise HTTPException(404,'Không có phiếu cấp')
            for item in data.items:
                row=c.execute('SELECT di.*,m.controlled FROM dispensation_items di JOIN medicines m ON m.id=di.medicine_id WHERE di.id=? AND di.dispensation_id=?',(item.dispensation_item_id,did)).fetchone()
                if not row:raise HTTPException(422,'Dòng không thuộc phiếu cấp')
                if row['controlled'] and 'controlled_pharmacy' not in u['roles']:raise HTTPException(403,'Thiếu quyền trả thuốc kiểm soát')
                returned=c.execute("SELECT COALESCE(SUM(i.quantity),0) FROM medication_return_items i JOIN medication_returns r ON r.id=i.return_id WHERE i.dispensation_item_id=? AND r.status IN ('approved','pending')",(row['id'],)).fetchone()[0]
                if returned+item.quantity>row['quantity']:raise HTTPException(409,'Số trả vượt số đã cấp còn có thể trả')
            c.execute('INSERT INTO medication_returns(dispensation_id,reason,requested_by,created_at,request_key) VALUES(?,?,?,?,?)',(did,data.reason,u['id'],now(),data.request_key))
            rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for item in data.items:c.execute('INSERT INTO medication_return_items(return_id,dispensation_item_id,quantity) VALUES(?,?,?)',(rid,item.dispensation_item_id,item.quantity))
            audit(c,u,'medication_return_requested','dispensation',did,data.reason)
            return {'id':rid,'status':'pending'}

    @app.get('/api/medication-returns')
    def returns(u=Depends(principal)):
        require(u,'pharmacy','manager','cashier')
        with db() as c:return [dict(x) for x in c.execute('SELECT r.*,d.visit_id FROM medication_returns r JOIN dispensations d ON d.id=r.dispensation_id ORDER BY r.id DESC LIMIT 100')]

    @app.post('/api/medication-returns/{rid}/review')
    def review_return(rid:int,data:Review,u=Depends(principal)):
        require(u,'manager')
        with db(True) as c:
            r=c.execute('SELECT r.*,d.visit_id,d.prescription_id FROM medication_returns r JOIN dispensations d ON d.id=r.dispensation_id WHERE r.id=?',(rid,)).fetchone()
            if not r:raise HTTPException(404,'Không có yêu cầu trả')
            if r['status']!='pending':raise HTTPException(409,'Đã xử lý yêu cầu')
            if r['requested_by']==u['id']:raise HTTPException(403,'Không tự duyệt trả thuốc')
            if c.execute('SELECT 1 FROM medication_return_items ri JOIN dispensation_items di ON di.id=ri.dispensation_item_id JOIN medicines m ON m.id=di.medicine_id WHERE ri.return_id=? AND m.controlled=1',(rid,)).fetchone() and 'controlled_reviewer' not in u['roles']:raise HTTPException(403,'Thiếu quyền duyệt thuốc kiểm soát')
            if data.approve:
                for it in c.execute('SELECT ri.*,di.quantity AS dispensed,di.medicine_id,di.stock_lot_id,di.unit_price,m.controlled,l.expiry_date FROM medication_return_items ri JOIN dispensation_items di ON di.id=ri.dispensation_item_id JOIN medicines m ON m.id=di.medicine_id JOIN stock_lots l ON l.id=di.stock_lot_id WHERE ri.return_id=? ORDER BY ri.id',(rid,)).fetchall():
                    if it['controlled'] and 'controlled_reviewer' not in u['roles']:raise HTTPException(403,'Thiếu quyền duyệt thuốc kiểm soát')
                    before=c.execute("SELECT COALESCE(SUM(ri.quantity),0) FROM medication_return_items ri JOIN medication_returns r ON r.id=ri.return_id WHERE ri.dispensation_item_id=? AND r.status='approved'",(it['dispensation_item_id'],)).fetchone()[0]
                    if before+it['quantity']>it['dispensed']:raise HTTPException(409,'Đã trả ở phiên khác')
                    charge=c.execute("SELECT ch.id,COALESCE(p.amount,ch.amount) AS base FROM charges ch JOIN charge_sources s ON s.charge_id=ch.id LEFT JOIN charge_pricing p ON p.charge_id=ch.id WHERE s.source_type='dispense_item' AND s.source_id=?",(it['dispensation_item_id'],)).fetchone()
                    if not charge:raise HTTPException(409,'Thiếu liên kết tiền thuốc')
                    credit=charge['base']*(before+it['quantity'])//it['dispensed']-charge['base']*before//it['dispensed']
                    c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,quarantined) VALUES(?,?,?,?,1)',(it['medicine_id'],f'RT-{rid}-{it["id"]}',it['expiry_date'],it['quantity']))
                    lot=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    c.execute('INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(?,?,?,?,?)',(lot,'patient_return_quarantine',it['quantity'],u['id'],now()))
                    if credit:c.execute('INSERT INTO charge_credits(charge_id,amount,source_id,created_by,created_at) VALUES(?,?,?,?,?)',(charge['id'],credit,it['id'],u['id'],now()))
                    if it['controlled']:c.execute('INSERT INTO controlled_ledger(medicine_id,stock_lot_id,event,quantity,actor_id,reviewer_id,register_ref,source_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(it['medicine_id'],lot,'return_quarantine',it['quantity'],r['requested_by'],u['id'],'RETURN-'+str(rid),'return:'+str(it['id']),now()))
                invoice(c,r['visit_id'])
            state='approved' if data.approve else 'rejected'
            c.execute('UPDATE medication_returns SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',(state,u['id'],now(),rid))
            if data.approve:
                remain=c.execute("SELECT 1 FROM dispensation_items di WHERE di.dispensation_id=? AND di.quantity>COALESCE((SELECT SUM(ri.quantity) FROM medication_return_items ri JOIN medication_returns r ON r.id=ri.return_id WHERE ri.dispensation_item_id=di.id AND r.status='approved'),0)",(r['dispensation_id'],)).fetchone()
                if not remain:c.execute("UPDATE prescriptions SET status='returned' WHERE id=?",(r['prescription_id'],))
            audit(c,u,'medication_return_'+state,'dispensation',r['dispensation_id'],r['reason'])
            return {'status':state,'billing':invoice(c,r['visit_id']),'stock_destination':'quarantine'}

    @app.post('/api/prescriptions/{rid}/controlled-approval')
    def approve_controlled(rid:int,data:ControlledApproval,u=Depends(principal)):
        require(u,'doctor')
        require(u,'controlled_reviewer')
        with db(True) as c:
            rx=c.execute('SELECT * FROM prescriptions WHERE id=?',(rid,)).fetchone()
            if not rx or rx['status']!='draft':raise HTTPException(409,'Đơn không còn chờ duyệt')
            ensure_open(c.execute('SELECT * FROM visits WHERE id=?',(rx['visit_id'],)).fetchone())
            if rx['doctor_id']==u['id']:raise HTTPException(403,'Cần bác sĩ duyệt độc lập')
            if not c.execute('SELECT 1 FROM prescription_items i JOIN medicines m ON m.id=i.medicine_id WHERE i.prescription_id=? AND m.controlled=1',(rid,)).fetchone():raise HTTPException(409,'Đơn không có thuốc kiểm soát')
            if c.execute('SELECT 1 FROM controlled_approvals WHERE prescription_id=?',(rid,)).fetchone():raise HTTPException(409,'Đã duyệt')
            c.execute('INSERT INTO controlled_approvals(prescription_id,approved_by,reason,register_ref,created_at) VALUES(?,?,?,?,?)',(rid,u['id'],data.reason,data.register_ref,now()))
            audit(c,u,'controlled_rx_approved','prescription',rid,data.reason+' / '+data.register_ref);return {'status':'approved'}

    @app.post('/api/controlled-receipts',status_code=201)
    def controlled_receipt(data:ControlledReceipt,u=Depends(principal)):
        require(u,'pharmacy');require(u,'controlled_pharmacy')
        try:
            if date.fromisoformat(data.expiry_date)<date.today():raise ValueError()
        except ValueError:raise HTTPException(422,'Hạn dùng không hợp lệ')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM medicines WHERE id=? AND controlled=1 AND active=1',(data.medicine_id,)).fetchone():raise HTTPException(422,'Không phải thuốc kiểm soát có hiệu lực')
            old=c.execute('SELECT * FROM controlled_receipts WHERE request_key=?',(data.request_key,)).fetchone()
            if old:
                if old['medicine_id']!=data.medicine_id or old['lot_number']!=data.lot_number or old['quantity']!=data.quantity or old['expiry_date']!=data.expiry_date or old['requested_by']!=u['id'] or old['register_ref']!=data.register_ref or old['reason']!=data.reason:raise HTTPException(409,'Khóa nhập đã dùng khác dữ liệu')
                return {'id':old['id'],'status':old['status']}
            c.execute('INSERT INTO controlled_receipts(medicine_id,lot_number,expiry_date,quantity,register_ref,reason,requested_by,created_at,request_key) VALUES(?,?,?,?,?,?,?,?,?)',(data.medicine_id,data.lot_number,data.expiry_date,data.quantity,data.register_ref,data.reason,u['id'],now(),data.request_key))
            rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,u,'controlled_receipt_requested','medicine',data.medicine_id,data.reason);return {'id':rid,'status':'pending'}

    @app.get('/api/controlled-receipts')
    def controlled_receipts(u=Depends(principal)):
        require(u,'controlled_pharmacy','controlled_reviewer')
        with db() as c:return [dict(x) for x in c.execute('SELECT * FROM controlled_receipts ORDER BY id DESC LIMIT 100')]

    @app.post('/api/controlled-receipts/{rid}/review')
    def review_controlled_receipt(rid:int,data:Review,u=Depends(principal)):
        require(u,'manager');require(u,'controlled_reviewer')
        with db(True) as c:
            r=c.execute('SELECT * FROM controlled_receipts WHERE id=?',(rid,)).fetchone()
            if not r or r['status']!='pending':raise HTTPException(409,'Yêu cầu đã xử lý/không có')
            if r['requested_by']==u['id']:raise HTTPException(403,'Không tự duyệt nhập kiểm soát')
            state='approved' if data.approve else 'rejected'
            if data.approve:
                if r['expiry_date']<date.today().isoformat():raise HTTPException(409,'Thuốc hết hạn trong thời gian chờ')
                if c.execute('SELECT 1 FROM stock_lots WHERE medicine_id=? AND lot_number=?',(r['medicine_id'],r['lot_number'])).fetchone():raise HTTPException(409,'Lô kiểm soát đã có; không nhập trùng')
                c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(?,?,?,?)',(r['medicine_id'],r['lot_number'],r['expiry_date'],r['quantity']))
                lid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute('INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(?,?,?,?,?)',(lid,'controlled_receipt',r['quantity'],u['id'],now()))
                c.execute('INSERT INTO controlled_ledger(medicine_id,stock_lot_id,event,quantity,actor_id,reviewer_id,register_ref,source_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(r['medicine_id'],lid,'receipt',r['quantity'],r['requested_by'],u['id'],r['register_ref'],'receipt:'+str(rid),now()))
            c.execute('UPDATE controlled_receipts SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',(state,u['id'],now(),rid))
            audit(c,u,'controlled_receipt_'+state,'medicine',r['medicine_id'],r['register_ref']);return {'status':state}

    @app.get('/api/controlled-ledger')
    def controlled_ledger(u=Depends(principal)):
        require(u,'controlled_pharmacy','controlled_reviewer')
        with db() as c:return [dict(x) for x in c.execute('SELECT * FROM controlled_ledger ORDER BY id DESC LIMIT 200')]

    @app.get('/api/visits/{vid}/care')
    def care(vid:int,u=Depends(principal)):
        require(u,'doctor','nurse')
        with db(True) as c:
            nurse_scope(c,u,vid);audit(c,u,'care_viewed','visit',vid)
            return {'notes':[dict(x) for x in c.execute('SELECT n.*,u.full_name AS nurse_name FROM nursing_notes n JOIN users u ON u.id=n.nurse_id WHERE n.visit_id=? ORDER BY n.id',(vid,))],
                    'tasks':[dict(x) for x in c.execute('SELECT t.*,e.content AS execution_content,e.created_at AS executed_at FROM nursing_tasks t LEFT JOIN nursing_executions e ON e.task_id=t.id WHERE t.visit_id=? ORDER BY t.id',(vid,))]}

    @app.post('/api/visits/{vid}/care-notes',status_code=201)
    def care_note(vid:int,data:CareInput,u=Depends(principal)):
        require(u,'nurse')
        with db(True) as c:
            v=nurse_scope(c,u,vid);ensure_open(v)
            old=c.execute('SELECT * FROM nursing_notes WHERE request_key=?',(data.request_key,)).fetchone()
            if old:
                if old['visit_id']!=vid or old['nurse_id']!=u['id'] or old['content']!=data.content:raise HTTPException(409,'Khóa ghi chú đã dùng khác nội dung')
                return {'id':old['id']}
            c.execute('INSERT INTO nursing_notes(visit_id,nurse_id,content,created_at,request_key) VALUES(?,?,?,?,?)',(vid,u['id'],data.content,now(),data.request_key))
            nid=c.execute('SELECT last_insert_rowid()').fetchone()[0];audit(c,u,'care_note_created','visit',vid,str(nid));return {'id':nid}

    @app.post('/api/visits/{vid}/nursing-tasks',status_code=201)
    def task(vid:int,data:TaskInput,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            v=visit_access(c,u,vid,clinical=True);ensure_open(v)
            if not c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=? AND active=1',(vid,data.nurse_id)).fetchone():raise HTTPException(422,'Điều dưỡng chưa được giao ca')
            old=c.execute('SELECT * FROM nursing_tasks WHERE request_key=?',(data.request_key,)).fetchone()
            if old:
                if old['visit_id']!=vid or old['nurse_id']!=data.nurse_id or old['ordered_by']!=u['id'] or old['description']!=data.content:raise HTTPException(409,'Khóa y lệnh đã dùng khác nội dung')
                return {'id':old['id']}
            c.execute('INSERT INTO nursing_tasks(visit_id,nurse_id,ordered_by,description,created_at,request_key) VALUES(?,?,?,?,?,?)',(vid,data.nurse_id,u['id'],data.content,now(),data.request_key))
            tid=c.execute('SELECT last_insert_rowid()').fetchone()[0];audit(c,u,'nursing_task_created','visit',vid,str(tid));return {'id':tid}

    @app.post('/api/nursing-tasks/{tid}/execute')
    def execute_task(tid:int,data:Execution,u=Depends(principal)):
        require(u,'nurse')
        with db(True) as c:
            t=c.execute('SELECT * FROM nursing_tasks WHERE id=?',(tid,)).fetchone()
            if not t:raise HTTPException(404,'Không có y lệnh')
            v=nurse_scope(c,u,t['visit_id']);ensure_open(v)
            if t['nurse_id']!=u['id']:raise HTTPException(403,'Y lệnh giao điều dưỡng khác')
            if t['status']!='pending':raise HTTPException(409,'Y lệnh đã xử lý')
            c.execute('INSERT INTO nursing_executions(task_id,nurse_id,content,created_at) VALUES(?,?,?,?)',(tid,u['id'],data.content,now()))
            c.execute("UPDATE nursing_tasks SET status='done' WHERE id=?",(tid,));audit(c,u,'nursing_task_executed','visit',t['visit_id'],str(tid));return {'status':'done'}

    @app.post('/api/nursing-tasks/{tid}/cancel')
    def cancel_task(tid:int,data:Reason,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            t=c.execute('SELECT * FROM nursing_tasks WHERE id=?',(tid,)).fetchone()
            if not t:raise HTTPException(404,'Không có y lệnh')
            v=visit_access(c,u,t['visit_id'],clinical=True);ensure_open(v)
            if t['status']!='pending':raise HTTPException(409,'Y lệnh đã thực hiện/hủy')
            c.execute("UPDATE nursing_tasks SET status='cancelled' WHERE id=?",(tid,))
            c.execute('INSERT INTO nursing_task_cancellations(task_id,actor_id,reason,created_at) VALUES(?,?,?,?)',(tid,u['id'],data.reason,now()))
            audit(c,u,'nursing_task_cancelled','visit',t['visit_id'],data.reason);return {'status':'cancelled'}

    @app.get('/api/visits/{vid}/revisions')
    def revisions(vid:int,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            visit_access(c,u,vid,clinical=True);audit(c,u,'clinical_revisions_viewed','visit',vid)
            return [dict(x) for x in c.execute('SELECT * FROM clinical_revisions WHERE visit_id=? ORDER BY version',(vid,))]

    @app.post('/api/visits/{vid}/cancel')
    def cancel_visit(vid:int,data:Reason,u=Depends(principal)):
        require(u,'manager')
        with db(True) as c:
            v=c.execute('SELECT * FROM visits WHERE id=?',(vid,)).fetchone()
            if not v:raise HTTPException(404,'Không có lượt')
            ensure_open(v)
            if c.execute("SELECT 1 FROM orders WHERE visit_id=? AND status<>'cancelled'",(vid,)).fetchone():raise HTTPException(409,'Phải xử lý/hủy các chỉ định trước')
            rx=c.execute('SELECT * FROM prescriptions WHERE visit_id=?',(vid,)).fetchone()
            if rx and c.execute('SELECT 1 FROM prescription_items i JOIN medicines m ON m.id=i.medicine_id WHERE i.prescription_id=? AND m.controlled=1',(rx['id'],)).fetchone() and 'controlled_reviewer' not in u['roles']:raise HTTPException(403,'Thiếu quyền đối soát lượt có thuốc kiểm soát')
            if rx and rx['status']=='dispensed':raise HTTPException(409,'Phải trả/đối soát thuốc đã cấp trước')
            if rx and rx['status']=='draft':
                c.execute("UPDATE prescriptions SET status='cancelled' WHERE id=?",(rx['id'],))
                c.execute('INSERT INTO prescription_cancellations(prescription_id,actor_id,reason,created_at) VALUES(?,?,?,?)',(rx['id'],u['id'],data.reason,now()))
            if c.execute("SELECT 1 FROM nursing_tasks WHERE visit_id=? AND status='pending'",(vid,)).fetchone():raise HTTPException(409,'Còn y lệnh chưa xử lý')
            for ch in c.execute('SELECT * FROM charges WHERE visit_id=? AND NOT EXISTS(SELECT 1 FROM charge_voids v WHERE v.charge_id=charges.id)',(vid,)).fetchall():
                c.execute('INSERT INTO charge_voids(charge_id,approved_by,reason,created_at) VALUES(?,?,?,?)',(ch['id'],u['id'],data.reason,now()))
            state=invoice(c,vid)
            c.execute("UPDATE visits SET status='cancelled',version=version+1 WHERE id=?",(vid,))
            c.execute('INSERT INTO visit_cancellations(visit_id,actor_id,reason,created_at) VALUES(?,?,?,?)',(vid,u['id'],data.reason,now()))
            revision(c,vid,u,now,'cancel',data.reason);audit(c,u,'visit_cancelled','visit',vid,data.reason)
            return {'status':'cancelled','billing':state}

    @app.get('/api/visits/{vid}/nurses')
    def assigned_nurses(vid:int,u=Depends(principal)):
        require(u,'doctor','admin')
        with db() as c:
            v=visit_access(c,u,vid,clinical=False)
            if 'admin' not in u['roles'] and v['doctor_id']!=u['id']:raise HTTPException(403,'Không được phân công')
            return [dict(x) for x in c.execute('SELECT n.*,u.full_name FROM visit_nurses n JOIN users u ON u.id=n.nurse_id WHERE n.visit_id=? AND n.active=1 ORDER BY n.nurse_id',(vid,))]

    @app.get('/api/controlled-review-queue')
    def controlled_queue(u=Depends(principal)):
        require(u,'doctor');require(u,'controlled_reviewer')
        with db(True) as c:
            rows=[dict(x) for x in c.execute("SELECT rx.id,rx.visit_id,rx.doctor_id,rx.drug_lines,rx.instructions,v.diagnosis,p.code AS patient_code FROM prescriptions rx JOIN visits v ON v.id=rx.visit_id JOIN patients p ON p.id=v.patient_id WHERE rx.status='draft' AND v.status NOT IN ('completed','cancelled') AND EXISTS(SELECT 1 FROM prescription_items i JOIN medicines m ON m.id=i.medicine_id WHERE i.prescription_id=rx.id AND m.controlled=1) AND NOT EXISTS(SELECT 1 FROM controlled_approvals a WHERE a.prescription_id=rx.id) ORDER BY rx.id DESC LIMIT 100")]
            audit(c,u,'controlled_queue_viewed','prescription',None)
            return rows
