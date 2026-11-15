CREATE TABLE clinic_profile (
    id INTEGER PRIMARY KEY CHECK(id=1),
    name TEXT NOT NULL DEFAULT '',
    governing_body TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT ''
);
INSERT INTO clinic_profile(id) VALUES(1);
CREATE TABLE user_signatures (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    image BLOB NOT NULL CHECK(length(image)>0 AND length(image)<=307200),
    media_type TEXT NOT NULL CHECK(media_type IN ('image/png','image/jpeg')),
    uploaded_at TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL REFERENCES users(id)
);
