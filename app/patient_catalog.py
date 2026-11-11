"""Public, source-backed catalogs. Patient names remain historical snapshots."""
import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, Query, UploadFile

from .manager_visits import fold_name

DATA = Path(__file__).resolve().parents[1] / 'du_lieu' / 'danh_muc'
GEO_HEADERS = ('Mã tỉnh (BNV)', 'Tên tỉnh/TP mới', 'Mã phường/xã mới', 'Tên Phường/Xã mới', 'Tên Quận huyện TMS (cũ)')
ETHNIC_HEADERS = ('Mã dân tộc', 'Tên dân tộc', 'Tên gọi khác')
CSV_GEO_HEADERS = GEO_HEADERS + ('Nguồn mã xã', 'Mã ĐVHC chính thức')
EXTRAS = [('ethnicity', 'FOREIGN', 'Người nước ngoài', '', '', '', '', None),
          ('ethnicity', 'UNKNOWN', 'Không rõ', '', '', '', '', None)]
COLUMNS = ('kind', 'code', 'name', 'parent_code', 'aliases', 'legacy_district', 'code_source', 'official_code')


def read_rows(raw, filename, header_row):
    """Bound uploaded workbooks; no formulas, external links, or guessed headers."""
    try:
        if filename.lower().endswith('.csv'):
            reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
            result = []
            for line, row in enumerate(reader, 1):
                if line > 20003: raise ValueError('Dòng 20004: tối đa 20.000 dòng dữ liệu')
                result.append((line, row))
            return result  # normalized CSV always has headers on line 1
        if not filename.lower().endswith('.xlsx'):
            raise ValueError('Dòng 1: chỉ nhận CSV UTF-8 hoặc Excel .xlsx')
        from openpyxl import load_workbook
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist()) > 1000 or sum(x.file_size for x in z.infolist()) > 20*1024*1024:
                raise ValueError('Dòng 1: Excel vượt giới hạn giải nén 20 MB')
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        try:
            if len(book.sheetnames) != 1: raise ValueError('Dòng 1: cần đúng một trang tính')
            sheet = book.active; sheet.reset_dimensions()
            result = []
            for line, cells in enumerate(sheet.iter_rows(max_col=32), 1):
                if line > 20003: raise ValueError('Dòng 20004: tối đa 20.000 dòng dữ liệu')
                if line < header_row: continue
                if any(c.data_type in ('f', 'e') for c in cells):
                    raise ValueError(f'Dòng {line}: không dùng công thức hoặc ô lỗi')
                result.append((line, [c.value for c in cells]))
            return result
        finally: book.close()
    except UnicodeDecodeError:
        raise ValueError('Dòng 1: CSV phải dùng UTF-8') from None
    except csv.Error:
        raise ValueError(f'Dòng {reader.line_num}: CSV không hợp lệ') from None
    except ValueError as exc:
        if str(exc).startswith('Dòng '):raise
        raise ValueError('Dòng 1: không đọc được tệp danh mục') from None
    except Exception:
        raise ValueError('Dòng 1: không đọc được tệp danh mục') from None


def text(value):
    if value is None: return ''
    if isinstance(value, float) and value.is_integer(): value = int(value)
    return str(value).strip()


def code(value, width=0):
    result = text(value)
    return result.zfill(width) if result.isascii() and result.isdigit() else result


def columns(rows, required):
    if not rows: raise ValueError('Dòng 1: thiếu cột: ' + ', '.join(required))
    line, row = rows[0]
    labels = [text(v) for v in row]
    missing = [name for name in required if name not in labels]
    if missing: raise ValueError(f'Dòng {line}: thiếu cột: ' + ', '.join(missing))
    if any(labels.count(name) != 1 for name in required):
        raise ValueError(f'Dòng {line}: trùng tên cột bắt buộc')
    return {name: i for i, name in enumerate(labels) if name}


def parse_geography(raw, filename, *, bundled=False):
    rows = read_rows(raw, filename, 3)
    cols = columns(rows, GEO_HEADERS)
    provinces, communes = {}, {}
    names = set()
    for line, row in rows[1:]:
        if not any(text(v) for v in row): continue
        get = lambda name: row[cols[name]] if name in cols and cols[name] < len(row) else None
        pc, pn = code(get(GEO_HEADERS[0]), 2), text(get(GEO_HEADERS[1]))
        cc, cn, district = code(get(GEO_HEADERS[2])), text(get(GEO_HEADERS[3])), text(get(GEO_HEADERS[4]))
        if not re.fullmatch(r'[0-9]{2}', pc) or not pn or not re.fullmatch(r'[0-9]+', cc) or not cn:
            raise ValueError(f'Dòng {line}: thiếu hoặc sai mã/tên tỉnh, xã')
        if max(map(len, (pn, cn, district, cc))) > 180: raise ValueError(f'Dòng {line}: giá trị dài quá 180 ký tự')
        if pc in provinces and provinces[pc][2] != pn: raise ValueError(f'Dòng {line}: mã tỉnh có hai tên khác nhau')
        if any(v[2] == pn and k != pc for k,v in provinces.items()): raise ValueError(f'Dòng {line}: tên tỉnh có hai mã khác nhau')
        if cc in communes: raise ValueError(f'Dòng {line}: trùng mã xã {cc}')
        if (pc, cn) in names: raise ValueError(f'Dòng {line}: trùng tên xã trong cùng tỉnh')
        official = text(get('Mã ĐVHC chính thức')) or None
        if official and not re.fullmatch(r'[0-9]+', official): raise ValueError(f'Dòng {line}: mã ĐVHC chính thức phải là chữ số')
        provinces[pc] = ('province', pc, pn, '', '', '', 'mã tỉnh BNV', None)
        communes[cc] = ('commune', cc, cn, pc, '', district, 'mã thuế TMS', official)
        names.add((pc, cn))
    if not communes: raise ValueError('Danh mục tỉnh/xã trống')
    if bundled and (len(provinces), len(communes)) != (34, 3321):
        raise ValueError(f'Danh mục đi kèm cần 34 tỉnh / 3.321 xã, nhận {len(provinces)} / {len(communes)}')
    return list(provinces.values()) + list(communes.values())


def parse_ethnicities(raw, filename, *, bundled=False):
    rows = read_rows(raw, filename, 1)
    cols = columns(rows, ETHNIC_HEADERS)
    result = {}; names = set()
    for line, row in rows[1:]:
        if not any(text(v) for v in row): continue
        get = lambda name: row[cols[name]] if cols[name] < len(row) else None
        ec, name, aliases = code(get(ETHNIC_HEADERS[0]), 2), text(get(ETHNIC_HEADERS[1])), text(get(ETHNIC_HEADERS[2]))
        if not re.fullmatch(r'(0[1-9]|[1-9][0-9])', ec) or not name or len(name) > 180 or len(aliases) > 4000:
            raise ValueError(f'Dòng {line}: mã, tên hoặc tên gọi khác của dân tộc không hợp lệ')
        if ec in result or name in names: raise ValueError(f'Dòng {line}: trùng mã hoặc tên dân tộc')
        result[ec] = ('ethnicity', ec, name, '', aliases, '', '', None); names.add(name)
    if not result: raise ValueError('Danh mục dân tộc trống')
    if bundled and set(result) != {f'{i:02d}' for i in range(1, 55)}:
        raise ValueError('Danh mục đi kèm cần đúng 54 dân tộc, mã 01–54 không trùng')
    return list(result.values()) + EXTRAS


def bundled_catalog(kind='all'):
    result = []
    if kind in ('all', 'geography'):
        result += parse_geography((DATA/'tinh_xa.csv').read_bytes(), 'tinh_xa.csv', bundled=True)
    if kind in ('all', 'ethnicity'):
        result += parse_ethnicities((DATA/'dan_toc.csv').read_bytes(), 'dan_toc.csv', bundled=True)
    return result


def apply_catalog(c, rows, kinds):
    """Upsert by code, retain removed rows, never rewrite a patient's name snapshot."""
    marks = ','.join('?' for _ in kinds)
    previous = {(r['kind'], r['code']): r['active'] for r in c.execute(f'SELECT kind,code,active FROM patient_catalog WHERE kind IN ({marks})', kinds)}
    incoming = {(r[0], r[1]) for r in rows}
    c.execute(f'UPDATE patient_catalog SET active=0 WHERE kind IN ({marks})', kinds)
    sql = '''INSERT INTO patient_catalog(kind,code,name,parent_code,aliases,legacy_district,code_source,official_code,active)
        VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(kind,code) DO UPDATE SET
        name=excluded.name,parent_code=excluded.parent_code,aliases=excluded.aliases,
        legacy_district=excluded.legacy_district,code_source=excluded.code_source,
        official_code=COALESCE(excluded.official_code,patient_catalog.official_code),active=1'''
    c.executemany(sql, rows)
    return {'imported': len(rows), 'added': len(incoming-previous.keys()),
            'updated': len(incoming & previous.keys()),
            'inactive': sum(bool(active) for key,active in previous.items() if key not in incoming),
            'provinces': sum(r[0]=='province' for r in rows),
            'communes': sum(r[0]=='commune' for r in rows),
            'ethnicities': sum(r[0]=='ethnicity' and r[1] not in ('FOREIGN','UNKNOWN') for r in rows)}


def migrate_public_catalog(c):
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=7').fetchone(): return
    rows = bundled_catalog()
    for name, definition in [('aliases', "TEXT NOT NULL DEFAULT ''"), ('legacy_district', "TEXT NOT NULL DEFAULT ''"),
            ('code_source', "TEXT NOT NULL DEFAULT ''"), ('official_code', 'TEXT'), ('active', 'INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))')]:
        c.execute(f'ALTER TABLE patient_catalog ADD COLUMN {name} {definition}')
    for name in ('province_code', 'commune_code', 'ethnicity_code'):
        c.execute(f'ALTER TABLE patients ADD COLUMN {name} TEXT')
    c.execute('CREATE INDEX idx_patient_catalog_parent ON patient_catalog(kind,parent_code,active)')
    summary = apply_catalog(c, rows, ('province','commune','ethnicity'))
    c.execute('INSERT INTO schema_migrations(version) VALUES(7)')
    c.execute("INSERT INTO audit_log(event,object_type,details,created_at) VALUES('patient_catalog_seeded','catalog',?,?)",
              (json.dumps(summary, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))


def resolve_patient_catalog(c, data, old=None):
    old = dict(old) if old is not None else {}
    for kind in ('province', 'commune', 'ethnicity'):
        number, name = getattr(data, kind+'_code'), getattr(data, kind)
        if not number and name and name == old.get(kind) and (kind!='commune' or data.province_code==old.get('province_code')):
            setattr(data, kind+'_code', old.get(kind+'_code'))
            continue
        if not number and name:
            args = [kind, name]
            where = 'kind=? AND name=? AND active=1'
            if kind == 'commune': where += ' AND parent_code=?'; args.append(data.province_code)
            row = c.execute('SELECT * FROM patient_catalog WHERE '+where, args).fetchone()
            if not row: raise HTTPException(422, 'Cần chọn '+{'province':'tỉnh/thành','commune':'xã/phường/đặc khu','ethnicity':'dân tộc'}[kind]+' từ danh mục')
            number = row['code']
        elif number:
            row = c.execute('SELECT * FROM patient_catalog WHERE kind=? AND code=?', (kind, number)).fetchone()
            if not row or (not row['active'] and number != old.get(kind+'_code')):
                raise HTTPException(422, 'Mã danh mục không có hoặc đã ngừng dùng')
        else:
            setattr(data, kind, None); continue
        historical_pair = old.get('commune_code') == number and old.get('province_code') == data.province_code
        if kind == 'commune' and row['parent_code'] != data.province_code and not historical_pair:
            raise HTTPException(422, 'Xã/phường/đặc khu không thuộc tỉnh/thành đã chọn')
        setattr(data, kind+'_code', number)
        setattr(data, kind, old.get(kind) if old.get(kind+'_code') == number and old.get(kind) else row['name'])


def search_catalog(c, kind='', province_code='', q='', limit=30):
    if kind == 'commune' and not province_code: return []
    where = 'active=1'; args = []
    if kind: where += ' AND kind=?'; args.append(kind)
    else: where += " AND kind<>'commune'"
    if kind == 'commune': where += ' AND parent_code=?'; args.append(province_code)
    rows = c.execute('SELECT * FROM patient_catalog WHERE '+where+' ORDER BY kind,code', args)
    needle = fold_name(q[:100])
    matches = [dict(r) for r in rows if needle in fold_name(r['name']+' '+r['aliases'])]
    if kind=='ethnicity' and not needle:matches.sort(key=lambda x:(x['code'] not in ('FOREIGN','UNKNOWN'),x['code']))
    return matches[:min(limit, 30) if kind == 'commune' else limit]


def install_patient_catalog(app, db, principal, require, audit):
    @app.get('/api/patient-catalog')
    def catalog(kind: str = '', province_code: str = '', q: str = '', limit: int = Query(100, ge=1, le=100), u=Depends(principal)):
        require(u, 'admin', 'reception', 'doctor')
        if kind not in ('', 'province', 'commune', 'ethnicity'): raise HTTPException(422, 'Loại danh mục không hợp lệ')
        with db() as c: return search_catalog(c, kind, province_code, q, limit)

    @app.post('/api/patient-catalog/import')
    def reload_catalog(kind: str = Form('all'), file: UploadFile | None = File(None), u=Depends(principal)):
        require(u, 'admin')
        if kind not in ('all','geography','ethnicity'): raise HTTPException(422, 'Chọn danh mục tỉnh/xã hoặc dân tộc')
        try:
            if file:
                if kind == 'all': raise ValueError('Chọn loại danh mục của tệp: Tỉnh/xã hoặc Dân tộc')
                raw = file.file.read(2*1024*1024+1)
                if len(raw)>2*1024*1024: raise HTTPException(413, 'Tệp danh mục tối đa 2 MB')
                rows = (parse_geography if kind == 'geography' else parse_ethnicities)(raw, file.filename or '')
            else: rows = bundled_catalog(kind)
        except ValueError as exc: raise HTTPException(422, str(exc)) from None
        kinds = ('province','commune','ethnicity') if kind == 'all' else ('province','commune') if kind == 'geography' else ('ethnicity',)
        with db(True) as c:
            result = apply_catalog(c, rows, kinds)
            audit(c, u, 'patient_catalog_imported', 'catalog', None, json.dumps(dict(result, kind=kind), ensure_ascii=False))
        return result
