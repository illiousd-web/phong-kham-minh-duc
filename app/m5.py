"""Structured laboratory results. No price, charge or authorization mutations."""
import json
from datetime import datetime,date
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from typing import Literal
from fastapi import Depends,HTTPException,Query,UploadFile,File,Form,Response
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator
from .labels import VN_TZ
from .practitioners import printed_name,scope_warning
from .domain import status_refresh
from .resources import export_slot
from .forms import format_patient_address

GROUPS={'hematology':'Huyết học','biochemistry':'Sinh hóa','urine':'Nước tiểu','other':'Khác'}
STAGES={'waiting_sample':'Chờ lấy mẫu','working':'Đang làm','pending_review':'Chờ duyệt','approved':'Đã duyệt'}
AFTER_CLOSE_LABEL='Có kết quả điều chỉnh sau khi đóng lượt'
STAGE_SQL="""CASE WHEN v.status='completed' THEN 'approved' WHEN r.status='approved' THEN 'approved' WHEN r.status='pending_review' THEN 'pending_review'
 WHEN r.sample_at IS NOT NULL THEN 'working' ELSE 'waiting_sample' END"""

def dump(v): return json.dumps(v,ensure_ascii=False)

def number(v):
    try:
        n=Decimal(str(v).strip().replace(',','.'))
        if not n.is_finite() or abs(n)>Decimal('1e15') or n.as_tuple().exponent < -50: raise ValueError()
        return n
    except (InvalidOperation,ValueError): raise ValueError('Cần nhập số hữu hạn, dùng dấu phẩy hoặc chấm thập phân')

def rounded_number(value,decimals):
    rounded=number(value).quantize(Decimal(1).scaleb(-decimals),rounding=ROUND_HALF_UP)
    return abs(rounded) if rounded==0 else rounded


def display_number(value,decimals):
    return format(rounded_number(value,decimals),'.'+str(decimals)+'f').replace('.',',')


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Reference(Strict):
    sex:Literal['Nam','Nữ','chung']='chung'
    age_from:int|None=Field(default=None,ge=0,le=1800)
    age_to:int|None=Field(default=None,ge=0,le=1800)
    lower_value:str|None=Field(default=None,max_length=60)
    upper_value:str|None=Field(default=None,max_length=60)
    normal_value:str=Field(default='',max_length=200)
    @model_validator(mode='after')
    def valid(self):
        self.normal_value=self.normal_value.strip()
        for key in ('lower_value','upper_value'):
            v=getattr(self,key)
            setattr(self,key,None if v is None or not str(v).strip() else format(number(v),'f'))
        if self.age_from is not None and self.age_to is not None and self.age_from>self.age_to: raise ValueError('Tuổi từ lớn hơn tuổi đến')
        if self.lower_value is not None and self.upper_value is not None and number(self.lower_value)>number(self.upper_value): raise ValueError('Cận dưới lớn hơn cận trên')
        if not self.normal_value and self.lower_value is None and self.upper_value is None: raise ValueError('Cần ít nhất một cận hoặc giá trị bình thường')
        if self.normal_value and (self.lower_value is not None or self.upper_value is not None): raise ValueError('Chọn cận số hoặc giá trị định tính')
        return self

class TestInput(Strict):
    code:str=Field(min_length=1,max_length=80)
    name:str=Field(min_length=1,max_length=180)
    abbreviation:str=Field(default='',max_length=80)
    group_name:Literal['hematology','biochemistry','urine','other']
    result_type:Literal['number','choice','text']='number'
    unit:str=Field(default='',max_length=80)
    decimals:int=Field(default=2,ge=0,le=8)
    print_order:int=Field(default=0,ge=0,le=10000)
    active:bool=True
    choices:list[str]=Field(default_factory=list,max_length=100)
    references:list[Reference]=Field(default_factory=list,max_length=100)
    @field_validator('code','name','abbreviation','unit')
    @classmethod
    def trim(cls,v):
        return v.strip()
    @model_validator(mode='after')
    def valid(self):
        if not self.code or not self.name: raise ValueError('Cần mã và tên chỉ số')
        self.choices=[s.strip() for s in self.choices]
        if any(not s or len(s)>200 for s in self.choices) or len(set(self.choices))!=len(self.choices): raise ValueError('Danh sách định tính có lựa chọn rỗng/trùng/quá dài')
        if self.result_type=='choice' and not self.choices: raise ValueError('Cần danh sách lựa chọn định tính')
        for i,r in enumerate(self.references):
            if self.result_type=='number' and r.normal_value: raise ValueError('Chỉ số số cần cận số')
            if self.result_type!='number' and not r.normal_value: raise ValueError('Chỉ số chữ/định tính cần giá trị bình thường')
            if self.result_type=='choice' and r.normal_value not in self.choices: raise ValueError('Giá trị bình thường ngoài danh sách lựa chọn')
            for old in self.references[:i]:
                if old.sex==r.sex and max(old.age_from or 0,r.age_from or 0)<=min(old.age_to if old.age_to is not None else 1800,r.age_to if r.age_to is not None else 1800):
                    raise ValueError('Khoảng tuổi tham chiếu chồng lấn cùng giới')
        return self

class LinkInput(Strict):
    test_ids:list[int]=Field(max_length=200)

class Version(Strict):
    version:int=Field(ge=0)

class ResultLine(Strict):
    test_id:int=Field(gt=0)
    value:str=Field(default='',max_length=500)
    note:str=Field(default='',max_length=1000)

class ResultInput(Version):
    sample_at:str|None=None
    result_at:str|None=None
    comment:str=Field(default='',max_length=3000)
    items:list[ResultLine]=Field(max_length=200)
    @field_validator('sample_at','result_at')
    @classmethod
    def stamp(cls,v):
        if not v:return None
        try:
            dt=datetime.fromisoformat(v.replace('Z','+00:00'))
            if dt.tzinfo is None or not 2000<=dt.year<=2100: raise ValueError()
            return dt.isoformat(timespec='seconds')
        except ValueError: raise ValueError('Thời điểm cần ngày giờ có múi giờ, năm 2000–2100')
    @model_validator(mode='after')
    def valid(self):
        if self.result_at and not self.sample_at: raise ValueError('Cần thời điểm lấy mẫu')
        if self.result_at and datetime.fromisoformat(self.result_at)<datetime.fromisoformat(self.sample_at): raise ValueError('Thời điểm kết quả trước lấy mẫu')
        if len({x.test_id for x in self.items})!=len(self.items):raise ValueError('Trùng chỉ số')
        return self

class Adjustment(Version):
    reason:str=Field(min_length=8,max_length=500)
    @field_validator('reason')
    @classmethod
    def reason_valid(cls,v):
        if len(v.strip())<8: raise ValueError('Lý do ít nhất 8 ký tự')
        return v.strip()


def catalog(c,service_id=None):
    predicate=' WHERE EXISTS(SELECT 1 FROM lab_service_tests link WHERE link.test_id=lab_tests.id AND link.service_id=?)' if service_id is not None else ''
    args=(service_id,) if service_id is not None else ()
    items={r['id']:dict(r,choices=json.loads(r['choices']),references=[]) for r in c.execute('SELECT * FROM lab_tests'+predicate+' ORDER BY group_name,print_order,id',args)}
    ref_predicate=' WHERE EXISTS(SELECT 1 FROM lab_service_tests link WHERE link.test_id=lab_reference_ranges.test_id AND link.service_id=?)' if service_id is not None else ''
    for r in c.execute('SELECT * FROM lab_reference_ranges'+ref_predicate+' ORDER BY id',args):
        d=dict(r);items[d.pop('test_id')]['references'].append({k:v for k,v in d.items() if k!='id'})
    return list(items.values())


def save_test(c,data,tid=None):
    old=c.execute('SELECT id FROM lab_tests WHERE code=?',(data.code,)).fetchone()
    if old and old['id']!=tid: raise HTTPException(409,'Mã chỉ số đã tồn tại')
    values=data.model_dump(exclude={'references'});values['choices']=dump(data.choices);values['active']=int(data.active)
    if tid:
        if not c.execute('SELECT 1 FROM lab_tests WHERE id=?',(tid,)).fetchone(): raise HTTPException(404,'Không có chỉ số')
        c.execute('UPDATE lab_tests SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),tid))
    else:
        c.execute('INSERT INTO lab_tests('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))
        tid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('DELETE FROM lab_reference_ranges WHERE test_id=?',(tid,))
    for ref in data.references:
        v=ref.model_dump();c.execute('INSERT INTO lab_reference_ranges(test_id,'+','.join(v)+') VALUES('+','.join('?' for _ in range(len(v)+1))+')',(tid,*v.values()))
    return tid


def age_at(dob,stamp):
    if not dob or not stamp:return None
    born=date.fromisoformat(dob);day=datetime.fromisoformat(stamp).astimezone(VN_TZ).date()
    months=(day.year-born.year)*12+day.month-born.month-(day.day<born.day)
    if months<0: raise HTTPException(422,'Ngày lấy mẫu trước ngày sinh')
    return months


def evaluate(definition,refs,value,sex,age):
    eligible=[r for r in refs if bool(r['normal_value'])==(definition['result_type']!='number') and r['sex'] in ('chung',sex) and
              (age is not None and (r['age_from'] is None or age>=r['age_from']) and (r['age_to'] is None or age<=r['age_to']) or age is None and r['age_from'] is None and r['age_to'] is None)]
    eligible.sort(key=lambda r:r['sex']==sex,reverse=True)
    ref=eligible[0] if eligible else None;flag=''
    if not ref: return {'reference':None,'reference_text':'Chưa có khoảng tham chiếu','flag':''}
    if ref['normal_value']:
        text=ref['normal_value']
        if value.strip() and value.strip().casefold()!=text.casefold(): flag='Bất thường'
    else:
        low,high=ref['lower_value'],ref['upper_value']
        decimals=definition.get('decimals',2)
        text=(display_number(low,decimals)+' – '+display_number(high,decimals)) if low is not None and high is not None else ('≥ '+display_number(low,decimals) if low is not None else '≤ '+display_number(high,decimals))
        if value.strip():
            n=rounded_number(value,decimals)
            if low is not None and n<rounded_number(low,decimals):flag='L'
            if high is not None and n>rounded_number(high,decimals):flag='H'
    return {'reference':{k:v for k,v in ref.items() if k not in ('id','test_id')},'reference_text':text,'flag':flag}


def order_access(c,u,oid,require):
    require(u,'technician','doctor','reception')
    o=c.execute('SELECT o.*,v.doctor_id,v.patient_id,v.status AS visit_status FROM orders o JOIN visits v ON v.id=o.visit_id WHERE o.id=?',(oid,)).fetchone()
    if not o or o['category']!='lab':raise HTTPException(404,'Không có chỉ định xét nghiệm')
    if 'doctor' in u['roles'] and not set(u['roles'])&{'technician','reception'} and o['doctor_id']!=u['id']:raise HTTPException(403,'Không phải bác sĩ phụ trách')
    return o


def report_access(c,u,rid,require,write=False):
    r=c.execute('SELECT * FROM lab_reports WHERE id=?',(rid,)).fetchone()
    if not r:raise HTTPException(404,'Không có phiếu xét nghiệm')
    o=order_access(c,u,r['order_id'],require)
    if write and (o['status'] in ('requested','cancelled') or o['visit_status']=='cancelled'):raise HTTPException(409,'Chỉ định chưa duyệt hoặc đã hủy')
    return r,o


def closed_adjustment_only(r,o):
    if o['visit_status']=='completed' and (not r['replaces_id'] or o['status']!='approved'):
        raise HTTPException(409,'Lượt đã hoàn tất chỉ cho sửa bằng phiếu điều chỉnh của chỉ định đã duyệt')


def report_data(c,r,o):
    if r['status']=='approved':return json.loads(r['snapshot'])
    p=dict(c.execute('SELECT full_name,code,date_of_birth,sex,phone,address,address_detail,province,commune FROM patients WHERE id=?',(o['patient_id'],)).fetchone())
    p['address']=format_patient_address(p);p['age_months']=age_at(p['date_of_birth'],r['sample_at'])
    refs={}
    for ref in c.execute('SELECT * FROM lab_reference_ranges ref WHERE EXISTS(SELECT 1 FROM lab_results line WHERE line.test_id=ref.test_id AND line.report_id=?)',(r['id'],)):
        refs.setdefault(ref['test_id'],[]).append(dict(ref))
    items=[]
    for line in c.execute('SELECT * FROM lab_results WHERE report_id=? ORDER BY id',(r['id'],)):
        definition=json.loads(line['definition']);value=line['value']
        shown=value
        if value and definition['result_type']=='number':
            value=format(rounded_number(value,definition['decimals']),'.'+str(definition['decimals'])+'f')
            shown=display_number(value,definition['decimals'])
        items.append({**definition,'test_id':line['test_id'],'value':value,'raw_value':line['value'],'display_value':shown,'note':line['note'],**evaluate(definition,refs.get(line['test_id'],[]),line['value'],p['sex'],p['age_months'])})
    items.sort(key=lambda x:(list(GROUPS).index(x['group_name']),x['print_order'],x['test_id']))
    return {**dict(r),'visit_id':o['visit_id'],'ordering_doctor_name':printed_name(c,o['doctor_id']),'patient':p,'items':items,'performer_name':printed_name(c,r['performed_by']),'approver_name':printed_name(c,r['approved_by']),'order_name':o['name']}


def redact_reason(c,o,reason):
    # Reasons are free text: never copy document numbers into audit.
    import re
    p=c.execute('SELECT citizen_id,document_number FROM patients WHERE id=?',(o['patient_id'],)).fetchone()
    for value in dict(p).values():
        if value:reason=re.sub(re.escape(str(value)),'[đã ẩn]',reason,flags=re.IGNORECASE)
    return re.sub(r'\b(?:[A-Za-z]{1,3})?\d{6,}\b','[đã ẩn]',reason)


def after_close_visits(c,ids):
    if not ids:return set()
    return {x[0] for x in c.execute("SELECT DISTINCT o.visit_id FROM lab_reports r JOIN orders o ON o.id=r.order_id WHERE o.visit_id IN ("+','.join('?' for _ in ids)+") AND EXISTS(SELECT 1 FROM audit_log a WHERE a.object_type='lab_report' AND a.object_id=r.id AND a.event='lab_adjusted_after_close')",tuple(ids))}


def decorate_orders(c,rows):
    if not rows:return rows
    ids=[x['id'] for x in rows]
    reports={x['order_id']:dict(x) for x in c.execute('SELECT r.order_id,r.id,r.status FROM lab_reports r WHERE r.order_id IN ('+','.join('?' for _ in ids)+') AND r.id=(SELECT MAX(n.id) FROM lab_reports n WHERE n.order_id=r.order_id)',ids)}
    for item in rows:
        report=reports.get(item['id'])
        item['lab_report_id']=report['id'] if report else None
        item['lab_report_status']=report['status'] if report else None
        if item['lab_report_id'] and item['status']!='approved':
            item['result_text']=None;item['file_name']=None
    return rows


def queue(c,u,status,visit_id,limit,offset):
    where=["o.category='lab'","v.status<>'cancelled'","o.status NOT IN ('requested','cancelled')","(r.id IS NOT NULL OR o.status='ordered')"]
    args=[]
    if 'doctor' in u['roles'] and 'technician' not in u['roles'] and 'reception' not in u['roles']:
        where.append('v.doctor_id=?');args.append(u['id'])
    if 'reception' in u['roles'] and not set(u['roles'])&{'doctor','technician'}:
        where.append("r.status='approved'")
    if status:where.append(STAGE_SQL+'=?');args.append(status)
    if visit_id is not None:where.append('v.id=?');args.append(visit_id)
    joins='''FROM orders o JOIN visits v ON v.id=o.visit_id JOIN patients p ON p.id=v.patient_id
        LEFT JOIN lab_reports r ON r.id=(SELECT MAX(x.id) FROM lab_reports x WHERE x.order_id=o.id)'''
    predicate=' AND '.join(where)
    total=c.execute('SELECT COUNT(*) '+joins+' WHERE '+predicate,args).fetchone()[0]
    rows=c.execute('SELECT o.id AS order_id,o.visit_id,o.name,p.full_name AS patient_name,r.id AS report_id,r.version,r.status AS report_status,v.status AS visit_status,'+STAGE_SQL+' AS stage '+joins+' WHERE '+predicate+' ORDER BY o.id DESC LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
    return {'items':[dict(x) for x in rows],'total':total}


def install_m5(app,db,principal,require,audit,visit_access,now):
    @app.get('/api/lab/catalog')
    def get_catalog(u=Depends(principal)):
        require(u,'admin','technician','doctor')
        with db() as c:return {'items':catalog(c),'groups':GROUPS}

    @app.post('/api/lab/catalog',status_code=201)
    def create_test(data:TestInput,u=Depends(principal)):
        require(u,'admin')
        with db(True) as c:
            tid=save_test(c,data);audit(c,u,'lab_catalog_updated','lab_test',tid,'Tạo chỉ số / khoảng tham chiếu');return {'id':tid}

    @app.put('/api/lab/catalog/{tid}')
    def update_test(tid:int,data:TestInput,u=Depends(principal)):
        require(u,'admin')
        with db(True) as c:
            save_test(c,data,tid);audit(c,u,'lab_catalog_updated','lab_test',tid,'Sửa chỉ số / khoảng tham chiếu');return {'id':tid}

    @app.get('/api/lab/services')
    def services(u=Depends(principal)):
        require(u,'admin')
        with db() as c:
            rows=[dict(x,test_ids=[]) for x in c.execute("SELECT s.id,s.name FROM service_catalog s JOIN service_categories cat ON cat.service_id=s.id WHERE cat.category='lab' ORDER BY s.name")]
            links={r['id']:r for r in rows}
            for x in c.execute('SELECT * FROM lab_service_tests'):
                if x['service_id'] in links:links[x['service_id']]['test_ids'].append(x['test_id'])
            return rows

    @app.put('/api/lab/services/{sid}')
    def link(sid:int,data:LinkInput,u=Depends(principal)):
        require(u,'admin')
        with db(True) as c:
            if not c.execute("SELECT 1 FROM service_categories WHERE service_id=? AND category='lab'",(sid,)).fetchone():raise HTTPException(422,'Chọn dịch vụ xét nghiệm đã có')
            for tid in data.test_ids:
                if not c.execute('SELECT 1 FROM lab_tests WHERE id=? AND active=1',(tid,)).fetchone():raise HTTPException(422,'Chỉ số không tồn tại hoặc ngừng dùng')
            c.execute('DELETE FROM lab_service_tests WHERE service_id=?',(sid,))
            for tid in set(data.test_ids):c.execute('INSERT INTO lab_service_tests(service_id,test_id) VALUES(?,?)',(sid,tid))
            audit(c,u,'lab_catalog_updated','service',sid,'Liên kết chỉ số: '+','.join(map(str,sorted(set(data.test_ids)))))
            return {'ok':True}

    @app.get('/api/lab/queue')
    def list_queue(status:Literal['','waiting_sample','working','pending_review','approved']='',visit_id:int|None=None,limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0),u=Depends(principal)):
        require(u,'technician','doctor','reception')
        with db() as c:return queue(c,u,status,visit_id,limit,offset)

    @app.post('/api/lab/orders/{oid}/reports',status_code=201)
    def open_report(oid:int,u=Depends(principal)):
        require(u,'technician')
        with db(True) as c:
            o=order_access(c,u,oid,require)
            if o['status']!='ordered' or o['visit_status'] in ('completed','cancelled'):raise HTTPException(409,'Chỉ mở phiếu từ chỉ định đã xác nhận, chưa có kết quả')
            existing=c.execute('SELECT id FROM lab_reports WHERE order_id=? ORDER BY id DESC LIMIT 1',(oid,)).fetchone()
            if existing:return {'id':existing['id']}
            definitions=catalog(c,o['service_id'])
            if any(not x['active'] for x in definitions):raise HTTPException(422,'Dịch vụ có chỉ số đã ngừng dùng; Quản trị cần rà soát lại liên kết')
            if not definitions:raise HTTPException(422,'Dịch vụ chưa liên kết chỉ số. Quản trị cần cấu hình; kết quả chữ/tệp cũ vẫn xem được.')
            c.execute('INSERT INTO lab_reports(order_id,created_at) VALUES(?,?)',(oid,now()));rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for d in definitions:
                definition={k:v for k,v in d.items() if k not in ('references','id')}
                c.execute('INSERT INTO lab_results(report_id,test_id,definition) VALUES(?,?,?)',(rid,d['id'],dump(definition)))
            audit(c,u,'lab_draft_updated','lab_report',rid,'Tạo nháp');return {'id':rid}

    @app.get('/api/lab/reports/{rid}')
    def detail(rid:int,u=Depends(principal)):
        with db() as c:
            r,o=report_access(c,u,rid,require)
            if r['status']!='approved' and 'technician' not in u['roles']:
                if 'doctor' in u['roles']:return {'id':rid,'status':'working','message':'Đang làm','items':[]}
                raise HTTPException(403,'Chỉ xem / in phiếu đã duyệt')
            return report_data(c,r,o)

    @app.get('/api/lab/reports/{rid}/review')
    def review(rid:int,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            r,o=report_access(c,u,rid,require)
            if o['doctor_id']!=u['id']:raise HTTPException(403,'Không phải bác sĩ phụ trách duyệt')
            if r['status']!='pending_review':raise HTTPException(409,'Phiếu chưa gửi chờ duyệt')
            audit(c,u,'lab_review_viewed','lab_report',rid,'Mở riêng để duyệt; không hiển thị ở kết quả khám')
            return report_data(c,r,o)

    @app.put('/api/lab/reports/{rid}')
    def save(rid:int,data:ResultInput,u=Depends(principal)):
        require(u,'technician')
        with db(True) as c:
            r,o=report_access(c,u,rid,require,True)
            closed_adjustment_only(r,o)
            if r['status']=='approved' or r['version']!=data.version:raise HTTPException(409,'Phiếu đã duyệt hoặc phiên bản đã đổi')
            rows={x['test_id']:x for x in c.execute('SELECT * FROM lab_results WHERE report_id=?',(rid,))}
            if set(rows)!={x.test_id for x in data.items}:raise HTTPException(422,'Cần đúng danh sách chỉ số trên phiếu')
            for line in data.items:
                d=json.loads(rows[line.test_id]['definition']);value=line.value.strip()
                try:
                    if value and d['result_type']=='number':value=format(number(value),'f')
                except ValueError as e:raise HTTPException(422,{'test_id':line.test_id,'message':str(e)})
                if value and d['result_type']=='choice' and value not in d['choices']:raise HTTPException(422,{'test_id':line.test_id,'message':'Chọn giá trị trong danh sách'})
                c.execute('UPDATE lab_results SET value=?,note=? WHERE report_id=? AND test_id=?',(value,line.note.strip(),rid,line.test_id))
            age_at(c.execute('SELECT date_of_birth FROM patients WHERE id=?',(o['patient_id'],)).fetchone()[0],data.sample_at)
            c.execute("UPDATE lab_reports SET status='draft',version=version+1,sample_at=?,result_at=?,comment=?,performed_by=? WHERE id=?",(data.sample_at,data.result_at,data.comment.strip(),u['id'],rid))
            if o['visit_status']!='completed':
                c.execute("UPDATE orders SET status='ordered' WHERE id=?",(o['id'],))
            audit(c,u,'lab_draft_updated','lab_report',rid,'Lưu kết quả nháp');return {'id':rid,'version':data.version+1}

    @app.post('/api/lab/reports/{rid}/submit')
    def submit(rid:int,data:Version,u=Depends(principal)):
        require(u,'technician')
        with db(True) as c:
            r,o=report_access(c,u,rid,require,True)
            closed_adjustment_only(r,o)
            if r['status']!='draft' or r['version']!=data.version:raise HTTPException(409,'Phiếu không còn là nháp hoặc phiên bản đã đổi')
            if not r['sample_at'] or not r['result_at'] or not r['performed_by'] or c.execute("SELECT 1 FROM lab_results WHERE report_id=? AND value=''",(rid,)).fetchone():raise HTTPException(422,'Cần đủ kết quả, thời điểm lấy mẫu / có kết quả và người thực hiện')
            c.execute("UPDATE lab_reports SET status='pending_review',version=version+1 WHERE id=?",(rid,))
            if o['visit_status']!='completed':
                c.execute("UPDATE orders SET status='pending_review' WHERE id=?",(o['id'],))
            audit(c,u,'lab_draft_updated','lab_report',rid,'Gửi chờ duyệt');return {'version':data.version+1}

    @app.post('/api/lab/reports/{rid}/approve')
    def approve(rid:int,data:Version,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            r,o=report_access(c,u,rid,require,True)
            closed_adjustment_only(r,o)
            if o['doctor_id']!=u['id']:raise HTTPException(403,'Không phải bác sĩ phụ trách duyệt')
            if r['status']!='pending_review' or r['version']!=data.version:raise HTTPException(409,'Phiếu chưa chờ duyệt hoặc phiên bản đã đổi')
            from .main import FILES
            from .ui_settings import read_settings,settings_path
            warnings=scope_warning(c,u,'lab',o['id'],now,block=read_settings(settings_path(FILES))['block_practitioner_scope'])
            payload=report_data(c,r,o);payload.update(status='approved',version=data.version+1,approved_at=now(),approved_by=u['id'],approver_name=printed_name(c,u['id']))
            # Snapshot includes patient demographics, definition, references, flags, names.
            payload.pop('snapshot',None)
            payload['adjusted_after_close']=o['visit_status']=='completed' and bool(r['replaces_id'])
            c.execute("UPDATE lab_reports SET status='approved',version=version+1,approved_at=?,approved_by=?,snapshot=? WHERE id=?",(payload['approved_at'],u['id'],dump(payload),rid))
            summary='\n'.join(x['name']+': '+x.get('display_value',x['value'])+' '+x['unit']+(' ['+x['flag']+']' if x['flag'] else '') for x in payload['items'])
            status_sql="" if o['visit_status']=='completed' else "status='approved',"
            c.execute("UPDATE orders SET "+status_sql+"result_text=?,result_by=?,approved_by=?,approved_at=? WHERE id=?",(summary,r['performed_by'],u['id'],payload['approved_at'],o['id']))
            if o['visit_status']!='completed':status_refresh(c,o['visit_id'])
            if payload['adjusted_after_close']:
                audit(c,u,'lab_adjusted_after_close','lab_report',rid,dump({'old_report_id':r['replaces_id'],'new_report_id':rid}))
            audit(c,u,'lab_approved','lab_report',rid,'Duyệt kết quả theo chỉ số');return {'version':data.version+1,'warnings':warnings}

    @app.post('/api/lab/reports/{rid}/adjust',status_code=201)
    def adjust(rid:int,data:Adjustment,u=Depends(principal)):
        require(u,'technician')
        with db(True) as c:
            r,o=report_access(c,u,rid,require,True)
            if r['status']!='approved' or r['version']!=data.version:raise HTTPException(409,'Cần phiếu đã duyệt đúng phiên bản')
            if c.execute('SELECT 1 FROM lab_reports WHERE replaces_id=?',(rid,)).fetchone():raise HTTPException(409,'Phiếu đã có bản điều chỉnh')
            c.execute('INSERT INTO lab_reports(order_id,replaces_id,adjustment_reason,sample_at,result_at,performed_by,comment,created_at) VALUES(?,?,?,?,?,?,?,?)',(o['id'],rid,data.reason,r['sample_at'],r['result_at'],u['id'],r['comment'],now()))
            new=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for item in c.execute('SELECT * FROM lab_results WHERE report_id=?',(rid,)).fetchall():c.execute('INSERT INTO lab_results(report_id,test_id,definition,value,note) VALUES(?,?,?,?,?)',(new,item['test_id'],item['definition'],item['value'],item['note']))
            audit(c,u,'lab_adjusted','lab_report',new,'Thay thế #'+str(rid)+': '+redact_reason(c,o,data.reason))
            return {'id':new}

    @app.get('/api/lab/visits/{vid}/results')
    def visit_results(vid:int,u=Depends(principal)):
        require(u,'doctor')
        with db() as c:
            visit_access(c,u,vid,clinical=True)
            reports=[]
            for r in c.execute("SELECT r.* FROM lab_reports r JOIN orders o ON o.id=r.order_id WHERE o.visit_id=? AND r.status='approved' AND NOT EXISTS(SELECT 1 FROM lab_reports n WHERE n.replaces_id=r.id AND n.status='approved') ORDER BY r.id",(vid,)).fetchall():
                reports.append(report_data(c,r,{}))
            waiting=c.execute("SELECT COUNT(*) FROM orders o WHERE o.visit_id=? AND o.category='lab' AND o.status IN ('ordered','pending_review')",(vid,)).fetchone()[0]
            return {'reports':reports,'waiting':waiting,'adjusted_after_close':vid in after_close_visits(c,[vid])}

    @app.get('/api/lab/visits/{vid}/history/{tid}')
    def history(vid:int,tid:int,u=Depends(principal)):
        require(u,'doctor')
        with db(True) as c:
            v=visit_access(c,u,vid,clinical=True)
            rows=c.execute("""SELECT r.snapshot FROM lab_reports r JOIN orders o ON o.id=r.order_id JOIN visits v ON v.id=o.visit_id
                JOIN lab_results x ON x.report_id=r.id WHERE v.patient_id=? AND v.doctor_id=? AND x.test_id=? AND r.status='approved'
                AND NOT EXISTS(SELECT 1 FROM lab_reports n WHERE n.replaces_id=r.id AND n.status='approved') ORDER BY r.sample_at,r.id""",(v['patient_id'],u['id'],tid)).fetchall()
            result=[]
            for row in rows:
                p=json.loads(row['snapshot'])
                for item in p['items']:
                    if item['test_id']==tid:result.append({'report_id':p['id'],'sample_at':p['sample_at'],'value':item['value'],'display_value':item.get('display_value',item['value']),'raw_value':item.get('raw_value',item['value']),'flag':item['flag'],'unit':item['unit'],'adjusted_after_close':p.get('adjusted_after_close',False)})
            audit(c,u,'lab_history_viewed','visit',vid,'Chỉ số #'+str(tid));return result

    @app.get('/api/lab/reports/{rid}/form')
    @export_slot
    def form(rid:int,group:Literal['hematology','biochemistry','urine','other'],fmt:Literal['docx','pdf']='pdf',u=Depends(principal)):
        from .m5_forms import render
        with db(True) as c:
            r,o=report_access(c,u,rid,require)
            if r['status']!='approved' and 'technician' not in u['roles']:raise HTTPException(403,'Chỉ in phiếu đã duyệt')
            payload=report_data(c,r,o)
            successor=c.execute("SELECT id FROM lab_reports WHERE replaces_id=? AND status='approved'",(rid,)).fetchone()
            if successor:payload['superseded_by']=successor['id']
            if not any(x['group_name']==group for x in payload['items']):raise HTTPException(404,'Nhóm không có chỉ định trên phiếu')
            audit(c,u,'lab_printed','lab_report',rid,'Nhóm '+GROUPS[group]+'; '+fmt)
        raw=render(payload,group,fmt)
        return Response(raw,media_type='application/pdf' if fmt=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'attachment; filename="Xet_nghiem_{rid}_{group}.{fmt}"','Cache-Control':'no-store'})

    from .m5_import import install_import
    install_import(app,db,principal,require,audit,now)
