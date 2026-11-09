"""Cài đặt bật/tắt chức năng phụ: chỉ quản trị đổi được, lưu ở máy chủ, có nhật ký."""
from tests.test_workflows import client, token


def test_defaults_and_admin_only_update():
    reception = token('letan')
    current = client.get('/api/ui-settings', headers=reception)
    assert current.status_code == 200
    assert current.json() == {'advance_payment': False, 'addendum': True, 'controlled_drugs': True}
    assert client.get('/api/ui-settings').status_code == 401
    for user in ('letan', 'quanly', 'thungan', 'bs_noi'):
        assert client.put('/api/ui-settings', headers=token(user), json={'advance_payment': True}).status_code == 403
    admin = token('quantri')
    assert client.put('/api/ui-settings', headers=admin, json={'unknown': True}).status_code == 422
    assert client.put('/api/ui-settings', headers=admin, json={'advance_payment': 'yes'}).status_code == 422
    changed = client.put('/api/ui-settings', headers=admin, json={'advance_payment': True, 'controlled_drugs': False})
    assert changed.status_code == 200
    assert changed.json() == {'advance_payment': True, 'addendum': True, 'controlled_drugs': False}
    assert client.get('/api/ui-settings', headers=reception).json()['controlled_drugs'] is False
    log = client.get('/api/audit?limit=20', headers=admin).json()
    assert any(x['event'] == 'ui_settings_changed' and 'advance_payment=bật' in x['details'] for x in log)
    restored = client.put('/api/ui-settings', headers=admin, json={'advance_payment': False, 'controlled_drugs': True})
    assert restored.json() == {'advance_payment': False, 'addendum': True, 'controlled_drugs': True}


def test_hidden_feature_keeps_server_permission_checks():
    """Tắt trên giao diện không mở thêm và không khóa API: quyền vẫn kiểm như cũ."""
    admin = token('quantri')
    client.put('/api/ui-settings', headers=admin, json={'advance_payment': False})
    # Lễ tân vẫn không nhận tiền được; thu ngân vẫn gọi được API (kiểm tra quyền giữ nguyên).
    assert client.post('/api/payments', headers=token('letan'), json={'visit_id': 1, 'amount': 1000, 'method': 'cash', 'idempotency_key': 'ui-settings-1', 'prepayment': True}).status_code == 403
