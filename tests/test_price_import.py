"""Service-price Excel imports use fake services, patients and payments only."""
import io
import json
import re
import secrets
import sqlite3
import zipfile

import pytest
from openpyxl import Workbook, load_workbook

from app.database import db
from app.price_import import GROUPS, HEADERS, MAX_BYTES, read_rows
from tests.test_workflows import client, token, prepare_visit


def workbook(rows, headers=HEADERS, instruction=True):
    w = Workbook()
    if instruction:
        w.active.append(['Hướng dẫn nhập dữ liệu giả lập'])
    w.active.append(headers)
    for row in rows:
        w.active.append(row)
    out = io.BytesIO()
    w.save(out)
    return out.getvalue()


@pytest.fixture(scope='module')
def manager():
    return token('quanly')


def upload(headers, content, preview_id=None, name='BANG_GIA.xlsx'):
    return client.post('/api/catalog/services/import/' + ('confirm' if preview_id is not None else 'preview'),
                       headers={**headers, 'X-File-Name': name, **({'X-Preview-Id': preview_id} if preview_id is not None else {})}, content=content)


def create_service(manager, price=45000, active=True):
    name = 'Dịch vụ nhập giả lập ' + secrets.token_hex(6)
    code = 'TEST' + secrets.token_hex(6)
    r = client.post('/api/catalog/services', headers=manager,
                    json={'name': name, 'code': code, 'price': price, 'category': 'lab', 'active': active})
    assert r.status_code == 201, r.text
    return r.json()['id'], code, name


def service(sid):
    with db() as c:
        return dict(c.execute('SELECT * FROM service_catalog WHERE id=?', (sid,)).fetchone())


def test_template_one_sheet_dropdown_and_integer_validation(manager):
    r = client.get('/api/catalog/services/import/template', headers=manager)
    assert r.status_code == 200
    w = load_workbook(io.BytesIO(r.content))
    assert len(w.sheetnames) == 1
    assert [c.value for c in w.active[2]] == list(HEADERS)
    validations = w.active.data_validations.dataValidation
    assert next(d for d in validations if d.type == 'list').formula1 == '"' + ','.join(GROUPS) + '"'
    assert next(d for d in validations if d.type == 'whole').formula1 == '0'
    assert 'Hướng dẫn' in w.active['A1'].value


def test_preview_confirm_reimport_and_missing_services(manager):
    sid, code, name = create_service(manager)
    new_code, new_name = 'NEW' + secrets.token_hex(5), 'Dịch vụ mới ' + secrets.token_hex(5)
    data = workbook([(code.lower(), '  ' + name.upper().replace(' ', '   ') + ' ', 'Xét nghiệm', 60000),
                     (new_code, new_name, 'Khám', 0)])
    before = upload(manager, data).json()
    assert before['can_confirm'] and [r['status'] for r in before['rows']] == ['ĐỔI GIÁ', 'THÊM MỚI']
    assert before['rows'][0]['old_price'] == 45000
    assert sid not in [s['id'] for s in before['missing']] and before['missing']
    absent = before['missing'][0]
    assert service(sid)['price'] == 45000  # preview is read-only
    imported = upload(manager, data, before['preview_id'])
    assert imported.status_code == 200, imported.text
    assert imported.json() == {'rows': 2, 'added': 1, 'changed': 1, 'unchanged': 0}
    assert service(sid)['name'] == name and service(sid)['price'] == 60000
    assert service(absent['id'])['price'] == absent['price']
    again = upload(manager, data).json()
    assert [r['status'] for r in again['rows']] == ['KHÔNG ĐỔI', 'KHÔNG ĐỔI']
    assert upload(manager, data, again['preview_id']).json()['unchanged'] == 2
    with db() as c:
        logs = [dict(r) for r in c.execute("SELECT * FROM audit_log WHERE event IN ('service_price_imported','service_prices_imported') ORDER BY id DESC LIMIT 3")]
    assert all(r['user_id'] for r in logs)
    detail = json.loads(next(r['details'] for r in logs if r['event'] == 'service_price_imported'))
    assert detail['old_price'] == 45000 and detail['new_price'] == 60000


@pytest.mark.parametrize('row,reason', [
    (('ERR01', 'Dịch vụ lỗi', 'Khám', -1), 'Giá phải'),
    (('ERR01', 'Dịch vụ lỗi', 'Khám', '50000'), 'Giá phải'),
    (('ERR01', 'Dịch vụ lỗi', 'Khám', 1.5), 'Giá phải'),
    (('ERR01', 'Dịch vụ lỗi', 'Khám', True), 'Giá phải'),
    (('ERR01', 'Dịch vụ lỗi', 'Thủ thuật', 1), 'Nhóm không hợp lệ'),
    (('ERR01', '', 'Khám', 1), 'Tên dịch vụ không được trống'),
    (('ERR01', 'Dịch vụ lỗi', 'Khám', '=1+2'), 'Không dùng công thức'),
])
def test_bad_row_blocks_whole_import(manager, row, reason):
    sid, code, name = create_service(manager)
    data = workbook([(code, name, 'Xét nghiệm', 99000), row])
    result = upload(manager, data).json()
    assert not result['can_confirm']
    assert result['rows'][1]['status'] == 'LỖI' and reason in '; '.join(result['rows'][1]['errors'])
    assert upload(manager, data, result['preview_id']).status_code == 422
    assert service(sid)['price'] == 45000


@pytest.mark.parametrize('rows', [
    [('DUP01', 'Tên một', 'Khám', 1), ('dup01', 'Tên hai', 'Khám', 2)],
    [('DUP01', 'Tên trùng', 'Khám', 1), ('DUP02', '  TÊN   TRÙNG ', 'Xét nghiệm', 2)],
])
def test_duplicates_mark_both_rows(manager, rows):
    result = upload(manager, workbook(rows)).json()
    assert not result['can_confirm'] and all(r['status'] == 'LỖI' for r in result['rows'])
    assert upload(manager, workbook(rows), result['preview_id']).status_code == 422


def test_missing_column_and_sheet_count(manager):
    assert upload(manager, workbook([('Tên', 'Khám', 1)], headers=HEADERS[1:])).status_code == 422
    w = Workbook(); w.create_sheet('Sai'); out = io.BytesIO(); w.save(out)
    assert upload(manager, out.getvalue()).status_code == 422


def test_all_existing_groups_and_no_instruction_line(manager):
    data = workbook([('GROUP' + str(i), 'Nhóm giả lập ' + str(i), group, 0)
                     for i, group in enumerate(GROUPS)], instruction=False)
    result = upload(manager, data)
    assert result.status_code == 200, result.text
    assert result.json()['can_confirm']
    assert [r['category'] for r in result.json()['rows']] == list(GROUPS.values())


def test_generated_code_does_not_collide_with_later_file_row(manager):
    with db() as c:
        next_id = c.execute('SELECT MAX(id)+1 FROM service_catalog').fetchone()[0]
    reserved = 'DV' + str(next_id)
    tag = secrets.token_hex(5)
    data = workbook([('', 'Tự cấp mã ' + tag, 'Khám', 0),
                     (reserved, 'Mã đã điền ' + tag, 'Khám', 1)])
    p = upload(manager, data).json()
    assert p['can_confirm']
    assert upload(manager, data, p['preview_id']).status_code == 200
    assert service(next_id)['code'] == reserved + '_1'
    assert service(next_id + 1)['code'] == reserved


def test_cached_formula_and_macro_workbooks_rejected(manager):
    data = workbook([('FORMULA01', 'Giả lập công thức', 'Khám', '=100+200')])
    for macro in (False, True):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(out, 'w') as modified:
            for item in original.infolist():
                value = original.read(item.filename)
                if item.filename == 'xl/worksheets/sheet1.xml':
                    value = value.replace(b'<v></v>', b'<v>300</v>')
                modified.writestr(item, value)
            if macro:
                modified.writestr('xl/vbaProject.bin', b'not executed')
        response = upload(manager, out.getvalue())
        if macro:
            assert response.status_code == 415
        else:
            assert response.json()['rows'][0]['status'] == 'LỖI'


def test_file_limits_and_fake_xlsx(manager):
    good = workbook([('VALID01', 'Giả lập', 'Khám', 1)])
    assert upload(manager, good, name='test.xls').status_code == 415
    assert upload(manager, b'x' * (MAX_BYTES + 1)).status_code == 413
    assert upload(manager, b'not a zip').status_code == 422
    assert upload(manager, workbook([('A1', 'Giả lập', 'Khám', 1)] * 2001)).status_code == 422
    # ZIP bomb rejected before XML parsing, with no extraction to disk.
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('bomb', b'0' * (16 * 1024 * 1024 + 1))
    assert upload(manager, out.getvalue()).status_code == 422
    assert len(read_rows(workbook([('A1', 'Giả lập', 'Khám', 1)] * 2000))) == 2000


@pytest.mark.parametrize('user', ['letan', 'bs_noi', 'bs_san', 'kythuat', 'dieuduong', 'duoc', 'thungan'])
def test_api_permission_checks(user):
    headers = token(user)
    data = workbook([('VALID01', 'Giả lập', 'Khám', 1)])
    assert upload(headers, data).status_code == 403
    assert upload(headers, data, 'untrusted').status_code == 403
    assert client.get('/api/catalog/services/import/template', headers=headers).status_code == 403


def test_admin_allowed_and_confirm_requires_preview():
    headers = token('quantri')
    data = workbook([('ADMIN01', 'Giả lập quản trị', 'Khám', 1)])
    assert upload(headers, data).status_code == 200
    assert client.post('/api/catalog/services/import/confirm', headers={**headers, 'X-File-Name': 'x.xlsx'}, content=data).status_code == 422
    assert upload({}, data).status_code == 401


def test_stale_preview_changed_file_and_metadata_mismatch(manager):
    sid, code, name = create_service(manager)
    data = workbook([(code, name, 'Xét nghiệm', 90000)])
    result = upload(manager, data).json()
    assert upload(manager, workbook([(code, name, 'Xét nghiệm', 91000)]), result['preview_id']).status_code == 409
    with db(True) as c:
        c.execute('UPDATE service_catalog SET price=50000 WHERE id=?', (sid,))
    assert upload(manager, data, result['preview_id']).status_code == 409
    assert service(sid)['price'] == 50000
    wrong = upload(manager, workbook([(code, 'Tên khác', 'Khám', 90000)])).json()
    assert wrong['rows'][0]['status'] == 'LỖI'


def test_audit_failure_rolls_back_all_prices_and_new_service(manager):
    sid, code, name = create_service(manager)
    new_code = 'ROLL' + secrets.token_hex(5)
    data = workbook([(new_code, 'Dịch vụ rollback ' + new_code, 'Khám', 1), (code, name, 'Xét nghiệm', 90000)])
    result = upload(manager, data).json()
    with db(True) as c:
        c.execute("CREATE TRIGGER price_import_fail BEFORE INSERT ON audit_log WHEN NEW.event='service_prices_imported' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            upload(manager, data, result['preview_id'])
        assert service(sid)['price'] == 45000
        with db() as c:
            assert not c.execute('SELECT 1 FROM service_catalog WHERE code=?', (new_code,)).fetchone()
    finally:
        with db(True) as c:
            c.execute('DROP TRIGGER price_import_fail')


def test_old_charge_receipt_and_draft_keep_price_new_order_uses_import(manager):
    sid, code, name = create_service(manager)
    _, vid = prepare_visit()
    doc, cash = token('bs_noi'), token('thungan')
    body = {'visit_id': vid, 'category': 'lab', 'service_id': sid}
    original = client.post('/api/orders', headers=doc, json={**body, 'request_key': secrets.token_hex(10)})
    assert original.json()['charge_amount'] == 45000
    draft = client.post('/api/orders', headers=doc, json={**body, 'defer_approval': True, 'request_key': secrets.token_hex(10)}).json()['id']
    payment = client.post('/api/payments', headers=cash, json={'visit_id': vid, 'amount': 10000, 'method': 'cash', 'idempotency_key': secrets.token_hex(10)}).json()['id']
    charges_before = client.get(f'/api/charges/{vid}', headers=cash).json()
    receipt_before = client.get(f'/api/print/receipt/{payment}', headers=cash).content
    with db() as c:
        payment_before = dict(c.execute('SELECT * FROM payments WHERE id=?', (payment,)).fetchone())
        order_before = dict(c.execute('SELECT * FROM orders WHERE id=?', (original.json()['id'],)).fetchone())
    data = workbook([(code, name, 'Xét nghiệm', 90000)])
    p = upload(manager, data).json()
    assert upload(manager, data, p['preview_id']).status_code == 200
    assert client.get(f'/api/charges/{vid}', headers=cash).json() == charges_before
    import pymupdf
    def printed_text(pdf):
        with pymupdf.open(stream=pdf, filetype='pdf') as document:
            text = ''.join(page.get_text() for page in document)
        # Reprinting can cross a minute boundary; only the print timestamp may change.
        return re.sub(r'Ngày in:\s*\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}', 'Ngày in: [thời điểm in]', text)
    assert printed_text(client.get(f'/api/print/receipt/{payment}', headers=cash).content) == printed_text(receipt_before)
    with db() as c:
        assert dict(c.execute('SELECT * FROM payments WHERE id=?', (payment,)).fetchone()) == payment_before
        assert dict(c.execute('SELECT * FROM orders WHERE id=?', (original.json()['id'],)).fetchone()) == order_before
    assert client.post(f'/api/orders/{draft}/authorize', headers=doc).json()['charge_amount'] == 45000
    assert client.post('/api/orders', headers=doc, json={**body, 'request_key': secrets.token_hex(10)}).json()['charge_amount'] == 90000
