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
    assert client.get('/api/queue-counts', headers=h).json()['reception'] == sum(v['status'] == 'waiting' for v in client.get('/api/visits', headers=h).json())
    h = token('thungan')
    assert client.get('/api/queue-counts', headers=h).json()['cashier'] == sum(d['charged'] - d['paid'] > 0 for d in client.get('/api/dues', headers=h).json())
