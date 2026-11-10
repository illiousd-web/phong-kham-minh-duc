"""Giá chuẩn độc lập + so từng dòng với view cho cả SQLite và PostgreSQL."""
import secrets
import sys
from app.charge_queries import priced_ctes


def check_prices(c,visit,actor,stamp):
    cases=[(1000,None,None,[],False,1000),(None,None,None,[],False,None),
           (0,None,None,[],False,0),(1000,1234,None,[],False,1234),
           (None,None,2345,[],False,2345),(None,1234,2345,[],False,1234),
           (1000,None,None,[200],False,800),(1000,None,None,[200,100],False,700),
           (None,None,2345,[200],False,2145),(1000,1234,2345,[200],False,1034),
           (1000,None,None,[],True,0),(None,None,None,[],True,0),
           (None,1234,2345,[200,100],True,0),(None,None,None,[200],False,None)]
    ids=[];expected={};returns=[]
    # Chuỗi FK thật cho nguồn hoàn thuốc; không dùng source_id giả không tồn tại.
    c.execute("INSERT INTO medicines(name,base_unit) VALUES(?,'viên')",('Giả lập C5 '+secrets.token_hex(6),))
    medicine=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute("INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(?,'C5','2099-01-01',100)",(medicine,))
    lot=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute("INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,created_at) VALUES(?,?,'Giả lập C5',?)",(visit,actor,stamp))
    rx=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('INSERT INTO prescription_items(prescription_id,medicine_id,quantity) VALUES(?,?,100)',(rx,medicine))
    item=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('INSERT INTO dispensations(prescription_id,visit_id,dispensed_by,dispensed_at) VALUES(?,?,?,?)',(rx,visit,actor,stamp))
    dispense=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('INSERT INTO dispensation_items(dispensation_id,prescription_item_id,medicine_id,stock_lot_id,quantity,unit_price) VALUES(?,?,?,?,100,1000)',(dispense,item,medicine,lot))
    disp_item=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    try:
        for original,price,manual,credits,void,amount in cases:
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,'Giả lập đối chứng C5',?,?)",(visit,original,stamp))
            cid=c.execute('SELECT last_insert_rowid()').fetchone()[0];ids.append(cid);expected[cid]=amount
            if price is not None:c.execute('INSERT INTO charge_pricing(charge_id,amount) VALUES(?,?)',(cid,price))
            if manual is not None:
                c.execute('INSERT INTO manual_charge_prices(charge_id,amount,description,priced_by,priced_at,request_key) VALUES(?,?,?,?,?,?)',
                          (cid,manual,'Giả lập C5',actor,stamp,secrets.token_hex(12)))
            for credit in credits:
                c.execute("INSERT INTO medication_returns(dispensation_id,reason,requested_by,created_at,request_key) VALUES(?,'Giả lập C5',?,?,?)",(dispense,actor,stamp,secrets.token_hex(12)))
                returned=c.execute('SELECT last_insert_rowid()').fetchone()[0];returns.append(returned)
                c.execute('INSERT INTO medication_return_items(return_id,dispensation_item_id,quantity) VALUES(?,?,1)',(returned,disp_item))
                source=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute('INSERT INTO charge_credits(charge_id,amount,source_id,created_by,created_at) VALUES(?,?,?,?,?)',
                          (cid,credit,source,actor,stamp))
            if void:c.execute("INSERT INTO charge_voids(charge_id,approved_by,reason,created_at) VALUES(?,?,'Giả lập C5',?)",(cid,actor,stamp))
        view={r[0]:r[2] for r in c.execute('SELECT id,visit_id,amount FROM effective_charges WHERE visit_id=? ORDER BY id',(visit,))}
        query='WITH wanted AS (SELECT ? AS visit_id),'+priced_ctes('visit_id IN (SELECT visit_id FROM wanted)')+' SELECT id,visit_id,amount FROM priced ORDER BY id'
        rows=c.execute(query,(visit,)).fetchall()
        optimized={r[0]:r[2] for r in rows}
        assert len(rows)==len(optimized) and optimized==view
        assert {cid:optimized[cid] for cid in ids}==expected
        assert sum(x is None for x in view.values())==sum(x is None for x in optimized.values())
    finally:
        # Caller luôn giữ db(True); khi lỗi, để context rollback thay vì chạy
        # DELETE trong giao dịch PostgreSQL đã abort và che mất lỗi gốc.
        if ids and sys.exc_info()[0] is None:
            marks=','.join('?' for _ in ids)
            for table in ('charge_voids','charge_pricing','manual_charge_prices','charge_credits'):
                c.execute('DELETE FROM '+table+' WHERE charge_id IN ('+marks+')',ids)
            c.execute('DELETE FROM charges WHERE id IN ('+marks+')',ids)
            for returned in returns:
                c.execute('DELETE FROM medication_return_items WHERE return_id=?',(returned,))
                c.execute('DELETE FROM medication_returns WHERE id=?',(returned,))
            c.execute('DELETE FROM dispensation_items WHERE id=?',(disp_item,))
            c.execute('DELETE FROM dispensations WHERE id=?',(dispense,))
            c.execute('DELETE FROM prescription_items WHERE id=?',(item,))
            c.execute('DELETE FROM prescriptions WHERE id=?',(rx,))
            c.execute('DELETE FROM stock_lots WHERE id=?',(lot,))
            c.execute('DELETE FROM medicines WHERE id=?',(medicine,))
