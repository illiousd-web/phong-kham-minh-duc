-- Run as schema owner after migration. Create clinic_app LOGIN with a unique
-- password interactively using psql \password clinic_app (never put it in Git).
-- Assumes database minhduc and runtime role clinic_app already exist.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE minhduc TO clinic_app;
GRANT USAGE ON SCHEMA public TO clinic_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO clinic_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO clinic_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinic_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON schema_migrations FROM clinic_app;
-- Reapply after each schema migration; application role must NOT own the tables
-- and must not be superuser, CREATEDB, CREATEROLE or BYPASSRLS.
-- v0.5: append-only evidence. Apply after owner migration version 3.
REVOKE UPDATE, DELETE, TRUNCATE ON clinical_revisions, nursing_notes,
 nursing_executions, nursing_task_cancellations, charge_price_history,
 charge_credits, controlled_ledger, controlled_approvals,
 prescription_cancellations, visit_cancellations, adjustment_reversals FROM clinic_app;

REVOKE UPDATE, DELETE, TRUNCATE ON order_authorizations, charge_sources,
 dispensation_items, dispensations, payments, charges, stock_movements,
 charge_voids, visit_closures, medicine_units FROM clinic_app;
REVOKE UPDATE, DELETE, TRUNCATE ON manual_charge_prices FROM clinic_app;
