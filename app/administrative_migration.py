"""Version 6: additive L1/L2 fields; preserve legacy values without guessing them."""
PATIENT_COLUMNS = {
    'document_type': 'TEXT', 'document_number': 'TEXT', 'ethnicity': 'TEXT',
    'occupation': 'TEXT', 'workplace': 'TEXT', 'province': 'TEXT',
    'commune': 'TEXT', 'address_detail': 'TEXT',
}
VISIT_COLUMNS = {
    'weight_kg': 'REAL CHECK(weight_kg>0 AND weight_kg<=500)',
    'escort_name': 'TEXT', 'escort_relationship': 'TEXT', 'escort_phone': 'TEXT',
}
PRACTITIONER_COLUMNS = {
    'printed_name': 'TEXT', 'printed_title': 'TEXT', 'practice_license': 'TEXT',
    'practice_scopes': "TEXT NOT NULL DEFAULT '[]'", 'certificate_provider': 'TEXT',
    'certificate_serial': 'TEXT', 'certificate_expiry': 'TEXT',
}


def migrate_administrative(c):
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=6').fetchone():
        return
    for table, columns in [('patients', PATIENT_COLUMNS), ('visits', VISIT_COLUMNS), ('users', PRACTITIONER_COLUMNS)]:
        for name, definition in columns.items():
            c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    # Duplicate documents are warnings, including documents in legacy citizen_id.
    c.execute('DROP INDEX IF EXISTS idx_patient_citizen')
    c.execute('CREATE INDEX idx_patient_document ON patients(document_number)')
    c.execute('CREATE INDEX idx_patient_citizen ON patients(citizen_id)')
    c.execute('''CREATE TABLE patient_catalog (
        kind TEXT NOT NULL CHECK(kind IN ('province','commune','ethnicity')),
        code TEXT NOT NULL, name TEXT NOT NULL, parent_code TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(kind,code))''')
    c.execute('INSERT INTO schema_migrations(version) VALUES(6)')
