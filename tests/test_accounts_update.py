"""PUT /api/accounts/{id}: chỉ đổi trường được gửi; không gửi roles thì giữ nguyên quyền."""
import secrets
from tests.test_workflows import client, token


def _roles(admin, uid):
    return next(u for u in client.get('/api/accounts', headers=admin).json() if u['id'] == uid)


def test_lock_unlock_and_rename_keep_roles():
    admin = token('quantri')
    username = 'bs_ks_' + secrets.token_hex(3)
    uid = client.post('/api/accounts', headers=admin, json={'username': username, 'full_name': 'Bác sĩ kiểm soát giả lập',
        'password': secrets.token_urlsafe(16), 'roles': ['doctor', 'controlled_prescriber']}).json()['id']
    before = _roles(admin, uid)['roles']
    assert before == ['controlled_prescriber', 'doctor']
    assert client.put(f'/api/accounts/{uid}', headers=admin, json={'active': False}).status_code == 200
    after = _roles(admin, uid)
    assert after['roles'] == before and after['active'] in (0, False)
    assert client.put(f'/api/accounts/{uid}', headers=admin, json={'active': True}).status_code == 200
    assert client.put(f'/api/accounts/{uid}', headers=admin, json={'full_name': 'Bác sĩ đã đổi tên'}).status_code == 200
    after = _roles(admin, uid)
    assert after['roles'] == before and after['full_name'] == 'Bác sĩ đã đổi tên' and after['active'] in (1, True)
    assert client.put(f'/api/accounts/{uid}', headers=admin, json={}).status_code == 422
    assert client.put(f'/api/accounts/{uid}', headers=admin, json={'roles': []}).status_code == 422
    assert client.put(f'/api/accounts/{uid}', headers=admin, json={'roles': ['doctor']}).status_code == 200
    assert _roles(admin, uid)['roles'] == ['doctor']


def test_cannot_lock_or_demote_last_admin_and_non_admin_forbidden():
    admin = token('quantri')
    me = next(u for u in client.get('/api/accounts', headers=admin).json() if u['username'] == 'quantri')
    assert client.put(f"/api/accounts/{me['id']}", headers=admin, json={'active': False}).status_code == 409
    assert client.put(f"/api/accounts/{me['id']}", headers=admin, json={'roles': ['manager']}).status_code == 409
    assert client.put(f"/api/accounts/{me['id']}", headers=token('quanly'), json={'active': True}).status_code == 403
