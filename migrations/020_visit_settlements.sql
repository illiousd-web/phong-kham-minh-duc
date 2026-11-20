CREATE TABLE visit_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id BIGINT NOT NULL REFERENCES visits(id),
    previous_settlement_id BIGINT UNIQUE,
    actor_id BIGINT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    charged BIGINT NOT NULL CHECK (charged >= 0),
    paid BIGINT NOT NULL,
    due BIGINT NOT NULL CHECK (due >= 0),
    refund_due BIGINT NOT NULL CHECK (refund_due = 0),
    kind TEXT NOT NULL CHECK (kind IN ('du_thu', 'mien_thu')),
    waived_amount BIGINT NOT NULL DEFAULT 0,
    reason TEXT,
    approved_by BIGINT REFERENCES users(id),
    UNIQUE (visit_id, id),
    CHECK (
        (kind = 'du_thu' AND due = 0 AND waived_amount = 0 AND reason IS NULL AND approved_by IS NULL)
        OR (kind = 'mien_thu' AND waived_amount = due AND reason IS NOT NULL
            AND length(trim(reason)) >= 10 AND approved_by IS NOT NULL AND approved_by = actor_id)
    )
);
CREATE UNIQUE INDEX visit_settlements_first ON visit_settlements(visit_id) WHERE previous_settlement_id IS NULL;
CREATE INDEX visit_settlements_waiver_period ON visit_settlements(created_at) WHERE kind = 'mien_thu';

CREATE TABLE visit_settlement_reopens (
    settlement_id BIGINT PRIMARY KEY NOT NULL,
    visit_id BIGINT NOT NULL,
    actor_id BIGINT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    UNIQUE (visit_id, settlement_id),
    FOREIGN KEY (visit_id, settlement_id) REFERENCES visit_settlements(visit_id, id)
);

CREATE VIEW active_visit_settlements AS
    SELECT s.* FROM visit_settlements s
    WHERE NOT EXISTS (SELECT 1 FROM visit_settlement_reopens r WHERE r.settlement_id = s.id);
