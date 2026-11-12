"""Clinical prescribing, free entry, immutable locked snapshots and offline outbox."""
import json
import re
import secrets
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation, DecimalException, localcontext
from io import BytesIO
from typing import Literal

from fastapi import Depends, HTTPException, Query, File, UploadFile, Form, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, StrictBool

from .administrative import months_old
from .domain import ensure_open
from .labels import VN_TZ
from .forms import format_patient_address
from .practitioners import SCOPES, printed_name


def fold(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD', value.lower().replace('đ', 'd')) if not unicodedata.combining(c)).split())


def components(value):
    return [v.strip() for v in value.split('+') if v.strip()]


def decimal(value):
    try:
        result = Decimal(str(value).strip().replace(',', '.'))
        return result if result.is_finite() and result > 0 else None
    except (InvalidOperation, ValueError):
        return None


def quantity(dose, frequency, days):
    values = [decimal(x) for x in (dose, frequency, days)]
    if not all(values) or any(v > 1000000 for v in values):
        return ''
    result = values[0] * values[1] * values[2]
    return format(result.normalize(), 'f') if result <= 1000000 else ''


class DrugInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=180)
    ingredient: str = Field(default='', max_length=500)
    brand_name: str = Field(default='', max_length=180)
    strength: str = Field(default='', max_length=180)
    dosage_form: str = Field(default='', max_length=180)
    route: str = Field(default='', max_length=180)
    unit: str = Field(default='', max_length=80)
    registration_number: str = Field(default='', max_length=180)
    national_code: str | None = Field(default=None, max_length=100)
    manufacturer: str = Field(default='', max_length=180)
    notes: str = Field(default='', max_length=500)
    toxic: bool = False
    controlled_type: Literal['', 'N', 'H', 'precursor'] = ''
    review_status: Literal['unreviewed', 'reviewed', 'inactive'] = 'unreviewed'

    @field_validator('*', mode='before')
    @classmethod
    def trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class LineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=180)
    ingredient: str = Field(default='', max_length=500)
    brand_name: str = Field(default='', max_length=180)
    strength: str = Field(default='', max_length=180)
    unit: str = Field(default='', max_length=80)
    quantity: str = Field(default='', max_length=100)
    dose: str = Field(default='', max_length=180)
    frequency: str = Field(default='', max_length=180)
    route: str = Field(default='', max_length=180)
    timing: str = Field(default='', max_length=180)
    days: str = Field(default='', max_length=80)
    notes: str = Field(default='', max_length=500)
    allergy_acknowledged: StrictBool = False
    allergy_reason: str = Field(default='', max_length=500)
    dose_unit: str = Field(default='', max_length=80)
    quantity_acknowledged: StrictBool = False
    quantity_reason: str = Field(default='', max_length=500)
    controlled_acknowledged: StrictBool = False
    controlled_reason: str = Field(default='', max_length=500)

    @field_validator('*', mode='before')
    @classmethod
    def text(cls, v):
        return v if isinstance(v, bool) else str(v).strip() if isinstance(v, (str, int, float)) else v


class RxInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    visit_id: int = Field(gt=0)
    version: int = Field(default=0, ge=0)
    items: list[LineInput] = Field(min_length=1, max_length=60)
    lifestyle_advice: str = Field(default='', max_length=2000)
    follow_up_advice: str = Field(default='', max_length=1000)
    purchase_advice: str = Field(default='', max_length=1000)
    replaces_id: int | None = Field(default=None, gt=0)


class Version(BaseModel):
    version: int = Field(ge=0)


class Cancel(Version):
    reason: str = Field(min_length=8, max_length=500)

    @field_validator('reason')
    @classmethod
    def trim(cls, value):
        if len(value.strip()) < 8:
            raise ValueError('Lý do cần ít nhất 8 ký tự')
        return value.strip()


class Merge(BaseModel):
    keep_id: int = Field(gt=0)


class ClinicSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    clinic_facility_code: str = Field(default='', pattern=r'^([A-Za-z0-9]{5})?$')
    clinic_name: str = Field(default='', max_length=180)
    clinic_address: str = Field(default='', max_length=500)
    clinic_phone: str = Field(default='', max_length=80)


def settings(c):
    values = ClinicSettings().model_dump()
    values.update({r['key']: r['value'] for r in c.execute('SELECT * FROM prescription_settings') if r['key'] in values})
    return values


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def lines(c, rid):
    return [dict(id=r['id'], drug_id=r['drug_id'], **json.loads(r['content'])) for r in c.execute('SELECT * FROM clinical_prescription_items WHERE prescription_id=? ORDER BY position', (rid,))]


def allergy_matches(allergies, line):
    """Conservative text matching, not inference about drug families or cross-allergy."""
    terms = [fold(x) for x in re.split(r'[+;,\n|]', allergies or '') if fold(x)]
    candidates = components(line.get('ingredient', '')) + [line.get('name', ''), line.get('brand_name', '')]
    def contains(text, term):
        return bool(term and re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)', text))
    return sorted({term for term in terms for candidate in candidates
                   if fold(candidate) and (contains(fold(candidate), term) or contains(term, fold(candidate)))})


def patient_for_rx(c, rid):
    return c.execute('SELECT p.* FROM patients p JOIN visits v ON v.patient_id=p.id JOIN clinical_prescriptions r ON r.visit_id=v.id WHERE r.id=?', (rid,)).fetchone()


def allergy_warning(row, matches):
    return {'row': row, 'field': 'ingredient', 'message': 'Trùng dị ứng thuốc: '+', '.join(matches)}


def safe_reason(reason, patient):
    for key in ('document_number', 'citizen_id'):
        if patient[key]: reason = reason.replace(patient[key], '[đã che số giấy tờ]')
    return re.sub(r'(?<![A-Za-z0-9])(?:[A-Za-z]{1,3}[0-9]{5,}|[0-9]{6,})(?![A-Za-z0-9])', '[đã che chuỗi định danh]', reason)


def replacement_parent(c, rx, exclude_id=0):
    old = c.execute('SELECT * FROM clinical_prescriptions WHERE id=?', (rx['replaces_id'],)).fetchone()
    if not old or old['status'] != 'locked':
        raise HTTPException(409, 'Đơn cũ đã hủy hoặc không còn được thay thế')
    if c.execute("SELECT 1 FROM clinical_prescriptions WHERE replaces_id=? AND id<>? AND status IN ('draft','locked')", (old['id'], exclude_id)).fetchone():
        raise HTTPException(409, 'Đơn cũ đã có đơn thay thế đang nháp/đã khóa')
    return old


def save_lines(c, rid, items, u, audit):
    c.execute('DELETE FROM clinical_prescription_items WHERE prescription_id=?', (rid,))
    warnings = []; seen = set(); allergy_warnings = []
    patient = patient_for_rx(c, rid)
    for pos, item in enumerate(items, 1):
        value = item.model_dump()
        matches = allergy_matches(patient['allergies'], value)
        value['allergy_basis'] = matches
        if matches:
            warning = allergy_warning(pos, matches)
            allergy_warnings.append(warning); warnings.append('Dòng '+str(pos)+': '+warning['message'])
        value['quantity'] = value['quantity'] or quantity(value['dose'], value['frequency'], value['days'])
        if quantity_mismatch(value):
            warnings.append(f'Dòng {pos}: số lượng lệch trên 20% so với cách dùng')
        key, strength = fold(item.name), fold(item.strength)
        drug = c.execute('SELECT * FROM drugs WHERE name_key=? AND strength_key=?', (key, strength)).fetchone()
        if drug and (drug['review_status'] == 'inactive' or drug['merged_into']):
            raise HTTPException(422, f'Dòng {pos}: thuốc đã ngừng dùng, chọn lại từ danh mục')
        if not drug:
            c.execute('INSERT INTO drugs(name,name_key,strength,strength_key,ingredient,ingredient_key,brand_name,brand_key,unit,route) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (item.name, key, item.strength, strength, item.ingredient, fold(item.ingredient), item.brand_name, fold(item.brand_name), item.unit, item.route))
            did = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        else:
            did = drug['id']
            # Suggestions are applied in the UI. Explicit row values, including
            # cleared use fields, are never silently filled back by the API.
            if drug['review_status'] == 'unreviewed' and item.ingredient:
                c.execute('UPDATE drugs SET ingredient=?,ingredient_key=?,brand_name=?,brand_key=? WHERE id=?', (item.ingredient, fold(item.ingredient), item.brand_name or drug['brand_name'], fold(item.brand_name or drug['brand_name']), did))
                if item.ingredient != drug['ingredient']:
                    audit(c, u, 'drug_updated', 'drug', did, dump({'fields': ['ingredient']}))
        from .controlled_substances import flag_drug, assess
        flag_drug(c,did,item.ingredient,u,audit)
        assessed=assess(c,value)
        warnings.extend(f'Dòng {pos}: '+w for w in assessed['warnings'])
        if assessed['label']: warnings.append(f'Dòng {pos}: '+assessed['label'])
        for active in components(value['ingredient']):
            k = fold(active)
            if k in seen: warnings.append(f'Dòng {pos}: trùng hoạt chất {active}')
            seen.add(k)
        c.execute('INSERT INTO clinical_prescription_items(prescription_id,drug_id,position,content) VALUES(?,?,?,?)', (rid, did, pos, dump(value)))
    return list(dict.fromkeys(warnings)), allergy_warnings


def lock_errors(c, rx, items, patient, visit, practitioner, clinic):
    errors = []
    def error(message, row=None, field=None): errors.append({'row': row, 'field': field, 'message': message})
    from .d0 import diagnosis_guard
    try:diagnosis_guard(c,visit)
    except HTTPException as exc:error(exc.detail,field='primary_icd10')
    if not visit['diagnosis']: error('Cần chẩn đoán trước khi khóa đơn')
    if not practitioner['practice_license'] or not set(json.loads(practitioner['practice_scopes'] or '[]')).intersection(SCOPES):
        error('Người kê chưa có đủ giấy phép / phạm vi chuyên môn')
    from .config import LAN
    if LAN and not clinic['clinic_facility_code']: error('Cần nhập mã cơ sở trước khi khóa đơn vận hành thật')
    age = months_old(patient['date_of_birth'])
    if age is not None and age < 72 and (not visit['weight_kg'] or not (visit['escort_name'] or '').strip()):
        error('Trẻ dưới 72 tháng cần cân nặng và họ tên người đưa trẻ')
    for pos, line in enumerate(items, 1):
        matches = allergy_matches(patient['allergies'], line)
        if matches and not (line.get('allergy_acknowledged') is True and len(line.get('allergy_reason', '').strip()) >= 8 and line.get('allergy_basis') == matches):
            error('Trùng dị ứng thuốc; cần xác nhận Đã biết dị ứng, vẫn kê và lý do ít nhất 8 ký tự', pos, 'allergy_reason')
        active = components(line['ingredient'])
        if not active: error('Bổ sung hoạt chất để in đúng tên theo TT 26/2025', pos, 'ingredient')
        if len(active) > 1 and not line['brand_name']: error('Thuốc nhiều hoạt chất phải có tên thương mại', pos, 'brand_name')
        for field, label in [('dose', 'liều mỗi lần'), ('frequency', 'số lần/ngày'), ('route', 'đường dùng'), ('days', 'số ngày dùng'), ('strength', 'hàm lượng/nồng độ'), ('timing', 'thời điểm dùng')]:
            if not line[field]: error('Thiếu '+label, pos, field)
        for field in ('dose','frequency','quantity'):
            if decimal(line[field]) is None:
                error('Cần nhập số dương, chấp nhận dấu phẩy thập phân',pos,field)
        if not (line.get('dose_unit') or line['unit']).strip():
            error('Liều mỗi lần phải có đơn vị',pos,'unit')
        days = decimal(line['days'])
        if line['days'] and (days is None or days != days.to_integral_value() or days > 30): error('Số ngày dùng phải là số nguyên từ 1 đến 30', pos, 'days')
        if not line['quantity']: error('Cần nhập số lượng hoặc đủ số để tự tính', pos, 'quantity')
        if quantity_mismatch(line) and not flexible_unit(line) and not (line.get('quantity_acknowledged') is True and len(line.get('quantity_reason','').strip())>=8):
            error('Số lượng lệch trên 20% cách dùng; xác nhận Số lượng khác cách dùng và nhập lý do ít nhất 8 ký tự',pos,'quantity_reason')
        drug = c.execute('SELECT * FROM drugs WHERE id=?', (line['drug_id'],)).fetchone()
        from .controlled_substances import assess
        assessed=assess(c,line)
        for message in assessed['errors']: error(message,pos,'ingredient')
        if drug['controlled_type'] and not assessed['label']: error('Đơn N/H chưa hỗ trợ', pos, 'name')
        if drug['review_status'] == 'inactive': error('Thuốc đã ngừng dùng', pos, 'name')
    return errors


def flexible_unit(line):
    return fold(line.get('unit','')) in ('ml','l','lit','giot','ong','chai','lo','tuyp','goi')


def quantity_mismatch(line):
    actual = decimal(line.get('quantity',''))
    factors = [decimal(line.get(k,'')) for k in ('dose','frequency','days')]
    if actual is None or any(value is None for value in factors): return False
    try:
        # Validation must not inherit the draft autofill's one-million cap.
        # Each input has at most 180 characters; retain all significant digits.
        with localcontext() as context:
            context.prec = 600
            expected = factors[0]*factors[1]*factors[2]
            return actual > expected*Decimal('1.2') or actual < expected*Decimal('0.8')
    except DecimalException:
        # Unrepresentable arithmetic never silently bypasses acknowledgement.
        return True


def payload(c, rx, code=None, locked_at=None):
    from .d0 import diagnosis_text
    visit = dict(c.execute('SELECT * FROM visits WHERE id=?', (rx['visit_id'],)).fetchone())
    p = dict(c.execute('SELECT * FROM patients WHERE id=?', (visit['patient_id'],)).fetchone())
    practitioner = dict(c.execute('SELECT * FROM users WHERE id=?', (rx['doctor_id'],)).fetchone())
    items = lines(c, rx['id']); clinic = settings(c)
    errors = lock_errors(c, rx, items, p, visit, practitioner, clinic)
    for item in items:
        drug = c.execute('SELECT toxic FROM drugs WHERE id=?', (item['drug_id'],)).fetchone()
        item['toxic'] = bool(drug['toxic'])
        from .controlled_substances import assess
        item['controlled_label']=assess(c,item)['label']
        active = components(item['ingredient'])
        item['display_name'] = ((item['brand_name'] or item['name']) if len(active) > 1 else (active[0] if active else item['name']) + (' ('+item['brand_name']+')' if item['brand_name'] else ''))
    items.sort(key=lambda x: not x['toxic'])
    age = months_old(p['date_of_birth'])
    return {'schema_version': '1.0', 'local_code': code if locked_at is not None else (rx['local_code'] if clinic['clinic_facility_code'] and (rx['local_code'] or '').startswith(clinic['clinic_facility_code']) else None), 'national_code': None,
            'integration_status': 'CHƯA LIÊN THÔNG', 'footer': {'reminder': 'Khám lại xin mang theo đơn này.'}, 'facility': clinic,
            'patient': {'full_name': p['full_name'], 'document_type': p['document_type'],
                        'document_number': p['document_number'] or p['citizen_id'], 'date_of_birth': p['date_of_birth'],
                        'sex': p['sex'], 'weight_kg': visit['weight_kg'], 'health_insurance_number': '',
                        'official_province_code':p['official_province_code'],'official_commune_code':p['official_commune_code'],'address': format_patient_address(p), 'contact_phone': (visit['escort_phone'] or p['phone']) if age is not None and age < 72 else p['phone'],
                        'age_months': age if age is not None and age < 72 else None,
                        'escort_name': visit['escort_name'] if age is not None and age < 72 else None},
            'encounter': {'visit_id': visit['id'], 'diagnosis': diagnosis_text(visit),'diagnosis_description':visit['diagnosis'],'primary_icd10':visit['primary_icd10'],'primary_icd10_canonical':next((x.get('canonical_code',x['code']) for x in json.loads(visit['diagnosis_codes']) if x.get('primary')),None),'diagnosis_codes':json.loads(visit['diagnosis_codes'])},
            'prescriber': {'name': printed_name(c, rx['doctor_id']), 'practice_license': practitioner['practice_license'],
                           'practice_scopes': json.loads(practitioner['practice_scopes'] or '[]')},
            'items': items, 'advice': {k: rx[k] for k in ('lifestyle_advice', 'follow_up_advice', 'purchase_advice')},
            'created_at': rx['created_at'], 'locked_at': locked_at or rx['locked_at'], 'errors': errors}


CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def allocate_code(c, facility_code):
    if not facility_code:
        return None
    for _ in range(128):
        code = facility_code+''.join(secrets.choice(CODE_ALPHABET) for _ in range(7))+'-C'
        if not c.execute('SELECT 1 FROM clinical_prescriptions WHERE local_code=?', (code,)).fetchone():
            return code
    raise HTTPException(503, 'Chưa cấp được mã đơn duy nhất; thử lại')


def install_m6(app, db, principal, require, audit, visit_access, now):
    def access(c, rid, u, write=False):
        rx = c.execute('SELECT * FROM clinical_prescriptions WHERE id=?', (rid,)).fetchone()
        if not rx: raise HTTPException(404, 'Không có đơn thuốc')
        if write:
            require(u, 'doctor')
            visit_access(c, u, rx['visit_id'], clinical=True)
            if rx['doctor_id'] != u['id']: raise HTTPException(403, 'Không được kê đơn cho lượt này')
        elif 'doctor' in u['roles']:
            visit_access(c, u, rx['visit_id'], clinical=True)
        else:
            require(u, 'reception', 'pharmacy')
            if rx['status'] != 'locked': raise HTTPException(403, 'Chỉ được xem/in đơn đã khóa')
        return dict(rx)

    @app.get('/api/prescription-settings')
    def get_settings(u=Depends(principal)):
        with db() as c: return settings(c)

    @app.put('/api/prescription-settings')
    def put_settings(data: ClinicSettings, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            old = settings(c)
            for k, v in data.model_dump().items():
                c.execute('INSERT INTO prescription_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, v))
            audit(c, u, 'prescription_settings_changed', 'prescription_settings', None,
                  dump({'fields': [k for k, v in data.model_dump().items() if old[k] != v], 'old_facility_code': old['clinic_facility_code'], 'new_facility_code': data.clinic_facility_code}))
        return data.model_dump()

    @app.get('/api/drugs')
    def search_drugs(q: str = '', status: Literal['unreviewed', 'reviewed', 'inactive'] | None = None,
                     ingredient_only: bool = False, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000), u=Depends(principal)):
        require(u, 'doctor', 'admin')
        with db() as c:
            where = 'review_status=?' if status else "review_status<>'inactive'"
            args = [status] if status else []
            needle = '%'+fold(q[:180])+'%'
            if q:
                where += ' AND (name_key LIKE ? OR brand_key LIKE ? OR ingredient_key LIKE ?)'; args += [needle, needle, needle]
            rows = [dict(r) for r in c.execute('SELECT * FROM drugs WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?', (*args, limit, offset))]
            return rows

    @app.put('/api/drugs/{did}')
    def review_drug(did: int, data: DrugInput, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            old = c.execute('SELECT * FROM drugs WHERE id=?', (did,)).fetchone()
            if not old: raise HTTPException(404, 'Không có thuốc')
            values = data.model_dump(); values['toxic'] = int(values['toxic']); values.update(name_key=fold(data.name), strength_key=fold(data.strength), ingredient_key=fold(data.ingredient), brand_key=fold(data.brand_name))
            duplicate = c.execute('SELECT id FROM drugs WHERE name_key=? AND strength_key=? AND id<>?', (values['name_key'], values['strength_key'], did)).fetchone()
            if duplicate: raise HTTPException(409, 'Tên và hàm lượng đã có; dùng chức năng gộp')
            c.execute('UPDATE drugs SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), did))
            from .controlled_substances import flag_drug
            flag_drug(c,did,data.ingredient,u,audit)
            audit(c, u, 'drug_updated', 'drug', did, dump({'fields': [k for k in values if old[k] != values[k]]}))
        return {'ok': True}

    @app.post('/api/drugs/{did}/merge')
    def merge_drug(did: int, data: Merge, u=Depends(principal)):
        require(u, 'admin')
        with db(True) as c:
            source = c.execute('SELECT * FROM drugs WHERE id=?', (did,)).fetchone()
            target = c.execute("SELECT * FROM drugs WHERE id=? AND review_status<>'inactive' AND merged_into IS NULL", (data.keep_id,)).fetchone()
            if not source or not target or did == data.keep_id or source['merged_into']: raise HTTPException(422, 'Chọn hai mục đang dùng khác nhau')
            # Content JSON and locked snapshots deliberately remain untouched.
            c.execute('UPDATE drugs SET toxic=?,controlled_type=? WHERE id=?', (int(bool(source['toxic'] or target['toxic'])), target['controlled_type'] or source['controlled_type'], data.keep_id))
            c.execute('UPDATE clinical_prescription_items SET drug_id=? WHERE drug_id=?', (data.keep_id, did))
            c.execute("UPDATE drugs SET review_status='inactive',merged_into=? WHERE id=?", (data.keep_id, did))
            audit(c, u, 'drug_merged', 'drug', did, dump({'keep_id': data.keep_id}))
        return {'ok': True}

    @app.post('/api/clinical-prescriptions', status_code=201)
    def create(data: RxInput, u=Depends(principal)):
        require(u, 'doctor')
        with db(True) as c:
            visit = visit_access(c, u, data.visit_id, clinical=True); ensure_open(visit)
            if data.replaces_id:
                old = access(c, data.replaces_id, u, True)
                replacement_parent(c, {'replaces_id': data.replaces_id})
                if old['visit_id'] != data.visit_id or not old['locked_at']: raise HTTPException(422, 'Đơn thay thế phải thuộc cùng lượt và đã từng khóa')
            c.execute('INSERT INTO clinical_prescriptions(visit_id,doctor_id,lifestyle_advice,follow_up_advice,purchase_advice,replaces_id,created_at,local_code) VALUES(?,?,?,?,?,?,?,?)',
                      (data.visit_id, u['id'], data.lifestyle_advice, data.follow_up_advice, data.purchase_advice, data.replaces_id, now(), allocate_code(c, settings(c)['clinic_facility_code'])))
            rid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            warnings, allergy_warnings = save_lines(c, rid, data.items, u, audit)
            audit(c, u, 'clinical_rx_created', 'clinical_prescription', rid)
        return {'id': rid, 'version': 0, 'status': 'draft', 'warnings': warnings, 'allergy_warnings': allergy_warnings}

    @app.put('/api/clinical-prescriptions/{rid}')
    def update(rid: int, data: RxInput, u=Depends(principal)):
        with db(True) as c:
            rx = access(c, rid, u, True); ensure_open(visit_access(c, u, rx['visit_id'], clinical=True))
            if rx['status'] != 'draft': raise HTTPException(409, 'Đơn đã khóa/hủy; lập đơn mới thay thế')
            if rx['version'] != data.version: raise HTTPException(409, 'Đơn đã thay đổi; tải lại')
            if rx['visit_id'] != data.visit_id or rx['replaces_id'] != data.replaces_id: raise HTTPException(422, 'Không được đổi lượt hay liên kết thay thế')
            warnings, allergy_warnings = save_lines(c, rid, data.items, u, audit)
            c.execute('UPDATE clinical_prescriptions SET lifestyle_advice=?,follow_up_advice=?,purchase_advice=?,version=version+1 WHERE id=?', (data.lifestyle_advice, data.follow_up_advice, data.purchase_advice, rid))
            audit(c, u, 'clinical_rx_updated', 'clinical_prescription', rid)
        return {'id': rid, 'version': data.version+1, 'warnings': warnings, 'allergy_warnings': allergy_warnings}

    @app.get('/api/clinical-prescriptions')
    def listing(status: Literal['draft', 'locked', 'cancelled'] | None = None, visit_id: int | None = None,
                limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000), u=Depends(principal)):
        require(u, 'doctor', 'reception', 'pharmacy')
        where = []; args = []
        if 'doctor' in u['roles']: where.append('doctor_id=?'); args.append(u['id'])
        else: where.append("status='locked'")
        if status: where.append('status=?'); args.append(status)
        if visit_id is not None: where.append('visit_id=?'); args.append(visit_id)
        clause = ' WHERE '+' AND '.join(where) if where else ''
        with db() as c:
            count = c.execute('SELECT COUNT(*) FROM clinical_prescriptions'+clause, args).fetchone()[0]
            rows = [dict(r) for r in c.execute('SELECT id,visit_id,doctor_id,status,version,local_code,replaces_id,created_at,locked_at FROM clinical_prescriptions'+clause+' ORDER BY id DESC LIMIT ? OFFSET ?', (*args, limit, offset))]
        return {'items': rows, 'total': count, 'limit': limit, 'offset': offset}

    @app.get('/api/clinical-prescriptions/{rid}')
    def detail(rid: int, u=Depends(principal)):
        with db() as c:
            rx = access(c, rid, u)
            # Snapshot contains identifiers: detail endpoint never exposes it.
            items = lines(c, rid); patient = patient_for_rx(c, rid); warnings = []
            for pos, item in enumerate(items, 1):
                from .controlled_substances import assess
                assessment=assess(c,item)
                item['controlled_label']=assessment['label']
                item['controlled_warning']=' · '.join(assessment['warnings'])
                if quantity_mismatch(item): item['quantity_warning'] = 'Số lượng lệch trên 20% so với cách dùng'
                matches = allergy_matches(patient['allergies'], item)
                if matches:
                    warning = allergy_warning(pos, matches); warnings.append(warning)
                    item['allergy_message'] = warning['message']
                if item.get('allergy_basis') != matches: item['allergy_acknowledged'] = False
            return {**{k: v for k, v in rx.items() if k != 'snapshot'}, 'items': items, 'allergy_warnings': warnings, 'printed_items': json.loads(rx['snapshot'])['items'] if rx['snapshot'] else None, 'integration_status': 'CHƯA LIÊN THÔNG'}

    @app.post('/api/clinical-prescriptions/{rid}/lock')
    def lock(rid: int, data: Version, u=Depends(principal)):
        with db(True) as c:
            rx = access(c, rid, u, True); ensure_open(visit_access(c, u, rx['visit_id'], clinical=True))
            if rx['status'] != 'draft' or rx['version'] != data.version: raise HTTPException(409, 'Đơn đã đổi/khóa/hủy; tải lại')
            parent = replacement_parent(c, rx, rid) if rx['replaces_id'] else None
            stamp = now(); clinic = settings(c)
            prefix = clinic['clinic_facility_code']
            existing = rx['local_code'] or ''
            code = existing if prefix and len(existing) == 14 and existing.startswith(prefix) and existing.endswith('-C') and set(existing[5:12]) <= set(CODE_ALPHABET) else allocate_code(c, prefix)
            value = payload(c, rx, code, stamp)
            if value['errors']: raise HTTPException(422, {'message': 'Chưa đủ điều kiện khóa đơn', 'errors': value['errors']})
            value.pop('errors')
            patient = patient_for_rx(c, rid)
            for item in value['items']:
                if item.get('controlled_acknowledged'):
                    audit(c,u,'clinical_rx_controlled_acknowledged','clinical_prescription',rid,dump({'item_id':item['id'],'reason':safe_reason(item.get('controlled_reason',''),patient)}),details_limit=3000)
                if quantity_mismatch(item) and item.get('quantity_acknowledged'):
                    audit(c,u,'clinical_rx_quantity_acknowledged','clinical_prescription',rid,
                          dump({'item_id':item['id'],'reason':safe_reason(item.get('quantity_reason',''),patient)}),details_limit=3000)
                if allergy_matches(patient['allergies'], item):
                    item['allergy_confirmed_by'] = u['id']; item['allergy_confirmed_at'] = stamp
                    content = {k: v for k, v in item.items() if k not in ('id','drug_id','toxic','display_name')}
                    c.execute('UPDATE clinical_prescription_items SET content=? WHERE id=?', (dump(content), item['id']))
                    audit(c, u, 'clinical_rx_allergy_acknowledged', 'clinical_prescription', rid,
                          dump({'row': c.execute('SELECT position FROM clinical_prescription_items WHERE id=?', (item['id'],)).fetchone()[0], 'reason': safe_reason(item['allergy_reason'], patient)}), details_limit=3000)
            if parent:
                reason = 'Thay thế bởi đơn '+(code or '#'+str(rid))
                c.execute("UPDATE clinical_prescriptions SET status='cancelled',version=version+1,cancellation_reason=?,cancelled_at=? WHERE id=?", (reason, stamp, parent['id']))
                c.execute("UPDATE prescription_outbox SET status='cancelled' WHERE prescription_id=?", (parent['id'],))
                audit(c, u, 'clinical_rx_replaced', 'clinical_prescription', parent['id'], dump({'replacement_id': rid, 'code': code}))
            c.execute("UPDATE clinical_prescriptions SET status='locked',version=version+1,local_code=?,locked_at=?,snapshot=? WHERE id=?", (code, stamp, dump(value), rid))
            c.execute('INSERT INTO prescription_outbox(prescription_id,schema_version,payload,created_at) VALUES(?,?,?,?)', (rid, value['schema_version'], dump(value), stamp))
            audit(c, u, 'clinical_rx_locked', 'clinical_prescription', rid)
        return {'id': rid, 'status': 'locked', 'version': data.version+1, 'local_code': code, 'integration_status': 'CHƯA LIÊN THÔNG'}

    @app.post('/api/clinical-prescriptions/{rid}/cancel')
    def cancel(rid: int, data: Cancel, u=Depends(principal)):
        with db(True) as c:
            rx = access(c, rid, u, True)
            if rx['status'] == 'cancelled' or rx['version'] != data.version: raise HTTPException(409, 'Đơn đã đổi/hủy; tải lại')
            c.execute("UPDATE clinical_prescriptions SET status='cancelled',version=version+1,cancellation_reason=?,cancelled_at=? WHERE id=?", (data.reason, now(), rid))
            c.execute("UPDATE prescription_outbox SET status='cancelled' WHERE prescription_id=?", (rid,))
            p = c.execute('SELECT p.document_number,p.citizen_id FROM patients p JOIN visits v ON v.patient_id=p.id WHERE v.id=?', (rx['visit_id'],)).fetchone()
            reason = data.reason
            for k in ('document_number', 'citizen_id'):
                if p[k]: reason = reason.replace(p[k], '[đã che số giấy tờ]')
            reason = re.sub(r'(?<![A-Za-z0-9])(?:[A-Za-z]{1,3}[0-9]{5,}|[0-9]{6,})(?![A-Za-z0-9])', '[đã che chuỗi định danh]', reason)
            audit(c, u, 'clinical_rx_cancelled', 'clinical_prescription', rid, reason)
        return {'status': 'cancelled', 'version': data.version+1}

    @app.get('/api/clinical-prescriptions/{rid}/json')
    def export_json(rid: int, u=Depends(principal)):
        require(u, 'doctor')
        with db('access') as c:
            rx = access(c, rid, u)
            if rx['status'] != 'locked': raise HTTPException(409, 'Chỉ xuất JSON đơn đã khóa')
            audit(c, u, 'clinical_rx_json_exported', 'clinical_prescription', rid)
            return Response(rx['snapshot'], media_type='application/json', headers={'Cache-Control': 'no-store'})

    @app.get('/api/clinical-prescriptions/{rid}/form')
    def export_form(rid: int, fmt: Literal['pdf', 'docx'] = 'pdf', u=Depends(principal)):
        from .m6_forms import render
        with db('access') as c:
            rx = access(c, rid, u)
            value = json.loads(rx['snapshot']) if rx['snapshot'] else payload(c, rx)
            if rx['status'] == 'cancelled':
                replacement = c.execute('SELECT id,local_code FROM clinical_prescriptions WHERE replaces_id=? AND locked_at IS NOT NULL ORDER BY id LIMIT 1', (rid,)).fetchone()
                if replacement: value['replaced_by_code'] = replacement['local_code'] or '#'+str(replacement['id'])
            content = render(value, rx['status'], fmt)
            audit(c, u, 'clinical_rx_printed', 'clinical_prescription', rid, fmt)
        mime = 'application/pdf' if fmt == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        return Response(content, media_type=mime, headers={'Cache-Control': 'no-store', 'Content-Disposition': f'attachment; filename="Don_thuoc_{rid}.{fmt}"'})

    from .controlled_substances import install_controlled
    install_controlled(app,db,principal,require,audit)

    from .m6_import import install_import
    install_import(app, db, principal, require, audit)
