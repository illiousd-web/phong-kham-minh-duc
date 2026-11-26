"""Migration 021: mã thao tác chống ghi trùng cho phiếu nhập/xuất kho (T4).

Phiếu cũ giữ request_key NULL; UNIQUE cho phép nhiều NULL trên cả SQLite và PostgreSQL.
Quay lui chỉ khi chưa có phiếu nào mang mã thao tác, để không mất dấu chống ghi trùng.
"""

TABLES = ('stock_receipts', 'stock_issues')


def migrate_stock_request_keys(c, postgres=False, *, down=False):
    applied = bool(c.execute('SELECT 1 FROM schema_migrations WHERE version=21').fetchone())
    if applied == (not down):
        return
    if not down and not c.execute('SELECT 1 FROM schema_migrations WHERE version=16').fetchone():
        return  # Bảng phiếu kho có từ 016; 021 được áp ở lần migrate sau khi đã có 016.
    if down:
        if any(c.execute(f'SELECT 1 FROM {table} WHERE request_key IS NOT NULL LIMIT 1').fetchone() for table in TABLES):
            raise ValueError('Chưa quay lui migration 021: đã có phiếu kho mang mã thao tác. '
                             'Khôi phục bản sao lưu trước nâng cấp để giữ dữ liệu.')
        for table in TABLES:
            c.execute(f'DROP INDEX idx_{table}_request_key')
            c.execute(f'ALTER TABLE {table} DROP COLUMN request_key')
        c.execute('DELETE FROM schema_migrations WHERE version=21')
        return
    for table in TABLES:
        c.execute(f'ALTER TABLE {table} ADD COLUMN request_key TEXT')
        c.execute(f'CREATE UNIQUE INDEX idx_{table}_request_key ON {table}(request_key)')
    c.execute('INSERT INTO schema_migrations(version) VALUES(21)')
