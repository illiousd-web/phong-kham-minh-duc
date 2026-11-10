"""Administrative patient fields, file-supplied catalogs and child prescribing guard."""
import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Literal

from fastapi import Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator

from .labels import VN_TZ
from .domain import ensure_open, revision


def masked_document(value):
    return ('••••' + value[-4:]) if value else None


def document_value(patient):
    return patient.get('document_number') or patient.get('citizen_id')


def redact_document(patient):
    data = dict(patient)
    for key in ('citizen_id', 'document_number'):
        if key in data:
            data[key] = masked_document(data[key])
    return data


def months_old(birthday, now=None):
    if not birthday:
        return None
    today = (now or datetime.now(VN_TZ)).astimezone(VN_TZ).date()
    born = date.fromisoformat(birthday)
    return (today.year-born.year)*12 + today.month-born.month - (today.day < born.day)


class AdministrativePatient(BaseModel):
    document_type: Literal['identity', 'passport', 'none'] | None = None
    document_number: str | None = Field(default=None, max_length=40)
    # Legacy API input stays supported; full numbers never leave a list endpoint.
    citizen_id: str | None = Field(default=None, max_length=24)
    ethnicity: str | None = Field(default=None, max_length=180)
    occupation: str | None = Field(default=None, max_length=180)
    workplace: str | None = Field(default=None, max_length=300)
    province: str | None = Field(default=None, max_length=180)
    commune: str | None = Field(default=None, max_length=180)
    address_detail: str | None = Field(default=None, max_length=300)

    @field_validator('*', mode='before')
    @classmethod
    def trim(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode='after')
    def documents(self):
        if self.citizen_id and self.document_number and self.citizen_id != self.document_number:
            raise ValueError('Hai ô số giấy tờ không khớp')
        if self.citizen_id and not self.document_type:
            self.document_type = 'identity'
        self.document_number = self.document_number or self.citizen_id
        if self.document_type in (None, 'none'):
            if self.document_number:
                raise ValueError('Cần chọn loại giấy tờ')
        elif not self.document_number:
            raise ValueError('Đã chọn loại giấy tờ thì phải nhập số giấy tờ')
        elif self.document_type == 'identity' and not re.fullmatch(r'[0-9]{12}', self.document_number):
            raise ValueError('CCCD / số định danh phải đúng 12 chữ số')
        elif self.document_type == 'passport' and not re.fullmatch(r'[A-Za-z0-9]+', self.document_number):
            raise ValueError('Số hộ chiếu chỉ gồm chữ hoặc số')
        self.citizen_id = self.document_number if self.document_type == 'identity' else None
        return self


def duplicate_warning(c, data, pid=0):
    value = data.document_number
    duplicate = value and c.execute('''SELECT 1 FROM patients WHERE id<>?
        AND (document_number=? OR citizen_id=?) LIMIT 1''', (pid, value, value)).fetchone()
    return ['Trùng số giấy tờ với hồ sơ khác; cần kiểm tra lại. Hồ sơ vẫn được lưu.'] if duplicate else []


def validate_catalog(c, data):
    for kind, name in [('province', data.province), ('commune', data.commune), ('ethnicity', data.ethnicity)]:
        if name and c.execute('SELECT 1 FROM patient_catalog WHERE kind=? LIMIT 1', (kind,)).fetchone():
            row = c.execute('SELECT parent_code FROM patient_catalog WHERE kind=? AND name=?', (kind, name)).fetchone()
            if not row:
                raise HTTPException(422, 'Giá trị không thuộc danh mục đã nạp: ' + {'province':'Tỉnh/thành','commune':'Xã/phường/đặc khu','ethnicity':'Dân tộc'}[kind])
            if kind == 'commune':
                parent = c.execute("SELECT code FROM patient_catalog WHERE kind='province' AND name=?", (data.province,)).fetchone()
                if not parent or parent['code'] != row['parent_code']:
                    raise HTTPException(422, 'Xã/phường/đặc khu không thuộc tỉnh/thành đã chọn')


class ChildVisitInput(BaseModel):
    version: int = Field(ge=0)
    weight_kg: float | None = Field(default=None, gt=0, le=500, allow_inf_nan=False)
    escort_name: str | None = Field(default=None, max_length=180)
    escort_relationship: str | None = Field(default=None, max_length=100)
    escort_phone: str | None = Field(default=None, max_length=30)

    @field_validator('escort_name', 'escort_relationship', 'escort_phone', mode='before')
    @classmethod
    def trim(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator('escort_phone')
    @classmethod
    def phone(cls, value):
        if value and not re.fullmatch(r'[0-9]{9,12}', value):
            raise ValueError('Điện thoại người đưa trẻ cần 9–12 chữ số')
        return value


def require_child_prescription(c, visit, now=None):
    p = c.execute('SELECT date_of_birth FROM patients WHERE id=?', (visit['patient_id'],)).fetchone()
    months = months_old(p['date_of_birth'], now)
    if months is not None and months < 72:
        if not visit['weight_kg'] or not all((visit['escort_name'], visit['escort_relationship'], visit['escort_phone'])):
            raise HTTPException(422, 'Trẻ dưới 72 tháng: cần cân nặng và đủ họ tên, quan hệ, điện thoại người đưa trẻ đi khám trước khi kê đơn')


def parse_catalog(raw, filename):
    """Validate every source row before opening the catalog mutation transaction."""
    try:
        if filename.lower().endswith('.csv'):
            rows = []
            reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
            for line,row in enumerate(reader,1):
                if line>20001:raise ValueError('Dòng 20002: tối đa 20.000 dòng dữ liệu')
                rows.append(row)
        elif filename.lower().endswith('.xlsx'):
            from openpyxl import load_workbook
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist())>1000 or sum(x.file_size for x in archive.infolist())>20*1024*1024:
                    raise ValueError('Dòng 1: tệp Excel vượt giới hạn giải nén 20 MB / 1.000 mục')
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                if len(book.sheetnames) != 1:
                    raise ValueError('Dòng 1: cần đúng một trang tính')
                sheet=book.active
                sheet.reset_dimensions()
                rows=[]
                for line,cells in enumerate(sheet.iter_rows(max_col=5),1):
                    if line>20001:raise ValueError('Dòng 20002: tối đa 20.000 dòng dữ liệu')
                    if any(c.data_type in ('f','e') for c in cells):raise ValueError(f'Dòng {line}: không dùng công thức hoặc ô lỗi')
                    row=[c.value for c in cells]
                    while len(row)>4 and row[-1] is None:row.pop()
                    rows.append(row)
            finally:
                book.close()
        else:
            raise ValueError('Dòng 1: chỉ nhận CSV UTF-8 hoặc Excel .xlsx')
    except UnicodeDecodeError:
        raise HTTPException(422,'Dòng 1: CSV phải dùng bảng mã UTF-8') from None
    except csv.Error:
        raise HTTPException(422,f'Dòng {reader.line_num}: CSV không hợp lệ') from None
    except Exception as exc:
        raise HTTPException(422, 'Không đọc được danh mục. ' + (str(exc) if isinstance(exc, ValueError) and str(exc).startswith('Dòng ') else 'Dòng 1: tệp không hợp lệ')) from None
    if not rows or list(rows[0]) != ['kind', 'code', 'name', 'parent_code']:
        raise HTTPException(422, 'Dòng 1: cần cột kind,code,name,parent_code theo thứ tự')
    parsed = []
    keys = set()
    names = set()
    for line, row in enumerate(rows[1:], 2):
        if not any(x is not None and str(x).strip() for x in row):
            continue
        if len(row) != 4:
            raise HTTPException(422, f'Dòng {line}: cần đủ 4 cột')
        kind, code, name, parent = [str(x).strip() if x is not None else '' for x in row]
        if kind not in ('province', 'commune', 'ethnicity') or not code or not name or max(map(len, (code, name, parent))) > 180:
            raise HTTPException(422, f'Dòng {line}: loại, mã hoặc tên không hợp lệ')
        if (kind, code) in keys or (kind, name) in names:
            raise HTTPException(422, f'Dòng {line}: trùng mã hoặc tên trong cùng loại')
        if (kind == 'commune') != bool(parent):
            raise HTTPException(422, f'Dòng {line}: chỉ xã/phường/đặc khu phải có mã tỉnh cha')
        keys.add((kind, code)); names.add((kind, name))
        parsed.append((line, kind, code, name, parent))
    if not parsed:
        raise HTTPException(422, 'Dòng 2: danh mục trống')
    for line, kind, code, name, parent in parsed:
        if kind == 'commune' and ('province', parent) not in keys:
            raise HTTPException(422, f'Dòng {line}: không có tỉnh/thành với mã cha đã nhập')
    return [row[1:] for row in parsed]


def install_administrative(app, db, principal, require, audit, visit_access, now):
    @app.get('/api/patient-catalog')
    def catalog(u=Depends(principal)):
        require(u, 'admin', 'reception', 'doctor')
        with db() as c:
            return [dict(x) for x in c.execute('SELECT * FROM patient_catalog ORDER BY kind,code')]

    @app.post('/api/patient-catalog/import')
    def import_catalog(file: UploadFile = File(...), u=Depends(principal)):
        require(u, 'admin')
        raw = file.file.read(2*1024*1024+1)
        if len(raw) > 2*1024*1024:
            raise HTTPException(413, 'Danh mục tối đa 2 MB')
        rows = parse_catalog(raw, file.filename or '')
        with db(True) as c:
            c.execute('DELETE FROM patient_catalog')
            c.executemany('INSERT INTO patient_catalog(kind,code,name,parent_code) VALUES(?,?,?,?)', rows)
            audit(c, u, 'patient_catalog_imported', 'catalog', None, 'Số dòng: '+str(len(rows)))
        return {'imported': len(rows)}

    @app.put('/api/patients/{pid}/administrative')
    def update_patient(pid: int, data: AdministrativePatient, u=Depends(principal)):
        require(u, 'reception')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM patients WHERE id=?', (pid,)).fetchone():
                raise HTTPException(404, 'Không có bệnh nhân')
            validate_catalog(c, data)
            warnings = duplicate_warning(c, data, pid)
            values = data.model_dump()
            c.execute('UPDATE patients SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), pid))
            # No document values in audit or operational logs.
            audit(c, u, 'patient_administrative_updated', 'patient', pid)
        return {'ok': True, 'warnings': warnings}

    @app.put('/api/visits/{vid}/child-details')
    def child_details(vid: int, data: ChildVisitInput, u=Depends(principal)):
        require(u, 'doctor')
        with db(True) as c:
            v = visit_access(c, u, vid, clinical=True)
            ensure_open(v)
            values = data.model_dump(exclude={'version'})
            updated = c.execute('UPDATE visits SET '+','.join(k+'=?' for k in values)+',version=version+1 WHERE id=? AND version=?', (*values.values(), vid, data.version))
            if updated.rowcount != 1:
                raise HTTPException(409, 'Hồ sơ đã sửa ở phiên khác; hãy tải lại')
            revision(c, vid, u, now, 'clinical', 'Lưu cân nặng và người đưa trẻ')
            audit(c, u, 'child_visit_updated', 'visit', vid)
        return {'version': data.version+1}
