"""Source-file-only standard catalogs. Preview proof binds bytes, mapping and metadata."""
import hashlib,json,re,io,zipfile
from datetime import date
from fastapi import Depends,File,Form,HTTPException,Query,UploadFile
from pydantic import BaseModel,ConfigDict,Field,StrictBool,field_validator
from .manager_visits import fold_name
from .patient_catalog import read_rows,text

COLUMNS={
 'icd10':['code','name_vi','name_en','chapter','not_primary','discouraged_primary','replaced','replacement_codes','death_only','sex'],
 'tech_catalog':['code','name','chapter'],
 'shared_lab_codes':['code','name','tech_code','loinc','component','property','timing','specimen','method','unit'],
 'official_addresses':['code','name','province_name','province_code','kind'],
 'occupation_catalog':['code','name'],
}
LABELS={'code':'Mã','name_vi':'Tên tiếng Việt','name_en':'Tên tiếng Anh','chapter':'Chương/nhóm','not_primary':'Không dùng bệnh chính','discouraged_primary':'Không khuyến khích bệnh chính','replaced':'Đã có mã chi tiết hơn','replacement_codes':'Mã thay thế','death_only':'Chỉ nguyên nhân tử vong','sex':'Giới tính','name':'Tên','tech_code':'Mã kỹ thuật','loinc':'LOINC','component':'Thành phần','property':'Tính chất','timing':'Thời gian','specimen':'Bệnh phẩm','method':'Phương pháp','unit':'Đơn vị','province_name':'Tên tỉnh','province_code':'Mã tỉnh chính thức','kind':'Cấp (province/commune)'}
FLAGS=('not_primary','discouraged_primary','replaced','death_only')

def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
class Metadata(BaseModel):
    model_config=ConfigDict(extra='forbid')
    @field_validator('document_number','source','version',mode='before')
    @classmethod
    def trim(cls,v):return v.strip() if isinstance(v,str) else v
    document_number:str=Field(min_length=1,max_length=180)
    document_date:date
    source:str=Field(min_length=1,max_length=500)
    version:str=Field(min_length=1,max_length=100)

def parse(raw,filename,kind,mapping,header_row):
    if kind not in COLUMNS:raise ValueError('Danh mục không hợp lệ')
    sheet=mapping.get('__sheet','')
    if not isinstance(sheet,str):raise ValueError('Tên sheet phải là chữ')
    rows=read_source_rows(raw,filename,header_row,sheet)
    if filename.lower().endswith('.csv'):rows=rows[header_row-1:]
    if not rows:raise ValueError('Không có dòng tiêu đề')
    labels=[text(x) for x in rows[0][1]];cols={}
    unknown=set(mapping)-set(COLUMNS[kind])-{'__sheet'}
    if unknown:raise ValueError('Trường ánh xạ không hợp lệ: '+', '.join(sorted(unknown)))
    def column(field):
        spec=mapping.get(field,LABELS[field])
        if isinstance(spec,str):return spec
        if not isinstance(spec,dict) or set(spec)-{'column','values'} or not isinstance(spec.get('column'),str) or not isinstance(spec.get('values',{}),dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in spec.get('values',{}).items()):raise ValueError('Ánh xạ cột/giá trị không hợp lệ: '+field)
        if spec.get('values') and field not in (*FLAGS,'sex','kind'):raise ValueError('Chỉ ánh xạ giá trị cờ, giới tính hoặc cấp hành chính; không đổi mã/tên trong file gốc')
        return spec['column']
    missing=[column(f) for f in COLUMNS[kind] if labels.count(column(f))!=1]
    if missing:raise ValueError('Thiếu hoặc trùng cột: '+', '.join(missing))
    for field in COLUMNS[kind]:
        label=column(field)
        if labels.count(label)!=1:raise ValueError('Thiếu hoặc trùng cột: '+label)
        cols[field]=labels.index(label)
    result=[];errors=[];seen=set()
    for line,row in rows[1:]:
        if not any(text(v) for v in row):continue
        value={key:text(row[i]) if i<len(row) else '' for key,i in cols.items()}
        for field in value:
            spec=mapping.get(field)
            if isinstance(spec,dict):value[field]=spec.get('values',{}).get(value[field],value[field])
        try:
            if not value['code'] or not value.get('name_vi',value.get('name')):raise ValueError('Thiếu mã hoặc tên')
            if any(len(x)>1000 for x in value.values()) or len(value['code'])>80:raise ValueError('Giá trị quá dài')
            if value['code'] in seen:raise ValueError('Trùng mã trong tệp')
            seen.add(value['code'])
            if kind=='icd10':
                for flag in FLAGS:
                    if value[flag] not in ('','0','1'):raise ValueError(LABELS[flag]+': dùng 0 hoặc 1; cần ánh xạ đúng file gốc')
                    value[flag]=int(value[flag] or 0)
                if value['sex'] not in ('','Nam','Nữ'):raise ValueError('Giới tính: để trống, Nam hoặc Nữ')
            if kind=='shared_lab_codes' and not re.fullmatch(r'[0-9]{7}',value['code']):raise ValueError('Mã dùng chung cần đúng 7 chữ số; ô Excel phải dạng chữ')
            if kind=='official_addresses':
                if value['kind'] not in ('province','commune') or not value['province_name'] or not value['province_code']:raise ValueError('Thiếu tỉnh hoặc cấp province/commune')
            result.append(value)
        except ValueError as exc:errors.append({'row':line,'message':str(exc)})
    if not result and not errors:errors.append({'row':header_row+1,'message':'Không có dữ liệu'})
    return result,errors

def fingerprint(raw,kind,meta,mapping,header_row):
    return hashlib.sha256(dump([kind,meta,mapping,header_row]).encode()+b'\0'+raw).hexdigest()

def required(c):
    row=c.execute("SELECT value FROM prescription_settings WHERE key='require_primary_icd10'").fetchone()
    return not row or row[0]!='false'

def validate_codes(c,patient_id,primary,codes):
    warnings=[];sex=c.execute('SELECT sex FROM patients WHERE id=?',(patient_id,)).fetchone()[0]
    for code in codes:
        r=c.execute('SELECT * FROM icd10 WHERE code=?',(code,)).fetchone()
        if not r or not r['active']:raise HTTPException(422,'Mã ICD-10 không có hoặc đã ngừng dùng: '+code)
        if r['death_only']:raise HTTPException(422,'Mã chỉ dùng cho nguyên nhân tử vong: '+code)
        if r['sex'] and r['sex']!=sex:raise HTTPException(422,'Mã không phù hợp giới tính: '+code)
        if r['replaced']:raise HTTPException(422,'Mã đã có mã chi tiết hơn: '+code+'; chọn mã thay thế: '+r['replacement_codes'])
        if code==primary and r['not_primary']:raise HTTPException(422,'Mã không dùng làm bệnh chính: '+code)
        if code==primary and r['discouraged_primary']:warnings.append('Không khuyến khích làm bệnh chính: '+code)
    return warnings

def diagnosis_guard(c,visit):
    v=dict(visit);items=json.loads(v.get('diagnosis_codes') or '[]');primary=v.get('primary_icd10')
    if required(c) and not primary:raise HTTPException(422,'Cần chọn mã bệnh chính ICD-10; hồ sơ chữ cũ chưa mã hóa')
    codes=[x['code'] for x in items]
    if primary and primary not in codes:raise HTTPException(422,'Mã bệnh chính chưa có trong chẩn đoán')
    return validate_codes(c,v['patient_id'],primary,codes)

def diagnosis_text(visit):
    v=dict(visit);items=json.loads(v.get('diagnosis_codes') or '[]')
    label='; '.join(x['code']+' – '+x['name'] for x in items)
    return (label+'\n' if label else 'Chưa mã hóa\n')+(v.get('diagnosis') or '')

class CodesInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=0)
    primary:str|None=None
    secondary:list[str]=Field(default_factory=list,max_length=30)
class Links(BaseModel):
    model_config=ConfigDict(extra='forbid')
    codes:list[str]=Field(max_length=50)
    package:StrictBool=False
class CodeLink(BaseModel):
    code:str|None=None
class Settings(BaseModel):
    require_primary_icd10:StrictBool
class GeoLink(BaseModel):
    tms_code:str
    official_code:str


def install_d0(app,db,principal,require,audit,visit_access,now):
    @app.get('/api/standards/config')
    def config(u=Depends(principal)):
        require(u,'admin','doctor','reception')
        with db() as c:return {'columns':{k:{f:LABELS[f] for f in fs} for k,fs in COLUMNS.items()},'require_primary_icd10':required(c)}

    @app.put('/api/standards/settings')
    def settings(data:Settings,u=Depends(principal)):
        require(u,'admin')
        with db(True) as c:
            old=required(c);c.execute("INSERT INTO prescription_settings(key,value) VALUES('require_primary_icd10',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('true' if data.require_primary_icd10 else 'false',))
            audit(c,u,'icd10_requirement_changed','catalog',None,dump({'old':old,'new':data.require_primary_icd10}))
        return {'ok':True}

    @app.get('/api/standards/imports')
    def imports(u=Depends(principal)):
        require(u,'admin')
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM catalog_imports ORDER BY id DESC LIMIT 100')]

    @app.post('/api/standards/{kind}/import')
    def import_file(kind:str,file:UploadFile=File(...),metadata:str=Form(...),mapping:str=Form('{}'),header_row:int=Form(1),preview:bool=Form(True),proof:str=Form(''),u=Depends(principal)):
        require(u,'admin')
        raw=file.file.read(5*1024*1024+1)
        if len(raw)>5*1024*1024:raise HTTPException(413,'Tệp tối đa 5 MB')
        try:
            meta=Metadata.model_validate_json(metadata).model_dump(mode='json');mp=json.loads(mapping)
            if not isinstance(mp,dict) or not all(isinstance(k,str) and isinstance(v,(str,dict)) for k,v in mp.items()) or not 1<=header_row<=100:raise ValueError('Ánh xạ hoặc dòng tiêu đề không hợp lệ')
        except (ValueError,TypeError):
            raise HTTPException(422,'Metadata/ánh xạ hoặc tệp không hợp lệ; cần đủ số văn bản, ngày ISO, nguồn, phiên bản và các cột: '+', '.join(LABELS[f] for f in COLUMNS.get(kind,[]))) from None
        try:rows,errors=parse(raw,file.filename or '',kind,mp,header_row)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        mark=fingerprint(raw,kind,meta,mp,header_row)
        if errors:raise HTTPException(422,{'errors':errors})
        with db(True) as c:
            if preview:
                audit(c,u,'standard_catalog_previewed','catalog',None,mark)
                return {'fingerprint':mark,'total':len(rows),'rows':rows[:30],'errors':[]}
            if proof!=mark or not c.execute("SELECT 1 FROM audit_log WHERE user_id=? AND event='standard_catalog_previewed' AND details=?",(u['id'],mark)).fetchone():raise HTTPException(422,'Cần xem trước đúng tệp, loại nạp, metadata và ánh xạ trước khi ghi')
            c.execute('INSERT INTO catalog_imports(kind,document_number,document_date,source,version,fingerprint,mapping,imported_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(kind,meta['document_number'],meta['document_date'],meta['source'],meta['version'],mark,dump({'columns':mp,'header_row':header_row}),u['id'],now()))
            iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute(f'UPDATE {kind} SET active=0')
            for row in rows:
                values={**row,'search_key':fold_name(row['code']+' '+row.get('name_vi',row.get('name',''))),'active':1,'version':meta['version'],'import_id':iid}
                columns=list(values);updates=','.join(k+'=excluded.'+k for k in columns if k!='code')
                c.execute(f'INSERT INTO {kind}('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(code) DO UPDATE SET '+updates,tuple(values.values()))
            unmatched=match_geography(c) if kind=='official_addresses' else []
            audit(c,u,'standard_catalog_imported','catalog',iid,dump({'kind':kind,'version':meta['version'],'rows':len(rows),'fingerprint':mark,'unmatched':len(unmatched)}))
        return {'imported':len(rows),'unmatched':unmatched}

    @app.get('/api/standards/{kind}')
    def search(kind:str,q:str='',limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0),u=Depends(principal)):
        require(u,'admin','doctor','reception','technician')
        if kind not in COLUMNS:raise HTTPException(404,'Danh mục không có')
        with db() as c:return search_catalog(c,kind,q,limit,offset)

    @app.put('/api/visits/{vid}/diagnosis-codes')
    def diagnoses(vid:int,data:CodesInput,u=Depends(principal)):
        require(u,'doctor')
        from .domain import ensure_open,revision
        with db(True) as c:
            v=visit_access(c,u,vid,clinical=True);ensure_open(v)
            codes=([data.primary] if data.primary else [])+data.secondary
            if len(set(codes))!=len(codes):raise HTTPException(422,'Trùng mã bệnh chính/kèm')
            warnings=validate_codes(c,v['patient_id'],data.primary,codes)
            snapshot=[]
            for code in codes:
                row=c.execute('SELECT name_vi,version,import_id FROM icd10 WHERE code=?',(code,)).fetchone()
                snapshot.append({'code':code,'name':row['name_vi'],'version':row['version'],'import_id':row['import_id'],'primary':code==data.primary})
            changed=c.execute('UPDATE visits SET primary_icd10=?,diagnosis_codes=?,version=version+1 WHERE id=? AND version=?',(data.primary,dump(snapshot),vid,data.version))
            if changed.rowcount!=1:raise HTTPException(409,'Hồ sơ đã đổi; tải lại')
            revision(c,vid,u,now,'clinical','Lưu mã chẩn đoán');audit(c,u,'diagnosis_codes_updated','visit',vid,dump({'codes':codes}))
        return {'version':data.version+1,'warnings':warnings}

    @app.get('/api/standards/unlinked/services')
    def unlinked_services(u=Depends(principal)):
        require(u,'admin')
        with db() as c:return [dict(r) for r in c.execute('SELECT id,name FROM service_catalog s WHERE NOT EXISTS(SELECT 1 FROM service_tech_codes l WHERE l.service_id=s.id) ORDER BY id')]

    @app.put('/api/standards/services/{sid}')
    def link_service(sid:int,data:Links,u=Depends(principal)):
        require(u,'admin')
        if len(set(data.codes))>1 and not data.package:raise HTTPException(422,'Dịch vụ lẻ chỉ gắn một mã; xác nhận dịch vụ gói để gắn nhiều mã')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM service_catalog WHERE id=?',(sid,)).fetchone():raise HTTPException(404,'Không có dịch vụ')
            for code in data.codes:
                if not c.execute('SELECT 1 FROM tech_catalog WHERE code=? AND active=1',(code,)).fetchone():raise HTTPException(422,'Mã kỹ thuật không hợp lệ')
            old=[r[0] for r in c.execute('SELECT tech_code FROM service_tech_codes WHERE service_id=?',(sid,))]
            c.execute('DELETE FROM service_tech_codes WHERE service_id=?',(sid,))
            for code in sorted(set(data.codes)):c.execute('INSERT INTO service_tech_codes(service_id,tech_code) VALUES(?,?)',(sid,code))
            audit(c,u,'service_standard_linked','catalog',sid,dump({'old':old,'new':data.codes,'package':data.package}))
        return {'ok':True}

    @app.get('/api/standards/unlinked/lab-tests')
    def unlinked_tests(u=Depends(principal)):
        require(u,'admin')
        with db() as c:return [dict(r) for r in c.execute('SELECT id,name FROM lab_tests WHERE shared_code IS NULL ORDER BY id')]

    @app.put('/api/standards/lab-tests/{tid}')
    def link_test(tid:int,data:CodeLink,u=Depends(principal)):
        require(u,'admin')
        with db(True) as c:
            if data.code and not c.execute('SELECT 1 FROM shared_lab_codes WHERE code=? AND active=1',(data.code,)).fetchone():raise HTTPException(422,'Mã dùng chung không hợp lệ')
            old=c.execute('SELECT shared_code FROM lab_tests WHERE id=?',(tid,)).fetchone()
            if not old:raise HTTPException(404,'Không có chỉ số')
            c.execute('UPDATE lab_tests SET shared_code=? WHERE id=?',(data.code,tid));audit(c,u,'lab_standard_linked','catalog',tid,dump({'old':old[0],'new':data.code}))
        return {'ok':True}

    @app.get('/api/standards/geography/unmatched')
    def unmatched(u=Depends(principal)):
        require(u,'admin')
        with db() as c:return match_geography(c,False)

    @app.put('/api/standards/geography/link')
    def link_geo(data:GeoLink,u=Depends(principal)):
        require(u,'admin')
        with db(True) as c:
            target=c.execute("SELECT * FROM official_addresses WHERE code=? AND kind='commune' AND active=1",(data.official_code,)).fetchone()
            source=c.execute("SELECT * FROM patient_catalog WHERE kind='commune' AND code=?",(data.tms_code,)).fetchone()
            if not target or not source:raise HTTPException(422,'Không có mã xã chính thức/TMS')
            c.execute("UPDATE patient_catalog SET official_code=? WHERE kind='commune' AND code=?",(data.official_code,data.tms_code))
            audit(c,u,'official_address_linked','catalog',None,dump(data.model_dump()))
        return {'ok':True}


def match_geography(c,write=True):
    if write:
        c.execute("""UPDATE patient_catalog SET official_code=NULL WHERE kind IN ('province','commune') AND official_code IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM official_addresses a WHERE a.code=patient_catalog.official_code AND a.kind=patient_catalog.kind AND a.active=1)""")
    provinces={r['code']:r['name'] for r in c.execute("SELECT code,name FROM patient_catalog WHERE kind='province'")}
    official={};active_codes=set()
    for r in c.execute("SELECT * FROM official_addresses WHERE active=1"):
        active_codes.add(r['code'])
        key=(fold_name(r['province_name']),fold_name(r['name']),r['kind']);official.setdefault(key,[]).append(r)
    unmatched=[]
    for r in c.execute("SELECT * FROM patient_catalog WHERE kind IN ('province','commune') AND active=1"):
        pn=r['name'] if r['kind']=='province' else provinces.get(r['parent_code'],'')
        candidates=official.get((fold_name(pn),fold_name(r['name']),r['kind']),[])
        if len(candidates)==1:
            if write:c.execute('UPDATE patient_catalog SET official_code=? WHERE kind=? AND code=?',(candidates[0]['code'],r['kind'],r['code']))
        elif not r['official_code'] or r['official_code'] not in active_codes:unmatched.append({'kind':r['kind'],'tms_code':r['code'],'name':r['name'],'province':pn,'reason':'Không ghép duy nhất theo tên tỉnh + tên xã'})
    return unmatched


def resolve_patient_standards(c,data,old=None):
    old=dict(old or {})
    geo_changed=any(getattr(data,k+'_code',None)!=old.get(k+'_code') for k in ('province','commune'))
    for kind in ('province','commune'):
        if old and not geo_changed:
            setattr(data,'official_'+kind+'_code',old.get('official_'+kind+'_code'));continue
        row=c.execute('SELECT official_code FROM patient_catalog WHERE kind=? AND code=?',(kind,getattr(data,kind+'_code',None))).fetchone()
        setattr(data,'official_'+kind+'_code',row[0] if row else None)
    if getattr(data,'occupation_code',None):
        if data.occupation_code==old.get('occupation_code') and data.occupation==old.get('occupation'):return
        row=c.execute('SELECT name FROM occupation_catalog WHERE code=? AND active=1',(data.occupation_code,)).fetchone()
        if not row:raise HTTPException(422,'Mã nghề nghiệp không có hoặc đã ngừng dùng')
        data.occupation=row[0]


def search_catalog(c,kind,q,limit=30,offset=0):
    if kind not in COLUMNS:raise HTTPException(404,'Danh mục không có')
    needle=fold_name(q[:100]).replace('!','!!').replace('%','!%').replace('_','!_')
    where="active=1 AND search_key LIKE ? ESCAPE '!'";args=('%'+needle+'%',)
    total=c.execute(f'SELECT COUNT(*) FROM {kind} WHERE '+where,args).fetchone()[0]
    return {'total':total,'items':[dict(r) for r in c.execute(f'SELECT * FROM {kind} WHERE '+where+' ORDER BY code LIMIT ? OFFSET ?',(*args,limit,offset))]}


def read_source_rows(raw,filename,header_row,sheet):
    if not sheet:return read_rows(raw,filename,header_row)
    if not filename.lower().endswith('.xlsx'):raise ValueError('Chọn sheet chỉ áp dụng cho Excel .xlsx')
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>1000 or sum(x.file_size for x in z.infolist())>20*1024*1024:raise ValueError('Excel vượt giới hạn giải nén 20 MB')
        book=load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
        try:
            if sheet not in book.sheetnames:raise ValueError('Không có sheet đã chọn: '+sheet)
            ws=book[sheet];ws.reset_dimensions();result=[]
            for line,cells in enumerate(ws.iter_rows(max_col=200),1):
                if line>20003:raise ValueError('Dòng 20004: tối đa 20.000 dòng dữ liệu')
                if line<header_row:continue
                if any(c.data_type in ('f','e') for c in cells):raise ValueError('Dòng '+str(line)+': không dùng công thức hoặc ô lỗi')
                result.append((line,[c.value for c in cells]))
            return result
        finally:book.close()
    except ValueError:raise
    except Exception:raise ValueError('Không đọc được Excel; kiểm tra tệp gốc và sheet') from None
