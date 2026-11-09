"""Bounded, memory-only Excel service-price import; never rewrite charge snapshots."""
import hashlib
import io
import json
import math
import re
import zipfile

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from starlette.concurrency import run_in_threadpool

from .database import ROOT

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
GROUPS = {'Khám': 'consultation', 'Xét nghiệm': 'lab', 'Siêu âm': 'ultrasound',
          'X-quang': 'xray', 'Điện tim': 'ecg', 'Thủ thuật': 'procedure'}
HEADERS = ('Mã dịch vụ (không bắt buộc)', 'Tên dịch vụ', 'Nhóm', 'Giá (đồng, số nguyên ≥ 0)')
HEADER_ALIASES = {'Mã dịch vụ': HEADERS[0], 'Giá (đồng)': HEADERS[3]}
REFERENCE_COLUMNS = {'Phân nhóm (tham khảo)', 'Dòng trong tệp gốc'}


def clean(value):
    return ' '.join(str(value or '').split())


def key(value):
    return clean(value).casefold()


def read_rows(content):
    """No macro loading, external links or formula evaluation, including cached formulas."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            # Bound decompression before openpyxl allocates XML/shared strings.
            if len(entries) > 100 or sum(x.file_size for x in entries) > 16 * 1024 * 1024:
                raise HTTPException(422, 'Tệp Excel có nội dung giải nén quá lớn')
            types = archive.read('[Content_Types].xml')
            if (b'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml' not in types
                    or any('vbaproject' in x.filename.casefold() for x in entries)):
                raise HTTPException(415, 'Chỉ nhận tệp .xlsx, không nhận tệp có macro')
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        try:
            if len(workbook.sheetnames) == 1:
                sheet = workbook.active
            elif set(workbook.sheetnames) == {'BANG_GIA', 'CAN_XEM_LAI'}:
                # The supplied clinic workbook has one data sheet and a named
                # review-notes sheet. Never select an arbitrary active sheet.
                sheet = workbook['BANG_GIA']
            else:
                raise HTTPException(422, 'Dùng tệp mẫu một trang tính; tệp tổng hợp chỉ được có BANG_GIA và CAN_XEM_LAI')
            # Do not trust the worksheet dimension advertised by an uploaded file.
            sheet.reset_dimensions()
            rows = []
            columns = None
            for number, cells in enumerate(sheet.iter_rows(max_col=7), 1):
                if number > MAX_ROWS + 2:
                    raise HTTPException(422, 'Tệp vượt giới hạn 2.000 dòng dữ liệu (không tính hướng dẫn và tiêu đề)')
                values = [c.value for c in cells]
                if columns is None:
                    if not any(v is not None for v in values):
                        continue
                    labels = [HEADER_ALIASES.get(clean(v), clean(v)) for v in values]
                    while labels and not labels[-1]:
                        labels.pop()
                    if 'Tên dịch vụ' not in labels and number == 1 and len([v for v in values if v is not None]) == 1:
                        continue  # Optional instruction row in the supplied template.
                    missing = [h for h in HEADERS if h not in labels]
                    if missing:
                        raise HTTPException(422, 'Thiếu cột: ' + ', '.join(missing))
                    if len(set(labels)) != len(labels) or set(labels) - set(HEADERS) - REFERENCE_COLUMNS:
                        raise HTTPException(422, 'Tệp cần đủ bốn cột của mẫu, không trùng tiêu đề; chỉ thêm cột tham khảo đã có trong tệp tổng hợp')
                    columns = [labels.index(h) for h in HEADERS]
                    continue
                if not any(v is not None and v != '' for v in values):
                    continue
                chosen = [cells[i] if i < len(cells) else None for i in columns]
                code, name, group, price = [c.value if c is not None else None for c in chosen]
                errors = []
                if any(c is not None and c.data_type in ('f', 'e') for c in chosen):
                    errors.append('Không dùng công thức hoặc ô lỗi; hãy dán giá trị')
                code, name, group = clean(code), clean(name), clean(group)
                group = next((label for label in GROUPS if key(label) == key(group)), group)
                if code and not re.fullmatch(r'[A-Za-z0-9_-]{2,40}', code):
                    errors.append('Mã dịch vụ cần 2–40 chữ không dấu, số, dấu gạch ngang hoặc gạch dưới')
                if not 2 <= len(name) <= 180:
                    errors.append('Tên dịch vụ không được trống, cần từ 2 đến 180 ký tự')
                if group not in GROUPS:
                    errors.append('Nhóm không hợp lệ; chọn: ' + ', '.join(GROUPS))
                manual = price is None or (isinstance(price, str) and not price.strip())
                if manual:
                    price = None
                elif (type(price) not in (int, float) or price < 0 or price > 2_000_000_000
                        or not math.isfinite(price) or int(price) != price):
                    errors.append('Giá phải là số nguyên từ 0 đến 2.000.000.000 đồng')
                    price = None
                else:
                    price = int(price)
                if any(v is not None and v != '' for v in values[len(labels):]):
                    errors.append('Dữ liệu nằm ngoài các cột có tiêu đề')
                rows.append({'row': number, 'code': code, 'name': name, 'group': group,
                             'category': GROUPS.get(group), 'price': price, 'price_at_collection': manual, 'errors': errors})
                if len(rows) > MAX_ROWS:
                    raise HTTPException(422, 'Tệp vượt giới hạn 2.000 dòng dữ liệu')
            if not columns or not rows:
                raise HTTPException(422, 'Tệp chưa có dữ liệu dịch vụ hoặc thiếu tiêu đề')
            return rows
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, 'Không đọc được tệp .xlsx; tệp hỏng hoặc không đúng định dạng') from exc


def preview(c, rows):
    services = [dict(x) for x in c.execute(
        "SELECT sc.*,COALESCE(cat.category,'consultation') AS category FROM service_catalog sc "
        'LEFT JOIN service_categories cat ON cat.service_id=sc.id ORDER BY sc.id')]
    by_code, by_name = {}, {}
    for service in services:
        if service['code']:
            by_code.setdefault(key(service['code']), []).append(service)
        by_name.setdefault(key(service['name']), []).append(service)
    seen_codes, seen_names, matched = {}, {}, set()
    for row in rows:
        for value, seen, label in ((key(row['code']), seen_codes, 'mã'),
                                    (key(row['name']), seen_names, 'tên')):
            if value:
                if value in seen:
                    reason = 'Trùng ' + label + ' dịch vụ trong tệp'
                    row['errors'].append(reason)
                    seen[value]['errors'].append(reason)
                else:
                    seen[value] = row
        candidates = by_code.get(key(row['code']), []) if row['code'] else [s for s in by_name.get(key(row['name']), []) if s['category'] == row['category']]
        service = candidates[0] if len(candidates) == 1 else None
        if len(candidates) > 1:
            row['errors'].append('Có nhiều dịch vụ khớp trong hệ thống; cần kiểm tra lại danh mục')
        row['service_id'] = service['id'] if service else None
        row['matched_code'] = service['code'] if service else None
        row['old_price'] = service['price'] if service else None
        row['old_price_at_collection'] = bool(service['price_at_collection']) if service else False
        if row['old_price_at_collection']:
            row['old_price'] = None
        if service:
            matched.add(service['id'])
            if key(row['name']) != key(service['name']) or row['category'] != service['category']:
                row['errors'].append('Mã đã có nhưng Tên dịch vụ hoặc Nhóm khác danh mục; kiểm tra lại mã')
        elif key(row['name']) in by_name:
            row['errors'].append('Tên dịch vụ đã có; hãy điền đúng Mã dịch vụ hiện có')
        same_price = service and row['price_at_collection'] == bool(service['price_at_collection']) and (row['price_at_collection'] or row['price'] == service['price'])
        row['status'] = 'THÊM MỚI' if not service else ('KHÔNG ĐỔI' if same_price else 'ĐỔI GIÁ')
    # A duplicate discovered later must also mark the first row as invalid.
    for row in rows:
        if row['errors']:
            row['status'] = 'LỖI'
    fingerprint = hashlib.sha256(json.dumps([services, rows], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'rows': rows, 'missing': [s for s in services if s['id'] not in matched],
            'can_confirm': not any(r['errors'] for r in rows), 'preview_id': fingerprint}


def install_price_import(app, db, principal, require, audit):
    @app.get('/api/catalog/services/import/template')
    def template(u=Depends(principal)):
        require(u, 'admin', 'manager')
        return FileResponse(ROOT / 'templates/nhap_lieu/BANG_GIA.xlsx', filename='BANG_GIA.xlsx')

    def process(content, u, expected=None):
        rows = read_rows(content)
        with db(expected is not None) as c:
            result = preview(c, rows)
            if expected is None:
                return result
            if not result['can_confirm']:
                raise HTTPException(422, 'Tệp có dòng lỗi; chưa nhập dòng nào. Hãy sửa và xem trước lại')
            if expected != result['preview_id']:
                raise HTTPException(409, 'Tệp hoặc bảng giá đã thay đổi. Hãy xem trước lại trước khi xác nhận')
            added = changed = 0
            for row in rows:
                if row['status'] == 'THÊM MỚI':
                    c.execute('INSERT INTO service_catalog(name,price,code,active,price_at_collection) VALUES(?,?,?,1,?)',
                              (row['name'], row['price'] if row['price'] is not None else 0, row['code'] or None, int(row['price_at_collection'])))
                    sid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    if not row['code']:
                        # Follow existing DV<id> convention; also avoid imported codes.
                        base = code = 'DV' + str(sid)
                        suffix = 0
                        reserved = {key(r['code']) for r in rows if r['code']}
                        while key(code) in reserved or c.execute('SELECT 1 FROM service_catalog WHERE lower(code)=?', (key(code),)).fetchone():
                            suffix += 1
                            code = base + '_' + str(suffix)
                        c.execute('UPDATE service_catalog SET code=? WHERE id=?', (code, sid))
                    c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)', (sid, row['category']))
                    added += 1
                elif row['status'] == 'ĐỔI GIÁ':
                    c.execute('UPDATE service_catalog SET price=?,price_at_collection=? WHERE id=?',
                              (row['price'] if row['price'] is not None else 0, int(row['price_at_collection']), row['service_id']))
                    audit(c, u, 'service_price_imported', 'service', row['service_id'], json.dumps(
                        {'row': row['row'], 'code': row['code'], 'name': row['name'],
                         'old_price': row['old_price'], 'new_price': row['price'], 'price_at_collection': row['price_at_collection']}, ensure_ascii=False))
                    changed += 1
            audit(c, u, 'service_prices_imported', 'service_import', None, json.dumps(
                {'rows': len(rows), 'added': added, 'changed': changed, 'unchanged': len(rows)-added-changed,
                 'preview_id': expected}, ensure_ascii=False))
            return {'rows': len(rows), 'added': added, 'changed': changed, 'unchanged': len(rows)-added-changed}

    async def upload(request, u, confirm=False):
        require(u, 'admin', 'manager')
        if not request.headers.get('x-file-name', '').casefold().endswith('.xlsx'):
            raise HTTPException(415, 'Chỉ nhận tệp .xlsx')
        # Raw binary body avoids multipart SpooledTemporaryFile writing to disk.
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise HTTPException(413, 'Tệp vượt giới hạn 2 MB')
        expected = request.headers.get('x-preview-id') if confirm else None
        if confirm and not expected:
            raise HTTPException(422, 'Cần xem trước tệp trước khi xác nhận')
        return await run_in_threadpool(process, bytes(content), u, expected)

    @app.post('/api/catalog/services/import/preview')
    async def view(request: Request, u=Depends(principal)):
        return await upload(request, u)

    @app.post('/api/catalog/services/import/confirm')
    async def confirm(request: Request, u=Depends(principal)):
        return await upload(request, u, confirm=True)
