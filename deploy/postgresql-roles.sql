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
