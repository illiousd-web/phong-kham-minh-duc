"""Lọc chỉ định theo lượt giữ quyền và tìm được lượt cũ ngoài 100 dòng gần nhất."""
import secrets
from tests.test_workflows import client,token
from app import main


def test_orders_visit_filter_keeps_doctor_scope_and_old_visit_results():
    doctor=token('bs_noi');other=token('bs_san');tech=token('kythuat');reception=token('letan');nurse=token('dieuduong')
    patient=client.post('/api/patients',headers=reception,json={'full_name':'Giả lập lọc chỉ định C5 '+secrets.token_hex(4),
        'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'}).json()['id']
    with main.db(True) as c:
        did=c.execute("SELECT id FROM users WHERE username='bs_noi'").fetchone()[0]
        rid=c.execute("SELECT id FROM users WHERE username='letan'").fetchone()[0]
        visits=[];orders=[]
        for count in (2,110):
            c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',(patient,did,rid,main.NOW()))
            vid=c.execute('SELECT last_insert_rowid()').fetchone()[0];visits.append(vid)
            group=[]
            for _ in range(count):
                c.execute("INSERT INTO orders(visit_id,category,name,status,requested_by,created_at,result_text) VALUES(?,'lab','Giả lập C5','approved',?,?,?)",
                          (vid,did,main.NOW(),'Kết quả giả lập C5'))
                group.append(c.execute('SELECT last_insert_rowid()').fetchone()[0])
            orders.append(group)
        nid=c.execute("SELECT id FROM users WHERE username='dieuduong'").fetchone()[0]
        c.execute('INSERT INTO visit_nurses(visit_id,nurse_id,assigned_by,assigned_at) VALUES(?,?,?,?)',(visits[0],nid,did,main.NOW()))
    for headers in (doctor,tech):
        response=client.get(f'/api/orders?visit_id={visits[0]}',headers=headers)
        assert response.status_code==200
        assert [x['id'] for x in response.json()]==list(reversed(orders[0]))
        assert all(x['result_text']=='Kết quả giả lập C5' for x in response.json())
    assert client.get(f'/api/orders?visit_id={visits[0]}',headers=other).json()==[]
    assert client.get(f'/api/orders?visit_id={visits[0]}',headers=reception).status_code==403
    care=client.get(f'/api/orders?visit_id={visits[0]}',headers=nurse).json()
    assert [x['id'] for x in care]==list(reversed(orders[0]))
    assert all(x['result_text'] is None and x['file_name'] is None for x in care)
    assert client.get(f'/api/orders?visit_id={visits[1]}',headers=nurse).json()==[]
    # Không truyền bộ lọc: hợp đồng 100 chỉ định gần nhất giữ nguyên.
    assert [x['id'] for x in client.get('/api/orders',headers=doctor).json()]==list(reversed(orders[1]))[:100]
