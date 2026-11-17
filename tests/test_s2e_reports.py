"""S2e-1: report rows, UTC+7 boundaries, authorization and XLSX, simulated records."""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.main import db
from tests.test_workflows import client, token


@pytest.fixture(scope='module')
def sample():
    actors = {name: token(name) for name in ('quanly','quantri','bs_noi','bs_san','thungan')}
    at1 = '2099-06-17T18:00:00+00:00'  # 18 June in Vietnam
    at2 = '2099-06-19T02:00:00+00:00'
    with db(True) as c:
        doctors = [c.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()[0]
                   for name in ('bs_noi','bs_san')]
        cashier = c.execute("SELECT id FROM users WHERE username='thungan'").fetchone()[0]
        manager = c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]

        def insert(statement, args):
            c.execute(statement, args)
            return c.execute('SELECT last_insert_rowid()').fetchone()[0]

        patients = [insert("INSERT INTO patients(code,full_name,sex,created_at) VALUES(?,?,?,?)",
                           (f'S2E-GIA-{i}',f'Bệnh nhân thử báo cáo {i}','Nam',at1)) for i in range(1,4)]
        visits = [insert("""INSERT INTO visits(patient_id,doctor_id,created_by,status,created_at)
                            VALUES(?,?,?,?,?)""", (patients[i],doctors[i%2],manager,
                            'cancelled' if i==2 else 'waiting', at2 if i==1 else at1))
                  for i in range(3)]
        charges = [insert('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',
                          (vid,label,amount,at2 if idx==3 else at1))
                   for idx,(vid,label,amount) in enumerate([
                       (visits[0],'Khám',100000),(visits[0],'Xét nghiệm',50000),
                       (visits[0],'Thuốc',30000),(visits[1],'Khám',120000),
                       (visits[2],'Khoản hủy',90000)])]
        # Medicine source_type is referenced by charge_sources, not free-text charge labels.
        c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'dispense_item',?)",
                  (charges[2],900001))
        lab_order = insert("""INSERT INTO orders(visit_id,category,name,requested_by,created_at)
                              VALUES(?,?,?,?,?)""",(visits[0],'lab','Xét nghiệm',doctors[0],at1))
        c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'order',?)",
                  (charges[1],lab_order))
        cancelled_order = insert("""INSERT INTO orders(visit_id,category,name,requested_by,status,created_at)
                VALUES(?,?,?,?,?,?)""",(visits[1],'xray','Chỉ định hủy',doctors[1],'cancelled',at2))
        imaging_order = insert("""INSERT INTO orders(visit_id,category,name,requested_by,created_at)
                VALUES(?,?,?,?,?)""",(visits[0],'ultrasound','Siêu âm',doctors[0],at1))
        c.execute('INSERT INTO charge_voids(charge_id,approved_by,reason,created_at) VALUES(?,?,?,?)',
                  (charges[4],manager,'Dịch vụ bị hủy',at1))
        rx = insert("""INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,status,created_at)
              VALUES(?,?,?,?,?)""",(visits[0],doctors[0],'Thuốc đã hủy','cancelled',at1))
        c.execute("""INSERT INTO prescription_cancellations(prescription_id,actor_id,reason,created_at)
              VALUES(?,?,?,?)""",(rx,doctors[0],'Hủy đơn nháp',at1))
        c.execute("""INSERT INTO order_cancel_requests(order_id,reason,status,requested_by,
              reviewed_by,requested_at,reviewed_at) VALUES(?,?,?,?,?,?,?)""",
              (cancelled_order,'Hủy chỉ định','approved',doctors[1],manager,at2,at2))
        template = c.execute('SELECT code FROM imaging_templates LIMIT 1').fetchone()[0]
        orig = insert("""INSERT INTO imaging_reports(order_id,template_code,descriptions,request,
             created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
             (imaging_order,template,'[]','',doctors[0],at1,at1))
        insert("""INSERT INTO imaging_reports(order_id,template_code,descriptions,request,
            created_by,created_at,updated_at,replaces_id,reason) VALUES(?,?,?,?,?,?,?,?,?)""",
            (imaging_order,template,'[]','',doctors[0],at1,at1,orig,'Sửa kết luận'))
        for n,(vid,amount,method,stamp) in enumerate(((visits[0],110000,'cash',at1),
                                                      (visits[1],90000,'transfer',at2))):
            insert("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,
                 idempotency_key) VALUES(?,?,?,?,?,?)""",
                 (vid,amount,method,cashier,stamp,'s2e_demo_payment_'+str(n)))

    yield dict(actors=actors, visits=visits, patients=patients, doctors=doctors)
    with db(True) as c:
        marks=','.join('?' for _ in visits)
        c.execute(f"DELETE FROM imaging_reports WHERE order_id IN (SELECT id FROM orders WHERE visit_id IN ({marks})) AND replaces_id IS NOT NULL",visits)
        c.execute(f"DELETE FROM imaging_reports WHERE order_id IN (SELECT id FROM orders WHERE visit_id IN ({marks}))",visits)
        c.execute(f"DELETE FROM order_cancel_requests WHERE order_id IN (SELECT id FROM orders WHERE visit_id IN ({marks}))",visits)
        c.execute(f"DELETE FROM prescription_cancellations WHERE prescription_id IN (SELECT id FROM prescriptions WHERE visit_id IN ({marks}))",visits)
        c.execute(f"DELETE FROM prescriptions WHERE visit_id IN ({marks})",visits)
        c.execute(f"DELETE FROM charge_voids WHERE charge_id IN (SELECT id FROM charges WHERE visit_id IN ({marks}))",visits)
        c.execute(f"DELETE FROM charge_sources WHERE charge_id IN (SELECT id FROM charges WHERE visit_id IN ({marks}))",visits)
        c.execute(f"DELETE FROM charges WHERE visit_id IN ({marks})",visits)
        c.execute(f"DELETE FROM payments WHERE visit_id IN ({marks})",visits)
        c.execute(f"DELETE FROM orders WHERE visit_id IN ({marks})",visits)
        c.execute(f"DELETE FROM visits WHERE id IN ({marks})",visits)
        marks2=','.join('?' for _ in patients)
        c.execute(f"DELETE FROM patients WHERE id IN ({marks2})",patients)


def params():
    return {'month':'2099-06'}


def test_amounts_visits_cashier_and_corrections(sample):
    manager = sample['actors']['quanly']
    revenue = client.get('/api/reports/revenue',headers=manager,params=params())
    assert revenue.status_code==200,revenue.text
    values = revenue.json()
    assert values['totals']['medicine']==30000
    assert values['totals']['clinical']==50000
    assert values['totals']['other']==220000
    assert values['totals']['gross']==300000  # 90,000 void is excluded
    assert values['totals']['paid']==200000
    assert values['totals']['outstanding']==100000
    assert {r['day'] for r in values['rows']}=={'2099-06-18','2099-06-19'}
    visits = client.get('/api/reports/visits',headers=manager,params=params()).json()
    assert visits['total']==2 and visits['cancelled']==1
    assert len(visits['rows'])==3 and len(visits['by_doctor'])==2
    cashier = client.get('/api/reports/cashier',headers=manager,params=params()).json()
    assert cashier['total']==200000 and len(cashier['rows'])==2
    assert cashier['by_cashier'][0]['cashier_name']=='Thu ngân'
    assert {r['method'] for r in cashier['by_method']}=={'cash','transfer'}
    corrections = client.get('/api/reports/corrections',headers=manager,params=params()).json()
    assert {'Hủy khoản thu','Hủy đơn thuốc','Hủy chỉ định','Đính chính hình ảnh'} <= {x['type'] for x in corrections['rows']}


@pytest.mark.parametrize('role', ['bs_noi','thungan'])
def test_denied_for_other_roles(sample,role):
    for kind in ('revenue','visits','cashier','corrections'):
        for suffix in ('','/export'):
            assert client.get(f'/api/reports/{kind}{suffix}',
                              headers=sample['actors'][role],params=params()).status_code==403


def test_excel_matches_json_rows_and_admin_access(sample):
    headers=sample['actors']['quantri']
    for kind in ('revenue','visits','cashier','corrections'):
        json_data=client.get('/api/reports/'+kind,headers=headers,params=params())
        response=client.get('/api/reports/'+kind+'/export',headers=headers,params=params())
        assert json_data.status_code==response.status_code==200
        assert response.content[:2]==b'PK'
        book=load_workbook(BytesIO(response.content),read_only=True)
        assert book.worksheets[0].max_row==len(json_data.json()['rows'])+1
        assert all(isinstance(cell.value,str) for cell in next(book.worksheets[0].iter_rows(max_row=1)))
        book.close()
