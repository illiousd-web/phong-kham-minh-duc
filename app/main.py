"""Minh Duc clinic: local demo and HTTPS/PostgreSQL LAN pilot, synthetic data only."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
import json
from .domain import authorize_order, revision, status_refresh, invoice
from .charge_queries import DUES_SQL,orders_sql
from .work_queues import visit_predicate, ACTIVE_ORDERS, approval_predicate, history_limit
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool
from .resources import LIMITS, export_slot
from .storage import check_upload, StorageLimitError
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator
from .print_forms import pdf_document
from .labels import parse_day

BASE = Path(__file__).resolve().parent
DB = Path(os.environ.get("CLINIC_DB_PATH", str(BASE.parent / "data" / "minh_duc_demo.sqlite3"))).resolve()
FILES = Path(os.environ.get('CLINIC_UPLOAD_DIR', str(DB.parent / 'attachments'))).resolve()
from .config import LAN, ORIGIN, HOSTS, client_allowed, DATA
from .database import DB, db
if LAN:
    FILES = Path(os.environ.get("CLINIC_UPLOAD_DIR", str(DATA / "attachments"))).resolve()
PASS = os.environ.get('DEMO_PASSWORD')
if not LAN and not PASS:
    raise RuntimeError('Set DEMO_PASSWORD before starting the demo (see README.md).')
DEMO_USERS = [
    ("quantri", "Quản trị hệ thống", ["admin"]),
    ("quanly", "Quản lý phòng khám", ["manager"]),
    ("letan", "Lễ tân", ["reception"]),
    ("bs_noi", "BS Nội", ["doctor"]),
    ("bs_san", "BS Sản", ["doctor"]),
    ("kythuat", "Kỹ thuật viên", ["technician"]),
    ("dieuduong", "Điều dưỡng", ["nurse"]),
    ("duoc", "Nhân viên dược", ["pharmacy"]),
    ("thungan", "Thu ngân", ["cashier"]),
]
NOW = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

SCHEMA = (BASE.parent / 'schema.sql').read_text(encoding='utf-8')

def row(x):return dict(x) if x is not None else None

def init_db():
    if LAN:
        with db() as c:
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=7").fetchone():
                raise RuntimeError("Run python -m scripts.manage migrate first")
        return
    DB.parent.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
        c.execute('PRAGMA journal_mode=WAL')
    with db(True) as c:
        from .migrations import migrate_v050
        migrate_v050(c)
    from .manual_price_migration import migrate_sqlite_manual_prices
    migrate_sqlite_manual_prices(DB)
    with db(True) as c:
        from .m0_migration import migrate_m0
        migrate_m0(c)
        from .administrative_migration import migrate_administrative
        migrate_administrative(c)
        from .patient_catalog import migrate_public_catalog
        migrate_public_catalog(c)
    with db(True) as c:
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:return
        for user,full,roles in DEMO_USERS:
            salt=secrets.token_hex(16)
            c.execute('INSERT INTO users(username,full_name,salt,password_hash) VALUES(?,?,?,?)',
                      (user,full,salt,pw_hash(PASS,salt)))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for role in roles:c.execute('INSERT INTO user_roles VALUES(?,?)',(uid,role))
        c.executemany('INSERT INTO service_catalog(name,price) VALUES(?,?)',[
            ('Khám nội (mẫu)',150000),('Khám sản (mẫu)',180000),('Khám chuyên khoa (mẫu)',160000)])
        c.executemany('INSERT INTO medicines(name,base_unit,controlled) VALUES(?,?,?)',[
            ('Thuốc mẫu A - không dùng điều trị','viên',0),('Vật tư mẫu B','cái',0),('Thuốc kiểm soát - mẫu, không xuất','ống',1)])
        c.executemany('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity,quarantined) VALUES(?,?,?,?,?)',[
            (1,'LO-MAU-001','2027-03-30',120,0),(1,'LO-MAU-002','2027-09-30',300,0),(3,'KS-MAU-001','2027-10-15',10,1)])
        # Dữ liệu được cố ý để trống: không tạo bệnh nhân giả nếu người dùng chưa thao tác.

@asynccontextmanager
async def lifespan(app):
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens=LIMITS.threads
    try:yield
    finally:
        from . import database
        if database._pool:
            database._pool.close()
            database._pool=None


app=FastAPI(title='Phòng khám đa khoa Minh Đức - bản thử nghiệm',version='0.5.0',lifespan=lifespan,docs_url=None if LAN else '/api/docs',openapi_url=None if LAN else '/api/openapi.json')
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=HOSTS,
    www_redirect=False,
)
from .middleware import BodyLimitMiddleware
app.add_middleware(BodyLimitMiddleware)
app.mount('/assets',StaticFiles(directory=BASE/'static'),name='assets')

@app.middleware('http')
async def security_headers(request:Request,call_next):
    if not request.client or not client_allowed(request.client.host):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Kết nối không thuộc mạng được cho phép'},status_code=403)
    if LAN:
        from fastapi.responses import JSONResponse
        if request.url.scheme != 'https':
            return JSONResponse({'detail':'Yêu cầu HTTPS nội bộ'}, status_code=400)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('origin') != ORIGIN or request.headers.get('x-clinic-request') != '1':
                return JSONResponse({'detail':'Nguồn yêu cầu không hợp lệ'}, status_code=403)
            if request.cookies.get('__Host-clinic') and request.url.path != '/api/login':
                csrf = request.cookies.get('__Host-clinic-csrf', '')
                if not csrf or not hmac.compare_digest(csrf, request.headers.get('x-csrf-token', '')):
                    return JSONResponse({'detail':'Mã CSRF không hợp lệ'}, status_code=403)
    response=await call_next(request)
    if LAN:
        response.headers['Strict-Transport-Security']='max-age=31536000'
        if response.status_code != 503 and request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/login','/api/audit','/api/queue-counts'):
            token = request.cookies.get('__Host-clinic', '')
            if token:
                try:
                    def log_access():
                        with db(True) as c:
                            actor = c.execute('SELECT user_id FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
                            if actor:
                                c.execute('INSERT INTO audit_log(user_id,event,object_type,details,created_at) VALUES(?,?,?,?,?)',
                                          (actor['user_id'],'api_access','http',request.method+' '+request.url.path[:250]+' '+str(response.status_code),NOW()))
                    await run_in_threadpool(log_access)
                except Exception:
                    # Business mutation audit is already committed atomically in
                    # its own transaction. Supplemental HTTP logging must not turn
                    # a committed payment into an ambiguous failure response.
                    import logging
                    logging.getLogger('clinic').error('Supplemental access audit unavailable')

    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
    return response

@app.get('/',include_in_schema=False)
def index():return FileResponse(BASE/'static'/'index.html',headers={'Cache-Control':'no-store'})

@app.get('/api/health')
def health():
    if LAN:
        with db() as c:c.execute('SELECT 1').fetchone()
    return {'status':'lan-pilot' if LAN else 'demo','version':'0.5.0','mode':'lan' if LAN else 'demo','clinic':'Phòng khám đa khoa Minh Đức'}

from .auth import install_auth, pw_hash
principal = install_auth(app, db, LAN, NOW)

def require(u, *roles):
    if not set(roles).intersection(u['roles']):raise HTTPException(403,'Không có quyền thực hiện chức năng')

def audit(c,u,event,typ,obj,details=''):
    c.execute('INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)',
              (u['id'],event,typ,obj,details[:500],NOW()))

def visit_access(c,u,vid:int,*,clinical=False):
    v=c.execute('''SELECT visits.*,patients.full_name AS patient_name,patients.code AS patient_code,
                 patients.sex AS patient_sex,patients.date_of_birth AS patient_dob,
                 patients.phone AS patient_phone,patients.allergies AS patient_allergies
                 FROM visits JOIN patients ON patients.id=visits.patient_id WHERE visits.id=?''',(vid,)).fetchone()
    if not v:raise HTTPException(404,'Không tìm thấy lượt khám')
    if clinical:
        if 'doctor' in u['roles'] and v['doctor_id']==u['id']:return v
        # Chưa có phân công điều dưỡng chi tiết: chặn quyền xem toàn bộ bệnh án.
        raise HTTPException(403,'Không được truy cập hồ sơ chuyên môn này')
    return v

from .workflows_v042 import ensure_open, install_workflows

@app.get('/api/staff')
def staff(u=Depends(principal)):
    require(u,'admin','manager','reception','doctor')
    with db() as c:
        return [dict(x) for x in c.execute("SELECT u.id,u.full_name,u.username FROM users u JOIN user_roles r ON r.user_id=u.id WHERE r.role='doctor' AND u.active=1 ORDER BY u.id")]

from .administrative import (AdministrativePatient, duplicate_warning, redact_document,
    document_value, months_old, require_child_prescription, install_administrative)
from .practitioners import printed_name, scope_warning, install_practitioners

class PatientInput(AdministrativePatient):
    # Khảo sát bước 4: họ tên, ngày sinh, giới tính, số điện thoại là bắt buộc;
    # căn cước và địa chỉ có thể bổ sung sau.
    full_name:str=Field(min_length=2,max_length=180)
    date_of_birth:str
    sex:Literal['Nam','Nữ','Khác']
    phone:str=Field(max_length=30)
    address:str|None=Field(default=None,max_length=300)

    @field_validator('full_name')
    @classmethod
    def name_valid(cls,v):
        v=' '.join(v.split())
        if len(v)<2:raise ValueError('Cần nhập họ và tên')
        return v

    @field_validator('date_of_birth')
    @classmethod
    def date_valid(cls,v):
        iso=parse_day(v)
        if not iso:raise ValueError('Cần nhập ngày sinh')
        if date.fromisoformat(iso)>datetime.now(timezone(timedelta(hours=7))).date() or date.fromisoformat(iso)<date(1900,1,1):raise ValueError('Ngày sinh không hợp lệ')
        return iso

    @field_validator('phone')
    @classmethod
    def phone_valid(cls,v):
        digits=''.join(ch for ch in v if ch.isdigit())
        if not 9<=len(digits)<=12:raise ValueError('Số điện thoại cần 9–12 chữ số')
        return digits

    @field_validator('address')
    @classmethod
    def blank_to_none(cls,v):
        return (v or '').strip() or None

@app.post('/api/patients',status_code=201)
def add_patient(data:PatientInput,u=Depends(principal)):
    require(u,'reception','admin')
    with db(True) as c:
        from .patient_catalog import resolve_patient_catalog
        resolve_patient_catalog(c,data)
        warnings=duplicate_warning(c,data)
        params=data.model_dump()
        cols=','.join(params)
        names=','.join('?' for _ in params)
        c.execute(f'INSERT INTO patients({cols},created_at) VALUES({names},?)',(*params.values(),NOW()))
        pid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        code=f'MD{pid:06d}'
        c.execute('UPDATE patients SET code=? WHERE id=?',(code,pid))
        audit(c,u,'patient_created','patient',pid)
        return {'id':pid,'code':code,'warnings':warnings}

@app.get('/api/patients')
def patients(q:str='',u=Depends(principal)):
    require(u,'reception','doctor','nurse','admin')
    q=q.strip()[:100]
    with db() as c:
        wh="WHERE (p.full_name LIKE ? OR p.code LIKE ? OR p.phone LIKE ? OR p.document_number=? OR p.citizen_id=?)" if q else ''
        args=['%'+q+'%']*3+[q,q] if q else []
        if not {'reception','admin'}.intersection(u['roles']):
            if 'doctor' in u['roles']:
                wh+=(' AND ' if wh else ' WHERE ')+ 'EXISTS (SELECT 1 FROM visits v WHERE v.patient_id=p.id AND v.doctor_id=?)'
            else:
                wh+=(' AND ' if wh else ' WHERE ')+ 'EXISTS (SELECT 1 FROM visits v JOIN visit_nurses n ON n.visit_id=v.id WHERE v.patient_id=p.id AND n.nurse_id=? AND n.active=1)'
            args.append(u['id'])
        sql=f'SELECT p.id,p.code,p.full_name,p.date_of_birth,p.sex,p.phone,p.address,p.document_type,p.document_number,p.citizen_id FROM patients p {wh} ORDER BY p.id DESC LIMIT 100'
        return [redact_document(dict(x)) for x in c.execute(sql,args)]

@app.get('/api/patients/{patient_id}')
def patient_detail(patient_id:int,u=Depends(principal)):
    require(u,'reception','doctor','nurse','admin')
    with db(True) as c:
        p=c.execute('SELECT * FROM patients WHERE id=?',(patient_id,)).fetchone()
        if not p:raise HTTPException(404,'Không có bệnh nhân')
        if not {'reception','admin'}.intersection(u['roles']):
            if 'doctor' in u['roles']:
                allowed=c.execute('SELECT 1 FROM visits WHERE patient_id=? AND doctor_id=?',(patient_id,u['id'])).fetchone()
            else:
                allowed=c.execute('SELECT 1 FROM visits v JOIN visit_nurses n ON n.visit_id=v.id WHERE v.patient_id=? AND n.nurse_id=? AND n.active=1',(patient_id,u['id'])).fetchone()
            if not allowed:raise HTTPException(403,'Không được xem hồ sơ này')
        if 'nurse' in u['roles'] and not {'doctor','reception','admin'}.intersection(u['roles']):return {k:p[k] for k in ('id','code','full_name','date_of_birth','sex')}
        data=dict(p)
        data['age_months']=months_old(data['date_of_birth'])
        if {'reception','doctor'}.intersection(u['roles']):
            if document_value(data):audit(c,u,'patient_document_viewed','patient',patient_id)
        else:data=redact_document(data)
        return data

class AppointmentInput(BaseModel):
    patient_id:int
    doctor_id:int
    scheduled_at:str=Field(min_length=10,max_length=40)
    reason:str=Field(default='',max_length=300)

    @field_validator('scheduled_at')
    @classmethod
    def valid_schedule(cls,v):
        if 'T' not in v:raise ValueError('Lịch hẹn cần ngày và giờ hợp lệ')
        datetime.fromisoformat(v)
        return v

@app.post('/api/appointments',status_code=201)
def add_appointment(data:AppointmentInput,u=Depends(principal)):
    require(u,'reception','admin')
    with db(True) as c:
        if not c.execute('SELECT 1 FROM patients WHERE id=?',(data.patient_id,)).fetchone():raise HTTPException(404,'Không có bệnh nhân')
        ensure_doctor(c,data.doctor_id)
        c.execute('INSERT INTO appointments(patient_id,doctor_id,scheduled_at,reason,created_by) VALUES(?,?,?,?,?)',
                  (data.patient_id,data.doctor_id,data.scheduled_at,data.reason,u['id']))
        aid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        audit(c,u,'appointment_created','appointment',aid)
        return {'id':aid}

@app.get('/api/appointments')
def get_appointments(u=Depends(principal)):
    require(u,'reception','doctor','admin')
    with db() as c:
        sql='SELECT a.*,p.code AS patient_code,p.full_name AS patient_name,users.full_name AS doctor_name FROM appointments a JOIN patients p ON p.id=a.patient_id JOIN users ON users.id=a.doctor_id'
        args=[]
        if 'doctor' in u['roles'] and 'reception' not in u['roles'] and 'admin' not in u['roles']:
            sql+=' WHERE a.doctor_id=?';args=[u['id']]
        return [dict(x) for x in c.execute(sql+' ORDER BY a.id DESC LIMIT 100',args)]

def ensure_doctor(c,doctor_id:int):
    if not c.execute("SELECT 1 FROM user_roles r JOIN users u ON u.id=r.user_id WHERE r.user_id=? AND r.role='doctor' AND u.active=1",(doctor_id,)).fetchone():raise HTTPException(422,'Bác sĩ không hợp lệ')

class VisitInput(BaseModel):
    patient_id:int
    doctor_id:int
    service_id:int=1
    appointment_id:int|None=None

@app.post('/api/visits',status_code=201)
def create_visit(data:VisitInput,u=Depends(principal)):
    require(u,'reception','admin')
    with db(True) as c:
        if not c.execute('SELECT 1 FROM patients WHERE id=?',(data.patient_id,)).fetchone():raise HTTPException(404,'Không có bệnh nhân')
        ensure_doctor(c,data.doctor_id)
        service=c.execute('SELECT * FROM service_catalog WHERE id=? AND active=1',(data.service_id,)).fetchone()
        if not service:raise HTTPException(422,'Dịch vụ không tồn tại')
        if data.appointment_id:
            a=c.execute('SELECT * FROM appointments WHERE id=?',(data.appointment_id,)).fetchone()
            if not a or a['patient_id']!=data.patient_id or a['doctor_id']!=data.doctor_id or a['status']!='booked':raise HTTPException(422,'Lịch hẹn không hợp lệ')
        c.execute('INSERT INTO visits(patient_id,doctor_id,created_by,appointment_id,created_at) VALUES(?,?,?,?,?)',
                  (data.patient_id,data.doctor_id,u['id'],data.appointment_id,NOW()))
        vid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO charges(visit_id,label,amount,created_at) VALUES(?,?,?,?)',(vid,service['name'],None if service['price_at_collection'] else service['price'],NOW()))
        if data.appointment_id:c.execute("UPDATE appointments SET status='arrived' WHERE id=?",(data.appointment_id,))
        revision(c,vid,u,NOW,'create','Tiếp nhận lượt khám giả lập')
        audit(c,u,'visit_created','visit',vid)
        return {'id':vid}

@app.get('/api/services')
def services(u=Depends(principal)):
    require(u,'reception','admin','manager')
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM service_catalog WHERE active=1')]

@app.get('/api/visits')
def list_visits(u=Depends(principal),history:bool=False):
    require(u,'reception','doctor','nurse','technician','cashier','pharmacy','manager','admin')
    predicate,args=visit_predicate(u,history)
    roles=set(u['roles'])
    if roles & {'manager','admin'}:
        fields='v.id,v.status,v.created_at'
    elif 'doctor' in roles or ('reception' in roles and 'technician' not in roles):
        fields='v.id,v.patient_id,v.status,v.created_at,p.code AS patient_code,p.full_name AS patient_name'
    else:
        fields='v.id,v.status,p.code AS patient_code,p.full_name AS patient_name'
    with db() as c:
        return [dict(x) for x in c.execute('SELECT '+fields+' FROM visits v JOIN patients p ON p.id=v.patient_id WHERE '+predicate+' ORDER BY v.id DESC'+history_limit(history),args)]

@app.get('/api/visits/{visit_id}')
def visit_detail(visit_id:int,u=Depends(principal)):
    require(u,'doctor','nurse','reception','cashier','admin')
    with db(True) as c:
        v=visit_access(c,u,visit_id,clinical=True) if 'doctor' in u['roles'] else visit_access(c,u,visit_id)
        if 'doctor' in u['roles']:
            audit(c,u,'clinical_viewed','visit',visit_id)
            data=dict(v)
            data['age_months']=months_old(v['patient_dob'])
            return data
        brief={'id':v['id'],'patient_id':v['patient_id'],'patient_name':v['patient_name'],'patient_code':v['patient_code'],'status':v['status'],'doctor_id':v['doctor_id'],'created_at':v['created_at']}
        if 'nurse' in u['roles']:
            if not c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=? AND active=1',(visit_id,u['id'])).fetchone():
                raise HTTPException(403,'Điều dưỡng chưa được phân công')
            brief.update(vitals=v['vitals'],version=v['version'])
        return brief

class ClinicalInput(BaseModel):
    chief_complaint:str=Field(default='',max_length=3000)
    history:str=Field(default='',max_length=4000)
    vitals:str=Field(default='',max_length=1000)
    diagnosis:str=Field(default='',max_length=3000)
    treatment:str=Field(default='',max_length=3000)
    follow_up:str|None=Field(default=None,max_length=80)
    version:int=Field(ge=0)

    @field_validator('follow_up')
    @classmethod
    def follow_up_day(cls,v):
        return parse_day(v)

@app.put('/api/visits/{visit_id}/clinical')
def update_clinical(visit_id:int,data:ClinicalInput,u=Depends(principal)):
    require(u,'doctor')
    with db(True) as c:
        v=visit_access(c,u,visit_id,clinical=True)
        ensure_open(v)
        changed=c.execute('UPDATE visits SET chief_complaint=?,history=?,vitals=?,diagnosis=?,treatment=?,follow_up=?,version=version+1,status=? WHERE id=? AND version=?',
                          (data.chief_complaint,data.history,data.vitals,data.diagnosis,data.treatment,data.follow_up,'in_progress',visit_id,data.version))
        if changed.rowcount!=1:raise HTTPException(409,'Hồ sơ đã được sửa ở phiên khác; hãy tải lại')
        status_refresh(c,visit_id)
        revision(c,visit_id,u,NOW,'clinical','Bác sĩ lưu phiếu khám')
        audit(c,u,'clinical_updated','visit',visit_id)
        return {'version':data.version+1}

class OrderInput(BaseModel):
    visit_id:int
    category:Literal['consultation','lab','ultrasound','xray','ecg','procedure']
    name:str=Field(default='',max_length=180)
    service_id:int|None=None
    request_key:str|None=Field(default=None,min_length=8,max_length=120)
    defer_approval:bool=False

@app.post('/api/orders',status_code=201)
def add_order(data:OrderInput,u=Depends(principal)):
    require(u,'doctor','nurse')
    with db(True) as c:
        if LAN and not data.request_key:
            raise HTTPException(422,'Chỉ định LAN phải có mã yêu cầu chống ghi trùng')
        if data.request_key:
            existing=c.execute('''SELECT q.order_id,q.visit_id,q.service_id,q.category,q.requested_by,ch.amount
                FROM order_requests q LEFT JOIN charge_sources src ON src.source_type='order' AND src.source_id=q.order_id
                LEFT JOIN charges ch ON ch.id=src.charge_id WHERE q.request_key=?''',(data.request_key,)).fetchone()
            if existing:
                if existing['visit_id']!=data.visit_id or existing['service_id']!=data.service_id or existing['category']!=data.category or existing['requested_by']!=u['id']:
                    raise HTTPException(409,'Mã yêu cầu đã dùng cho nội dung khác')
                return {'id':existing['order_id'],'charge_amount':existing['amount'],'status':'already_recorded'}
        if 'nurse' in u['roles'] and c.execute('SELECT 1 FROM visit_nurses WHERE visit_id=? AND nurse_id=? AND active=1',(data.visit_id,u['id'])).fetchone():
            v=visit_access(c,u,data.visit_id,clinical=False)
        else:
            v=visit_access(c,u,data.visit_id,clinical=True)
        ensure_open(v)
        service=None
        if data.service_id is not None:
            service=c.execute('''SELECT sc.id,sc.name,sc.price,sc.price_at_collection,cat.category FROM service_catalog sc
                JOIN service_categories cat ON cat.service_id=sc.id WHERE sc.id=?''',(data.service_id,)).fetchone()
            if not service or service['category']!=data.category or service['price']<0 or (service['category']=='consultation' and not service['price_at_collection']) or not c.execute('SELECT active FROM service_catalog WHERE id=?',(data.service_id,)).fetchone()[0]:
                raise HTTPException(422,'Dịch vụ cận lâm sàng chưa có loại/giá hợp lệ')
        elif LAN or 'doctor' not in u['roles']:
            raise HTTPException(422,'Chỉ định LAN phải chọn dịch vụ từ bảng giá; không lập chỉ định miễn phí ngoài quy trình')
        elif len(data.name.strip())<3:
            raise HTTPException(422,'Cần nhập tên chỉ định thử nghiệm')
        label=service['name'] if service else data.name.strip()
        c.execute('INSERT INTO orders(visit_id,category,name,requested_by,created_at) VALUES(?,?,?,?,?)',
                  (data.visit_id,data.category,label,u['id'],NOW()))
        oid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        if service:
            c.execute('UPDATE orders SET service_id=?,proposed_price=?,status=? WHERE id=?',
                      (service['id'],None if service['price_at_collection'] else service['price'],'requested',oid))
            if data.request_key:
                c.execute('INSERT INTO order_requests(request_key,order_id,visit_id,service_id,category,requested_by) VALUES(?,?,?,?,?,?)',
                          (data.request_key,oid,data.visit_id,data.service_id,data.category,u['id']))
        audit(c,u,'order_created','order',oid,'Nháp' if data.defer_approval else 'Người được phân công xác nhận')
        if service and not data.defer_approval:return authorize_order(c,oid,u,audit,NOW)
        status_refresh(c,data.visit_id)
        return {'id':oid,'charge_amount':0,'status':'requested' if service else 'ordered'}

@app.get('/api/orders')
def list_orders(u=Depends(principal),visit_id:int|None=None,history:bool=False):
    require(u,'doctor','nurse','technician')
    with db() as c:
        args=[];where=[];hide_results=False
        if 'nurse' in u['roles'] and 'doctor' not in u['roles'] and 'technician' not in u['roles']:
            hide_results=True
            where.append('EXISTS(SELECT 1 FROM visit_nurses n WHERE n.visit_id=v.id AND n.nurse_id=? AND n.active=1)');args=[u['id']]
        elif 'doctor' in u['roles'] and 'technician' not in u['roles']:
            where.append('v.doctor_id=?');args=[u['id']]
        if visit_id is not None:where.append('o.visit_id=?');args.append(visit_id)
        if visit_id is None:where.append('NOT ('+ACTIVE_ORDERS+')' if history else ACTIVE_ORDERS)
        return [dict(x) for x in c.execute(orders_sql(' AND '.join(where),hide_results,limit=100 if history else None),args)]

class ResultInput(BaseModel):
    result_text:str=Field(min_length=1,max_length=10000)

@app.put('/api/orders/{order_id}/result')
def submit_result(order_id:int,data:ResultInput,u=Depends(principal)):
    require(u,'technician')
    with db(True) as c:
        order=c.execute('SELECT o.status,v.status AS visit_status FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?',(order_id,)).fetchone()
        if order and order['visit_status'] in ('completed','cancelled'):raise HTTPException(409,'Lượt khám đã kết thúc')
        if not order:raise HTTPException(404,'Không có chỉ định')
        if order['status'] not in ('ordered','pending_review'):raise HTTPException(409,'Kết quả đã duyệt, không được sửa trực tiếp')
        c.execute("UPDATE orders SET result_text=?,result_by=?,status='pending_review' WHERE id=?",(data.result_text,u['id'],order_id))
        audit(c,u,'result_submitted','order',order_id)
        return {'status':'pending_review'}

@app.post('/api/orders/{order_id}/approve')
def approve_result(order_id:int,u=Depends(principal)):
    require(u,'doctor')
    with db(True) as c:
        o=c.execute('SELECT o.*,v.doctor_id FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?',(order_id,)).fetchone()
        if not o:raise HTTPException(404,'Không có chỉ định')
        if o['doctor_id']!=u['id']:raise HTTPException(403,'Không phải bác sĩ phụ trách')
        if c.execute("SELECT status FROM visits WHERE id=?",(o['visit_id'],)).fetchone()['status'] in ('completed','cancelled'):raise HTTPException(409,'Lượt khám đã kết thúc')
        if o['status']!='pending_review' or not o['result_text'].strip():raise HTTPException(409,'Chưa có kết quả chờ duyệt')
        from .ui_settings import read_settings, settings_path
        warnings=scope_warning(c,u,o['category'],order_id,NOW,block=read_settings(settings_path(FILES))['block_practitioner_scope'])
        c.execute("UPDATE orders SET status='approved',approved_by=?,approved_at=? WHERE id=?",(u['id'],NOW(),order_id))
        status_refresh(c,o['visit_id'])
        audit(c,u,'result_approved_demo','order',order_id,'Chưa ký số; phê duyệt mô phỏng')
        return {'status':'approved','warnings':warnings,'note':'Chỉ xác nhận quy trình demo, không có chữ ký số chuyên môn'}

@app.post('/api/orders/{order_id}/attachment')
def add_attachment(order_id:int,file:UploadFile=File(...),u=Depends(principal)):
    require(u,'technician')
    if file.content_type not in ('application/pdf','image/png','image/jpeg'):raise HTTPException(415,'Chỉ chấp nhận PDF/PNG/JPEG')
    raw=file.file.read(LIMITS.upload_bytes+1)
    if not raw or len(raw)>LIMITS.upload_bytes:raise HTTPException(413,'Tệp không được quá 5 MB')
    if not (raw.startswith(b'%PDF-') or raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):raise HTTPException(415,'Không nhận dạng định dạng tệp')
    ext={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg'}[file.content_type]
    key=uuid.uuid4().hex+ext
    FILES.mkdir(parents=True,exist_ok=True)
    target=FILES/key
    previous=None
    try:
        with db(True) as c:
            o=c.execute('SELECT o.status,o.file_key,v.status AS visit_status FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?',(order_id,)).fetchone()
            if o and o['visit_status'] in ('completed','cancelled'):raise HTTPException(409,'Lượt khám đã kết thúc')
            if not o:raise HTTPException(404,'Không có chỉ định')
            if o['status'] in ('approved','cancelled','requested'):raise HTTPException(409,'Kết quả đã duyệt')
            if LAN:check_upload(FILES,len(raw))
            previous=o['file_key']
            with target.open('xb') as output:
                output.write(raw);output.flush();os.fsync(output.fileno())
            c.execute('UPDATE orders SET file_key=?,file_name=? WHERE id=?',(key,(file.filename or 'Kết quả')[:120],order_id))
            audit(c,u,'attachment_uploaded','order',order_id,key)
    except Exception:
        if target.exists():
            try:
                # A lost COMMIT acknowledgement is ambiguous: the database may
                # already reference this file. Delete only after reconciliation
                # under the same lock as writers/backup; preserve on DB outage.
                with db(True) as c:
                    if not c.execute('SELECT 1 FROM orders WHERE file_key=?',(key,)).fetchone():
                        target.unlink(missing_ok=True)
            except Exception:
                import logging
                logging.getLogger('clinic').warning('Attachment preserved pending transaction reconciliation')
        raise
    # Retire only the replaced, unreferenced attachment after successful commit,
    # taking the same lock as backup so a directory scan cannot race deletion.
    if previous and previous!=key:
        try:
            with db(True) as c:
                if not c.execute('SELECT 1 FROM orders WHERE file_key=?',(previous,)).fetchone():
                    (FILES/previous).unlink(missing_ok=True)
        except Exception:
            import logging
            logging.getLogger('clinic').warning('Replaced attachment cleanup deferred')
    return {'ok':True,'file_name':file.filename}

@app.get('/api/orders/{order_id}/attachment')
def get_attachment(order_id:int,u=Depends(principal)):
    require(u,'doctor','technician')
    with db(True) as c:
        o=c.execute('SELECT o.*,v.doctor_id FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?',(order_id,)).fetchone()
        if not o or not o['file_key']:raise HTTPException(404,'Không có tệp')
        if 'doctor' in u['roles'] and o['doctor_id']!=u['id'] and 'technician' not in u['roles']:raise HTTPException(403,'Không có quyền')
        audit(c,u,'attachment_viewed','order',order_id)
        target=FILES/o['file_key']
        if not target.is_file():raise HTTPException(404,'Tệp không tồn tại')
        return FileResponse(target,filename=o['file_name'],headers={'Cache-Control':'no-store'})

class RxItemInput(BaseModel):
    medicine_id:int=Field(gt=0)
    quantity:int=Field(gt=0,le=10000)
    unit_id:int|None=None
    directions:str=Field(default='',max_length=300)

class PrescriptionInput(BaseModel):
    visit_id:int
    drug_lines:str=Field(default='',max_length=6000)
    items:list[RxItemInput]=Field(default_factory=list,max_length=30)
    instructions:str=Field(default='',max_length=3000)
    follow_up:str|None=Field(default=None,max_length=80)

    @field_validator('follow_up')
    @classmethod
    def follow_up_day(cls,v):
        return parse_day(v)

@app.post('/api/prescriptions',status_code=201)
def create_rx(data:PrescriptionInput,u=Depends(principal)):
    require(u,'doctor')
    with db(True) as c:
        v=visit_access(c,u,data.visit_id,clinical=True)
        ensure_open(v)
        require_child_prescription(c,v)
        if not (v['diagnosis'] or '').strip():raise HTTPException(409,'Cần lưu chẩn đoán trên phiếu khám trước khi lập đơn thuốc')
        if c.execute('SELECT 1 FROM prescriptions WHERE visit_id=?',(data.visit_id,)).fetchone():raise HTTPException(409,'Lượt khám đã có đơn nháp')
        if LAN and not data.items:raise HTTPException(422,'Đơn LAN phải có dòng thuốc cấu trúc liên kết danh mục kho')
        if not data.items and not data.drug_lines.strip():raise HTTPException(422,'Cần nhập thuốc')
        lines=[];normalized=[]
        for item in data.items:
            med=c.execute('SELECT id,name,base_unit,controlled,active FROM medicines WHERE id=?',(item.medicine_id,)).fetchone()
            if not med:raise HTTPException(422,'Thuốc không có trong danh mục')
            if not med['active']:raise HTTPException(409,'Thuốc không còn hiệu lực')
            if med['controlled'] and 'controlled_prescriber' not in u['roles']:raise HTTPException(403,'Thiếu quyền bác sĩ thuốc kiểm soát đặc biệt')
            factor=1;unit=med['base_unit']
            if item.unit_id:
                conversion=c.execute('SELECT * FROM medicine_units WHERE id=? AND medicine_id=? AND active=1',(item.unit_id,item.medicine_id)).fetchone()
                if not conversion:raise HTTPException(422,'Đơn vị thuốc không hợp lệ')
                factor=conversion['base_factor'];unit=conversion['name']
            if item.quantity*factor>10000:raise HTTPException(422,'Số lượng quy đổi quá giới hạn')
            normalized.append((item,item.quantity*factor,unit,factor))
            lines.append(f'{med["name"]} | {item.quantity} {unit} | {item.directions}')
        narrative='\n'.join(lines) if lines else data.drug_lines
        c.execute('INSERT INTO prescriptions(visit_id,doctor_id,drug_lines,instructions,follow_up,created_at) VALUES(?,?,?,?,?,?)',
                  (data.visit_id,u['id'],narrative,data.instructions,data.follow_up,NOW()))
        rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        for item,base_qty,unit,factor in normalized:
            c.execute('INSERT INTO prescription_items(prescription_id,medicine_id,quantity,directions,unit_name,unit_factor,unit_quantity) VALUES(?,?,?,?,?,?,?)',
                      (rid,item.medicine_id,base_qty,item.directions,unit,factor,item.quantity))
        audit(c,u,'rx_draft_created','prescription',rid)
        return {'id':rid,'status':'draft','structured_items':len(data.items)}

@app.get('/api/prescriptions')
def get_rx(u=Depends(principal), visit_id:int|None=None,
           status:Literal['draft','dispensed','cancelled']|None=None,
           limit:Annotated[int|None,Query(ge=1,le=200)]=None,
           offset:Annotated[int,Query(ge=0,le=1000000)]=0):
    require(u,'doctor','pharmacy')
    with db() as c:
        sql="SELECT rx.*,v.patient_id,p.full_name AS patient_name,p.code AS patient_code FROM prescriptions rx JOIN visits v ON v.id=rx.visit_id JOIN patients p ON p.id=v.patient_id"
        args=[];where=[]
        if 'doctor' in u['roles'] and 'pharmacy' not in u['roles']:
            where.append('rx.doctor_id=?');args.append(u['id'])
        if visit_id is not None:where.append('rx.visit_id=?');args.append(visit_id)
        if status:where.append('rx.status=?');args.append(status)
        if where:sql+=' WHERE '+' AND '.join(where)
        sql+=' ORDER BY rx.id DESC'
        if limit is not None:sql+=' LIMIT ? OFFSET ?';args.extend((limit,offset))
        rows=[dict(x) for x in c.execute(sql,args)]
        by_id={rx['id']:rx for rx in rows}
        for rx in rows:rx['items']=[]
        if rows:
            # Một lần lấy các dòng thuốc của đúng các đơn đã được lọc quyền;
            # không thêm một lượt đi/về PostgreSQL cho mỗi đơn trong lịch sử.
            selected=list(by_id)
            for start in range(0,len(selected),500):
                batch=selected[start:start+500];marks=','.join('?' for _ in batch)
                for item in c.execute('''SELECT pi.prescription_id,pi.id,pi.medicine_id,pi.quantity,pi.directions,pi.unit_name,pi.unit_quantity,pi.unit_factor,m.name,m.base_unit
                    FROM prescription_items pi JOIN medicines m ON m.id=pi.medicine_id
                    WHERE pi.prescription_id IN ('''+marks+''') ORDER BY pi.id''',batch):
                    value=dict(item);rid=value.pop('prescription_id');by_id[rid]['items'].append(value)
        return rows

# Hàng chờ thu ngân: KHÔNG cắt theo "100 lượt mới nhất". Trả mọi lượt còn nợ, còn khoản
# chưa có giá, cần hoàn tiền (đã thu > phải thu), cộng mọi lượt tạo trong ngày hôm nay (giờ VN).
# Tính tổng một lần bằng GROUP BY (không truy vấn con theo từng lượt) để đủ nhanh với vài chục nghìn lượt.
def today_start_utc():
    """0 giờ hôm nay theo giờ Việt Nam, dạng chuỗi UTC như cột created_at."""
    vn=timezone(timedelta(hours=7))
    return datetime.now(vn).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat(timespec='seconds')


def dues_rows(c,since=None):
    return [dict(x) for x in c.execute(DUES_SQL,(since or today_start_utc(),))]


@app.get('/api/dues')
def dues(u=Depends(principal)):
    # Lễ tân không xem công nợ từng lượt; người kiêm thu ngân đọc qua vai trò cashier.
    require(u,'cashier','manager')
    with db() as c:
        return dues_rows(c)

class PaymentInput(BaseModel):
    visit_id:int
    amount:int=Field(gt=0,le=2_000_000_000)
    method:Literal['cash','transfer']
    idempotency_key:str=Field(min_length=8,max_length=120)
    external_ref:str|None=Field(default=None,max_length=120)
    prepayment:bool=False  # Chỉ chức năng "Nhận tiền ứng trước" gửi True.
    confirm_over_limit:bool=False  # Xác nhận trong trang khi thu tạm vượt trần.

# Trần thu tạm (cộng dồn mọi phiếu thu tạm của lượt, kể cả phiếu đang thu).
PROVISIONAL_CAP=5_000_000
PROVISIONAL_MULTIPLE=3

def provisional_limit(c,vid,amount):
    """(tổng thu tạm sau phiếu này, tổng các khoản đã có giá, có vượt trần không)."""
    before=c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE visit_id=? AND kind='provisional'",(vid,)).fetchone()[0]
    priced=c.execute('SELECT COALESCE(SUM(amount),0) FROM effective_charges WHERE visit_id=? AND amount IS NOT NULL',(vid,)).fetchone()[0]
    total=before+amount
    return total,priced,total>PROVISIONAL_CAP or total>PROVISIONAL_MULTIPLE*priced

@app.post('/api/payments',status_code=201)
def create_payment(data:PaymentInput,u=Depends(principal)):
    require(u,'cashier')
    with db(True) as c:
        old=c.execute('SELECT * FROM payments WHERE idempotency_key=?',(data.idempotency_key,)).fetchone()
        if old:
            if old['created_by']!=u['id'] or old['amount']!=data.amount or old['visit_id']!=data.visit_id or old['method']!=data.method or (old['external_ref'] or None)!=(data.external_ref or None) or old['is_advance']!=int(data.prepayment):raise HTTPException(409,'Khóa giao dịch đã được sử dụng với dữ liệu khác')
            return {'id':old['id'],'status':'already_recorded'}
        if not c.execute('SELECT 1 FROM visits WHERE id=?',(data.visit_id,)).fetchone():raise HTTPException(404,'Không có lượt khám')
        if c.execute('SELECT status FROM visits WHERE id=?',(data.visit_id,)).fetchone()[0]=='cancelled':raise HTTPException(409,'Không nhận tiền mới cho lượt đã hủy')
        # Loại giao dịch do máy chủ quyết định lúc thu và lưu lại; in phiếu luôn theo loại đã lưu.
        if data.prepayment:kind='advance'
        elif invoice(c,data.visit_id)['unpriced_count']:kind='provisional'
        else:kind='regular'
        if kind=='provisional':
            total,priced,over=provisional_limit(c,data.visit_id,data.amount)
            if over and not data.confirm_over_limit:
                raise HTTPException(409,f'Thu tạm cộng dồn {total:,} đ vượt trần (5.000.000 đ hoặc 3 lần {priced:,} đ đã có giá). Đánh dấu ô xác nhận rồi thu lại'.replace(',', '.'))
        charged=c.execute("SELECT (SELECT COALESCE(SUM(ch.amount),0) FROM effective_charges ch WHERE ch.visit_id=? AND NOT EXISTS (SELECT 1 FROM charge_voids cv WHERE cv.charge_id=ch.id))-(SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE visit_id=? AND kind='discount' AND status='approved')",(data.visit_id,data.visit_id)).fetchone()[0]
        paid=c.execute("SELECT (SELECT COALESCE(SUM(amount),0) FROM payments WHERE visit_id=?)-(SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE visit_id=? AND kind='refund' AND status='approved')",(data.visit_id,data.visit_id)).fetchone()[0]
        if kind=='regular' and data.amount>charged-paid:raise HTTPException(409,'Số tiền vượt khoản còn phải thu')
        c.execute('INSERT INTO payments(visit_id,amount,method,created_by,created_at,external_ref,idempotency_key,is_advance,kind) VALUES(?,?,?,?,?,?,?,?,?)',
                  (data.visit_id,data.amount,data.method,u['id'],NOW(),data.external_ref,data.idempotency_key,int(kind=='advance'),kind))
        payid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        audit(c,u,'payment_recorded_demo','payment',payid,kind+('; vượt trần thu tạm đã xác nhận' if kind=='provisional' and data.confirm_over_limit else ''))
        return {'id':payid,'status':'recorded','kind':kind}

@app.get('/api/stock')
def stock(u=Depends(principal)):
    require(u,'pharmacy','manager')
    with db() as c:
        return [dict(x) for x in c.execute('''SELECT l.id,m.name,m.base_unit,m.controlled,l.lot_number,l.expiry_date,l.quantity,l.quarantined
          FROM stock_lots l JOIN medicines m ON m.id=l.medicine_id ORDER BY m.id,l.expiry_date''')]


@app.get('/api/medicines')
def get_medicines(u=Depends(principal)):
    require(u,'pharmacy','manager')
    with db() as c:
        return [dict(x) for x in c.execute('SELECT id,name,base_unit,controlled FROM medicines ORDER BY id')]

class StockReceipt(BaseModel):
    medicine_id:int=Field(gt=0)
    lot_number:str=Field(min_length=2,max_length=80)
    expiry_date:str
    quantity:int=Field(gt=0,le=10_000_000)

    @field_validator('expiry_date')
    @classmethod
    def check_expiry(cls,v):
        if date.fromisoformat(v)<date.today():raise ValueError('Không nhận thuốc đã hết hạn')
        return v

@app.post('/api/stock/receipts',status_code=201)
def add_stock_receipt(data:StockReceipt,u=Depends(principal)):
    require(u,'pharmacy')
    with db(True) as c:
        med=c.execute('SELECT * FROM medicines WHERE id=?',(data.medicine_id,)).fetchone()
        if not med:raise HTTPException(404,'Không tìm thấy mặt hàng')
        if med['controlled']:raise HTTPException(403,'Chưa triển khai tiếp nhận thuốc phải kiểm soát đặc biệt trong bản demo')
        old=c.execute('SELECT * FROM stock_lots WHERE medicine_id=? AND lot_number=?',(data.medicine_id,data.lot_number)).fetchone()
        if old:
            if old['expiry_date']!=data.expiry_date or old['quarantined']:
                raise HTTPException(409,'Lô đã có thông tin khác hoặc đang cách ly')
            c.execute('UPDATE stock_lots SET quantity=quantity+? WHERE id=?',(data.quantity,old['id']))
            lid=old['id']
        else:
            c.execute('INSERT INTO stock_lots(medicine_id,lot_number,expiry_date,quantity) VALUES(?,?,?,?)',
                      (data.medicine_id,data.lot_number,data.expiry_date,data.quantity))
            lid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(?,?,?,?,?)',
                  (lid,'receipt',data.quantity,u['id'],NOW()))
        audit(c,u,'stock_received_demo','stock_lot',lid,str(data.quantity))
        return {'stock_lot_id':lid,'quantity_added':data.quantity}

@app.get('/api/overview')
def overview(u=Depends(principal)):
    with db() as c:
        visits=c.execute('SELECT COUNT(*) FROM visits').fetchone()[0]
        orders=c.execute("SELECT COUNT(*) FROM orders WHERE status!='approved'").fetchone()[0]
        out={'visits':visits,'pending_orders':orders,'role':u['roles'][0]}
        if 'manager' in u['roles']:
            charged=c.execute("SELECT (SELECT COALESCE(SUM(ch.amount),0) FROM effective_charges ch WHERE NOT EXISTS (SELECT 1 FROM charge_voids cv WHERE cv.charge_id=ch.id))-(SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE kind='discount' AND status='approved')").fetchone()[0]
            paid=c.execute("SELECT (SELECT COALESCE(SUM(amount),0) FROM payments)-(SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE kind='refund' AND status='approved')").fetchone()[0]
            unpriced=c.execute('SELECT COUNT(*) FROM effective_charges WHERE amount IS NULL').fetchone()[0]
            out.update(charged=charged,paid=paid,outstanding=None if unpriced else charged-paid,
                       known_outstanding=charged-paid,unpriced_count=unpriced,
                       stock_warning=c.execute("SELECT COUNT(*) FROM stock_lots WHERE quarantined=1 OR expiry_date<=date('now','+90 days')").fetchone()[0])
        return out

@app.get('/api/audit')
def audit_entries(offset:int=0,limit:int=100,u=Depends(principal)):
    require(u,'admin')
    if offset<0 or limit<1 or limit>200:raise HTTPException(422,'Phân trang không hợp lệ')
    with db() as c:
        return [dict(x) for x in c.execute('SELECT a.id,a.user_id,u.username,a.event,a.object_type,a.object_id,a.details,a.created_at FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ? OFFSET ?',(limit,offset))]

# Export only source-verified visit data; export endpoints enforce role/visit scope.
from .forms_api import mount_forms
mount_forms(app, db, principal, require, audit)


# The following extensions are strictly confined to the local pilot.

def _invoice_state(c, vid:int):
    charged=c.execute('''SELECT COALESCE(SUM(ch.amount),0) FROM effective_charges ch WHERE ch.visit_id=?
        AND NOT EXISTS (SELECT 1 FROM charge_voids v WHERE v.charge_id=ch.id)''',(vid,)).fetchone()[0]
    discounts=c.execute("SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE visit_id=? AND kind='discount' AND status='approved'",(vid,)).fetchone()[0]
    incoming=c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE visit_id=?',(vid,)).fetchone()[0]
    refunds=c.execute("SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE visit_id=? AND kind='refund' AND status='approved'",(vid,)).fetchone()[0]
    return {'charged':charged-discounts,'paid':incoming-refunds,'discounts':discounts,'refunds':refunds,'raw_charges':charged,
            'unpriced_count':invoice(c,vid)['unpriced_count']}

@app.get('/api/payments')
def list_payments(u=Depends(principal)):
    require(u,'cashier','manager')
    with db() as c:
        return [dict(x) for x in c.execute('''SELECT m.id,m.visit_id,m.amount,m.method,m.created_at,m.external_ref,m.kind,
             (SELECT COUNT(*) FROM effective_charges ch WHERE ch.visit_id=m.visit_id AND ch.amount IS NULL) AS unpriced_count,
             p.code AS patient_code,p.full_name AS patient_name,users.full_name AS cashier_name
             FROM payments m JOIN visits v ON v.id=m.visit_id JOIN patients p ON p.id=v.patient_id
             JOIN users ON users.id=m.created_by ORDER BY m.id DESC LIMIT 100''')]

class AdjustmentInput(BaseModel):
    visit_id:int=Field(gt=0)
    kind:Literal['discount','refund']
    amount:int=Field(gt=0,le=2_000_000_000)
    reason:str=Field(min_length=5,max_length=500)
    payment_id:int|None=None

@app.post('/api/adjustments',status_code=201)
def propose_adjustment(data:AdjustmentInput,u=Depends(principal)):
    require(u,'cashier')
    with db(True) as c:
        if not c.execute('SELECT 1 FROM visits WHERE id=?',(data.visit_id,)).fetchone():
            raise HTTPException(404,'Không có lượt khám')
        st=_invoice_state(c,data.visit_id)
        if data.kind=='discount':
            if data.payment_id is not None:raise HTTPException(422,'Giảm giá không gắn một phiếu thu')
            if st['charged']-data.amount<0:raise HTTPException(409,'Giảm giá vượt tổng phí còn được giảm')
        else:
            if st['unpriced_count']:raise HTTPException(409,'Chưa xác định đủ giá, chưa thể đối soát tiền trả thừa để hoàn')
            if data.payment_id is None:raise HTTPException(422,'Cần chọn phiếu thu được đề nghị hoàn')
            pay=c.execute('SELECT * FROM payments WHERE id=? AND visit_id=?',(data.payment_id,data.visit_id)).fetchone()
            if not pay:raise HTTPException(422,'Phiếu thu không khớp lượt khám')
            current=c.execute("SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE payment_id=? AND kind='refund' AND status='approved'",(data.payment_id,)).fetchone()[0]
            if data.amount>pay['amount']-current:raise HTTPException(409,'Số hoàn vượt số đã thu ở phiếu')
        c.execute('''INSERT INTO adjustments(visit_id,payment_id,kind,amount,reason,proposed_by,proposed_at)
                     VALUES(?,?,?,?,?,?,?)''',(data.visit_id,data.payment_id,data.kind,data.amount,data.reason,u['id'],NOW()))
        id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        audit(c,u,'adjustment_requested','adjustment',id)
        return {'id':id,'status':'pending'}

@app.get('/api/adjustments')
def adjustments_list(u=Depends(principal),history:bool=False):
    require(u,'cashier','manager')
    with db() as c:
        sql='''SELECT a.id,a.visit_id,a.payment_id,a.kind,a.amount,a.reason,a.status,a.proposed_at,a.reviewed_at,
          p.full_name AS patient_name,users.full_name AS proposed_name FROM adjustments a
          JOIN visits v ON v.id=a.visit_id JOIN patients p ON p.id=v.patient_id JOIN users ON users.id=a.proposed_by'''
        args=()
        if 'manager' not in u['roles']:
            sql+=' WHERE a.proposed_by=? AND ';args=(u['id'],)
        else:sql+=' WHERE '
        sql+=approval_predicate('a',history)
        return [dict(x) for x in c.execute(sql+' ORDER BY a.id DESC'+history_limit(history),args)]

class AdjustmentReview(BaseModel):
    approve:bool

@app.post('/api/adjustments/{adj_id}/review')
def review_adjustment(adj_id:int,data:AdjustmentReview,u=Depends(principal)):
    require(u,'manager')
    with db(True) as c:
        a=c.execute('SELECT * FROM effective_adjustments WHERE id=?',(adj_id,)).fetchone()
        if not a:raise HTTPException(404,'Không có đề nghị')
        if a['status']!='pending':raise HTTPException(409,'Đã giải quyết đề nghị này')
        if a['proposed_by']==u['id']:raise HTTPException(403,'Không được tự duyệt đề nghị của mình')
        st=_invoice_state(c,a['visit_id'])
        if data.approve:
            if a['kind']=='discount' and st['charged']-a['amount']<0:
                raise HTTPException(409,'Số giảm giá vượt tổng phí còn được giảm')
            if a['kind']=='refund':
                if st['unpriced_count']:raise HTTPException(409,'Lượt còn khoản CHƯA CÓ GIÁ; chưa được duyệt hoàn phần trả thừa')
                pay=c.execute('SELECT amount FROM payments WHERE id=? AND visit_id=?',(a['payment_id'],a['visit_id'])).fetchone()
                already=c.execute("SELECT COALESCE(SUM(amount),0) FROM effective_adjustments WHERE payment_id=? AND kind='refund' AND status='approved'",(a['payment_id'],)).fetchone()[0]
                if not pay or a['amount']>pay['amount']-already or a['amount']>st['paid']:
                    raise HTTPException(409,'Số tiền hoàn vượt số còn có thể hoàn')
                # Refund only for an agreed overpayment after a discount/cancellation, not an arbitrary cash payout.
                if st['paid']-a['amount']<st['charged']:
                    raise HTTPException(409,'Chỉ hoàn phần tiền lớn hơn khoản phải thu đã được giảm hoặc điều chỉnh')
        new='approved' if data.approve else 'rejected'
        c.execute('UPDATE adjustments SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',(new,u['id'],NOW(),adj_id))
        audit(c,u,'adjustment_'+new,'adjustment',adj_id)
        return {'id':adj_id,'status':new}

class StockIssue(BaseModel):
    medicine_id:int=Field(gt=0)
    quantity:int=Field(gt=0,le=10_000_000)
    purpose:str=Field(default='Sử dụng nội bộ mô phỏng',min_length=5,max_length=200)

@app.post('/api/stock/issues',status_code=201)
def stock_issue(data:StockIssue,u=Depends(principal)):
    require(u,'pharmacy')
    with db(True) as c:
        med=c.execute('SELECT * FROM medicines WHERE id=?',(data.medicine_id,)).fetchone()
        if not med:raise HTTPException(404,'Không có thuốc/vật tư')
        if med['controlled']:raise HTTPException(403,'Chưa triển khai xuất thuốc phải kiểm soát đặc biệt')
        lots=c.execute("SELECT id,quantity FROM stock_lots WHERE medicine_id=? AND quarantined=0 AND expiry_date>=? AND quantity>0 ORDER BY expiry_date,id",(data.medicine_id,date.today().isoformat())).fetchall()
        if sum(l['quantity'] for l in lots)<data.quantity:raise HTTPException(409,'Không đủ tồn khả dụng hoặc đã hết hạn')
        remaining=data.quantity;used=[]
        for l in lots:
            if not remaining:break
            take=min(remaining,l['quantity']); remaining-=take
            updated=c.execute('UPDATE stock_lots SET quantity=quantity-? WHERE id=? AND quantity>=?',(take,l['id'],take))
            if updated.rowcount!=1:raise HTTPException(409,'Tồn kho đã thay đổi; hãy tải lại')
            c.execute('INSERT INTO stock_movements(stock_lot_id,movement_type,quantity,created_by,created_at) VALUES(?,?,?,?,?)',
                      (l['id'],'issue',take,u['id'],NOW()))
            used.append({'lot_id':l['id'],'quantity':take})
        audit(c,u,'stock_issued_demo','medicine',data.medicine_id,f'{data.purpose}: {data.quantity} base units')
        return {'medicine_id':data.medicine_id,'quantity':data.quantity,'lots':used,'status':'demo_issued'}

@app.get('/api/print/{kind}/{item_id}')
@export_slot
def print_form(kind:str,item_id:int,u=Depends(principal)):
    if kind not in ('intake','clinical','order','result','rx','follow_up','receipt'):
        raise HTTPException(404,'Biểu mẫu không tồn tại')
    with db(True) as c:
        if kind in ('intake','clinical','follow_up'):
            v=c.execute('''SELECT v.*,p.full_name AS patient_name,p.code AS patient_code,
                     p.date_of_birth,p.sex,p.phone,p.address,users.full_name AS doctor_name
                     FROM visits v JOIN patients p ON p.id=v.patient_id
                     JOIN users ON users.id=v.doctor_id WHERE v.id=?''',(item_id,)).fetchone()
            if not v:raise HTTPException(404,'Lượt khám không tồn tại')
            if kind=='intake':require(u,'reception','admin')
            else:
                require(u,'doctor')
                if v['doctor_id']!=u['id']:raise HTTPException(403,'Bác sĩ không được phân công')
            data=dict(v);data['code']=f'MD-V-{item_id:06d}'
        elif kind in ('order','result'):
            o=c.execute('''SELECT o.*,v.doctor_id,p.code AS patient_code,p.full_name AS patient_name,
                      p.date_of_birth,p.sex,users.full_name AS doctor_name,
                      appr.full_name AS approved_name,tech.full_name AS result_by_name FROM orders o
                      JOIN visits v ON v.id=o.visit_id JOIN patients p ON p.id=v.patient_id
                      JOIN users ON users.id=v.doctor_id LEFT JOIN users appr ON appr.id=o.approved_by
                      LEFT JOIN users tech ON tech.id=o.result_by
                      WHERE o.id=?''',(item_id,)).fetchone()
            if not o:raise HTTPException(404,'Không có chỉ định')
            require(u,'doctor')
            if o['doctor_id']!=u['id']:raise HTTPException(403,'Không phải bác sĩ phụ trách')
            if kind=='result' and o['status']!='approved':raise HTTPException(409,'Kết quả chưa được duyệt')
            data=dict(o);data['code']=f'MD-CLS-{item_id:06d}'
        elif kind=='rx':
            rx=c.execute('''SELECT rx.*,v.diagnosis,v.doctor_id,p.full_name AS patient_name,
                        p.code AS patient_code,p.date_of_birth,p.sex,p.phone,p.address,users.full_name AS doctor_name
                        FROM prescriptions rx JOIN visits v ON v.id=rx.visit_id
                        JOIN patients p ON p.id=v.patient_id JOIN users ON users.id=rx.doctor_id WHERE rx.id=?''',(item_id,)).fetchone()
            if not rx:raise HTTPException(404,'Không có đơn nháp')
            require(u,'doctor')
            if rx['doctor_id']!=u['id']:raise HTTPException(403,'Không được in đơn bệnh nhân khác')
            data=dict(rx);data['code']=f'MD-RX-{item_id:06d}'
        else:
            pay=c.execute('''SELECT pay.*,p.code AS patient_code,p.full_name AS patient_name,
                         users.full_name AS cashier_name FROM payments pay
                         JOIN visits v ON v.id=pay.visit_id JOIN patients p ON p.id=v.patient_id
                         JOIN users ON users.id=pay.created_by WHERE pay.id=?''',(item_id,)).fetchone()
            if not pay:raise HTTPException(404,'Không có khoản thu')
            require(u,'cashier','manager')
            data=dict(pay);data['code']=f'MD-PT-{item_id:06d}'
            # Tiêu đề theo loại đã lưu lúc thu; người gọi không đổi được (không nhận tham số loại).
            data['receipt_kind']=pay['kind']
        if kind=='receipt':data['cashier_name']=printed_name(c,data['created_by'])
        if kind!='receipt':
            data['doctor_name']=printed_name(c,data['doctor_id'])
            if kind in ('order','result'):
                data['approved_name']=printed_name(c,data.get('approved_by'))
                data['result_by_name']=printed_name(c,data.get('result_by'))
        if kind=='clinical':data['addenda']=[dict(x) for x in c.execute("SELECT * FROM visit_addenda WHERE visit_id=? AND status='approved' ORDER BY id",(item_id,))]
        pdf=pdf_document(kind,data)
        audit(c,u,'form_pdf_generated_demo',kind,item_id)
        return Response(content=pdf,media_type='application/pdf',headers={
            'Content-Disposition':f'attachment; filename="MinhDuc_{kind}_{item_id}.pdf"',
            'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff'})

# --- v0.2: Xuất biểu mẫu từ chính dữ liệu SQLite; quyền kiểm tra phía API. ---
from fastapi.responses import Response
from .forms import generate_docx, generate_pdf, TEMPLATE_BY_TYPE

def form_context(c, kind: str, object_id: int):
    order=None;rx=None
    if kind in ('order','lab','ultrasound','xray','ecg'):
        order=row(c.execute('SELECT * FROM orders WHERE id=?',(object_id,)).fetchone())
        if not order:raise HTTPException(404,'Không có chỉ định / kết quả')
        if kind in ('lab','ultrasound','xray','ecg') and order['category']!=kind:
            raise HTTPException(422,'Loại biểu mẫu không phù hợp loại chỉ định')
        visit_id=order['visit_id']
    elif kind=='rx':
        rx=row(c.execute('SELECT * FROM prescriptions WHERE id=?',(object_id,)).fetchone())
        if not rx:raise HTTPException(404,'Không có đơn thuốc nháp')
        visit_id=rx['visit_id']
    else:visit_id=object_id
    visit=row(c.execute('SELECT * FROM visits WHERE id=?',(visit_id,)).fetchone())
    if not visit:raise HTTPException(404,'Không có lượt khám')
    patient=redact_document(row(c.execute('SELECT * FROM patients WHERE id=?',(visit['patient_id'],)).fetchone()))
    charge=c.execute('SELECT label FROM effective_charges WHERE visit_id=? ORDER BY id LIMIT 1',(visit_id,)).fetchone()
    context={'visit':visit,'patient':patient,'doctor_name':printed_name(c,visit['doctor_id']),
             'service_label':charge['label'] if charge else 'Chưa xác định',
             'orders':[dict(x) for x in c.execute('SELECT * FROM orders WHERE visit_id=? ORDER BY id LIMIT 201',(visit_id,))]}
    if len(context['orders'])>200:raise HTTPException(413,'Lượt khám quá nhiều chỉ định để xuất gộp; liên hệ quản trị')
    if order:
        names=lambda uid:printed_name(c,uid)
        order['result_by_name']=names(order.get('result_by'))
        order['approved_by_name']=names(order.get('approved_by'))
        context['order']=order
    if kind=='visit':context['addenda']=[dict(x) for x in c.execute("SELECT a.*,u.full_name AS author_name FROM visit_addenda a JOIN users u ON u.id=a.created_by WHERE a.visit_id=? AND a.status='approved' ORDER BY a.id",(visit_id,))]
    for appendix in context.get('addenda',[]):appendix['author_name']=printed_name(c,appendix['created_by'])
    if rx:context['rx']=rx
    if kind=='followup':
        r=c.execute('SELECT * FROM prescriptions WHERE visit_id=?',(visit_id,)).fetchone()
        if r:context['rx']=dict(r)
    return context

@app.get('/api/forms/{kind}/{object_id}',name='download_demo_form')
@export_slot
def export_form(kind:str,object_id:int,fmt:Literal['pdf','docx']='pdf',u=Depends(principal)):
    if kind not in TEMPLATE_BY_TYPE:raise HTTPException(404,'Không có biểu mẫu')
    if kind=='intake':require(u,'reception','admin')
    elif kind in ('visit','order','followup'):require(u,'doctor')
    elif kind=='rx':require(u,'doctor','pharmacy')
    else:require(u,'doctor','technician')
    with db(True) as c:
        context=form_context(c,kind,object_id)
        v=context['visit'];o=context.get('order')
        if kind in ('visit','order','followup') or (kind=='rx' and 'doctor' in u['roles']):
            if v['doctor_id']!=u['id']:raise HTTPException(403,'Không phải bác sĩ được phân công')
        if kind=='rx' and 'doctor' not in u['roles'] and 'pharmacy' not in u['roles']:
            raise HTTPException(403,'Không được truy cập đơn')
        if kind in ('lab','ultrasound','xray','ecg'):
            if 'doctor' in u['roles'] and v['doctor_id']!=u['id'] and 'technician' not in u['roles']:
                raise HTTPException(403,'Không phải bác sĩ được phân công')
            if (o or {}).get('status')!='approved':
                raise HTTPException(409,'Kết quả chưa được duyệt mô phỏng')
        # Data is fetched solely from the authorized record, never client-submitted text.
        audit(c,u,'draft_form_exported','visit',v['id'],f'{kind}.{fmt}')
    try:
        payload=generate_pdf(kind,context) if fmt=='pdf' else generate_docx(kind,context)
    except Exception as exc:
        # Do not expose server-local file paths to clients.
        raise HTTPException(503,'Không tạo được biểu mẫu, kiểm tra phông chữ hoặc tệp mẫu') from exc
    ext='pdf' if fmt=='pdf' else 'docx'
    mime='application/pdf' if fmt=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    name=f'MinhDuc_DEMO_{kind}_{object_id}.{ext}'
    return Response(payload,media_type=mime,headers={'Content-Disposition':f'attachment; filename="{name}"',
                                                   'Cache-Control':'no-store','X-Demo-Only':'true'})

install_administrative(app,db,principal,require,audit,visit_access,NOW)
install_practitioners(app,db,principal,require,NOW)

from .accounts import install_accounts
install_accounts(app, db, principal, require, audit, pw_hash, NOW)
init_db()

from .catalog import install_catalog
install_catalog(app, db, principal, require, audit)
from .price_import import install_price_import
install_price_import(app, db, principal, require, audit)
from .manual_prices import install_manual_prices
install_manual_prices(app, db, principal, require, audit, NOW)
install_workflows(app, db, principal, require, audit, visit_access, NOW)
from .workflows_v050 import install_v050
install_v050(app,db,principal,require,audit,visit_access,NOW)
from .manager_visits import install_manager_visits
install_manager_visits(app,db,principal,require)
from .doctor_workspace import install_doctor_workspace
install_doctor_workspace(app,db,principal,require,audit,visit_access,NOW)
from .ui_settings import install_ui_settings
install_ui_settings(app,db,principal,require,audit,FILES)
from .ui_settings import settings_path, read_settings
from .queue_counts import install_queue_counts
install_queue_counts(app,principal.peek,lambda:read_settings(settings_path(FILES)),db)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not reflect passwords or clinical payloads in validation responses.
    return JSONResponse(status_code=422, content={'detail':[
        {'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()
    ]})

if LAN:
    import psycopg
    from psycopg_pool import PoolTimeout

    @app.exception_handler(psycopg.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409,content={'detail':'Dữ liệu trùng hoặc quan hệ không hợp lệ; hãy tải lại'})

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_unavailable(request, exc):
        return JSONResponse(status_code=503,content={'detail':'Cơ sở dữ liệu tạm không sẵn sàng; kiểm tra trước khi gửi lại giao dịch'},headers={'Retry-After':'5'})

@app.exception_handler(StorageLimitError)
async def storage_full(request,exc):
    return JSONResponse(status_code=507,content={'detail':str(exc)})
