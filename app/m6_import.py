"""Optional Excel import: parse every row before any write; preview is read-only."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from fastapi import Depends, UploadFile, File, Form, HTTPException
from openpyxl import load_workbook
from pydantic import ValidationError
from .m6 import DrugInput, fold, dump

HEADERS = ('STT', 'Tên thuốc (tên thương mại)', 'Hoạt chất', 'Hàm lượng', 'Dạng bào chế', 'Đường dùng', 'Đơn vị tính', 'Số đăng ký', 'Nhà sản xuất', 'Ghi chú')


def parse(raw):
    if len(raw) > 2*1024*1024: raise HTTPException(413, 'Tệp tối đa 2 MB')
    try:
        with ZipFile(BytesIO(raw)) as z:
            if sum(x.file_size for x in z.infolist()) > 20*1024*1024: raise ValueError('Excel quá lớn sau giải nén')
        book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        if 'DanhMucThuoc' not in book.sheetnames: raise ValueError('Thiếu sheet DanhMucThuoc')
        sheet = book['DanhMucThuoc']
        if (sheet.max_row or 0) > 20001 or (sheet.max_column or 0) > 32: raise ValueError('Tối đa 20.000 dòng và 32 cột')
        iterator = sheet.iter_rows(); header = [str(c.value or '').strip() for c in next(iterator)]
        missing = [h for h in HEADERS if h not in header]
        if missing: raise ValueError('Thiếu cột: '+', '.join(missing))
        if len(set(header)) != len(header): raise ValueError('Dòng 1: trùng tên cột')
        rows = []; errors = []; seen = set()
        for number, cells in enumerate(iterator, 2):
            values = [str(c.value or '').strip() for c in cells]
            if not any(values): continue
            record = dict(zip(header, values))
            if record['Tên thuốc (tên thương mại)'].upper().startswith('VÍ DỤ'): continue
            try:
                if any(c.data_type in ('f', 'e') for c in cells): raise ValueError('Không chấp nhận công thức hoặc ô lỗi')
                item = DrugInput(name=record[HEADERS[1]], brand_name=record[HEADERS[1]], ingredient=record['Hoạt chất'],
                    strength=record['Hàm lượng'], dosage_form=record['Dạng bào chế'], route=record['Đường dùng'], unit=record['Đơn vị tính'],
                    registration_number=record['Số đăng ký'], manufacturer=record['Nhà sản xuất'], notes=record['Ghi chú'])
                key = (fold(item.name), fold(item.strength))
                if key in seen: raise ValueError('Trùng tên + hàm lượng trong tệp')
                seen.add(key); rows.append({'row': number, 'drug': item.model_dump()})
            except (ValueError, ValidationError) as exc:
                errors.append({'row': number, 'message': 'Thông tin thuốc không hợp lệ' if isinstance(exc, ValidationError) else str(exc)})
        book.close()
        if errors: raise HTTPException(422, {'message': 'Tệp có dòng lỗi; chưa nạp dữ liệu', 'errors': errors})
        if not rows: raise ValueError('Tệp không có dòng thuốc hợp lệ')
        return rows
    except HTTPException: raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(422, 'Excel không hợp lệ: cần sheet DanhMucThuoc và đủ cột mẫu') from None


def install_import(app, db, principal, require, audit):
    @app.get('/api/drugs/template')
    def template(u=Depends(principal)):
        require(u, 'admin')
        from pathlib import Path
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1]/'templates'/'nhap_lieu'/'DANH_MUC_THUOC_GIA_LAP.xlsx', filename='DANH_MUC_THUOC_GIA_LAP.xlsx', headers={'Cache-Control':'no-store'})

    @app.post('/api/drugs/import')
    def import_drugs(file: UploadFile = File(...), preview: bool = Form(True), u=Depends(principal)):
        require(u, 'admin')
        rows = parse(file.file.read(2*1024*1024+1))
        if preview: return {'preview': True, 'rows': rows, 'count': len(rows)}
        added = 0; updated = 0
        with db(True) as c:
            for row in rows:
                d = row['drug']; key = (fold(d['name']), fold(d['strength']))
                old = c.execute('SELECT * FROM drugs WHERE name_key=? AND strength_key=?', key).fetchone()
                # Import never silently overwrites a reviewed/inactive/merged item.
                if old and old['review_status'] != 'unreviewed': continue
                values = {k: v for k, v in d.items() if k not in ('toxic', 'controlled_type', 'review_status', 'national_code')}
                values.update(name_key=key[0], strength_key=key[1], ingredient_key=fold(d['ingredient']), brand_key=fold(d['brand_name']))
                if old:
                    c.execute('UPDATE drugs SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), old['id'])); updated += 1
                else:
                    c.execute('INSERT INTO drugs('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')', tuple(values.values())); added += 1
            audit(c, u, 'drugs_imported', 'drug', None, dump({'added': added, 'updated': updated}))
        return {'added': added, 'updated': updated, 'skipped': len(rows)-added-updated}
