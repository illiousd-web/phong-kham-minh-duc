"""Administrative patient fields, file-supplied catalogs and child prescribing guard."""
import re
from datetime import date, datetime
from typing import Literal

from fastapi import Depends, HTTPException
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
    ethnicity_code: str | None = Field(default=None, max_length=40)
    province_code: str | None = Field(default=None, max_length=40)
    commune_code: str | None = Field(default=None, max_length=40)
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


def install_administrative(app, db, principal, require, audit, visit_access, now):
    from .patient_catalog import install_patient_catalog, resolve_patient_catalog
    install_patient_catalog(app, db, principal, require, audit)

    @app.put('/api/patients/{pid}/administrative')
    def update_patient(pid: int, data: AdministrativePatient, u=Depends(principal)):
        require(u, 'reception')
        with db(True) as c:
            old=c.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
            if not old:
                raise HTTPException(404, 'Không có bệnh nhân')
            resolve_patient_catalog(c, data, old)
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
