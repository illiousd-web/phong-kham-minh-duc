"""C5: chỉ tạo CSDL PostgreSQL MỚI, không có đường ghi vào CSDL có sẵn.

Mật khẩu kết nối nguồn chỉ đọc từ CLINIC_PERF_SOURCE_DATABASE_URL; không dùng
CLINIC_DATABASE_URL của phòng khám. Tên đích phải clinic_perf_test_<12 hex>.
"""
import argparse
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
CONFIRM = 'TAO_DU_LIEU_GIA_C5'
NAME = re.compile(r'clinic_perf_test_[0-9a-f]{12}')
ROLES = ('admin', 'manager', 'reception', 'doctor', 'technician', 'pharmacy', 'cashier', 'nurse')
VN = timezone(timedelta(hours=7))


def validate(source, name, output, confirmation):
    if confirmation != CONFIRM:
        raise ValueError('Phải xác nhận rõ: --xac-nhan ' + CONFIRM)
    if not NAME.fullmatch(name):
        raise ValueError('Chỉ nhận tên clinic_perf_test_ và đúng 12 ký tự hex')
    parts = urlsplit(source)
    if parts.scheme not in ('postgresql', 'postgres') or parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Nguồn PostgreSQL kiểm thử phải ở loopback')
    if parts.path.lstrip('/') == name:
        raise ValueError('Nguồn không được là CSDL đích')
    if parts.path != '/postgres':
        raise ValueError('Nguồn quản trị phải là /postgres; không nhận URL CSDL phòng khám đang dùng')
    output = Path(output).resolve()
    if output.name != name or output.exists():
        raise ValueError('Thư mục đích phải mới, trùng tên CSDL kiểm thử; không ghi đè thư mục có sẵn')
    return output


def generate(source, name, output, confirmation, *, visits=22000, patients=20000, attachments=2000):
    output = validate(source, name, output, confirmation)
    if not 30 <= visits <= 100000 or not 1 <= patients <= visits or not 0 <= attachments <= visits * 4:
        raise ValueError('Quy mô không hợp lệ')
    # Không IF NOT EXISTS, không TRUNCATE, không DROP. CSDL dù trống nhưng đã có
    # cùng tên cũng phải bị PostgreSQL từ chối, trước khi mở kết nối ghi dữ liệu.
    with psycopg.connect(source, autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
    url = urlunsplit(urlsplit(source)._replace(path='/' + name))
    output.mkdir(parents=True, exist_ok=False)
    uploads = output / 'attachments'; uploads.mkdir()
    from app.auth import pw_hash
    from app.database import PGConnection, record_factory
    from app.migrations import migrate_v050
    from app.manual_price_migration import migrate_manual_prices
    credentials = {role: {'id': i, 'username': 'c5_' + role, 'password': secrets.token_urlsafe(24)}
                   for i, role in enumerate(ROLES, 1)}
    ids = {role: value['id'] for role, value in credentials.items()}
    today = datetime.now(VN).date()
    closed = visits - 30
    with psycopg.connect(url, row_factory=record_factory) as c:
        assert c.execute('SELECT current_database()').fetchone()[0] == name
        assert c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0] == 0
        c.execute((ROOT / 'schema.postgresql.sql').read_text(encoding='utf-8'))
        migrate_v050(PGConnection(c), postgres=True)
        migrate_manual_prices(PGConnection(c), postgres=True)
        for role, value in credentials.items():
            salt = secrets.token_hex(16)
            c.execute('INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(%s,%s,%s,%s,%s)',
                      (value['id'], value['username'], 'Nhân viên giả lập C5 ' + role, salt, pw_hash(value['password'], salt)))
            c.execute('INSERT INTO user_roles(user_id,role) VALUES(%s,%s)', (value['id'], role))
        c.execute("INSERT INTO service_catalog(id,code,name,price) VALUES(1,'C5_KHAM','Khám giả lập C5',150000)")
        c.execute("INSERT INTO service_categories VALUES(1,'consultation')")
        for i, category in enumerate(('lab', 'ultrasound', 'xray', 'ecg'), 2):
            c.execute('INSERT INTO service_catalog(id,code,name,price) VALUES(%s,%s,%s,20000)', (i, 'C5_'+category, 'Dịch vụ giả lập C5 '+category))
            c.execute('INSERT INTO service_categories VALUES(%s,%s)', (i, category))
        stamp = datetime.combine(today, datetime.min.time(), VN).replace(hour=8).astimezone(timezone.utc)
        c.execute("""INSERT INTO patients(id,code,full_name,date_of_birth,sex,phone,address,created_at)
            SELECT g,'C5-'||g,'Bệnh nhân giả lập C5 '||g,'1990-01-01','Nữ',
            '09'||lpad(g::text,8,'0'),'Địa chỉ giả lập C5',%s FROM generate_series(1,%s) g""", ((stamp-timedelta(days=731)).isoformat(), patients))
        times = []
        for g in range(1, visits+1):
            age = 0 if g > closed else 1 + (closed-g)*729 // max(1, closed-1)
            times.append((g, 1+(g-1) % patients, ids['doctor'], ids['reception'],
                          'completed' if g <= closed else 'waiting_results',
                          'Khám giả lập C5', 'Mạch 78; HA 120/80', 'Chẩn đoán giả lập C5',
                          (stamp-timedelta(days=age, minutes=-(g % 30)*10)).isoformat(timespec='seconds')))
        with c.cursor() as cur:
            cur.executemany('''INSERT INTO visits(id,patient_id,doctor_id,created_by,status,chief_complaint,vitals,diagnosis,created_at,version)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)''', times)
        c.execute('''INSERT INTO orders(id,visit_id,category,name,status,requested_by,result_text,result_by,approved_by,approved_at,created_at,service_id,proposed_price)
            SELECT (v.id-1)*4+k,v.id,cat.category,cat.name,
            CASE WHEN v.id<=%s THEN 'approved' ELSE 'ordered' END,%s,
            CASE WHEN v.id<=%s THEN 'Kết quả giả lập C5' ELSE '' END,
            CASE WHEN v.id<=%s THEN %s ELSE NULL END,CASE WHEN v.id<=%s THEN %s ELSE NULL END,
            CASE WHEN v.id<=%s THEN v.created_at ELSE NULL END,v.created_at,k+1,20000
            FROM visits v CROSS JOIN generate_series(1,4) k
            JOIN (SELECT s.id,s.name,g.category FROM service_catalog s JOIN service_categories g ON g.service_id=s.id) cat ON cat.id=k+1''',
                  (closed,ids['doctor'],closed,closed,ids['technician'],closed,ids['doctor'],closed))
        c.execute('''INSERT INTO order_authorizations SELECT id,service_id,20000,%s,created_at FROM orders''', (ids['doctor'],))
        c.execute("INSERT INTO charges(id,visit_id,label,amount,created_at) SELECT id,id,'Khám giả lập C5',150000,created_at FROM visits")
        c.execute("INSERT INTO charges(id,visit_id,label,amount,created_at) SELECT %s+id,visit_id,name,20000,created_at FROM orders", (visits,))
        c.execute("INSERT INTO charge_sources SELECT %s+id,'order',id FROM orders", (visits,))
        for mid in range(1,6):
            issued = sum(2 for g in range(1,closed+1) if 1+(g-1)%5 == mid)
            c.execute("INSERT INTO medicines(id,code,name,base_unit) VALUES(%s,%s,%s,'viên')", (mid,'C5_TH'+str(mid),'Thuốc giả lập C5 '+str(mid)))
            c.execute('INSERT INTO medicine_prices VALUES(%s,1000,%s,%s)', (mid,ids['manager'],stamp.isoformat()))
            c.execute("INSERT INTO stock_lots(id,medicine_id,lot_number,expiry_date,quantity) VALUES(%s,%s,%s,%s,%s)",
                      (mid,mid,'C5_LO_'+str(mid),(today+timedelta(days=730)).isoformat(),50000-issued))
            c.execute("INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(%s,'receipt',50000,%s,%s)",
                      (mid,ids['pharmacy'],(stamp-timedelta(days=731)).isoformat()))
        c.execute('''INSERT INTO prescriptions(id,visit_id,doctor_id,drug_lines,instructions,status,created_at)
            SELECT id,id,%s,'Thuốc giả lập C5 | 2 viên | Chỉ dùng kiểm thử','Không dùng điều trị',
            CASE WHEN id<=%s THEN 'dispensed' ELSE 'draft' END,created_at FROM visits''', (ids['doctor'],closed))
        c.execute("INSERT INTO prescription_items(id,prescription_id,medicine_id,quantity,directions,unit_name,unit_factor,unit_quantity) SELECT id,id,1+mod(id-1,5),2,'Chỉ dùng kiểm thử','viên',1,2 FROM visits")
        c.execute('INSERT INTO dispensations SELECT id,id,id,%s,created_at FROM visits WHERE id<=%s', (ids['pharmacy'],closed))
        c.execute('INSERT INTO dispensation_items SELECT id,id,id,1+mod(id-1,5),1+mod(id-1,5),2,1000 FROM visits WHERE id<=%s', (closed,))
        c.execute("INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) SELECT 1+mod(id-1,5),'rx_dispense',2,%s,created_at FROM visits WHERE id<=%s", (ids['pharmacy'],closed))
        c.execute("INSERT INTO charges(id,visit_id,label,amount,created_at) SELECT %s+id,id,'Thuốc giả lập C5',2000,created_at FROM visits WHERE id<=%s", (5*visits,closed))
        c.execute("INSERT INTO charge_sources SELECT %s+id,'dispense_item',id FROM visits WHERE id<=%s", (5*visits,closed))
        c.execute("INSERT INTO charges(id,visit_id,label,amount,created_at) SELECT %s+id,id,'Khoản giả lập chưa có giá',NULL,created_at FROM visits WHERE mod(id,173)=0", (6*visits,))
        c.execute('''INSERT INTO payments(id,visit_id,amount,method,created_by,created_at,idempotency_key,kind)
            SELECT id,id,CASE WHEN mod(id,173)=0 OR mod(id,17)=0 OR id>%s THEN 100000 ELSE 232000 END,
            'cash',%s,created_at,'c5-pay-'||id,CASE WHEN mod(id,173)=0 THEN 'provisional' ELSE 'regular' END
            FROM visits WHERE mod(id,19)<>0''', (closed,ids['cashier']))
        c.execute('INSERT INTO visit_nurses(visit_id,nurse_id,assigned_by,assigned_at) SELECT id,%s,%s,created_at FROM visits', (ids['nurse'],ids['doctor']))
        c.execute('INSERT INTO visit_closures SELECT id,%s,created_at,1 FROM visits WHERE id<=%s', (ids['doctor'],closed))
        c.execute('''INSERT INTO clinical_revisions(id,visit_id,version,snapshot,actor_id,reason,kind,created_at)
            SELECT id,id,1,json_build_object('diagnosis',diagnosis,'vitals',vitals)::text,%s,'Dữ liệu giả lập C5','clinical',created_at FROM visits''', (ids['doctor'],))
        c.execute("INSERT INTO nursing_notes(id,visit_id,nurse_id,content,created_at,request_key) SELECT id,id,%s,'Chăm sóc giả lập C5',created_at,'c5-note-'||id FROM visits", (ids['nurse'],))
        c.execute("INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) SELECT %s,'patient_created','patient',id,'Giả lập C5',created_at FROM patients", (ids['reception'],))
        for event, role, typ in [('visit_created','reception','visit'),
                                  ('nurse_assigned','doctor','visit'),('nurse_vitals_recorded','nurse','visit'),
                                  ('clinical_updated','doctor','visit'),('rx_draft_created','doctor','prescription'),
                                  ('visit_completed','doctor','visit'),('rx_dispensed','pharmacy','prescription')]:
            limit = closed if event in ('visit_completed','rx_dispensed') else visits
            c.execute('INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) SELECT %s,%s,%s,id,\'Giả lập C5\',created_at FROM visits WHERE id<=%s', (ids[role],event,typ,limit))
        for event, role in [('order_created','doctor'),('order_authorized','doctor'),('result_submitted','technician'),('result_approved_demo','doctor')]:
            c.execute("INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) SELECT %s,%s,'order',id,'Giả lập C5',created_at FROM orders WHERE id<=%s", (ids[role],event,4*closed if 'result' in event else 4*visits))
        c.execute("INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) SELECT %s,'payment_recorded_demo','payment',id,'Giả lập C5',created_at FROM payments", (ids['cashier'],))
        from reportlab.pdfgen import canvas
        buffer=BytesIO(); page=canvas.Canvas(buffer);page.drawString(50,780,'DU LIEU GIA LAP C5');page.save()
        body,trailer=buffer.getvalue().rsplit(b'\nstartxref\n',1)
        trailer=b'\nstartxref\n'+trailer
        for oid in range(1,attachments+1):
            key=f'c5-{oid}.pdf'
            # PDF nhỏ 64 KiB, phần đệm là comment có dữ liệu ngẫu nhiên để
            # benchmark backup không hưởng lợi từ 2.000 bản sao nén gần về 0.
            # Chèn comment SAU bảng xref nhưng TRƯỚC startxref/EOF: giữ nguyên
            # offset xref và để EOF cuối tệp, không bắt trình đọc phải sửa PDF.
            header=body+f'\n%C5-{oid}-'.encode()
            remaining=64*1024-len(header)-len(trailer)
            padding=secrets.token_hex((remaining+1)//2).encode()[:remaining]
            (uploads/key).write_bytes(header+padding+trailer)
        c.execute("UPDATE orders SET file_name='Ket_qua_gia_lap_C5.pdf',file_key='c5-'||id||'.pdf' WHERE id<=%s", (attachments,))
        for table in ('users','patients','visits','orders','charges','prescriptions','prescription_items','dispensations','dispensation_items','payments','medicines','stock_lots','clinical_revisions','nursing_notes'):
            c.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'),COALESCE((SELECT MAX(id) FROM {}),1))").format(sql.Identifier(table)), (table,))
        c.execute('ANALYZE')
        counts={table:c.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                for table in ('patients','visits','orders','prescriptions','charges','payments','audit_log')}
        assert counts['visits']==visits and counts['orders']==4*visits and counts['prescriptions']==visits
    manifest={'synthetic_only':True,'database_name':name,'counts':counts,'attachments':attachments,
              'attachment_bytes':sum(p.stat().st_size for p in uploads.iterdir()),'today':today.isoformat(),
              'oldest_day':(today-timedelta(days=730)).isoformat(),'active_visits':30,
              'doctor_visit':visits,'prescription':visits,'patient_query':'C5-'+str(patients),
              'roles':{role:value['id'] for role,value in credentials.items()}}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    private=output/'credentials.json';private.write_text(json.dumps(credentials),encoding='utf-8');private.chmod(0o600)
    return manifest


def main():
    parser=argparse.ArgumentParser(description='Tạo CSDL MỚI chỉ có dữ liệu giả lập C5; luôn từ chối CSDL có sẵn')
    parser.add_argument('--ten-csdl',required=True)
    parser.add_argument('--thu-muc',type=Path,required=True)
    parser.add_argument('--xac-nhan',required=True)
    args=parser.parse_args()
    try:
        result=generate(os.environ.get('CLINIC_PERF_SOURCE_DATABASE_URL',''),args.ten_csdl,args.thu_muc,args.xac_nhan)
    except (ValueError,psycopg.Error) as error:
        # Không in URL/mật khẩu hoặc dữ liệu máy chủ từ exception kết nối.
        print('KHÔNG TẠO: '+(str(error) if isinstance(error,ValueError) else type(error).__name__))
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
