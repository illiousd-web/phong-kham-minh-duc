"""Số đếm hàng chờ: chỉ trả con số, chỉ cho màn hình của vai trò, đúng phạm vi phân quyền."""
from tests.test_workflows import client, token, prepare_visit


def test_counts_are_numbers_scoped_to_role():
    prepare_visit('bs_noi')
    assert client.get('/api/queue-counts').status_code == 401
    expected = {'letan': {'reception'}, 'bs_noi': {'doctor'}, 'bs_san': {'doctor'}, 'kythuat': {'lab'},
                'dieuduong': {'nurse'}, 'duoc': {'pharmacy'}, 'thungan': {'cashier'}, 'quanly': {'manager'}, 'quantri': set()}
    for user, keys in expected.items():
        data = client.get('/api/queue-counts', headers=token(user)).json()
        assert set(data) == keys, (user, data)
        assert all(type(v) is int and v >= 0 for v in data.values()), (user, data)


def test_counts_match_the_role_queue():
    prepare_visit('bs_san')
    for user in ('bs_noi', 'bs_san'):
        h = token(user)
        visits = client.get('/api/visits', headers=h).json()
        assert client.get('/api/queue-counts', headers=h).json()['doctor'] == sum(v['status'] not in ('completed', 'cancelled') for v in visits)
    h = token('letan')
    # Cùng điều kiện với hàng chờ Tiếp đón: lượt chưa hoàn tất, chưa hủy.
    assert client.get('/api/queue-counts', headers=h).json()['reception'] == sum(v['status'] not in ('completed', 'cancelled') for v in client.get('/api/visits', headers=h).json())
    h = token('thungan')
    assert client.get('/api/queue-counts', headers=h).json()['cashier'] == sum(d['charged'] - d['paid'] > 0 or d['unpriced_count'] > 0 for d in client.get('/api/dues', headers=h).json())


def test_dues_not_readable_by_reception_but_by_cashier_role():
    """Lễ tân không đọc công nợ; người kiêm lễ tân + thu ngân vẫn đọc qua vai trò thu ngân."""
    import secrets
    assert client.get('/api/dues', headers=token('letan')).status_code == 403
    assert client.get('/api/dues', headers=token('thungan')).status_code == 200
    assert client.get('/api/dues', headers=token('quanly')).status_code == 200
    admin = token('quantri')
    name = 'kiem_' + secrets.token_hex(3)
    password = secrets.token_urlsafe(16)
    assert client.post('/api/accounts', headers=admin, json={'username': name, 'full_name': 'Lễ tân kiêm thu ngân',
        'password': password, 'roles': ['reception', 'cashier']}).status_code == 201
    both = {'Authorization': 'Bearer ' + client.post('/api/login', json={'username': name, 'password': password}).json()['access_token']}
    assert client.get('/api/dues', headers=both).status_code == 200
    assert set(client.get('/api/queue-counts', headers=both).json()) == {'reception', 'cashier'}


def test_known_render_count_skips_only_duplicate_query_and_poll_remains_complete():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.queue_counts import install_queue_counts
    from contextlib import contextmanager
    app=FastAPI();calls=[]
    class Connection:
        def execute(self,sql,args=()):
            assert 'COUNT(*)' in sql
            kind='cashier' if 'WITH charge_changes' in sql else 'lab' if "o.status='ordered'" in sql else 'visits'
            calls.append(kind)
            return self
        def fetchone(self):return (1,)
    @contextmanager
    def database():yield Connection()
    install_queue_counts(app,lambda:{'id':1,'roles':['reception','technician','cashier']},lambda:{},database)
    c=TestClient(app)
    assert c.get('/api/queue-counts?known=lab').json()=={'reception':1,'cashier':1}
    assert calls==['visits','cashier'];calls.clear()
    assert c.get('/api/queue-counts?known=cashier').json()=={'reception':1,'lab':1}
    assert calls==['visits','lab'];calls.clear()
    assert c.get('/api/queue-counts').json()=={'reception':1,'lab':1,'cashier':1}
    assert calls==['visits','lab','cashier']
    assert c.get('/api/queue-counts?known=doctor').status_code==422
