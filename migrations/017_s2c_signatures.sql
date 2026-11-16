CREATE TABLE document_signatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_kind TEXT NOT NULL CHECK(document_kind IN ('rx','order','lab','clinical_rx','lab_report')),
    document_id INTEGER NOT NULL,
    visit_id INTEGER NOT NULL REFERENCES visits(id),
    signed_by INTEGER NOT NULL REFERENCES users(id),
    signed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    image BLOB NOT NULL,
    username TEXT NOT NULL
);
CREATE INDEX idx_document_signature ON document_signatures(document_kind,document_id,id);
CREATE INDEX idx_document_signature_visit ON document_signatures(visit_id);
