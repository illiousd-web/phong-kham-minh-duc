CREATE TABLE IF NOT EXISTS manual_charge_prices (
 charge_id INTEGER PRIMARY KEY REFERENCES charges(id), amount INTEGER NOT NULL CHECK(amount>0 AND amount<=2000000000),
 description TEXT NOT NULL, priced_by INTEGER NOT NULL REFERENCES users(id), priced_at TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS manual_price_requests (
 id INTEGER PRIMARY KEY, charge_id INTEGER NOT NULL REFERENCES charges(id),
 previous_amount INTEGER NOT NULL CHECK(previous_amount>0), previous_description TEXT NOT NULL,
 new_amount INTEGER NOT NULL CHECK(new_amount>0 AND new_amount<=2000000000), description TEXT NOT NULL,
 reason TEXT NOT NULL, proposed_by INTEGER NOT NULL REFERENCES users(id), proposed_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 reviewed_by INTEGER REFERENCES users(id), reviewed_at TEXT, request_key TEXT NOT NULL UNIQUE);
CREATE INDEX IF NOT EXISTS idx_manual_price_requests_charge ON manual_price_requests(charge_id,id);
CREATE INDEX IF NOT EXISTS idx_manual_price_requests_pending ON manual_price_requests(status,id);
CREATE INDEX IF NOT EXISTS idx_manual_charge_prices_day ON manual_charge_prices(priced_at);
CREATE INDEX IF NOT EXISTS idx_charges_visit ON charges(visit_id);
