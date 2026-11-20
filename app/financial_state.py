"""Financial write guard, called inside the existing serialized write transaction."""
from fastapi import HTTPException


def ensure_financial_open(c, visit_id):
    if c.execute('SELECT 1 FROM active_visit_settlements WHERE visit_id=?', (visit_id,)).fetchone():
        raise HTTPException(409, 'Lượt đã kết thúc tài chính')
