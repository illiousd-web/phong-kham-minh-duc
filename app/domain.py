"""Shared v0.5 invariants. Call only inside db(True) for mutations."""
import json
from datetime import date
from fastapi import HTTPException


def ensure_open(v):
    if v['status'] in ('completed','cancelled'):
        raise HTTPException(409,'Lượt khám đã khóa hoặc hủy; dùng phụ lục có phê duyệt')


def invoice(c,vid):
    gross=c.execute('SELECT COALESCE(SUM(amount),0) FROM effective_charges WHERE visit_id=?',(vid,)).fetchone()[0]
    discount=c.execute("SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE visit_id=? AND kind='discount' AND status='approved'",(vid,)).fetchone()[0]
    incoming=c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE visit_id=?',(vid,)).fetchone()[0]
    refunds=c.execute("SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE visit_id=? AND kind='refund' AND status='approved'",(vid,)).fetchone()[0]
    if gross<discount:raise HTTPException(409,'Giảm phí đã duyệt vượt phí còn lại; phải hoàn tác giảm phí có lý do trước')
    charged=gross-discount;paid=incoming-refunds
    unpriced=c.execute('SELECT COUNT(*) FROM effective_charges WHERE visit_id=? AND amount IS NULL',(vid,)).fetchone()[0]
    return {'gross':gross,'discount':discount,'charged':charged,'paid':paid,
            'unpriced_count':unpriced,'known_due':max(0,charged-paid),
            'due':None if unpriced else max(0,charged-paid),'refund_due':0 if unpriced else max(0,paid-charged)}


def revision(c,vid,u,now,kind,reason):
    v=dict(c.execute('SELECT * FROM visits WHERE id=?',(vid,)).fetchone())
    c.execute('INSERT INTO clinical_revisions(visit_id,version,snapshot,actor_id,reason,kind,created_at) VALUES(?,?,?,?,?,?,?)',
              (vid,v['version'],json.dumps(v,ensure_ascii=False),u['id'],reason,kind,now()))


def status_refresh(c,vid):
    v=c.execute('SELECT status FROM visits WHERE id=?',(vid,)).fetchone()
    if not v or v['status'] in ('completed','cancelled'):return
    pending=c.execute("SELECT 1 FROM orders WHERE visit_id=? AND status IN ('requested','ordered','pending_review')",(vid,)).fetchone()
    c.execute('UPDATE visits SET status=? WHERE id=?',('waiting_results' if pending else 'in_progress',vid))


def authorize_order(c,oid,u,audit,now):
    o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
    if not o:raise HTTPException(404,'Không có chỉ định')
    v=c.execute('SELECT * FROM visits WHERE id=?',(o['visit_id'],)).fetchone()
    assigned_doctor='doctor' in u['roles'] and v['doctor_id']==u['id']
    assigned_nurse='nurse' in u['roles'] and c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=? AND active=1',(v['id'],u['id'])).fetchone()
    if not (assigned_doctor or assigned_nurse):raise HTTPException(403,'Chỉ bác sĩ hoặc điều dưỡng được phân công lập/duyệt chỉ định')
    old=c.execute('SELECT * FROM order_authorizations WHERE order_id=?',(oid,)).fetchone()
    if old:return {'id':oid,'charge_amount':old['unit_price'],'status':'already_authorized'}
    ensure_open(v)
    if o['status'] not in ('requested','ordered'):raise HTTPException(409,'Chỉ định không còn chờ duyệt')
    s=c.execute('SELECT * FROM service_catalog WHERE id=?',(o['service_id'],)).fetchone()
    if not s or not s['active'] or (o['proposed_price'] is not None and o['proposed_price']<0):raise HTTPException(409,'Dịch vụ không còn hiệu lực hoặc giá không hợp lệ')
    price=o['proposed_price']  # Giá chụp khi lập chỉ định, kể cả nháp trước khi nhập bảng giá.
    c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',(o['visit_id'],o['name'],price,now()))
    cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'order',?)",(cid,oid))
    c.execute('INSERT INTO order_authorizations(order_id,service_id,unit_price,authorized_by,authorized_at) VALUES(?,?,?,?,?)',(oid,s['id'],price,u['id'],now()))
    c.execute("UPDATE orders SET status='ordered' WHERE id=?",(oid,))
    status_refresh(c,o['visit_id']);audit(c,u,'order_authorized','order',oid,str(price))
    return {'id':oid,'charge_amount':price,'status':'ordered'}


def dispense_rx(c,rid,u,audit,now):
    rx=c.execute('SELECT * FROM prescriptions WHERE id=?',(rid,)).fetchone()
    if not rx:raise HTTPException(404,'Không có đơn')
    v=c.execute('SELECT status FROM visits WHERE id=?',(rx['visit_id'],)).fetchone()
    if v['status']=='cancelled':raise HTTPException(409,'Lượt đã hủy')
    if rx['status']!='draft' or c.execute('SELECT 1 FROM dispensations WHERE prescription_id=?',(rid,)).fetchone():raise HTTPException(409,'Không cấp trùng đơn đã xử lý')
    items=[dict(x) for x in c.execute('SELECT i.*,m.name,m.base_unit,m.controlled,m.active,mp.unit_price FROM prescription_items i JOIN medicines m ON m.id=i.medicine_id LEFT JOIN medicine_prices mp ON mp.medicine_id=m.id WHERE i.prescription_id=? ORDER BY i.id',(rid,))]
    if not items:raise HTTPException(409,'Đơn cũ chỉ có văn bản, chưa thể cấp phát')
    controlled=any(i['controlled'] for i in items)
    approval=None
    if controlled:
        if 'controlled_pharmacy' not in u['roles']:raise HTTPException(403,'Cần quyền dược kiểm soát đặc biệt')
        approval=c.execute('SELECT * FROM controlled_approvals WHERE prescription_id=?',(rid,)).fetchone()
        if not approval or approval['approved_by'] in (u['id'],rx['doctor_id']):raise HTTPException(409,'Đơn kiểm soát phải có người duyệt độc lập và sổ theo dõi')
    # Validate each aggregated medicine demand, including duplicate Rx lines.
    needs={}
    for it in items:
        if not it['active'] or not it['unit_price']:raise HTTPException(409,'Thuốc chưa có giá hoặc hết hiệu lực')
        needs[it['medicine_id']]=needs.get(it['medicine_id'],0)+it['quantity']
    for mid,qty in needs.items():
        total=c.execute('SELECT COALESCE(SUM(quantity),0) FROM stock_lots WHERE medicine_id=? AND quarantined=0 AND expiry_date>=?',(mid,date.today().isoformat())).fetchone()[0]
        if total<qty:raise HTTPException(409,'Không đủ tồn kho hợp lệ cho toàn đơn')
    c.execute('INSERT INTO dispensations(prescription_id,visit_id,dispensed_by,dispensed_at) VALUES(?,?,?,?)',(rid,rx['visit_id'],u['id'],now()))
    did=c.execute('SELECT last_insert_rowid()').fetchone()[0];total=0;parts=[]
    for it in items:
        remain=it['quantity']
        lots=c.execute('SELECT id,quantity FROM stock_lots WHERE medicine_id=? AND quarantined=0 AND expiry_date>=? AND quantity>0 ORDER BY expiry_date,id',(it['medicine_id'],date.today().isoformat())).fetchall()
        for lot in lots:
            if not remain:break
            take=min(remain,lot['quantity']);remain-=take
            amount=take*it['unit_price']
            if amount>2_000_000_000:raise HTTPException(409,'Khoản tiền quá giới hạn')
            if c.execute('UPDATE stock_lots SET quantity=quantity-? WHERE id=? AND quantity>=?',(take,lot['id'],take)).rowcount!=1:raise HTTPException(409,'Tồn đã đổi')
            c.execute('INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(?,?,?,?,?)',(lot['id'],'rx_dispense',take,u['id'],now()))
            c.execute('INSERT INTO dispensation_items(dispensation_id,prescription_item_id,medicine_id,stock_lot_id,quantity,unit_price) VALUES(?,?,?,?,?,?)',(did,it['id'],it['medicine_id'],lot['id'],take,it['unit_price']))
            itemid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',(rx['visit_id'],f'Thuốc: {it["name"]} - {take} {it["base_unit"]}',amount,now()))
            cid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'dispense_item',?)",(cid,itemid))
            if it['controlled']:
                c.execute('INSERT INTO controlled_ledger(medicine_id,stock_lot_id,event,quantity,actor_id,reviewer_id,register_ref,source_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(it['medicine_id'],lot['id'],'dispense',take,u['id'],approval['approved_by'],approval['register_ref'],'dispense:'+str(itemid),now()))
            total+=amount;parts.append({'id':itemid,'medicine_id':it['medicine_id'],'stock_lot_id':lot['id'],'quantity':take,'amount':amount})
        if remain:raise HTTPException(409,'Không đủ tồn sau đối chiếu')
    c.execute("UPDATE prescriptions SET status='dispensed' WHERE id=?",(rid,));audit(c,u,'rx_dispensed','prescription',rid,str(total))
    return {'dispensation_id':did,'visit_id':rx['visit_id'],'total':total,'lots':parts,'status':'dispensed','payment_status':'unpaid_until_cashier_records_payment'}
