"""Financial settlement with PostgreSQL transactions and migration 19 to 20."""
from contextlib import ExitStack
import secrets

import psycopg
import pytest
from psycopg import sql

from app import database, s2e_settlement_migration, stock_request_key_migration
from tests.test_s2e_settlements import (
    REASON, REOPEN, snapshot,
    test_fully_paid_waiver_rejected_and_not_reported as test_fully_paid_waiver_rejected_and_not_reported,
    test_waiver_with_fifty_thousand_due as test_waiver_with_fifty_thousand_due,
    test_fully_paid_pending_refund_blocks_closure as test_fully_paid_pending_refund_blocks_closure,
    test_each_pending_request_blocks_closure as test_each_pending_request_blocks_closure,
    test_concurrent_request_and_closure_cannot_both_succeed as test_concurrent_request_and_closure_cannot_both_succeed,
    test_resolved_request_allows_closure as test_resolved_request_allows_closure,
    test_closed_visit_blocks_all_financial_writes as test_closed_visit_blocks_all_financial_writes,
    test_overview_excludes_active_waiver_and_restores_outstanding_after_reopen as test_overview_excludes_active_waiver_and_restores_outstanding_after_reopen,
    test_reopen_restores_queue_and_allows_new_payment_and_a_second_closure as test_reopen_restores_queue_and_allows_new_payment_and_a_second_closure,
    test_settle_records_an_immutable_invoice_and_rejects_concurrent_duplicate as test_settle_records_an_immutable_invoice_and_rejects_concurrent_duplicate,
    test_settlement_preconditions as test_settlement_preconditions,
    test_waiver_is_reported_without_becoming_payment as test_waiver_is_reported_without_becoming_payment,
    test_waiver_requires_admin_and_an_independent_approver as test_waiver_requires_admin_and_an_independent_approver,
)
from .conftest import URL
from .test_ui_settings_backup import _new_db, _drop


def test_postgres_upgrade_19_to_20_preserves_existing_data(monkeypatch):
    name, url = _new_db()
    migrate = s2e_settlement_migration.migrate_settlements
    stock_keys = stock_request_key_migration.migrate_stock_request_keys
    try:
        monkeypatch.setattr(database, 'DATABASE_URL', url)
        monkeypatch.setattr(s2e_settlement_migration, 'migrate_settlements', lambda c, postgres: None)
        # Bản v19 thật chưa có migration 021 (mã thao tác phiếu kho, T4).
        monkeypatch.setattr(stock_request_key_migration, 'migrate_stock_request_keys', lambda c, postgres: None)
        database.migrate()
        monkeypatch.setattr(s2e_settlement_migration, 'migrate_settlements', migrate)
        monkeypatch.setattr(stock_request_key_migration, 'migrate_stock_request_keys', stock_keys)
        with psycopg.connect(url, row_factory=database.record_factory) as c:
            assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 19
            c.execute("INSERT INTO users(id,username,full_name,salt,password_hash) VALUES(1,'gia_lap','Nhân viên giả lập','00','x')")
            c.execute("INSERT INTO patients(code,full_name,sex,created_at) VALUES('VA19','Người bệnh giả lập','Nam','2026-01-01')")
            c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at,status) VALUES(1,1,1,'2026-01-01','completed')")
            c.execute("INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(1,1,1,'2026-01-01')")
            c.execute("INSERT INTO charges(visit_id,label,amount,created_at) VALUES(1,'Khám',1000,'2026-01-01')")
            c.execute("""INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key)
                         VALUES(1,700,'cash',1,'2026-01-01','v19-payment')""")
            before = snapshot(c)
        database.migrate()
        database.migrate()
        with psycopg.connect(url, row_factory=database.record_factory) as c:
            assert c.execute('SELECT 1 FROM schema_migrations WHERE version=20').fetchone()
            assert c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 21
            assert snapshot(c) == before
            assert not c.execute('SELECT * FROM visit_settlements').fetchall()
            assert [row[0] for row in c.execute('SELECT visit_id FROM legacy_completed_visits')] == [1]
            for statement in (
                'INSERT INTO legacy_completed_visits VALUES(2)',
                'UPDATE legacy_completed_visits SET visit_id=2',
                'DELETE FROM legacy_completed_visits',
                'TRUNCATE legacy_completed_visits',
            ):
                with pytest.raises(psycopg.errors.RaiseException), c.transaction():
                    c.execute(statement)
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


def test_postgres_settlement_acl_before_and_after_backup_restore(tmp_path, monkeypatch):
    from scripts import backup_lan, install_db

    # grant() substitutes the configured runtime role for clinic_app. Use a
    # disposable role so the test never changes a role shared by other databases.
    runtime = 's2e_runtime_' + secrets.token_hex(6)
    role = sql.Identifier(runtime)
    with psycopg.connect(URL, autocommit=True) as admin, ExitStack() as cleanup:
        admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(role))
        cleanup.callback(admin.execute, sql.SQL('DROP ROLE {}').format(role))
        source_name, source = _new_db()
        cleanup.callback(_drop, source_name)
        target_name, target = _new_db()
        cleanup.callback(_drop, target_name)

        monkeypatch.setattr(database, 'DATABASE_URL', source)
        monkeypatch.setattr(backup_lan, 'DATABASE_URL', source)
        monkeypatch.setenv('CLINIC_UPLOAD_DIR', str(tmp_path/'source-files'))
        database.migrate()
        with psycopg.connect(source) as c:
            assert not c.execute(
                "SELECT has_function_privilege(%s, 'public.visit_settlement_immutable()', 'EXECUTE')",
                (runtime,)).fetchone()[0]

        install_db.grant(source, runtime, source_name)
        assert_settlement_runtime_acl(source, role)

        key = tmp_path/'backup.key'
        key.write_bytes(secrets.token_bytes(32))
        backup = backup_lan.backup(tmp_path/'backups', key)
        backup_lan.restore(backup, key, target, tmp_path/'restored-files')
        # Same restore-then-grant sequence as the Windows rollback path.
        install_db.grant(target, runtime, target_name)
        assert_settlement_runtime_acl(target, role)


def assert_settlement_runtime_acl(url, role):
    statements = (
        ('UPDATE visit_settlements SET waived_amount=500', 'visit_settlements'),
        ('DELETE FROM visit_settlements', 'visit_settlements'),
        ('TRUNCATE visit_settlements', 'visit_settlements'),
        ('UPDATE active_visit_settlements SET waived_amount=500', 'active_visit_settlements'),
        ('DELETE FROM active_visit_settlements', 'active_visit_settlements'),
        ('INSERT INTO active_visit_settlements(visit_id) VALUES(2)', 'active_visit_settlements'),
        ("UPDATE visit_settlement_reopens SET reason='Lý do khác'", 'visit_settlement_reopens'),
        ('DELETE FROM visit_settlement_reopens', 'visit_settlement_reopens'),
        ('TRUNCATE visit_settlement_reopens', 'visit_settlement_reopens'),
        ('INSERT INTO legacy_completed_visits VALUES(2)', 'legacy_completed_visits'),
        ('UPDATE legacy_completed_visits SET visit_id=2', 'legacy_completed_visits'),
        ('DELETE FROM legacy_completed_visits', 'legacy_completed_visits'),
        ('TRUNCATE legacy_completed_visits', 'legacy_completed_visits'),
    )
    with psycopg.connect(url) as c:
        c.execute(sql.SQL('SET ROLE {}').format(role))
        assert c.execute('SELECT id FROM active_visit_settlements').fetchall() == []
        assert not c.execute(
            "SELECT has_function_privilege('public.visit_settlement_immutable()', 'EXECUTE')").fetchone()[0]
        for statement, table in statements:
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied, c.transaction():
                c.execute(statement)
            assert denied.value.sqlstate == '42501'
            assert table in denied.value.diag.message_primary
