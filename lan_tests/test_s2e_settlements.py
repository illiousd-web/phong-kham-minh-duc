"""Financial settlement with PostgreSQL transactions and migration 19 to 20."""
import psycopg
import pytest

from app import database, s2e_settlement_migration
from tests.test_s2e_settlements import (
    REASON, REOPEN, snapshot,
    test_closed_visit_blocks_all_financial_writes as test_closed_visit_blocks_all_financial_writes,
    test_reopen_restores_queue_and_allows_new_payment_and_a_second_closure as test_reopen_restores_queue_and_allows_new_payment_and_a_second_closure,
    test_settle_records_an_immutable_invoice_and_rejects_concurrent_duplicate as test_settle_records_an_immutable_invoice_and_rejects_concurrent_duplicate,
    test_settlement_preconditions as test_settlement_preconditions,
    test_waiver_is_reported_without_becoming_payment as test_waiver_is_reported_without_becoming_payment,
    test_waiver_requires_admin_and_an_independent_approver as test_waiver_requires_admin_and_an_independent_approver,
)
from .test_ui_settings_backup import _new_db, _drop


def test_postgres_upgrade_19_to_20_preserves_existing_data(monkeypatch):
    name, url = _new_db()
    migrate = s2e_settlement_migration.migrate_settlements
    try:
        monkeypatch.setattr(database, 'DATABASE_URL', url)
        monkeypatch.setattr(s2e_settlement_migration, 'migrate_settlements', lambda c, postgres: None)
        database.migrate()
        monkeypatch.setattr(s2e_settlement_migration, 'migrate_settlements', migrate)
        with psycopg.connect(url, row_factory=database.record_factory) as c:
            assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 19
            c.execute("INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(1,'gia_lap','Nhân viên giả lập','00','x')")
            c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES('VA19','Người bệnh giả lập','Nam','2026-01-01')")
            c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at,status) VALUES(1,1,1,'2026-01-01','completed')")
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(1,'Khám',1000,'2026-01-01')")
            c.execute("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                         VALUES(1,700,'cash',1,'2026-01-01','v19-payment')""")
            before = snapshot(c)
        database.migrate()
        database.migrate()
        with psycopg.connect(url, row_factory=database.record_factory) as c:
            assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 20
            assert snapshot(c) == before
            assert not c.execute('SELECT * FROM visit_settlements').fetchall()
            c.execute("""INSERT INTO visit_settlements(visit_id,actor_id,created_at,charged,paid,due,refund_due,kind,waived_amount,reason,approved_by)
                         VALUES(1,1,'2026-01-02',1000,700,300,0,'mien_thu',300,%s,1)""", (REASON,))
            with pytest.raises(psycopg.errors.UniqueViolation), c.transaction():
                c.execute('''INSERT INTO visit_settlements(visit_id,actor_id,created_at,charged,paid,due,refund_due,kind)
                             VALUES(1,1,'2026-01-02',1000,1000,0,0,'du_thu')''')
            c.execute("INSERT INTO visit_settlement_reopens VALUES(1,1,1,'2026-01-03',%s)", (REOPEN,))
            for statement in (
                "UPDATE visit_settlements SET waived_amount=500",
                "DELETE FROM visit_settlements",
                "UPDATE visit_settlement_reopens SET reason='Lý do khác'",
                "DELETE FROM visit_settlement_reopens",
                "TRUNCATE visit_settlements, visit_settlement_reopens",
            ):
                with pytest.raises(psycopg.errors.RaiseException, match='lịch sử kết thúc lượt'), c.transaction():
                    c.execute(statement)
    finally:
        _drop(name)
