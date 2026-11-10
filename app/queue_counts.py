"""COUNT trực tiếp bằng điều kiện hàng chờ; peek không gia hạn phiên.

known cũ vẫn nhận để tương thích nhưng không bỏ COUNT; không nhận số từ client.
Mọi lần tải/định kỳ/quay lại tab đều đếm đủ phía máy chủ.
"""
from fastapi import Depends
from typing import Literal
from .work_queues import visit_predicate,approval_predicate
from .charge_queries import DUES_COUNT_SQL


def install_queue_counts(app, peek, load_ui, db):
    @app.get('/api/queue-counts')
    def queue_counts(u=Depends(peek),known:Literal['lab','cashier']|None=None):
        roles=set(u['roles']);ui=load_ui();out={}
        with db() as c:
            def count(sql,args=()):
                return c.execute('SELECT COUNT(*) FROM '+sql,args).fetchone()[0]
            if roles & {'reception','doctor','nurse'}:
                predicate,args=visit_predicate(u)
                total=count('visits v JOIN patients p ON p.id=v.patient_id WHERE '+predicate,args)
                for role in roles & {'reception','doctor','nurse'}:out[role]=total
            if 'technician' in roles:
                out['lab']=count("orders o JOIN visits v ON v.id=o.visit_id JOIN patients p ON p.id=v.patient_id WHERE o.status='ordered'")
            if 'pharmacy' in roles:
                out['pharmacy']=count("prescriptions WHERE status='draft'")
            if 'cashier' in roles:
                out['cashier']=c.execute(DUES_COUNT_SQL).fetchone()[0]
            if 'manager' in roles:
                total=count('adjustments a JOIN visits v ON v.id=a.visit_id JOIN patients p ON p.id=v.patient_id JOIN users u ON u.id=a.proposed_by WHERE '+approval_predicate('a'))
                total+=count('order_cancel_requests r JOIN orders o ON o.id=r.order_id WHERE '+approval_predicate('r'))
                total+=count('medication_returns r JOIN dispensations d ON d.id=r.dispensation_id WHERE '+approval_predicate('r'))
                total+=count("manual_price_requests r WHERE "+approval_predicate('r'))
                if ui['addendum']:
                    total+=count('visit_addenda a JOIN visits v ON v.id=a.visit_id JOIN patients p ON p.id=v.patient_id WHERE '+approval_predicate('a'))
                if ui['controlled_drugs'] and 'controlled_reviewer' in roles:
                    total+=count('controlled_receipts r WHERE '+approval_predicate('r'))
                out['manager']=total
        return out
