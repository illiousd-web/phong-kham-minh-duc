"""Cùng dữ liệu và phép đối chiếu cho SQLite lẫn PostgreSQL thật."""
from contextlib import contextmanager
import secrets


@contextmanager
def pending_data(db,ids):
    tag='Hàng chờ giả lập '+secrets.token_hex(5)
    with db(True) as c:
        def insert(sql,args):
            c.execute(sql,args)
            return c.execute('SELECT last_insert_rowid()').fetchone()[0]
        pid=insert('INSERT INTO patients(code,full_name,sex,created_at) VALUES(?,?,?,?)',(tag,tag,'Nữ','2026-01-01T00:00:00+00:00'))
        visits=[]
        for i in range(151):
            vid=insert('INSERT INTO visits(patient_id,doctor_id,created_by,created_at,status) VALUES(?,?,?,?,?)',(pid,ids['doctor'],ids['reception'],'2026-01-01T00:00:00+00:00','waiting' if i==0 else 'completed'))
            visits.append(vid)
            c.execute('INSERT INTO visit_nurses(visit_id,nurse_id,assigned_by,assigned_at) VALUES(?,?,?,?)',(vid,ids['nurse'],ids['doctor'],'2026-01-01T00:00:00+00:00'))
        ordered=[]
        # 120 việc cũ xen kẽ việc xong, rồi thêm hẳn 150 việc xong mới hơn.
        for i in range(390):
            status='ordered' if i<240 and i%2==0 else 'approved'
            oid=insert('INSERT INTO orders(visit_id,category,name,status,requested_by,created_at) VALUES(?,?,?,?,?,?)',(visits[0],'lab',tag,status,ids['doctor'],'2026-01-01T00:00:00+00:00'))
            if status=='ordered':ordered.append(oid)
        rx=insert('INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,status,created_at) VALUES(?,?,?,?,?)',(visits[0],ids['doctor'],tag,'dispensed','2026-01-01T00:00:00+00:00'))
        disp=insert('INSERT INTO dispensations(prescription_id,visit_id,dispensed_by,dispensed_at) VALUES(?,?,?,?)',(rx,visits[0],ids['pharmacy'],'2026-01-01T00:00:00+00:00'))
        pending={}
        for i in range(151):
            status='pending' if i==0 else 'approved'
            records={
              '/api/adjustments':('INSERT INTO adjustments(visit_id,kind,amount,reason,status,proposed_by,proposed_at) VALUES(?,?,?,?,?,?,?)',(visits[0],'discount',1,tag,status,ids['cashier'],'2026-01-01T00:00:00+00:00')),
              '/api/orders/cancellation-requests':('INSERT INTO order_cancel_requests(order_id,reason,status,requested_by,requested_at) VALUES(?,?,?,?,?)',(ordered[0],tag,status,ids['doctor'],'2026-01-01T00:00:00+00:00')),
              '/api/visits/addenda/pending':('INSERT INTO visit_addenda(visit_id,created_by,reason,content,status,created_at) VALUES(?,?,?,?,?,?)',(visits[0],ids['doctor'],tag,tag,status,'2026-01-01T00:00:00+00:00')),
              '/api/medication-returns':('INSERT INTO medication_returns(dispensation_id,reason,requested_by,status,created_at,request_key) VALUES(?,?,?,?,?,?)',(disp,tag,ids['pharmacy'],status,'2026-01-01T00:00:00+00:00',tag+str(i)))}
            for path,(sql,args) in records.items():
                rid=insert(sql,args)
                if i==0:pending[path]=rid
    try:yield {'tag':tag,'visits':visits,'ordered':ordered,'pending':pending}
    finally:
        with db(True) as c:
            for table in ('adjustments','order_cancel_requests','visit_addenda','medication_returns'):
                c.execute('DELETE FROM '+table+' WHERE reason=?',(tag,))
            c.execute('DELETE FROM dispensations WHERE id=?',(disp,))
            c.execute('DELETE FROM prescriptions WHERE id=?',(rx,))
            c.execute('DELETE FROM orders WHERE name=?',(tag,))
            c.execute('DELETE FROM visit_nurses WHERE visit_id IN (SELECT id FROM visits WHERE patient_id=?)',(pid,))
            c.execute('DELETE FROM visits WHERE patient_id=?',(pid,))
            c.execute('DELETE FROM patients WHERE id=?',(pid,))


def assert_pending_queues(get,data,before,addendum):
    def rows(role,path):
        response=get(role,path);assert response.status_code==200,response.text
        return response.json()
    orders=rows('technician','/api/orders')
    found=[x['id'] for x in orders if x['name']==data['tag']]
    assert len(found)==len(set(found))==120
    assert set(found)==set(data['ordered'])
    assert all(x['status'] in ('requested','ordered','pending_review') for x in orders)
    assert rows('technician','/api/queue-counts')['lab']==before['technician']['lab']+120
    for role in ('reception','doctor','nurse'):
        visits=rows(role,'/api/visits')
        found=[x['id'] for x in visits if x['id'] in data['visits']]
        assert found==[data['visits'][0]],(role,found)
        assert rows(role,'/api/queue-counts')[role]==before[role][role]+1
        history=rows(role,'/api/visits?history=true')
        assert len(history)==100 and all(x['status'] in ('completed','cancelled') for x in history)
    for path,rid in data['pending'].items():
        result=rows('manager',path)
        assert [x['id'] for x in result if x['reason']==data['tag']]==[rid],path
        assert all(x['status']=='pending' for x in result)
        if 'addenda' not in path:
            history=rows('manager',path+'?history=true')
            assert len(history)==100 and all(x['status']!='pending' for x in history)
    assert rows('manager','/api/queue-counts')['manager']==before['manager']['manager']+3+int(addendum)
    assert rows('doctor2','/api/orders?visit_id='+str(data['visits'][0]))==[]
    assert data['visits'][0] not in [x['id'] for x in rows('doctor2','/api/visits')]
    for path in ('/api/orders','/api/adjustments','/api/orders/cancellation-requests','/api/medication-returns','/api/visits/addenda/pending'):
        assert get('reception',path).status_code==403,path
    assert get('anonymous','/api/visits').status_code==401


def assert_more_than_100_pending_approvals(db,get,data,before,addendum):
    with db(True) as c:
        for table in ('adjustments','order_cancel_requests','visit_addenda','medication_returns'):
            c.execute("UPDATE "+table+" SET status='pending' WHERE reason=?",(data['tag'],))
    for path in data['pending']:
        response=get('manager',path);assert response.status_code==200,response.text
        ids=[x['id'] for x in response.json() if x['reason']==data['tag']]
        assert len(ids)==len(set(ids))==151,path
    assert get('manager','/api/queue-counts').json()['manager']==before['manager']['manager']+151*(3+int(addendum))
