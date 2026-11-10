from .conftest import IDS, db
from tests.m0_cases import check_m0


def test_m0_postgres_permissions_audit_closing_and_daily_queue(clients):
    check_m0(clients, IDS, db)


def test_six_payment_states_with_real_receipts(clients):
    from .conftest import SERVICE
    r, d, cashier = clients['reception'], clients['doctor'], clients['cashier']
    statuses = []
    for label, unknown, price, receipt in [
        ('Chưa phát sinh thu', False, 0, 0), ('Chưa xác định phí', True, 0, 0),
        ('Thu tạm', True, 0, 100), ('Còn nợ', False, 1000, 100),
        ('Cần hoàn', False, 100, 200), ('Đã thu đủ', False, 1000, 1000)]:
        pid = r.post('/api/patients', json={'full_name':'Giả lập thanh toán M0','sex':'Nữ','date_of_birth':'1990-01-01','phone':'0900000000'}).json()['id']
        vid = r.post('/api/visits', json={'patient_id':pid,'doctor_id':IDS['doctor'],'service_id':SERVICE}).json()['id']
        # Establish the fee fixture, then receive money through the real cashier API.
        with db(True) as c:
            c.execute('UPDATE charges SET amount=? WHERE visit_id=?', (None if unknown else max(price, receipt),vid))
        if receipt:
            import secrets
            paid = cashier.post('/api/payments', json={'visit_id':vid,'amount':receipt,'method':'cash','confirm_over_limit':True,'idempotency_key':secrets.token_hex(16)})
            assert paid.status_code == 201, paid.text
        if label == 'Cần hoàn':
            # Approved price correction creates a genuine excess on an existing receipt.
            charge = cashier.get(f'/api/charges/{vid}').json()[0]['id']
            response = clients['manager'].post(f'/api/charges/{charge}/reprice', json={'amount':price,'reason':'Điều chỉnh giá giả lập M0','request_key':'m0-reprice-'+str(vid)})
            assert response.status_code == 200, response.text
        result = d.get(f'/api/visits/{vid}/payment-status').json()
        assert result['status'] == label, result
        assert result['paid'] == receipt
        assert result['receipt_count'] == int(bool(receipt))
        statuses.append(result['status'])
    assert len(set(statuses)) == 6
