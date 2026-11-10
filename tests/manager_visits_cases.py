"""Kịch bản kiểm thử Quản lý → Lượt khám, dùng chung cho SQLite (tests/) và PostgreSQL (lan_tests/).

Chỉ dữ liệu giả lập. `call(role, path)` trả về phản hồi HTTP GET/POST của vai trò đó;
role là một trong: manager, admin, reception, doctor, technician, nurse, pharmacy, cashier.
"""
import secrets
import unicodedata
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone

VN = timezone(timedelta(hours=7))
OTHER_ROLES = ('admin', 'reception', 'doctor', 'technician', 'nurse', 'pharmacy', 'cashier')
ITEM_KEYS = {'visit_id', 'created_at', 'status', 'patient_code', 'patient_name', 'charged', 'paid',
             'unpriced_count', 'money_status', 'due', 'refund_due'}
CLINICAL = ('chief_complaint', 'history', 'vitals', 'diagnosis', 'treatment', 'follow_up', 'phone', 'citizen_id', 'address')


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds')


def vn_day(moment):
    return moment.astimezone(VN).strftime('%d/%m/%Y')


def new_patient(post, name):
    phone = '09' + ''.join(secrets.choice('0123456789') for _ in range(8))
    r = post('reception', '/api/patients', {'full_name': name, 'date_of_birth': '1980-02-03', 'sex': 'Nam', 'phone': phone})
    assert r.status_code == 201, r.text
    return r.json()['id'], r.json()['code'], phone


def insert_visit(c, pid, created_at, charges=(), payments=(), status=None):
    """Lượt khám giả lập ghi thẳng CSDL: các khoản phải thu và phiếu thu cho trước."""
    c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,created_at) VALUES(?,?,?,?)',
              (pid, c.execute("SELECT user_id FROM user_roles WHERE role='doctor' ORDER BY user_id LIMIT 1").fetchone()[0],
               c.execute('SELECT MIN(id) FROM users').fetchone()[0], created_at))
    vid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    for amount in charges:
        c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)', (vid, 'Khoản giả lập', amount, created_at))
    for amount in payments:
        c.execute("INSERT INTO payments(visit_id,amount,method,created_by,created_at,idempotency_key) VALUES(?,?,'cash',?,?,?)",
                  (vid, amount, c.execute('SELECT MIN(id) FROM users').fetchone()[0], created_at, 'mv-' + secrets.token_hex(10)))
    if status:
        c.execute('UPDATE visits SET status=? WHERE id=?', (status, vid))
    return vid


def search(get, **params):
    r = get('manager', '/api/manager/visits' + ('?' + urlencode(params) if params else ''))
    assert r.status_code == 200, r.text
    return r.json()


def all_pages(get, **params):
    first = search(get, **params)
    items = list(first['items'])
    for page in range(2, first['pages'] + 1):
        items += search(get, page=page, **params)['items']
    return first, items


def old_settled_visit_is_found(get, post, service_id, doctor_id):
    """Lượt đã thu đủ cách đây 30 ngày, bị hơn 150 lượt mới hơn đẩy xuống, vẫn tìm thấy theo tên và theo ngày."""
    from app.database import db
    tag = secrets.token_hex(4)
    name = f'Người bệnh tra cứu cũ {tag}'
    pid, code, phone = new_patient(post, name)
    v = post('reception', '/api/visits', {'patient_id': pid, 'doctor_id': doctor_id, 'service_id': service_id})
    assert v.status_code == 201, v.text
    target = v.json()['id']
    owed = get('cashier', f'/api/visits/{target}/settlement').json()['billing']['due']
    assert owed > 0
    paid = post('cashier', '/api/payments', {'visit_id': target, 'amount': owed, 'method': 'cash', 'idempotency_key': secrets.token_hex(12)})
    assert paid.status_code == 201, paid.text
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=30)
    filler_name = f'Người bệnh lượt mới {tag}'
    filler_pid, _, _ = new_patient(post, filler_name)
    with db(True) as c:
        c.execute('UPDATE visits SET created_at=? WHERE id=?', (iso(old), target))
        newer = [insert_visit(c, filler_pid, iso(now - timedelta(hours=i)), charges=[1000], payments=[1000]) for i in range(1, 161)]
    assert min(newer) > target and len(newer) > 150
    # Hồi quy sau PR #11: /api/dues (không đổi) không có lượt cũ đã thu đủ, và nằm ngoài "100 lượt mới nhất".
    assert target not in {d['visit_id'] for d in get('cashier', '/api/dues').json()}
    with db() as c:
        assert target not in {x['id'] for x in c.execute('SELECT id FROM visits ORDER BY id DESC LIMIT 100')}
    # Đã thu đủ vẫn có thể chưa hoàn tất khám: hàng chờ mới phải giữ lượt này.
    assert target in {x['id'] for x in get('manager', '/api/visits').json()}
    assert target not in {x['visit_id'] for x in get('manager', '/api/payments').json()}

    # Mặc định 7 ngày gần nhất theo giờ Việt Nam: lượt 30 ngày trước không nằm trong đó.
    default = search(get, q=tag)
    today = datetime.now(VN).date()
    assert default['date_from'] == (today - timedelta(days=6)).isoformat() and default['date_to'] == today.isoformat()
    assert target not in {x['visit_id'] for x in default['items']}

    since = vn_day(old - timedelta(days=5))
    for q in (name, name.lower(), f'tra cứu cũ {tag}', code, code.lower(), phone, phone[-6:]):
        found = search(get, q=q, date_from=since)
        hits = [x for x in found['items'] if x['visit_id'] == target]
        assert len(hits) == 1, (q, found)
        x = hits[0]
        assert set(x) == ITEM_KEYS
        assert x['patient_name'] == name and x['patient_code'] == code
        assert x['money_status'] == 'settled' and x['due'] == 0 and x['refund_due'] == 0 and x['charged'] == x['paid'] == owed
    # Theo ngày: chỉ đúng ngày đó (dd/mm/yyyy), không cần tên.
    day = vn_day(old)
    first, items = all_pages(get, date_from=day, date_to=day)
    assert target in {x['visit_id'] for x in items}
    assert first['date_from'] == old.astimezone(VN).date().isoformat() == first['date_to']
    assert not set(newer) & {x['visit_id'] for x in items}
    # Ngày ISO cũng nhận; ngày sau đó không có lượt này.
    after = (old.astimezone(VN) + timedelta(days=1)).date().isoformat()
    assert target not in {x['visit_id'] for x in all_pages(get, q=tag, date_from=after)[1]}

    # Mở lượt: bảng kê, phiếu thu, trạng thái tiền của lượt cũ đều đọc được.
    detail = get('manager', f'/api/manager/visits/{target}')
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body['visit']['id'] == target and body['visit']['patient_name'] == name
    assert [p['id'] for p in body['payments']] == [paid.json()['id']] and body['payments'][0]['amount'] == owed
    assert body['adjustments'] == []
    assert not any(k in body['visit'] for k in CLINICAL)
    assert get('manager', f'/api/manager/visits/{max(newer) + 10_000}').status_code == 404
    assert get('manager', f'/api/visits/{target}/settlement').json()['payment_status'] == 'settled'
    assert [ch['amount'] for ch in get('manager', f'/api/charges/{target}').json()] == [owed]
    receipt = get('manager', f"/api/print/receipt/{paid.json()['id']}")
    assert receipt.status_code == 200 and receipt.content.startswith(b'%PDF')
    return target, name, tag


def money_filters_are_exact(get, post):
    """Từng tình trạng tiền lọc đúng và khớp trạng thái thanh toán của chính lượt đó."""
    from app.database import db
    tag = secrets.token_hex(4)
    pid, _, _ = new_patient(post, f'Người bệnh lọc tiền {tag}')
    now = iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    with db(True) as c:
        expected = {
            'owing': insert_visit(c, pid, now, charges=[150000], payments=[50000]),
            'settled': insert_visit(c, pid, now, charges=[150000], payments=[150000]),
            'unpriced': insert_visit(c, pid, now, charges=[150000, None], payments=[150000]),
            'refund': insert_visit(c, pid, now, charges=[1000], payments=[5000], status='completed'),
        }
    assert {x['visit_id'] for x in search(get, q=tag)['items']} == set(expected.values())
    settlement = {'owing': 'due', 'settled': 'settled', 'unpriced': 'unpriced', 'refund': 'refund_due'}
    for money, vid in expected.items():
        found = search(get, q=tag, money=money)
        assert [x['visit_id'] for x in found['items']] == [vid] and found['total'] == 1, (money, found)
        x = found['items'][0]
        assert x['money_status'] == money
        assert get('manager', f'/api/visits/{vid}/settlement').json()['payment_status'] == settlement[money]
    by_id = {x['visit_id']: x for x in search(get, q=tag)['items']}
    assert by_id[expected['owing']]['due'] == 100000
    assert by_id[expected['unpriced']]['due'] is None and by_id[expected['unpriced']]['unpriced_count'] == 1
    assert by_id[expected['refund']]['refund_due'] == 4000
    # Trạng thái lượt
    assert [x['visit_id'] for x in search(get, q=tag, status='completed')['items']] == [expected['refund']]
    assert {x['visit_id'] for x in search(get, q=tag, status='waiting')['items']} == set(expected.values()) - {expected['refund']}
    assert search(get, q=tag, status='completed', money='owing')['items'] == []
    for bad in ({'money': 'paid'}, {'status': 'done'}, {'date_from': '31/02/2026'}, {'date_from': '2026-13-01'},
                {'date_from': '10/11/2026', 'date_to': '09/11/2026'}, {'page': '0'}, {'page': 'abc'}):
        r = get('manager', '/api/manager/visits?' + urlencode(bad))
        assert r.status_code == 422 and isinstance(r.json()['detail'], str), (bad, r.text)


def dates_outside_2000_2100_are_rejected(get):
    """Ngày ngoài 01/01/2000–31/12/2100 trả 422 tiếng Việt, không phải 500."""
    for bad in ({'date_from': '01/01/0001'}, {'date_to': '31/12/9999'}, {'date_from': '0001-01-01'}, {'date_to': '9999-12-31'},
                {'date_from': '01/01/0001', 'date_to': '31/12/9999'}, {'date_from': '31/12/1999'}, {'date_to': '01/01/2101'}):
        r = get('manager', '/api/manager/visits?' + urlencode(bad))
        assert r.status_code == 422, (bad, r.status_code, r.text)
        assert 'phải trong khoảng 01/01/2000 đến 31/12/2100' in r.json()['detail'], (bad, r.text)
    edge = search(get, date_from='01/01/2000', date_to='31/12/2100')
    assert edge['date_from'] == '2000-01-01' and edge['date_to'] == '2100-12-31'


def vietnamese_names_are_found(get, post):
    """Gõ có dấu hay không dấu, hoa hay thường đều ra đúng người; chữ có dấu ở đầu, giữa, cuối tên."""
    from app.database import db
    tag = secrets.token_hex(4)
    names = {
        'bich': f'Đặng Thị Thu Bích {tag}',           # chữ có dấu ở đầu (Đặng) và cuối (Bích)
        'hang_end': f'Lê Thị Hằng {tag}',             # cuối
        'hang_mid': f'Vũ Hằng Nga {tag}',             # giữa
        'dat': f'Trần Hữu Đạt {tag}',                 # cuối, có đ
        'nfd': unicodedata.normalize('NFD', f'Đỗ Mỹ Uyên {tag}'),  # tên lưu dạng tổ hợp rời (NFD)
        'plain': f'Hoàng Văn Sơn {tag}',              # đối chứng
    }
    now = iso(datetime.now(timezone.utc) - timedelta(minutes=3))
    visits = {}
    for key, name in names.items():
        pid, _, _ = new_patient(post, name)
        with db(True) as c:
            visits[key] = insert_visit(c, pid, now, charges=[1000])
    mine = set(visits.values())

    def hits(q):
        return {x['visit_id'] for x in all_pages(get, q=q)[1]} & mine

    expected = {
        ('đặng', 'ĐẶNG', 'dang', 'Dang', 'DANG', 'Đặng'): {'bich'},
        ('bích', 'BÍCH', 'bich', 'thu bich', 'đặng thị thu bích', 'DANG THI THU BICH', f'bích {tag}'): {'bich'},
        ('hằng', 'HẰNG', 'HANG', 'hang', unicodedata.normalize('NFD', 'Hằng')): {'hang_end', 'hang_mid'},
        ('Đạt', 'đạt', 'ĐẠT', 'dat', 'DAT', 'huu dat'): {'dat'},
        ('uyên', 'UYEN', 'mỹ uyên', 'do my uyen', 'Đỗ'): {'nfd'},
        ('sơn', 'SON', 'hoang van son'): {'plain'},
        (tag, tag.upper()): set(names),
    }
    for queries, keys in expected.items():
        for q in queries:
            assert hits(q) == {visits[k] for k in keys}, (q, keys)
    # Tên trả về giữ nguyên như đã lưu, không bị bỏ dấu.
    assert {x['patient_name'] for x in search(get, q=f'dang thi thu bich {tag}')['items']} == {names['bich']}


def pagination_is_exact(get, post):
    """50 dòng một trang, mới nhất trước, không lặp, không sót."""
    from app.database import db
    tag = secrets.token_hex(4)
    pid, _, _ = new_patient(post, f'Người bệnh phân trang {tag}')
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    with db(True) as c:
        ids = [insert_visit(c, pid, iso(base + timedelta(seconds=i)), charges=[1000]) for i in range(123)]
    first = search(get, q=tag)
    assert (first['total'], first['pages'], first['page'], first['page_size']) == (123, 3, 1, 50)
    pages = [first['items']] + [search(get, q=tag, page=n)['items'] for n in (2, 3)]
    assert [len(p) for p in pages] == [50, 50, 23]
    seen = [x['visit_id'] for p in pages for x in p]
    assert seen == sorted(ids, reverse=True)
    beyond = search(get, q=tag, page=4)
    assert beyond['items'] == [] and beyond['total'] == 123
    assert search(get, q=tag, money='owing')['total'] == 123


def only_manager_may_read(get, visit_id):
    for role in OTHER_ROLES:
        for path in ('/api/manager/visits', '/api/manager/visits?' + urlencode({'q': 'a', 'date_from': '01/01/2020'}), f'/api/manager/visits/{visit_id}'):
            r = get(role, path)
            assert r.status_code == 403, (role, path, r.status_code)
    assert get(None, '/api/manager/visits').status_code == 401
    assert get(None, f'/api/manager/visits/{visit_id}').status_code == 401
