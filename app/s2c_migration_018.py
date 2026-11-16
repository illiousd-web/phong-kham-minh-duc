"""Scope signature invalidation to documents and protect signature evidence."""
from .s2c_migration import CHANGES, update_condition

SCOPED = ('orders', 'prescriptions', 'clinical_prescriptions', 'clinical_prescription_items', 'lab_reports', 'lab_results')
COLUMNS = ('id', 'document_kind', 'document_id', 'visit_id', 'signed_by', 'signed_at', 'content_hash', 'image', 'username')


def predicate(table, row):
    if table == 'orders':
        return f"((document_kind='order' AND visit_id={row}.visit_id) OR (document_kind='lab' AND document_id={row}.id) OR (document_kind='lab_report' AND document_id IN (SELECT id FROM lab_reports WHERE order_id={row}.id)))"
    if table == 'prescriptions':
        return f"(document_kind='rx' AND document_id={row}.id)"
    if table == 'clinical_prescriptions':
        return f"(document_kind='clinical_rx' AND document_id={row}.id)"
    if table == 'clinical_prescription_items':
        return f"(document_kind='clinical_rx' AND document_id={row}.prescription_id)"
    if table == 'lab_reports':
        return f"((document_kind='lab_report' AND document_id={row}.id) OR (document_kind='lab' AND document_id={row}.order_id))"
    return f"((document_kind='lab_report' AND document_id={row}.report_id) OR (document_kind='lab' AND document_id IN (SELECT order_id FROM lab_reports WHERE id={row}.report_id)))"


def replace_triggers(c, postgres, scoped):
    for table in SCOPED:
        events, key = CHANGES[table]
        for event in events.split(' OR '):
            row = 'NEW' if event == 'INSERT' else 'OLD'
            name = f's2c_{table}_{event.lower()}'
            c.execute(f'DROP TRIGGER {name}'+(f' ON {table}' if postgres else ''))
            if postgres:
                c.execute(f'DROP FUNCTION {name}()')
            if scoped:
                where = predicate(table, row)
                if event == 'UPDATE':
                    where = '('+where+' OR '+predicate(table, 'NEW')+')'
            else:
                expr = key.format(row=row) if key.startswith('(') else row+'.'+key
                where = 'visit_id IN '+expr if expr.startswith('(') else 'visit_id='+expr
            update = 'UPDATE document_signatures SET invalidated=1 WHERE invalidated=0 AND '+where+';'
            condition = update_condition(table, postgres) if event == 'UPDATE' else ''
            if postgres:
                c.connection.execute(f'CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {update} RETURN {row}; END $$;')
                c.execute(f'CREATE TRIGGER {name} AFTER {event} ON {table} FOR EACH ROW{condition} EXECUTE FUNCTION {name}()')
            else:
                c.execute(f'CREATE TRIGGER {name} AFTER {event} ON {table}{condition} BEGIN {update} END')


def migrate_018(c, postgres=False, *, down=False):
    applied = bool(c.execute('SELECT 1 FROM schema_migrations WHERE version=18').fetchone())
    if applied == (not down):
        return
    if down:
        if c.execute('SELECT 1 FROM document_signatures LIMIT 1').fetchone():
            raise ValueError('Chưa quay lui S2c 018: đã có bản ký; khôi phục bản sao lưu trước nâng cấp để giữ lịch sử ký.')
        c.execute('DROP TRIGGER s2c_users_update'+(' ON users' if postgres else ''))
        if postgres:
            c.execute('DROP FUNCTION s2c_users_update()')
        for event in ('update', 'invalidated', 'delete'):
            c.execute('DROP TRIGGER s2c_signature_guard_'+event+(' ON document_signatures' if postgres else ''))
        if postgres:
            c.execute('DROP FUNCTION s2c_signature_guard()')
        replace_triggers(c, postgres, False)
        c.execute('DELETE FROM schema_migrations WHERE version=18')
        return
    replace_triggers(c, postgres, True)
    different = 'IS DISTINCT FROM' if postgres else 'IS NOT'
    condition = ' OR '.join('OLD.'+key+' '+different+' NEW.'+key for key in ('printed_name', 'printed_title', 'full_name'))
    if postgres:
        c.connection.execute("CREATE FUNCTION s2c_users_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE document_signatures SET invalidated=1 WHERE invalidated=0; RETURN NEW; END $$;")
        c.execute('CREATE TRIGGER s2c_users_update AFTER UPDATE ON users FOR EACH ROW WHEN ('+condition+') EXECUTE FUNCTION s2c_users_update()')
    else:
        c.execute('CREATE TRIGGER s2c_users_update AFTER UPDATE ON users WHEN ('+condition+') BEGIN UPDATE document_signatures SET invalidated=1 WHERE invalidated=0; END')
    columns = ', '.join(COLUMNS)
    if postgres:
        c.connection.execute("""CREATE FUNCTION s2c_signature_guard() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'Không thể sửa hoặc xóa bản ký'; END $$;""")
        c.execute(f'CREATE TRIGGER s2c_signature_guard_update BEFORE UPDATE OF {columns} ON document_signatures FOR EACH ROW EXECUTE FUNCTION s2c_signature_guard()')
        c.execute('CREATE TRIGGER s2c_signature_guard_invalidated BEFORE UPDATE OF invalidated ON document_signatures FOR EACH ROW WHEN (OLD.invalidated=1 AND NEW.invalidated=0) EXECUTE FUNCTION s2c_signature_guard()')
        c.execute('CREATE TRIGGER s2c_signature_guard_delete BEFORE DELETE ON document_signatures FOR EACH ROW EXECUTE FUNCTION s2c_signature_guard()')
    else:
        c.execute(f"CREATE TRIGGER s2c_signature_guard_update BEFORE UPDATE OF {columns} ON document_signatures BEGIN SELECT RAISE(ABORT,'Không thể sửa bản ký'); END")
        c.execute("CREATE TRIGGER s2c_signature_guard_invalidated BEFORE UPDATE OF invalidated ON document_signatures WHEN OLD.invalidated=1 AND NEW.invalidated=0 BEGIN SELECT RAISE(ABORT,'Không thể khôi phục bản ký'); END")
        c.execute("CREATE TRIGGER s2c_signature_guard_delete BEFORE DELETE ON document_signatures BEGIN SELECT RAISE(ABORT,'Không thể xóa bản ký'); END")
    c.execute('INSERT INTO schema_migrations(version) VALUES(18)')
