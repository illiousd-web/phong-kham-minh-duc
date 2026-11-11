"""Run L1/L2 over a populated C5 schema, then open and print legacy records."""
import io
import secrets
from urllib.parse import urlsplit,urlunsplit

import psycopg
from psycopg import sql
from docx import Document

from .conftest import SOURCE
from app.database import PGConnection, record_factory
from app.administrative_migration import migrate_administrative
from app.m0_migration import migrate_m0
from app.patient_catalog import migrate_public_catalog
from scripts.tao_du_lieu_gia import generate, CONFIRM


def test_l12_migration_on_populated_c5_preserves_legacy_data_and_prints(tmp_path):
    name='clinic_perf_test_'+secrets.token_hex(6)
    source=urlunsplit(urlsplit(SOURCE)._replace(path='/postgres'))
    url=urlunsplit(urlsplit(SOURCE)._replace(path='/'+name))
    try:
        generate(source,name,tmp_path/name,CONFIRM,visits=60,patients=45,attachments=0)
        with psycopg.connect(url,row_factory=record_factory) as con:
            # Record old columns, not a reduced projection, before the additive migration.
            tables=('patients','visits','users','payments','charges','prescriptions','orders','clinical_revisions')
            before={}
            for table in tables:
                cursor=con.execute('SELECT * FROM '+table+' ORDER BY id')
                before[table]=([col.name for col in cursor.description],cursor.fetchall())
            c=PGConnection(con)
            migrate_m0(c);migrate_administrative(c);migrate_public_catalog(c);migrate_public_catalog(c)
            for table,(columns,rows) in before.items():
                query=sql.SQL('SELECT {} FROM {} ORDER BY id').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table))
                assert con.execute(query).fetchall()==rows
            assert con.execute('SELECT COUNT(*) FROM patients WHERE document_number IS NOT NULL').fetchone()[0]==0
            from app.main import form_context
            from app.forms import generate_docx, generate_pdf
            ctx=form_context(c,'visit',1)
            doc=Document(io.BytesIO(generate_docx('visit',ctx)))
            text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(cell.text for t in doc.tables for row in t.rows for cell in row.cells)
            assert ctx['patient']['full_name'] in text
            assert ctx['doctor_name'] in text
            import pymupdf
            with pymupdf.open(stream=generate_pdf('visit',ctx),filetype='pdf') as pdf:
                assert ctx['patient']['full_name'] in ''.join(page.get_text() for page in pdf)
    finally:
        with psycopg.connect(SOURCE,autocommit=True) as con:
            con.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
