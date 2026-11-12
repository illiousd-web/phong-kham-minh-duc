"""Owner-supplied public source files: never repair or manufacture a code."""
import csv,io,json,re,hashlib
from pathlib import Path
from .manager_visits import fold_name
ROOT=Path(__file__).resolve().parents[1]/'data/danh_muc_goc'
SOURCES={
 'icd10':('ICD10_TT06_2026.csv',15844,'05f4db19f5935c5c106185937c4bb956618c7d00408f29c64c0614640d3c73d4','TT 06/2026/TT-BYT',None,'2026'),
 'shared_lab_codes':('QD1227_MA_DUNG_CHUNG_CLS_DOT1.csv',2964,'c3db0f38ff1e9a7cf857a87d3636e6c39d0a047b98de27a353db94110d0fdbed','QĐ 1227/QĐ-BYT 2025',None,'Đợt 1'),
 'tech_catalog':('TT23_PL01_DANH_MUC_KY_THUAT.csv',19438,'d4854c88304456c615d28d6bd7f3a0b5ab4a56dc0f00533604c57aaaf9984b1f','TT 23/2024/TT-BYT',None,'PL01 đến 30/06/2026'),
 'tech_catalog_pl02':('TT23_PL02_DANH_MUC_KY_THUAT_TU_01072026.csv',9128,'38eab59894dbec1c904b1d7b54cad5e9f43afe75e854de7ea1497409e0fd666f','TT 23/2024/TT-BYT',None,'PL02 từ 01/07/2026'),
 'official_addresses':('DVHC_XA_CV1027_2025.csv',3321,'3a657a35fd6427d98774c8d74209cf3ec335e4225c4c8b35677358a1b1d8d06a','CV 1027/CTK-CSCL','2025-06-25','2025'),
}
HEADERS={
 'icd10':'stt chuong pham_vi_chuong ten_chuong_en ten_chuong_vi ma_khoi ten_khoi_en ten_khoi_vi ma_tieu_khoi_1 ten_tieu_khoi_1_en ten_tieu_khoi_1_vi ma_tieu_khoi_2 ten_tieu_khoi_2_en ten_tieu_khoi_2_vi ma_nhom_3_ky_tu ten_nhom_en ten_nhom_vi ma_benh ma_benh_khong_dau ten_benh_en huong_dan_ma_hoa_en ten_benh_vi huong_dan_ma_hoa_vi khong_dung_lam_benh_chinh khong_khuyen_khich_lam_benh_chinh khong_dung_vi_co_ma_chi_tiet_hon chi_dung_nguyen_nhan_tu_vong chi_o_nu chi_o_nam'.split(),
 'shared_lab_codes':'nhom stt_trong_phu_luc ma_dung_chung ten ma_kt_tt23 ten_kt_tt23 ma_loinc ten_loinc thanh_phan thuoc_tinh thoi_gian he_mau phuong_phap don_vi'.split(),
 'tech_catalog':'stt ma_ky_thuat ten_chuong ten_ky_thuat'.split(),
 'tech_catalog_pl02':'stt stt_trong_chuong ten_chuong ma_lien_ket_pl01 ten_ky_thuat'.split(),
 'official_addresses':'stt ma_xa ten_xa ten_tinh'.split(),
}
KEYS={'icd10':'ma_benh','shared_lab_codes':'ma_dung_chung','tech_catalog':'ma_ky_thuat','tech_catalog_pl02':'stt','official_addresses':'ma_xa'}
FLAGS=HEADERS['icd10'][-6:]
def province_name(name):
    return 'Thành phố Hồ Chí Minh' if fold_name(name) in ('tp ho chi minh','tp. ho chi minh','thanh pho ho chi minh') else name.strip()

def parse_source(raw,kind):
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
        fields=[x.strip() for x in (reader.fieldnames or [])]
        missing=[x for x in HEADERS[kind] if x not in fields]
        if missing:raise ValueError('Thiếu cột: '+', '.join(missing))
        if len(fields)!=len(set(fields)):raise ValueError('Trùng tên cột')
        reader.fieldnames=fields;rows=[];errors=[];seen=set();canonical=set()
        for row in reader:
            line=reader.line_num
            if line>100000:raise ValueError('Tối đa 100.000 dòng')
            if not any(row.values()):continue
            try:
                if None in row or any(v is None for v in row.values()):raise ValueError('Sai số cột')
                if any(len(v)>12000 for v in row.values()):raise ValueError('Ô vượt 12.000 ký tự')
                key=row[KEYS[kind]]
                if not key or key in seen:raise ValueError('Mã/STT trống hoặc trùng')
                seen.add(key)
                if kind=='icd10':
                    if any(row[f] not in ('','1') for f in FLAGS):raise ValueError('Cờ chỉ nhận 1 hoặc rỗng')
                    if not row['ma_benh_khong_dau'] or row['ma_benh_khong_dau'] in canonical:raise ValueError('Khóa liên thông trống hoặc trùng')
                    canonical.add(row['ma_benh_khong_dau'])
                    if row['chi_o_nu'] and row['chi_o_nam']:raise ValueError('Đồng thời chỉ ở nam và nữ')
                    value={'code':key,'name_vi':row['ten_benh_vi'],'name_en':row['ten_benh_en'],'chapter':row['chuong'],'not_primary':int(bool(row[FLAGS[0]])),'discouraged_primary':int(bool(row[FLAGS[1]])),'replaced':int(bool(row[FLAGS[2]])),'death_only':int(bool(row[FLAGS[3]])),'sex':'Nữ' if row['chi_o_nu'] else 'Nam' if row['chi_o_nam'] else '',**row}
                elif kind=='shared_lab_codes':
                    if not re.fullmatch('[0-9]{7}',key):raise ValueError('Mã dùng chung cần 7 chữ số')
                    value={'code':key,'name':row['ten'],'tech_code':row['ma_kt_tt23'],'loinc':row['ma_loinc'],'component':row['thanh_phan'],'property':row['thuoc_tinh'],'timing':row['thoi_gian'],'specimen':row['he_mau'],'method':row['phuong_phap'],'unit':row['don_vi'],**row}
                elif kind in ('tech_catalog','tech_catalog_pl02'):
                    value={'code':key,'name':row['ten_ky_thuat'],'chapter':row['ten_chuong'],**row}
                else:
                    if not re.fullmatch('[0-9]{5}',key):raise ValueError('Mã xã cần 5 chữ số, giữ số 0 đầu')
                    value={'code':key,'name':row['ten_xa'],'province_name':province_name(row['ten_tinh']),'province_code':'','kind':'commune',**row}
                rows.append(value)
            except ValueError as exc:errors.append({'row':line,'message':str(exc)})
        if not rows and not errors:errors=[{'row':2,'message':'Không có dữ liệu'}]
        return rows,errors
    except (UnicodeError,csv.Error) as exc:raise ValueError('CSV UTF-8 không hợp lệ') from exc

def rebuild_links(c):
    c.execute('DELETE FROM tech_pl02_links WHERE pl02_id IN (SELECT id FROM tech_catalog_pl02 WHERE active=1)')
    known={r[0] for r in c.execute('SELECT ma_ky_thuat FROM tech_catalog_pl01 WHERE active=1')}
    values=[]
    for r in c.execute('SELECT id,stt,ma_lien_ket_pl01 FROM tech_catalog_pl02 WHERE active=1'):
        for pos,token in enumerate(re.split(r'[;,\s]+',r['ma_lien_ket_pl01']),1):
            if token:values.append((r['id'],r['stt'],pos,token,token if token in known else None,int(token not in known)))
    c.executemany('INSERT INTO tech_pl02_links(pl02_id,pl02_stt,position,raw_token,pl01_code,needs_review) VALUES(?,?,?,?,?,?)',values)
    return sum(v[-1] for v in values)

def apply_rows(c,kind,rows,meta,raw,actor,now,mapping=None):
    from .d0 import dump,match_geography
    mark=hashlib.sha256(raw).hexdigest()
    c.execute('INSERT INTO catalog_imports(kind,document_number,document_date,source,version,fingerprint,mapping,imported_by,created_at,row_count) VALUES(?,?,?,?,?,?,?,?,?,?)',(kind,meta['document_number'],meta.get('document_date'),meta['source'],meta['version'],mark,dump(mapping or {}),actor,now,len(rows)))
    iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute(f'UPDATE {kind} SET active=0')
    if kind=='tech_catalog':c.execute('UPDATE tech_catalog_pl01 SET active=0')
    def upsert(table,values):
        cols=list(values)
        sql=f'INSERT INTO {table}('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')'
        if table!='tech_catalog_pl02':sql+=' ON CONFLICT(code) DO UPDATE SET '+','.join(x+'=excluded.'+x for x in cols if x!='code')
        c.execute(sql,tuple(values[x] for x in cols))
    for row in rows:
        search=fold_name(' '.join(str(row.get(k,'') or '') for k in ('code','name','name_vi','name_en','ma_benh_khong_dau','loinc','ten_loinc')))
        v={**row,'search_key':search,'active':1,'version':meta['version'],'import_id':iid}
        upsert(kind,v)
        if kind=='tech_catalog':upsert('tech_catalog_pl01',v)
    review=rebuild_links(c) if kind in ('tech_catalog','tech_catalog_pl02') else 0
    unmatched=match_geography(c) if kind=='official_addresses' else []
    return {'imported':len(rows),'import_id':iid,'sha256':mark,'needs_review':review,'unmatched':unmatched}

def seed_sources(c,now):
    for kind,(filename,count,sha,document,day,version) in SOURCES.items():
        raw=(ROOT/filename).read_bytes()
        if not raw.startswith(b'\xef\xbb\xbf') or hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Sai BOM/SHA-256 file gốc: '+filename)
        rows,errors=parse_source(raw,kind)
        if errors or len(rows)!=count:raise ValueError('Sai dữ liệu/số dòng file gốc: '+filename)
        result=apply_rows(c,kind,rows,{'document_number':document,'document_date':day,'source':filename+' — tệp công khai do chủ dự án cung cấp','version':version},raw,None,now)
        c.execute("INSERT INTO audit_log(event,object_type,object_id,details,created_at) VALUES('standard_catalog_seeded','catalog',?,?,?)",(result['import_id'],json.dumps({'file':filename,'rows':count,'sha256':sha},ensure_ascii=False),now))
