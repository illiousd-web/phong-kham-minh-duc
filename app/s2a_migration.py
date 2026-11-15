"""S2a v15: server-side clinic profile and signature bytes; no seeded identities."""
from pathlib import Path


def migrate_s2a(c, postgres=False, *, down=False):
    applied = bool(c.execute('SELECT 1 FROM schema_migrations WHERE version=15').fetchone())
    if applied == (not down):
        return
    if down:
        if (c.execute('SELECT 1 FROM user_signatures LIMIT 1').fetchone() or
                c.execute("SELECT 1 FROM clinic_profile WHERE name<>'' OR governing_body<>'' OR address<>'' OR phone<>'' OR email<>''").fetchone()):
            raise ValueError('Chưa quay lui S2a: đã có thông tin phòng khám hoặc chữ ký. Khôi phục bản sao lưu trước nâng cấp để giữ dữ liệu.')
        c.execute('DROP TABLE user_signatures')
        c.execute('DROP TABLE clinic_profile')
        c.execute('DELETE FROM schema_migrations WHERE version=15')
        return
    ddl = (Path(__file__).resolve().parents[1] / 'migrations/015_s2a_clinic.sql').read_text(encoding='utf-8')
    if postgres:
        ddl = ddl.replace('BLOB', 'BYTEA')
    for statement in ddl.split(';'):
        if statement.strip():
            c.execute(statement)
    c.execute('INSERT INTO schema_migrations(version) VALUES(15)')


if __name__ == '__main__':
    import argparse
    import sqlite3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite', required=True, type=Path)
    parser.add_argument('--down', action='store_true')
    args = parser.parse_args()
    if not args.sqlite.is_file():
        parser.error('Không có CSDL SQLite để nâng cấp / quay lui')
    with sqlite3.connect(args.sqlite) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        migrate_s2a(connection, down=args.down)
