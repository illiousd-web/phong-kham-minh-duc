"""Hàng chờ thu ngân với 22.000 lượt trên PostgreSQL thật: đủ nhanh, không bỏ sót lượt cũ còn nợ."""
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from .conftest import SOURCE

ROOT = Path(__file__).resolve().parents[1]
VISITS = 22_000


def test_dues_query_with_22000_visits_is_fast_and_complete():
    from app.database import PGConnection, record_factory
    from app.migrations import migrate_v050
    from app.manual_price_migration import migrate_manual_prices
    from app.main import dues_rows
    name = 'clinic_scale_' + secrets.token_hex(5)
    with psycopg.connect(SOURCE, autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    url = urlunsplit(urlsplit(SOURCE)._replace(path='/' + name))
    try:
        with psycopg.connect(url, row_factory=record_factory) as con:
            con.execute((ROOT / 'schema.postgresql.sql').read_text(encoding='utf-8'))
            migrate_v050(PGConnection(con), postgres=True)
            migrate_manual_prices(PGConnection(con), postgres=True)
            old, today = '2025-01-01T03:00:00+00:00', '2026-11-09T03:00:00+00:00'
            con.execute("INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(1,'gia_lap','Nhân viên giả lập','00','x')")
            con.execute("INSERT INTO patients(full_name,sex,created_at) SELECT 'Người bệnh giả lập '||g,'Nữ',%s FROM generate_series(1,2000) g", (old,))
            con.execute('''INSERT INTO visits(patient_id,doctor_id,created_by,created_at)
                           SELECT 1+(g %% 2000),1,1,%s FROM generate_series(1,%s) g''', (old, VISITS))
            # Mỗi lượt 3 khoản; lượt chia hết cho 1000 có thêm một khoản chưa có giá.
            con.execute('''INSERT INTO charges(visit_id,label,amount,created_at)
                           SELECT v.id,'Khoản giả lập '||k,50000,%s FROM visits v CROSS JOIN generate_series(1,3) k''', (old,))
            con.execute("INSERT INTO charges(visit_id,label,amount,created_at) SELECT id,'Thủ thuật chưa giá',NULL,%s FROM visits WHERE id %% 1000=0", (old,))
            # Thu đủ mọi lượt, trừ: lượt chia hết cho 500 (còn nợ), lượt chia hết cho 700 (thu thừa).
            con.execute('''INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                           SELECT id,CASE WHEN id %% 700=0 THEN 160000 ELSE 150000 END,'cash',1,%s,'scale-'||id
                           FROM visits WHERE id %% 500<>0''', (old,))
            con.execute('UPDATE visits SET created_at=%s WHERE id>%s', (today, VISITS - 5))
            con.execute('ANALYZE')
            c = PGConnection(con)
            dues_rows(c, '2026-11-09T00:00:00+00:00')  # làm nóng bộ nhớ đệm
            started = time.perf_counter()
            rows = dues_rows(c, '2026-11-09T00:00:00+00:00')
            elapsed = time.perf_counter() - started
        ids = {r['visit_id'] for r in rows}
        owing = {v for v in range(500, VISITS + 1, 500)}
        overpaid = {v for v in range(700, VISITS + 1, 700) if v % 500}
        unpriced = {v for v in range(1000, VISITS + 1, 1000)}
        today_ids = set(range(VISITS - 4, VISITS + 1))
        assert ids == owing | overpaid | unpriced | today_ids
        assert min(owing) == 500 and 500 in ids  # lượt cũ hơn 21.000 lượt vẫn hiện
        print(f'dues_rows: {elapsed:.3f} giây, {len(rows)} lượt')
        assert elapsed < 2.0, f'Truy vấn hàng chờ thu ngân mất {elapsed:.2f} giây với {VISITS} lượt'
    finally:
        with psycopg.connect(SOURCE, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
