"""S2e-1: report rows, UTC+7 boundaries, authorization and XLSX, simulated records."""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.main import db
from tests.test_workflows import client, token


@pytest.fixture
def sample(tmp_path_factory):
    # Isolate the entire DB: S2d deliberately forbids deleting imaging reports
    # even when unsigned. Never leave synthetic rows in other tests' DB.
    from app import main as main_module, database as database_module
    original_main, original_database = main_module.DB, database_module.DB
    separate = tmp_path_factory.mktemp('s2e_reports') / 'clinic.sqlite3'
    main_module.DB = separate
    database_module.DB = separate
    main_module.init_db()
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
                          (vid,label,amount,at2 if idx in (3, 6) else at1))
                   for idx,(vid,label,amount) in enumerate([
                       (visits[0],'Khám',100000),(visits[0],'Xét nghiệm',50000),
                       (visits[0],'Thuốc',30000),(visits[1],'Khám',120000),
                       (visits[2],'Khoản hủy',90000),
                       (visits[0],'Điện tim',40000),(visits[1],'Thủ thuật',60000)])]
        manual = insert('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,NULL,?)',
                        (visits[0],'Dịch vụ nhập giá tay',at1))
        c.execute("""INSERT INTO manual_charge_prices(charge_id,amount,description,priced_by,priced_at,request_key)
            VALUES(?,?,?,?,?,?)""",(manual,70000,'Giá thủ công giả lập',cashier,at2,'s2e_manual_price_1'))
        # Only tests use this independent cashier identity, no login session is created.
        cashier2 = insert("""INSERT INTO users(username,full_name,salt,password_hash,active)
            VALUES(?,?,?,?,1)""",('thu_ngan_s2e','Thu ngân thứ hai','0'*32,'test_account_no_login'))
        c.execute("INSERT INTO user_roles(user_id,role) VALUES(?,'cashier')",(cashier2,))
        # Medicine source_type is referenced by charge_sources, not free-text charge labels.
        c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'dispense_item',?)",
                  (charges[2],900001))
        lab_order = insert("""INSERT INTO orders(visit_id,category,name,requested_by,created_at)
                              VALUES(?,?,?,?,?)""",(visits[0],'lab','Xét nghiệm',doctors[0],at1))
        c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'order',?)",
                  (charges[1],lab_order))
        for category, label, charge_id, visit_id, doctor_id in (
            ('ecg', 'Điện tim', charges[5], visits[0], doctors[0]),
            ('procedure', 'Thủ thuật', charges[6], visits[1], doctors[1]),
        ):
            service_order = insert("""INSERT INTO orders(visit_id,category,name,requested_by,created_at)
                                   VALUES(?,?,?,?,?)""", (visit_id, category, label, doctor_id,
                                                        at2 if category == 'procedure' else at1))
            c.execute("INSERT INTO charge_sources(charge_id,source_type,source_id) VALUES(?,'order',?)",
                      (charge_id, service_order))
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
        draft_correction = insert("""INSERT INTO imaging_reports(order_id,template_code,descriptions,request,
            created_by,created_at,updated_at,replaces_id,reason) VALUES(?,?,?,?,?,?,?,?,?)""",
            (imaging_order,template,'[]','',doctors[0],at1,at1,orig,'Sửa kết luận'))
        first_payment = None
        for n,(vid,amount,method,stamp,actor) in enumerate(((visits[0],110000,'cash',at1,cashier),
                                                           (visits[1],90000,'transfer',at2,cashier2))):
            payment_id = insert("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,
                 idempotency_key) VALUES(?,?,?,?,?,?)""",
                 (vid,amount,method,actor,stamp,'s2e_demo_payment_'+str(n)))
            if n==0:
                first_payment=payment_id
        discount = insert("""INSERT INTO adjustments(visit_id,kind,amount,reason,status,
            proposed_by,reviewed_by,proposed_at,reviewed_at) VALUES(?,'discount',?,?,'approved',?,?,?,?)""",
            (visits[0],20000,'Giảm giá thử nghiệm',cashier,manager,at1,at1))
        refund = insert("""INSERT INTO adjustments(visit_id,payment_id,kind,amount,reason,status,
            proposed_by,reviewed_by,proposed_at,reviewed_at)
            VALUES(?,?,'refund',?,?,'approved',?,?,?,?)""",
            (visits[0],first_payment,10000,'Hoàn tiền thử nghiệm',cashier,manager,at2,at2))

    try:
        yield dict(actors=actors, visits=visits, patients=patients, doctors=doctors,
                   manual=manual, discount=discount, refund=refund, cashier2=cashier2,
                   draft_correction=draft_correction, at1=at1, at2=at2)
    finally:
        database_module.DB = original_database
        main_module.DB = original_main


def params():
    return {'month':'2099-06'}


def test_amounts_visits_cashier_and_corrections(sample):
    manager = sample['actors']['quanly']
    revenue = client.get('/api/reports/revenue',headers=manager,params=params())
    assert revenue.status_code==200,revenue.text
    values = revenue.json()
    assert values['totals']['medicine']==30000
    assert values['totals']['clinical']==90000  # 50,000 lab + 40,000 ECG
    assert values['totals']['procedure']==60000
    assert values['totals']['other']==290000  # Includes 70,000 manually priced service
    assert values['totals']['gross']==470000  # 90,000 void is excluded
    assert values['totals']['discount']==20000
    assert values['totals']['revenue']==450000
    assert values['totals']['payments']==200000
    assert values['totals']['refund']==10000
    assert values['totals']['paid']==190000
    assert values['totals']['outstanding']==260000
    assert values['totals']['known_due']==260000
    assert values['totals']['unpriced_count']==0
    assert len(values['unpaid_visits'])==2
    assert sum(item['known_due'] for item in values['unpaid_visits'])==260000
    assert 'warning' not in values
    assert values['note'].startswith('Số liệu theo giá hiện hành')
    assert sum(r['discount'] for r in values['rows'])==20000
    assert sum(r['refund'] for r in values['rows'])==10000
    assert {r['day'] for r in values['rows']}=={'2099-06-18','2099-06-19'}
    by_day = {row['day']: row for row in values['rows']}
    assert by_day['2099-06-18']['clinical']==90000  # Both lab and ECG
    assert by_day['2099-06-18']['procedure']==0
    assert by_day['2099-06-19']['procedure']==60000
    assert by_day['2099-06-18']['outstanding']==160000
    assert by_day['2099-06-19']['outstanding']==100000
    visits = client.get('/api/reports/visits',headers=manager,params=params()).json()
    assert visits['total']==2 and visits['cancelled']==1
    assert len(visits['rows'])==3 and len(visits['by_doctor'])==2
    cashier = client.get('/api/reports/cashier',headers=manager,params=params()).json()
    assert cashier['total']==200000 and len(cashier['rows'])==2
    assert len(cashier['by_cashier'])==2
    assert {r['cashier_name'] for r in cashier['by_cashier']}=={'Thu ngân','Thu ngân thứ hai'}
    assert all(r['count']==1 for r in cashier['by_cashier'])
    assert {r['method'] for r in cashier['by_method']}=={'cash','transfer'}
    corrections = client.get('/api/reports/corrections',headers=manager,params=params()).json()
    assert {'Hủy khoản thu','Hủy đơn thuốc','Hủy chỉ định',
            'Giảm giá','Hoàn tiền'} <= {x['type'] for x in corrections['rows']}
    assert not any(x['type']=='Đính chính hình ảnh' for x in corrections['rows'])
    assert next(r for r in corrections['rows'] if r['type']=='Giảm giá')['actor']=='Quản lý phòng khám'
    assert next(r for r in corrections['rows'] if r['type']=='Hoàn tiền')['reason']=='Hoàn tiền thử nghiệm'


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
        assert book.worksheets[0].max_row==len(json_data.json()['rows'])+2
        assert book.worksheets[0]['A1'].value==json_data.json()['note']
        assert all(isinstance(cell.value,str) for cell in next(book.worksheets[0].iter_rows(min_row=2,max_row=2)))
        assert all(ws['A1'].value==json_data.json()['note'] for ws in book.worksheets)
        book.close()


def test_manual_price_and_effective_adjustments_are_used(sample):
    with db() as c:
        ch = c.execute('SELECT amount,original_amount FROM effective_charges WHERE id=?',
                       (sample['manual'],)).fetchone()
        assert ch['amount']==70000 and ch['original_amount'] is None
        assert c.execute("SELECT COUNT(*) FROM effective_adjustments WHERE id IN (?,?) AND status='approved'",
                         (sample['discount'],sample['refund'])).fetchone()[0]==2
    value = client.get('/api/reports/revenue',
                       headers=sample['actors']['quanly'],params=params()).json()
    assert sum(row['medicine']+row['clinical']+row['procedure']+row['other']-row['discount']
               for row in value['rows']) == value['totals']['revenue']
    assert sum(row['payments']-row['refund'] for row in value['rows'])==value['totals']['paid']
    book = load_workbook(BytesIO(client.get('/api/reports/revenue/export',
                         headers=sample['actors']['quanly'],params=params()).content),read_only=True)
    header = [cell.value for cell in book.active[2]]
    assert 'Giảm giá' in header and 'Hoàn tiền' in header
    assert 'Thủ thuật' in header and 'Chênh lệch trong ngày' in header
    assert 'Chưa thu' not in header
    daily_values = list(book.active.iter_rows(min_row=3, values_only=True))
    assert sum(row[header.index('Thủ thuật')] for row in daily_values[1:])==60000
    total = list(book['Tổng kỳ'].iter_rows(values_only=True))
    total_header, summary = total[1], total[2]
    assert 'Chưa thu' in total_header and 'Chênh lệch trong ngày' not in total_header
    assert 'Chênh lệch thu – phát sinh trong kỳ' in total_header
    assert 'Khoản chưa có giá' in total_header
    assert summary[total_header.index('Thủ thuật')]==60000
    assert summary[total_header.index('Phát sinh sau giảm')]==450000
    assert summary[total_header.index('Đã thu thuần')]==190000
    assert summary[total_header.index('Chênh lệch thu – phát sinh trong kỳ')]==260000
    assert summary[total_header.index('Chưa thu')]==260000
    assert summary[total_header.index('Khoản chưa có giá')]==0
    due_sheet = book['Lượt khám còn thiếu tiền']
    assert due_sheet.max_row==2+len(value['unpaid_visits'])
    assert due_sheet['A1'].value==value['note']
    book.close()


def test_paid_on_day_two_is_not_unpaid(sample):
    manager = sample['actors']['quanly']
    first = '2099-07-01T00:00:00+00:00'
    second = '2099-07-02T00:00:00+00:00'
    with db(True) as c:
        doctor = sample['doctors'][0]
        user = c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        cashier = c.execute("SELECT id FROM users WHERE username='thungan'").fetchone()[0]
        c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES('S2E-PAID','Đã trả đủ','Nam',?)", (first,))
        pid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)",
                  (pid,doctor,user,first))
        vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)",
                  (vid,'Phí khám tháng 7',88000,first))
        c.execute("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
            VALUES(?,88000,'cash',?,?,'s2e_paid_next_day')""",(vid,cashier,second))
    full = client.get('/api/reports/revenue',headers=manager,
                      params={'date_from':'2099-07-01','date_to':'2099-07-02'}).json()
    assert full['totals']['known_due']==0
    assert full['unpaid_visits']==[]
    next_day = client.get('/api/reports/revenue',headers=manager,
                          params={'date_from':'2099-07-02','date_to':'2099-07-02'}).json()
    assert next_day['totals']['known_due']==0
    assert next_day['unpaid_visits']==[]
    assert next_day['totals']['outstanding']==-88000  # Day-flow is not actual debt


def test_unpriced_charge_warns_and_is_listed(sample):
    manager = sample['actors']['quanly']
    stamp = '2099-07-03T02:00:00+00:00'
    with db(True) as c:
        user = c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        c.execute("""INSERT INTO patients(code,full_name,sex,created_at)
            VALUES('S2E-UNPRICED','Chưa nhập giá','Nam',?)""",(stamp,))
        pid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
                  (pid,sample['doctors'][0],user,stamp))
        vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("""INSERT INTO charges(visit_id,label,amount,created_at)
            VALUES(?,'Chưa định giá',NULL,?)""",(vid,stamp))
    value = client.get('/api/reports/revenue',headers=manager,
                       params={'date_from':'2099-07-03','date_to':'2099-07-03'}).json()
    assert value['totals']['unpriced_count']==1
    assert value['rows'][0]['unpriced_count']==1
    assert value['rows'][0]['gross']==0
    assert value['totals']['known_due']==0
    assert len(value['unpaid_visits'])==1
    assert value['unpaid_visits'][0]['patient_code']=='S2E-UNPRICED'
    assert value['unpaid_visits'][0]['unpriced_count']==1
    assert value['warning']=='Còn khoản chưa nhập giá, doanh thu chưa đầy đủ'
    response = client.get('/api/reports/revenue/export',headers=manager,
                          params={'date_from':'2099-07-03','date_to':'2099-07-03'})
    book = load_workbook(BytesIO(response.content),read_only=True)
    for sheet in book.worksheets:
        assert sheet['A1'].value==value['note']
        assert sheet['A2'].value==value['warning']
    assert 'Khoản chưa có giá' in [cell.value for cell in book['Tổng kỳ'][3]]
    book.close()


def test_discount_reversal_appears_in_corrections(sample):
    manager = sample['actors']['quanly']
    with db(True) as c:
        uid = c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        c.execute("""INSERT INTO adjustment_reversals(adjustment_id,reason,reversed_by,created_at)
            VALUES(?,?,?,?)""",(sample['discount'],'Hoàn tác giảm phí thử nghiệm',uid,sample['at2']))
    rows = client.get('/api/reports/corrections',headers=manager,params=params()).json()['rows']
    matches = [r for r in rows if r['type']=='Hoàn tác giảm giá']
    assert len(matches)==1
    assert matches[0]['actor']=='Quản lý phòng khám'
    assert matches[0]['reason']=='Hoàn tác giảm phí thử nghiệm'
    assert '20000' in matches[0]['content']


def test_cancelled_visit_appears_in_corrections(sample):
    with db(True) as c:
        uid = c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        c.execute("""INSERT INTO visit_cancellations(visit_id,actor_id,reason,created_at)
            VALUES(?,?,?,?)""",(sample['visits'][2],uid,'Hủy lượt khám theo yêu cầu',sample['at2']))
    rows = client.get('/api/reports/corrections',
                      headers=sample['actors']['quanly'],params=params()).json()['rows']
    matches = [r for r in rows if r['type']=='Hủy lượt khám']
    assert len(matches)==1
    assert matches[0]['patient_code']=='S2E-GIA-3'
    assert matches[0]['reason']=='Hủy lượt khám theo yêu cầu'


def test_return_two_tablets_in_corrections(sample):
    with db(True) as c:
        vid=sample['visits'][0]
        rxid=c.execute('SELECT id FROM prescriptions WHERE visit_id=?',(vid,)).fetchone()[0]
        user=c.execute("SELECT id FROM users WHERE username='thungan'").fetchone()[0]
        mid=c.execute("SELECT id FROM medicines WHERE base_unit='viên' LIMIT 1").fetchone()[0]
        lot=c.execute('SELECT id FROM stock_lots WHERE medicine_id=? LIMIT 1',(mid,)).fetchone()[0]
        c.execute('INSERT INTO prescription_items(prescription_id,medicine_id,quantity) VALUES(?,?,?)',
                  (rxid,mid,5))
        pi=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO dispensations(prescription_id,visit_id,dispensed_by,dispensed_at) VALUES(?,?,?,?)',
                  (rxid,vid,user,sample['at1']))
        disp=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("""INSERT INTO dispensation_items(dispensation_id,prescription_item_id,
            medicine_id,stock_lot_id,quantity,unit_price) VALUES(?,?,?,?,?,?)""",
            (disp,pi,mid,lot,5,1000))
        di=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        reviewer=c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        c.execute("""INSERT INTO medication_returns(
            dispensation_id,reason,requested_by,status,reviewed_by,
            created_at,reviewed_at,request_key
        ) VALUES(?,? ,?,'approved',?,?,?,?)""",
            (disp,'Trả thuốc chưa sử dụng',user,reviewer,sample['at1'],
             sample['at2'],'s2e_return_two_pills'))
        rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("""INSERT INTO medication_return_items(return_id,dispensation_item_id,quantity)
            VALUES(?,?,2)""",(rid,di))
        for status, key in (('pending','s2e_pending_return'),('rejected','s2e_rejected_return')):
            c.execute("""INSERT INTO medication_returns(
                dispensation_id,reason,requested_by,status,reviewed_by,
                created_at,reviewed_at,request_key
            ) VALUES(?,?,?,?,?,?,?,?)""",
                (disp,'Yêu cầu không được tính',user,status,
                 reviewer if status=='rejected' else None,
                 sample['at1'],sample['at2'] if status=='rejected' else None,key))
            rejected_or_pending=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("""INSERT INTO medication_return_items(
                return_id,dispensation_item_id,quantity) VALUES(?,?,1)""",
                (rejected_or_pending,di))
        medicine_name=c.execute('SELECT name FROM medicines WHERE id=?',(mid,)).fetchone()[0]
    manager=sample['actors']['quanly']
    day_one=client.get('/api/reports/corrections',headers=manager,
                       params={'date_from':'2099-06-18','date_to':'2099-06-18'}).json()
    assert not any(row['type']=='Trả thuốc' for row in day_one['rows'])
    day_two=client.get('/api/reports/corrections',headers=manager,
                       params={'date_from':'2099-06-19','date_to':'2099-06-19'}).json()
    matches=[r for r in day_two['rows'] if r['type']=='Trả thuốc']
    assert len(matches)==1  # Pending and rejected requests do not appear.
    assert matches[0]['medicine_name']==medicine_name
    assert matches[0]['quantity']==2
    assert matches[0]['actor']=='Đề nghị: Thu ngân · Duyệt: Quản lý phòng khám'
    assert matches[0]['occurred_at']=='2099-06-19 09:00:00'
    assert matches[0]['content']==f'{medicine_name}: 2 viên'
    assert 'approved' not in matches[0]['content']
    assert matches[0]['reason']=='Trả thuốc chưa sử dụng'
    workbook=load_workbook(BytesIO(client.get('/api/reports/corrections/export',
        headers=manager,params={'date_from':'2099-06-19','date_to':'2099-06-19'}).content),
        read_only=True)
    export_rows=list(workbook.active.iter_rows(values_only=True))
    assert any('Đề nghị: Thu ngân · Duyệt: Quản lý phòng khám' in row for row in export_rows)
    workbook.close()


def test_imaging_correction_only_after_signature_and_by_signed_day(sample):
    manager=sample['actors']['quanly']
    rid=sample['draft_correction']
    before=client.get('/api/reports/corrections',headers=manager,
                      params={'date_from':'2099-06-19','date_to':'2099-06-19'}).json()
    assert not any(row['type']=='Đính chính hình ảnh' for row in before['rows'])
    with db(True) as c:
        doctor=sample['doctors'][0]
        c.execute("UPDATE imaging_reports SET snapshot='{}' WHERE id=?",(rid,))
        c.execute("""INSERT INTO document_signatures(document_kind,document_id,visit_id,
            signed_by,signed_at,content_hash,image,username)
            VALUES('ultrasound',?,?,?,?,?,?,?)""",
            (rid,sample['visits'][0],doctor,sample['at2'],'a'*64,b'synthetic_signature','bs_noi'))
    first_day=client.get('/api/reports/corrections',headers=manager,
                         params={'date_from':'2099-06-18','date_to':'2099-06-18'}).json()
    assert not any(row['type']=='Đính chính hình ảnh' for row in first_day['rows'])
    signed_day=client.get('/api/reports/corrections',headers=manager,
                          params={'date_from':'2099-06-19','date_to':'2099-06-19'}).json()
    matches=[row for row in signed_day['rows'] if row['type']=='Đính chính hình ảnh']
    assert len(matches)==1
    assert matches[0]['occurred_at']=='2099-06-19 09:00:00'
    assert matches[0]['actor']=='BS Nội'


def test_overdiscount_invoice_409_is_flagged(sample):
    manager = sample['actors']['quanly']
    stamp='2099-08-10T02:00:00+00:00'
    with db(True) as c:
        uid=c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        doctor=sample['doctors'][0]
        c.execute("""INSERT INTO patients(code,full_name,sex,created_at)
            VALUES('S2E-OVER','Giảm vượt phí','Nam',?)""",(stamp,))
        patient=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)",
                  (patient,doctor,uid,stamp))
        vid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,10000,?)",
                  (vid,'Phí đã giảm quá mức',stamp))
        c.execute("""INSERT INTO adjustments(visit_id,kind,amount,reason,status,
            proposed_by,reviewed_by,proposed_at,reviewed_at)
            VALUES(?,'discount',15000,'Thử lỗi nghiệp vụ','approved',?,?,?,?)""",
            (vid,uid,uid,stamp,stamp))
    data=client.get('/api/reports/revenue',headers=manager,
                    params={'month':'2099-08'}).json()
    assert data['totals']['known_due']==0
    assert len(data['unpaid_visits'])==1
    item=data['unpaid_visits'][0]
    assert item['patient_code']=='S2E-OVER'
    assert item['known_due'] is None
    assert item['note']=='Giảm phí vượt phí, cần kiểm tra'
    assert data['warning']=='Có lượt giảm phí vượt phí, số chưa thu chưa đầy đủ'
    workbook=load_workbook(BytesIO(client.get('/api/reports/revenue/export',
        headers=manager,params={'month':'2099-08'}).content),read_only=True)
    assert all(sheet['A2'].value==data['warning'] for sheet in workbook.worksheets)
    workbook.close()


def test_visit_with_unpriced_charge_after_period_still_warns(sample):
    """Period charge count stays zero; invoice sees a later unpriced charge."""
    manager=sample['actors']['quanly']
    out_of_period='2099-07-04T02:00:00+00:00'
    with db(True) as c:
        c.execute("""INSERT INTO charges(visit_id,label,amount,created_at)
            VALUES(?,'Dịch vụ chưa có giá sau kỳ',NULL,?)""",
            (sample['visits'][0],out_of_period))
    june=client.get('/api/reports/revenue',headers=manager,params=params()).json()
    assert june['totals']['unpriced_count']==0
    assert all(row['unpriced_count']==0 for row in june['rows'])
    unpaid=next(row for row in june['unpaid_visits']
                if row['visit_id']==sample['visits'][0])
    assert unpaid['unpriced_count']==1
    assert june['warning']=='Còn khoản chưa nhập giá, doanh thu chưa đầy đủ'
    book=load_workbook(BytesIO(client.get('/api/reports/revenue/export',
        headers=manager,params=params()).content),read_only=True)
    assert all(sheet['A2'].value==june['warning'] for sheet in book.worksheets)
    book.close()


def test_both_unpriced_and_overdiscount_warnings_are_shown(sample):
    """A 409 invoice may also contain a charge with an unknown price."""
    manager=sample['actors']['quanly']
    stamp='2099-08-10T02:00:00+00:00'
    after_period='2099-09-11T02:00:00+00:00'
    with db(True) as c:
        actor=c.execute("SELECT id FROM users WHERE username='quanly'").fetchone()[0]
        c.execute("""INSERT INTO patients(code,full_name,sex,created_at)
            VALUES('S2E-BOTH','Hai loại cảnh báo','Nam',?)""",(stamp,))
        patient=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)",
                  (patient,sample['doctors'][0],actor,stamp))
        visit=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,10000,?)",
                  (visit,'Phí khám',stamp))
        c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,NULL,?)",
                  (visit,'Chưa nhập giá ngoài kỳ',after_period))
        c.execute("""INSERT INTO adjustments(visit_id,kind,amount,reason,status,
            proposed_by,reviewed_by,proposed_at,reviewed_at)
            VALUES(?,'discount',15000,'Lỗi giảm phí','approved',?,?,?,?)""",
            (visit,actor,actor,stamp,stamp))
    result=client.get('/api/reports/revenue',headers=manager,
                      params={'month':'2099-08'}).json()
    assert result['totals']['unpriced_count']==0
    item=next(x for x in result['unpaid_visits'] if x['visit_id']==visit)
    assert item['unpriced_count']==1 and item['known_due'] is None
    assert result['warning']==(
        'Còn khoản chưa nhập giá, doanh thu chưa đầy đủ\n'
        'Có lượt giảm phí vượt phí, số chưa thu chưa đầy đủ')
    book=load_workbook(BytesIO(client.get('/api/reports/revenue/export',
        headers=manager,params={'month':'2099-08'}).content),read_only=True)
    assert all(ws['A2'].value==result['warning'] for ws in book.worksheets)
    book.close()
