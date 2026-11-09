"""Vietnamese display labels and shared parsers for codes stored in the database.

Database values stay in English codes (stable for queries and tests); anything a
person reads on screen or on paper goes through these maps.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

STATUS = {
    # visits
    'waiting_results':'Chờ kết quả','requested':'Chờ bác sĩ duyệt','completed':'Hoàn tất chuyên môn','dispensed':'Đã cấp thuốc','returned':'Đã trả toàn bộ thuốc','waiting': 'Chờ khám', 'in_progress': 'Đang khám', 'done': 'Đã khám xong', 'cancelled': 'Đã hủy',
    # appointments
    'booked': 'Đã đặt lịch', 'arrived': 'Đã đến khám',
    # orders
    'ordered': 'Chờ thực hiện', 'pending_review': 'Chờ duyệt kết quả', 'approved': 'Đã duyệt',
    # prescriptions
    'draft': 'Đơn nháp',
    # adjustments
    'pending': 'Chờ quản lý duyệt', 'rejected': 'Bị từ chối',
}
CATEGORY = {'lab': 'Xét nghiệm', 'ultrasound': 'Siêu âm', 'xray': 'X-quang', 'ecg': 'Điện tim'}
METHOD = {'cash': 'Tiền mặt', 'transfer': 'Chuyển khoản'}
ADJUSTMENT = {'discount': 'Giảm phí', 'refund': 'Hoàn tiền'}


def vi(code, table=STATUS):
    """Return the Vietnamese label; unknown codes are shown as-is rather than hidden."""
    if code is None:
        return '—'
    return table.get(str(code), str(code))


def parse_day(value):
    """Accept dd/mm/yyyy (what staff type) or yyyy-mm-dd (browser/ISO); return ISO or None."""
    text = str(value or '').strip()
    if not text:
        return None
    m = re.fullmatch(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})', text)
    if m:
        day, month, year = (int(x) for x in m.groups())
        return date(year, month, day).isoformat()
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', text)
    if m:
        return date(*(int(x) for x in m.groups())).isoformat()
    raise ValueError('Ngày phải theo dạng ngày/tháng/năm, ví dụ 05/12/2026')


VN_TZ = timezone(timedelta(hours=7))  # Việt Nam không đổi giờ mùa hè; tránh phụ thuộc tzdata trên Windows


def local_day(value):
    """Timestamps are stored in UTC; staff read Vietnamese local dates."""
    text = str(value or '').strip()
    if re.search(r'T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})$', text):
        try:
            return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(VN_TZ).date().isoformat()
        except ValueError:
            return text
    return text


def show_day(value):
    """ISO date (or timestamp) to dd/mm/yyyy for people; leave anything else untouched."""
    text = local_day(value)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', text)
    return f'{m[3]}/{m[2]}/{m[1]}' if m else (text or '—')


def lab_rows(result_text):
    """Split a technician's result into table rows and free notes.

    One test per line: ``Tên chỉ số | Kết quả | Đơn vị | Khoảng tham chiếu | Đánh dấu``.
    A line starting with ``Kết luận`` becomes the conclusion. Other lines are notes.
    Nothing is dropped: every input line ends up in rows, notes or conclusion.
    """
    rows, notes, conclusion = [], [], []
    for raw in str(result_text or '').splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r'(?i)^(kết luận|kl)\s*[:：]', line):
            conclusion.append(re.sub(r'(?i)^(kết luận|kl)\s*[:：]\s*', '', line))
        elif '|' in line:
            cells = [c.strip() for c in line.split('|')]
            cells = (cells + ['', '', '', '', ''])[:5] if len(cells) <= 5 else cells[:4] + [' | '.join(cells[4:])]
            rows.append(cells)
        else:
            notes.append(line)
    return rows, notes, ' '.join(conclusion)
