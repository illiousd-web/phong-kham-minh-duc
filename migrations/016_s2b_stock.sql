CREATE TABLE stock_receipts (
    id INTEGER PRIMARY KEY,
    document_no TEXT NOT NULL UNIQUE,
    supplier TEXT NOT NULL DEFAULT '',
    invoice_no TEXT NOT NULL DEFAULT '',
    invoice_date TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE stock_issues (
    id INTEGER PRIMARY KEY,
    document_no TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    purpose TEXT NOT NULL,
    recipient TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE stock_document_sequences (
    kind TEXT NOT NULL CHECK(kind IN ('PN','PX')),
    year INTEGER NOT NULL,
    last_number INTEGER NOT NULL CHECK(last_number>0),
    PRIMARY KEY(kind,year)
);
ALTER TABLE medicines ADD COLUMN min_stock INTEGER CHECK(min_stock>=0);
ALTER TABLE stock_lots ADD COLUMN unit_cost INTEGER CHECK(unit_cost>=0 AND unit_cost<=2000000000);
ALTER TABLE stock_lots ADD COLUMN vat_rate NUMERIC CHECK(vat_rate>=0 AND vat_rate<=100);
ALTER TABLE stock_lots ADD COLUMN receipt_id INTEGER REFERENCES stock_receipts(id);
ALTER TABLE stock_movements ADD COLUMN unit_cost INTEGER CHECK(unit_cost>=0 AND unit_cost<=2000000000);
ALTER TABLE stock_movements ADD COLUMN vat_rate NUMERIC CHECK(vat_rate>=0 AND vat_rate<=100);
ALTER TABLE stock_movements ADD COLUMN revenue_amount BIGINT;
ALTER TABLE stock_movements ADD COLUMN receipt_id INTEGER REFERENCES stock_receipts(id);
ALTER TABLE stock_movements ADD COLUMN issue_id INTEGER REFERENCES stock_issues(id);
CREATE INDEX idx_s2b_movement_time ON stock_movements(created_at,stock_lot_id);
CREATE INDEX idx_s2b_movement_receipt ON stock_movements(receipt_id);
CREATE INDEX idx_s2b_movement_issue ON stock_movements(issue_id);
