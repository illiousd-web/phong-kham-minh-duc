"""Full C5 cohort plus 12,500 synthetic ICD codes; same SQL as the API."""
import hashlib,secrets,time
from urllib.parse import urlsplit,urlunsplit
import psycopg
from psycopg import sql
from .conftest import SOURCE
from app.database import PGConnection,record_factory
from scripts.tao_du_lieu_gia import generate,CONFIRM

def test_d0_main_upgrade_full_c5_and_icd_search_p95(tmp_path):
    from app.m0_migration import migrate_m0
    from app.administrative_migration import migrate_administrative
    from app.patient_catalog import migrate_public_catalog
    from app.m6_migration import migrate_m6
    from app.m5_migration import migrate_m5
    from app.d0 import search_catalog
    from app.manager_visits import fold_name
    name='clinic_perf_test_'+secrets.token_hex(6);source=urlunsplit(urlsplit(SOURCE)._replace(path='/postgres'));url=urlunsplit(urlsplit(SOURCE)._replace(path='/'+name))
    try:
        generate(source,name,tmp_path/name,CONFIRM,attachments=0)
        with psycopg.connect(url,row_factory=record_factory) as con:
            c=PGConnection(con)
            for fn in (migrate_m0,migrate_administrative,migrate_public_catalog):fn(c)
            migrate_m6(c,postgres=True);migrate_m5(c,postgres=True)
            # Main schema 9. Compare every original column, not only row counts.
            tables=['patients','visits','lab_tests','service_catalog','charges','payments','stock_lots','orders']
            columns={t:[r['column_name'] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position",(t,))] for t in tables}
            def fingerprint():
                result={}
                for table in tables:
                    h=hashlib.sha256()
                    for r in con.execute(sql.SQL('SELECT {} FROM {} ORDER BY id').format(sql.SQL(',').join(map(sql.Identifier,columns[table])),sql.Identifier(table))):h.update(repr(list(r.values())).encode())
                    result[table]=h.hexdigest()
                return result
            from scripts.do_hieu_nang import migrate_profile_schema
            before=fingerprint();migrate_profile_schema(c);assert fingerprint()==before
            assert c.execute("SELECT 1 FROM schema_migrations WHERE version=10").fetchone()
            assert con.execute('SELECT COUNT(*) FROM visits').fetchone()[0]==22000
            c.execute("INSERT INTO catalog_imports(kind,document_number,document_date,source,version,fingerprint,mapping,created_at) VALUES('icd10','GIẢ LẬP','2026-01-01','C5 giả lập','fake','fake','{}','2026-01-01')")
            iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            # Fixture generation is intentionally synthetic, never a medical code list.
            with con.cursor() as cur:
                cur.executemany('INSERT INTO icd10(code,name_vi,search_key,version,import_id) VALUES(%s,%s,%s,%s,%s)',[(f'FAKE{i:05d}','Bệnh mô phỏng '+str(i),fold_name(f'FAKE{i:05d} Bệnh mô phỏng '+str(i)),'fake',iid) for i in range(12500)])
            con.execute('ANALYZE');samples=[]
            for i in range(40):
                start=time.perf_counter();found=search_catalog(c,'icd10','benh mo phong',20,20);samples.append(time.perf_counter()-start)
                assert found['total']==12500 and len(found['items'])==20
            p95=sorted(samples)[37];print('D0 C5 22000 lượt / 12500 mã, p95 giây:',p95);assert p95<.3,p95
    finally:
        with psycopg.connect(SOURCE,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
