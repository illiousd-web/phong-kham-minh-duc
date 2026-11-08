PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 full_name TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS user_roles (
 user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL,
 PRIMARY KEY(user_id,role));
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patients (
 id INTEGER PRIMARY KEY, code TEXT UNIQUE, full_name TEXT NOT NULL,
 date_of_birth TEXT, sex TEXT NOT NULL, phone TEXT,
 citizen_id TEXT, address TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients(phone);
CREATE TABLE IF NOT EXISTS appointments (
 id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
 doctor_id INTEGER NOT NULL REFERENCES users(id), scheduled_at TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'booked', created_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS visits (
 id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
 doctor_id INTEGER NOT NULL REFERENCES users(id), created_by INTEGER NOT NULL REFERENCES users(id),
 appointment_id INTEGER REFERENCES appointments(id), status TEXT NOT NULL DEFAULT 'waiting',
 chief_complaint TEXT NOT NULL DEFAULT '', history TEXT NOT NULL DEFAULT '',
 vitals TEXT NOT NULL DEFAULT '', diagnosis TEXT NOT NULL DEFAULT '', treatment TEXT NOT NULL DEFAULT '',
 follow_up TEXT, version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS service_catalog (
 id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS charges (
 id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id),
 label TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id),
 category TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ordered',
 requested_by INTEGER NOT NULL REFERENCES users(id), result_text TEXT NOT NULL DEFAULT '',
 file_name TEXT, file_key TEXT, result_by INTEGER REFERENCES users(id),
 approved_by INTEGER REFERENCES users(id), approved_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prescriptions (
 id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL UNIQUE REFERENCES visits(id),
 doctor_id INTEGER NOT NULL REFERENCES users(id), drug_lines TEXT NOT NULL,
 instructions TEXT NOT NULL DEFAULT '', follow_up TEXT,
 status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id),
 amount INTEGER NOT NULL CHECK(amount>0), method TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 external_ref TEXT, idempotency_key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS medicines (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, base_unit TEXT NOT NULL,
 controlled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS stock_lots (
 id INTEGER PRIMARY KEY, medicine_id INTEGER NOT NULL REFERENCES medicines(id),
 lot_number TEXT NOT NULL, expiry_date TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
 quarantined INTEGER NOT NULL DEFAULT 0, UNIQUE(medicine_id,lot_number));
CREATE TABLE IF NOT EXISTS stock_movements (
 id INTEGER PRIMARY KEY, stock_lot_id INTEGER NOT NULL REFERENCES stock_lots(id),
 movement_type TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS adjustments (
 id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id),
 payment_id INTEGER REFERENCES payments(id), kind TEXT NOT NULL CHECK(kind IN ('discount','refund')),
 amount INTEGER NOT NULL CHECK(amount>0), reason TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 proposed_by INTEGER NOT NULL REFERENCES users(id), reviewed_by INTEGER REFERENCES users(id),
 proposed_at TEXT NOT NULL, reviewed_at TEXT);
CREATE INDEX IF NOT EXISTS idx_adjustments_visit ON adjustments(visit_id,status);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), event TEXT NOT NULL,
 object_type TEXT NOT NULL, object_id INTEGER, details TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL);
