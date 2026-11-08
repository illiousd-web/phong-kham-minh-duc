"""Dòng nghiệp vụ v0.4.2: phí chỉ định, cấp phát theo đơn, điều dưỡng, khóa lượt.

Các thao tác thay đổi số dư/tồn kho dùng chung db(True) advisory lock của ứng dụng.
Không có đường thực thi nào cấp phát thuốc kiểm soát đặc biệt.
"""
from datetime import date
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

CLS = ('lab', 'ultrasound', 'xray', 'ecg')


def ensure_open(visit):
    if visit['status'] == 'completed':
        raise HTTPException(409, 'Lượt khám đã hoàn tất, hồ sơ chuyên môn bị khóa')


class CancelRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


class Review(BaseModel):
    approve: bool


class PriceInput(BaseModel):
    unit_price: int = Field(gt=0, le=2_000_000_000)


class NurseAssignment(BaseModel):
    nurse_id: int = Field(gt=0)


class VitalInput(BaseModel):
    vitals: str = Field(min_length=2, max_length=1000)
    version: int = Field(ge=0)


class AddendumInput(BaseModel):
    reason: str = Field(min_length=8, max_length=500)
    content: str = Field(min_length=10, max_length=5000)


def install_workflows(app, db, principal, require, audit, visit_access, now):
    @app.get('/api/cls-services')
    def cls_services(u=Depends(principal)):
        require(u, 'doctor', 'admin', 'manager')
        with db() as c:
            return [dict(x) for x in c.execute('''SELECT sc.id, sc.name, sc.price, cat.category
                FROM service_catalog sc JOIN service_categories cat ON cat.service_id=sc.id
                WHERE cat.category IN ('lab','ultrasound','xray','ecg') AND sc.price>0
                ORDER BY cat.category,sc.name''')]

    @app.get('/api/charges/{visit_id}')
    def visit_charges(visit_id: int, u=Depends(principal)):
        require(u, 'cashier', 'reception', 'manager', 'admin')
        with db() as c:
            if not c.execute('SELECT id FROM visits WHERE id=?', (visit_id,)).fetchone():
                raise HTTPException(404, 'Không có lượt khám')
            return [dict(x) for x in c.execute('''SELECT ch.id,ch.label,ch.amount,ch.created_at,
                cs.source_type,cs.source_id,cv.reason AS void_reason
                FROM charges ch LEFT JOIN charge_sources cs ON cs.charge_id=ch.id
                LEFT JOIN charge_voids cv ON cv.charge_id=ch.id
                WHERE ch.visit_id=? ORDER BY ch.id''', (visit_id,))]

    @app.post('/api/orders/{order_id}/request-cancel',status_code=201)
    def order_cancel_request(order_id: int, data: CancelRequest, u=Depends(principal)):
        require(u, 'doctor')
        with db(True) as c:
            order=c.execute('''SELECT o.*,v.doctor_id FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?''',(order_id,)).fetchone()
            if not order: raise HTTPException(404, 'Không có chỉ định')
            if order['doctor_id']!=u['id']: raise HTTPException(403, 'Không phải bác sĩ phụ trách')
            if order['status']=='cancelled': raise HTTPException(409,'Chỉ định đã hủy')
            if c.execute("SELECT 1 FROM order_cancel_requests WHERE order_id=? AND status='pending'",(order_id,)).fetchone():
                raise HTTPException(409,'Đã có yêu cầu hủy chờ quản lý')
            c.execute('''INSERT INTO order_cancel_requests(order_id,reason,requested_by,requested_at)
                VALUES(?,?,?,?)''',(order_id,data.reason,u['id'],now()))
            rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,u,'order_cancel_requested','order',order_id,data.reason)
            return {'id':rid,'status':'pending'}

    @app.get('/api/orders/cancellation-requests')
    def cancellation_requests(u=Depends(principal)):
        require(u,'manager','admin','doctor')
        with db() as c:
            sql='''SELECT r.*,o.visit_id,o.name AS order_name FROM order_cancel_requests r
                JOIN orders o ON o.id=r.order_id'''
            args=[]
            if 'manager' not in u['roles'] and 'admin' not in u['roles']:
                sql+=' JOIN visits v ON v.id=o.visit_id WHERE v.doctor_id=?';args=[u['id']]
            return [dict(x) for x in c.execute(sql+' ORDER BY r.id DESC LIMIT 100',args)]

    @app.post('/api/orders/cancellation-requests/{request_id}/review')
    def review_order_cancel(request_id: int, data: Review, u=Depends(principal)):
        require(u,'manager')
        with db(True) as c:
            r=c.execute('SELECT * FROM order_cancel_requests WHERE id=?',(request_id,)).fetchone()
            if not r: raise HTTPException(404,'Không có yêu cầu hủy')
            if r['status']!='pending':raise HTTPException(409,'Yêu cầu đã xử lý')
            if r['requested_by']==u['id']:raise HTTPException(403,'Không tự duyệt yêu cầu của mình')
            order=c.execute('SELECT * FROM orders WHERE id=?',(r['order_id'],)).fetchone()
            if order['status']=='cancelled':raise HTTPException(409,'Chỉ định đã hủy')
            state='approved' if data.approve else 'rejected'
            c.execute('UPDATE order_cancel_requests SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',(state,u['id'],now(),request_id))
            if data.approve:
                ch=c.execute('''SELECT ch.id FROM charges ch JOIN charge_sources s ON s.charge_id=ch.id
                  WHERE s.source_type='order' AND s.source_id=?''',(order['id'],)).fetchone()
                if ch:
                    # An already approved discount cannot exceed the remaining gross charges.
                    # Never silently make the financial ledger negative after cancellation.
                    gross=c.execute('''SELECT COALESCE(SUM(amount),0) FROM charges ch
                       WHERE visit_id=? AND id<>? AND NOT EXISTS(
                       SELECT 1 FROM charge_voids v WHERE v.charge_id=ch.id)''',
                       (order['visit_id'],ch['id'])).fetchone()[0]
                    discount=c.execute('''SELECT COALESCE(SUM(amount),0) FROM adjustments
                       WHERE visit_id=? AND kind='discount' AND status='approved' ''',
                       (order['visit_id'],)).fetchone()[0]
                    if discount>gross:
                        raise HTTPException(409,'Khoản giảm giá đã duyệt vượt tổng phí còn lại; phải đối soát trước khi hủy')
                    c.execute('INSERT INTO charge_voids(charge_id,approved_by,reason,created_at) VALUES(?,?,?,?)',
                         (ch['id'],u['id'],r['reason'],now()))
                c.execute("UPDATE orders SET status='cancelled' WHERE id=?",(order['id'],))
            audit(c,u,'order_cancel_'+state,'order',order['id'],r['reason'])
            return {'status':state,'order_id':order['id'],'refund_requires_separate_approval':True}

    @app.get('/api/dispensable-medicines')
    def dispensable_medicines(u=Depends(principal)):
        require(u,'doctor','pharmacy','manager','admin')
        with db() as c:
            # Bác sĩ chỉ cần biết thuốc nào có thể kê; giá do quản lý thiết lập.
            return [dict(x) for x in c.execute('''SELECT m.id,m.name,m.base_unit,
                 mp.unit_price FROM medicines m LEFT JOIN medicine_prices mp ON mp.medicine_id=m.id
                 WHERE m.controlled=0 ORDER BY m.name''')]

    @app.put('/api/medicines/{medicine_id}/price')
    def set_medicine_price(medicine_id:int, data:PriceInput, u=Depends(principal)):
        require(u,'manager','admin')
        with db(True) as c:
            m=c.execute('SELECT id,controlled FROM medicines WHERE id=?',(medicine_id,)).fetchone()
            if not m:raise HTTPException(404,'Không có thuốc')
            if m['controlled']:raise HTTPException(403,'Thuốc kiểm soát đặc biệt chưa được triển khai')
            exists=c.execute('SELECT 1 FROM medicine_prices WHERE medicine_id=?',(medicine_id,)).fetchone()
            if exists:
                c.execute('UPDATE medicine_prices SET unit_price=?,updated_by=?,updated_at=? WHERE medicine_id=?',
                          (data.unit_price,u['id'],now(),medicine_id))
            else:
                c.execute('INSERT INTO medicine_prices(medicine_id,unit_price,updated_by,updated_at) VALUES(?,?,?,?)',
                          (medicine_id,data.unit_price,u['id'],now()))
            audit(c,u,'medicine_price_changed','medicine',medicine_id,str(data.unit_price))
            return {'medicine_id':medicine_id,'unit_price':data.unit_price}

    @app.post('/api/prescriptions/{prescription_id}/dispense',status_code=201)
    def dispense(prescription_id:int,u=Depends(principal)):
        require(u,'pharmacy')
        with db(True) as c:
            rx=c.execute('SELECT * FROM prescriptions WHERE id=?',(prescription_id,)).fetchone()
            if not rx:raise HTTPException(404,'Không có đơn')
            # Unique rx link + application transaction lock = no repeat dispensing.
            if rx['status']!='draft' or c.execute('SELECT 1 FROM dispensations WHERE prescription_id=?',(prescription_id,)).fetchone():
                raise HTTPException(409,'Đơn đã cấp phát hoặc không còn là đơn nháp')
            items=[dict(x) for x in c.execute('''SELECT i.*,m.name,m.base_unit,m.controlled,mp.unit_price
                FROM prescription_items i JOIN medicines m ON m.id=i.medicine_id
                LEFT JOIN medicine_prices mp ON mp.medicine_id=i.medicine_id
                WHERE i.prescription_id=? ORDER BY i.id''',(prescription_id,))]
            if not items:raise HTTPException(409,'Đơn chỉ có văn bản, chưa có dòng thuốc cấu trúc; chưa thể cấp phát')
            for it in items:
                if it['controlled']:raise HTTPException(403,'Chặn cấp phát thuốc kiểm soát đặc biệt')
                if not it['unit_price'] or it['unit_price']<=0:raise HTTPException(409,'Thuốc chưa có giá đã được quản lý phê duyệt')
                lots=c.execute('''SELECT id,quantity FROM stock_lots
                    WHERE medicine_id=? AND quarantined=0 AND expiry_date>=? AND quantity>0
                    ORDER BY expiry_date,id''',(it['medicine_id'],date.today().isoformat())).fetchall()
                if sum(l['quantity'] for l in lots)<it['quantity']:raise HTTPException(409,f'Không đủ tồn hợp lệ: {it["name"]}')
            c.execute('INSERT INTO dispensations(prescription_id,visit_id,dispensed_by,dispensed_at) VALUES(?,?,?,?)',
                      (prescription_id,rx['visit_id'],u['id'],now()))
            did=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            total=0;parts=[]
            for it in items:
                qty=it['quantity'];unit_price=it['unit_price']
                lots=c.execute('''SELECT id,quantity FROM stock_lots
                    WHERE medicine_id=? AND quarantined=0 AND expiry_date>=? AND quantity>0
                    ORDER BY expiry_date,id''',(it['medicine_id'],date.today().isoformat())).fetchall()
                for lot in lots:
                    if not qty:break
                    take=min(qty,lot['quantity']);qty-=take
                    changed=c.execute('UPDATE stock_lots SET quantity=quantity-? WHERE id=? AND quantity>=?',
                                      (take,lot['id'],take))
                    if changed.rowcount!=1:raise HTTPException(409,'Tồn kho đã thay đổi; vui lòng thử lại')
                    c.execute('''INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at)
                        VALUES(?,?,?,?,?)''',(lot['id'],'rx_dispense',take,u['id'],now()))
                    c.execute('''INSERT INTO dispensation_items(dispensation_id,prescription_item_id,medicine_id,stock_lot_id,quantity,unit_price)
                        VALUES(?,?,?,?,?,?)''',(did,it['id'],it['medicine_id'],lot['id'],take,unit_price))
                    item_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    amount=take*unit_price
                    if amount>2_000_000_000:raise HTTPException(409,'Khoản tiền thuốc quá giới hạn')
                    c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',
                              (rx['visit_id'],f'Thuốc: {it["name"]} - {take} {it["base_unit"]}',amount,now()))
                    cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'dispense_item',?)",(cid,item_id))
                    total+=amount
                    parts.append({'medicine_id':it['medicine_id'],'stock_lot_id':lot['id'],'quantity':take,'amount':amount})
                if qty:raise HTTPException(409,'Không đủ tồn kho sau khi đối chiếu')
            c.execute("UPDATE prescriptions SET status='dispensed' WHERE id=?",(prescription_id,))
            audit(c,u,'rx_dispensed','prescription',prescription_id,f'count={len(parts)} total={total}')
            return {'dispensation_id':did,'visit_id':rx['visit_id'],'total':total,'lots':parts,'status':'dispensed',
                    'payment_status':'unpaid_until_cashier_records_payment'}

    @app.get('/api/dispensations')
    def list_dispensations(u=Depends(principal)):
        require(u,'pharmacy','cashier','manager')
        with db() as c:
            return [dict(x) for x in c.execute('''SELECT d.*,p.code AS patient_code,p.full_name AS patient_name
             FROM dispensations d JOIN visits v ON v.id=d.visit_id JOIN patients p ON p.id=v.patient_id
             ORDER BY d.id DESC LIMIT 100''')]

    @app.get('/api/nurses')
    def nurses(u=Depends(principal)):
        require(u,'doctor','admin')
        with db() as c:
            return [dict(x) for x in c.execute('''SELECT u.id,u.full_name FROM users u JOIN user_roles r
            ON r.user_id=u.id WHERE r.role='nurse' AND u.active=1 ORDER BY u.id''')]

    @app.post('/api/visits/{visit_id}/nurses',status_code=201)
    def assign_nurse(visit_id:int,data:NurseAssignment,u=Depends(principal)):
        require(u,'doctor','admin')
        with db(True) as c:
            v=visit_access(c,u,visit_id,clinical=False)
            if 'admin' not in u['roles'] and v['doctor_id']!=u['id']:
                raise HTTPException(403,'Bác sĩ không được phân công')
            ensure_open(v)
            found=c.execute('''SELECT 1 FROM users u JOIN user_roles r ON r.user_id=u.id
                WHERE u.id=? AND u.active=1 AND r.role='nurse' ''',(data.nurse_id,)).fetchone()
            if not found: raise HTTPException(422,'Điều dưỡng không hợp lệ')
            if c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=?',(visit_id,data.nurse_id)).fetchone():
                raise HTTPException(409,'Điều dưỡng đã được phân công')
            c.execute('INSERT INTO visit_nurses(visit_id,nurse_id,assigned_by,assigned_at) VALUES(?,?,?,?)',
                      (visit_id,data.nurse_id,u['id'],now()))
            audit(c,u,'nurse_assigned','visit',visit_id,str(data.nurse_id))
            return {'visit_id':visit_id,'nurse_id':data.nurse_id}

    @app.put('/api/visits/{visit_id}/vitals')
    def save_vitals(visit_id:int,data:VitalInput,u=Depends(principal)):
        require(u,'nurse')
        with db(True) as c:
            v=visit_access(c,u,visit_id,clinical=False)
            if not c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=?',(visit_id,u['id'])).fetchone():
                raise HTTPException(403,'Chưa được phân công lượt này')
            ensure_open(v)
            changed=c.execute("UPDATE visits SET vitals=?,version=version+1,status='in_progress' WHERE id=? AND version=?",
                              (data.vitals,visit_id,data.version))
            if changed.rowcount!=1:raise HTTPException(409,'Hồ sơ đã thay đổi; tải lại để tránh ghi đè')
            audit(c,u,'nurse_vitals_recorded','visit',visit_id)
            return {'id':visit_id,'version':data.version+1}

    @app.post('/api/visits/{visit_id}/complete')
    def complete_visit(visit_id:int,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            v=visit_access(c,u,visit_id,clinical=True)
            ensure_open(v)
            if not (v['diagnosis'] or '').strip():raise HTTPException(409,'Bác sĩ cần kết luận chẩn đoán trước khi hoàn tất')
            if c.execute("SELECT 1 FROM orders WHERE visit_id=? AND status IN ('ordered','pending_review')",(visit_id,)).fetchone():
                raise HTTPException(409,'Còn chỉ định chưa có kết quả duyệt hoặc chưa hủy')
            changed=c.execute("UPDATE visits SET status='completed',version=version+1 WHERE id=? AND status!='completed'",(visit_id,))
            if changed.rowcount!=1:raise HTTPException(409,'Lượt đã kết thúc ở phiên khác')
            c.execute('INSERT INTO visit_closures(visit_id,doctor_id,completed_at,clinical_version) VALUES(?,?,?,?)',
                      (visit_id,u['id'],now(),v['version']+1))
            audit(c,u,'visit_completed','visit',visit_id)
            return {'id':visit_id,'status':'completed','version':v['version']+1}

    @app.post('/api/visits/{visit_id}/addenda',status_code=201)
    def propose_addendum(visit_id:int,data:AddendumInput,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            v=visit_access(c,u,visit_id,clinical=True)
            if v['status']!='completed':raise HTTPException(409,'Phụ lục chỉnh sửa chỉ dùng sau khi kết thúc')
            c.execute('''INSERT INTO visit_addenda(visit_id,created_by,reason,content,created_at)
                VALUES(?,?,?,?,?)''',(visit_id,u['id'],data.reason,data.content,now()))
            aid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,u,'visit_addendum_proposed','visit',visit_id,str(aid))
            return {'id':aid,'status':'pending'}

    @app.get('/api/visits/{visit_id}/addenda')
    def get_addenda(visit_id:int,u=Depends(principal)):
        require(u,'doctor','manager','admin')
        with db() as c:
            v=visit_access(c,u,visit_id,clinical=False)
            if not {'manager','admin'}.intersection(u['roles']) and v['doctor_id']!=u['id']:
                raise HTTPException(403,'Không được xem phụ lục')
            return [dict(x) for x in c.execute('SELECT * FROM visit_addenda WHERE visit_id=? ORDER BY id',(visit_id,))]

    @app.get('/api/visits/addenda/pending')
    def pending_addenda(u=Depends(principal)):
        require(u,'manager','admin')
        with db() as c:
            return [dict(x) for x in c.execute('''SELECT a.*,p.code AS patient_code
                FROM visit_addenda a JOIN visits v ON v.id=a.visit_id
                JOIN patients p ON p.id=v.patient_id
                WHERE a.status='pending' ORDER BY a.id DESC LIMIT 100''')]

    @app.post('/api/visits/addenda/{addendum_id}/review')
    def review_addendum(addendum_id:int,data:Review,u=Depends(principal)):
        require(u,'manager')
        with db(True) as c:
            a=c.execute('SELECT * FROM visit_addenda WHERE id=?',(addendum_id,)).fetchone()
            if not a:raise HTTPException(404,'Không có phụ lục')
            if a['status']!='pending':raise HTTPException(409,'Đã xử lý phụ lục')
            if a['created_by']==u['id']:raise HTTPException(403,'Không tự duyệt phụ lục của mình')
            state='approved' if data.approve else 'rejected'
            c.execute('UPDATE visit_addenda SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',
                      (state,u['id'],now(),addendum_id))
            audit(c,u,'visit_addendum_'+state,'visit',a['visit_id'],str(addendum_id))
            return {'id':addendum_id,'status':state}
