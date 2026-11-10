"""Quản lý → Lượt khám ở quy mô lớn trên PostgreSQL thật: 22.000 lượt, 20.000 bệnh nhân.

- Tìm theo khoảng 1 năm có lọc tình trạng tiền: mỗi lần ≤ 1 giây, kết quả đúng.
- Tìm theo tên (chuẩn hóa trong Python) với 20.000 bệnh nhân: mỗi lần ≤ 300 ms, kể cả lần đầu.
Không thêm chỉ mục, không đổi CSDL. Chỉ dữ liệu giả lập.
"""
import secrets
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from .conftest import SOURCE

ROOT = Path(__file__).resolve().parents[1]
VISITS, PATIENTS = 22_000, 20_000
TODAY = date(2026, 11, 9)
YEAR = {'date_from': '10/11/2025', 'date_to': '09/11/2026'}
HO = ['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Đặng', 'Bùi', 'Đỗ', 'Vũ', 'Hồ']
DEM = ['Văn', 'Thị', 'Hữu', 'Đức', 'Ngọc', 'Thu', 'Minh', 'Quốc']
TEN = ['An', 'Bích', 'Cường', 'Dũng', 'Đạt', 'Hằng', 'Hương', 'Khánh', 'Lâm', 'Mỹ', 'Nghĩa', 'Oanh', 'Phúc', 'Quỳnh', 'Sơn', 'Thảo', 'Uyên', 'Vượng', 'Xuân', 'Yến']


def test_search_with_22000_visits_and_20000_patients_is_fast_and_exact():
    from app.database import PGConnection, record_factory
    from app.migrations import migrate_v050
    from app.manual_price_migration import migrate_manual_prices
    from app import manager_visits as mv
    name = 'clinic_scale_' + secrets.token_hex(5)
    with psycopg.connect(SOURCE, autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    url = urlunsplit(urlsplit(SOURCE)._replace(path='/' + name))
    timings = {}
    try:
        with psycopg.connect(url, row_factory=record_factory) as con:
            con.execute((ROOT / 'schema.postgresql.sql').read_text(encoding='utf-8'))
            migrate_v050(PGConnection(con), postgres=True)
            migrate_manual_prices(PGConnection(con), postgres=True)
            old = '2025-01-01T03:00:00+00:00'
            con.execute("INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(1,'gia_lap','Nhân viên giả lập','00','x')")
            with con.cursor() as cur:
                cur.executemany("INSERT INTO patients(id,code,full_name,sex,phone,created_at) VALUES(%s,%s,%s,'Nữ',%s,%s)",
                                [(i, f'MD{i:06d}', f'{HO[i % 10]} {DEM[(i // 10) % 8]} {TEN[(i // 80) % 20]} {i}', f'09{i:08d}', old)
                                 for i in range(1, PATIENTS)])
            con.execute("INSERT INTO patients(id,code,full_name,sex,phone,created_at) VALUES(%s,%s,'Đặng Thị Thu Bích','Nữ','0911111111',%s)",
                        (PATIENTS, f'MD{PATIENTS:06d}', old))
            # 22.000 lượt rải đều 365 ngày gần nhất; lượt g của bệnh nhân 1+(g mod 20.000).
            con.execute('''INSERT INTO visits(patient_id,doctor_id,created_by,created_at)
                SELECT 1+(g %% %s),1,1,to_char(timestamp '2026-11-09 03:00:00'-(g %% 365)*interval '1 day','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00'
                FROM generate_series(1,%s) g''', (PATIENTS, VISITS))
            # Mỗi lượt 3 khoản; lượt chia hết cho 1000 có thêm một khoản chưa có giá.
            con.execute('''INSERT INTO charges(visit_id,label,amount,created_at)
                SELECT v.id,'Khoản giả lập '||k,50000,%s FROM visits v CROSS JOIN generate_series(1,3) k''', (old,))
            con.execute("INSERT INTO charges(visit_id,label,amount,created_at) SELECT id,'Thủ thuật chưa giá',NULL,%s FROM visits WHERE id %% 1000=0", (old,))
            # Thu đủ mọi lượt, trừ: lượt chia hết cho 500 (còn nợ), lượt chia hết cho 700 (thu thừa).
            con.execute('''INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                SELECT id,CASE WHEN id %% 700=0 THEN 160000 ELSE 150000 END,'cash',1,%s,'scale-'||id
                FROM visits WHERE id %% 500<>0''', (old,))
            con.execute('ANALYZE')
            assert not con.execute("SELECT 1 FROM pg_indexes WHERE tablename='visits' AND indexdef LIKE '%%created_at%%'").fetchone()
            c = PGConnection(con)

            def timed(label, **kw):
                started = time.perf_counter()
                result = mv.search_visits(c, today=TODAY, **kw)
                timings[label] = time.perf_counter() - started
                return result

            unpriced = {v for v in range(1000, VISITS + 1, 1000)}
            owing = {v for v in range(500, VISITS + 1, 500)} - unpriced
            refund = {v for v in range(700, VISITS + 1, 700) if v % 500}
            expected = {'owing': owing, 'unpriced': unpriced, 'refund': refund}
            # Mục 4: khoảng 1 năm + lọc tình trạng tiền, không làm nóng trước.
            for money, ids in expected.items():
                found = timed('1 năm, ' + money, money=money, **YEAR)
                assert {x['visit_id'] for x in found['items']} == ids and found['total'] == len(ids), money
                assert all(x['money_status'] == money for x in found['items'])
            settled = timed('1 năm, settled', money='settled', **YEAR)
            assert settled['total'] == VISITS - len(owing | unpriced | refund) and len(settled['items']) == 50
            everything = timed('1 năm, không lọc tiền', **YEAR)
            assert everything['total'] == VISITS and everything['items'][0]['visit_id'] == VISITS
            last_page = timed('1 năm, settled, trang cuối', money='settled', page_no=settled['pages'], **YEAR)
            assert 0 < len(last_page['items']) <= 50 and last_page['total'] == settled['total']
            beyond = timed('1 năm, settled, quá trang cuối', money='settled', page_no=settled['pages'] + 1, **YEAR)
            assert beyond['items'] == [] and beyond['total'] == settled['total']

            # Mục 2: tìm tên với 20.000 bệnh nhân; lần đầu (chưa có gì trong bộ nhớ đệm chuẩn hóa) cũng phải đạt.
            mv.fold_name.cache_clear()
            by_family = timed('tên "dang" (lần đầu)', q='dang', **YEAR)
            family_patients = {i for i in range(1, PATIENTS) if i % 10 == 5} | {PATIENTS}
            assert by_family['total'] == sum(1 for g in range(1, VISITS + 1) if 1 + g % PATIENTS in family_patients)
            for q in ('đặng', 'ĐẶNG'):
                assert timed(f'tên "{q}"', q=q, **YEAR)['total'] == by_family['total']
            for q in ('Đặng Thị Thu Bích', 'dang thi thu bich', 'ĐẶNG THỊ THU BÍCH'):
                one = timed(f'tên "{q}"', q=q, **YEAR)
                assert one['total'] >= 1 and {x['patient_name'] for x in one['items']} == {'Đặng Thị Thu Bích'}, q
            assert timed('tên "hằng"', q='hằng', **YEAR)['total'] == timed('tên "HANG"', q='HANG', **YEAR)['total'] > 0
            assert timed('tên "Đạt"', q='Đạt', **YEAR)['total'] == timed('tên "dat"', q='dat', **YEAR)['total'] > 0
            timed('tên "dang", 7 ngày mặc định', q='dang')
        for label, seconds in timings.items():
            print(f'{label}: {seconds * 1000:.0f} ms')
        for label, seconds in timings.items():
            limit = 0.3 if label.startswith('tên') else 1.0
            assert seconds <= limit, f'{label}: {seconds:.3f} giây (giới hạn {limit} giây)'
    finally:
        with psycopg.connect(SOURCE, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
