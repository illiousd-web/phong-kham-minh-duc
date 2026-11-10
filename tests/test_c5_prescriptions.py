"""Phân trang không mất đơn; bác sĩ vẫn chỉ đọc đúng đơn được phân công."""
from contextlib import contextmanager
import secrets
from tests.test_workflows import client,token
from app import main


def test_rx_pages_are_complete_scoped_and_fetch_items_in_batches(monkeypatch):
    reception=token('letan');pharmacy=token('duoc');doctor=token('bs_noi');other=token('bs_san')
    patient=client.post('/api/patients',headers=reception,json={'full_name':'Giả lập phân trang C5 '+secrets.token_hex(4),
        'sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'}).json()['id']
    with main.db(True) as c:
        did=c.execute("SELECT id FROM users WHERE username='bs_noi'").fetchone()[0]
        rid=c.execute("SELECT id FROM users WHERE username='letan'").fetchone()[0]
        mid=c.execute('SELECT id FROM medicines ORDER BY id LIMIT 1').fetchone()[0]
        created=[]
        for _ in range(205):
            c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,diagnosis,created_at) VALUES(?,?,?,'Giả lập C5',?)",(patient,did,rid,main.NOW()))
            vid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,created_at) VALUES(?,?,'Thuốc giả lập C5',?)",(vid,did,main.NOW()))
            rx=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO prescription_items(prescription_id,medicine_id,quantity,directions) VALUES(?,?,2,?)',(rx,mid,'Giả lập C5'))
            created.append((vid,rx))
    # Lọc đúng một lượt cũ, dù đơn đó không nằm trong trang mới nhất.
    vid,rx=created[0]
    scoped=client.get(f'/api/prescriptions?visit_id={vid}',headers=doctor)
    assert scoped.status_code==200 and [x['id'] for x in scoped.json()]==[rx]
    assert client.get(f'/api/prescriptions?visit_id={vid}',headers=other).json()==[]
    assert client.get(f'/api/prescriptions?visit_id={vid}',headers=reception).status_code==403
    pages=[client.get(f'/api/prescriptions?status=draft&limit=100&offset={offset}',headers=pharmacy).json() for offset in (0,100,200)]
    found=[x['id'] for page in pages for x in page]
    expected=[x[1] for x in reversed(created)]
    assert found[:205]==expected and len(found)==len(set(found))
    assert all(x['items'][0]['quantity']==2 for page in pages for x in page if x['id'] in expected)
    # Đường cũ vẫn trả đủ lịch sử; đường UI giới hạn 101 chỉ cần một truy vấn dòng thuốc.
    assert set(expected)<= {x['id'] for x in client.get('/api/prescriptions',headers=pharmacy).json()}
    original=main.db;item_queries=[]
    class Connection:
        def __init__(self,c):self.c=c
        def execute(self,query,args=()):
            if 'FROM prescription_items pi' in query:item_queries.append(query)
            return self.c.execute(query,args)
    @contextmanager
    def counted(write=False):
        with original(write) as c:yield Connection(c)
    monkeypatch.setattr(main,'db',counted)
    assert client.get('/api/prescriptions?status=draft&limit=101',headers=pharmacy).status_code==200
    assert len(item_queries)==1
    for query in ('limit=0','limit=201','offset=-1','status=khong_hop_le'):
        assert client.get('/api/prescriptions?'+query,headers=pharmacy).status_code==422
