"""Two-sheet workbook, complete validation before atomic upsert; no price columns."""
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from fastapi import Depends,File,UploadFile,Form,HTTPException,Response
from pydantic import ValidationError
from .m5 import TestInput,Reference,catalog,save_test

TEST_HEADERS={'Mã chỉ số':'code','Tên chỉ số':'name','Viết tắt':'abbreviation','Nhóm':'group_name','Kiểu kết quả':'result_type','Đơn vị':'unit','Số thập phân':'decimals','Thứ tự in':'print_order','Đang dùng':'active','Lựa chọn (mỗi dòng một giá trị)':'choices'}
REF_HEADERS={'Mã chỉ số':'code','Giới':'sex','Tuổi từ (tháng)':'age_from','Tuổi đến (tháng)':'age_to','Cận dưới':'lower_value','Cận trên':'upper_value','Giá trị bình thường':'normal_value'}
GROUP_MAP={'Huyết học':'hematology','Sinh hóa':'biochemistry','Nước tiểu':'urine','Khác':'other'}
TYPE_MAP={'Số':'number','Định tính':'choice','Chữ':'text'}


def workbook(items=()):
    w=Workbook();w.remove(w.active)
    a=w.create_sheet('ChiSo');a.append(list(TEST_HEADERS));b=w.create_sheet('ThamChieu');b.append(list(REF_HEADERS))
    def add(sheet,values):
        sheet.append(values)
        # Excel formulas must never be emitted from imported/user-entered strings.
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value,str):cell.data_type='s'
    for x in items:
        vals={**x,'group_name':next(k for k,v in GROUP_MAP.items() if v==x['group_name']),'result_type':next(k for k,v in TYPE_MAP.items() if v==x['result_type']),'choices':'\n'.join(x['choices']),'active':int(x['active'])}
        add(a,[vals[k] for k in TEST_HEADERS.values()])
        for r in x['references']:add(b,[x['code']]+[r[k] for k in list(REF_HEADERS.values())[1:]])
    for s in w:
        s.freeze_panes='A2'
        for c in s[1]:s.column_dimensions[c.column_letter].width=25
    out=BytesIO();w.save(out);return out.getvalue()


def parse(raw):
    if len(raw)>2*1024*1024:raise HTTPException(413,'Tệp tối đa 2 MB')
    w=None
    try:
        with ZipFile(BytesIO(raw)) as z:
            if sum(x.file_size for x in z.infolist())>20*1024*1024:raise ValueError('Excel quá lớn sau giải nén')
        w=load_workbook(BytesIO(raw),read_only=True,data_only=False,keep_links=False)
        rows={};errors=[];locations={}
        def read(sheet,headers):
            if sheet not in w.sheetnames:raise ValueError('Thiếu sheet '+sheet)
            s=w[sheet]
            if (s.max_row or 0)>10001 or (s.max_column or 0)>32:raise ValueError('Tối đa 10.000 dòng, 32 cột mỗi sheet')
            it=s.iter_rows();head=[str(c.value or '').strip() for c in next(it,[])]
            missing=[h for h in headers if h not in head]
            if missing:raise ValueError(sheet+': thiếu cột '+', '.join(missing))
            if len(set(head))!=len(head):raise ValueError(sheet+': trùng cột')
            for n,cells in enumerate(it,2):
                if not any(c.value is not None and str(c.value).strip() for c in cells):continue
                if any(c.data_type in ('f','e') for c in cells):errors.append({'sheet':sheet,'row':n,'message':'Không nhận công thức/ô lỗi'});continue
                d={headers[h]:cells[i].value if i<len(cells) else None for i,h in enumerate(head) if h in headers}
                yield n,d
        for n,d in read('ChiSo',TEST_HEADERS):
            try:
                for key in ('code','name','abbreviation','unit'):d[key]=str(d[key] or '').strip()
                if d['code'] in rows:raise ValueError('Trùng mã chỉ số')
                d['group_name']=GROUP_MAP.get(d['group_name'],d['group_name']);d['result_type']=TYPE_MAP.get(d['result_type'],d['result_type'])
                if d['active'] not in (0,1,'0','1'):raise ValueError('Đang dùng phải là 0 hoặc 1')
                d['choices']=str(d['choices'] or '').splitlines();d['references']=[]
                validated=TestInput(**d)
                rows[d['code']]=validated.model_dump();locations[d['code']]=n
            except ValueError as e:errors.append({'sheet':'ChiSo','row':n,'message':'; '.join(x['msg'] for x in e.errors()) if isinstance(e,ValidationError) else str(e)})
        for n,d in read('ThamChieu',REF_HEADERS):
            try:
                code=str(d.pop('code') or '').strip()
                if code not in rows:raise ValueError('Mã chỉ số không có ở sheet ChiSo')
                for k in ('lower_value','upper_value'):d[k]=None if d[k] is None else str(d[k])
                d['normal_value']=str(d['normal_value'] or '')
                ref=Reference(**d)
                # Validate compatibility/overlap here so the error names the actual reference row.
                candidate=TestInput(**{**rows[code],'references':rows[code]['references']+[ref.model_dump()]})
                rows[code]=candidate.model_dump()
            except (ValueError,ValidationError) as e:errors.append({'sheet':'ThamChieu','row':n,'message':str(e) if not isinstance(e,ValidationError) else '; '.join(x['msg'] for x in e.errors())})
        out=[]
        for code,d in rows.items():
            try:out.append({'row':locations[code],'test':TestInput(**d).model_dump()})
            except ValidationError as e:errors.append({'sheet':'ChiSo','row':locations[code],'message':'; '.join(x['msg'] for x in e.errors())})
        if errors:raise HTTPException(422,{'message':'Tệp có lỗi; chưa nạp dữ liệu','errors':errors})
        if not out:raise ValueError('Tệp chưa có chỉ số')
        return out
    except HTTPException:raise
    except ValueError as e:raise HTTPException(422,str(e)) from None
    except Exception:raise HTTPException(422,'Excel không hợp lệ; dùng mẫu ChiSo / ThamChieu') from None
    finally:
        if w:w.close()


def install_import(app,db,principal,require,audit,now):
    @app.get('/api/lab/catalog-file')
    def export(template:bool=False,u=Depends(principal)):
        require(u,'admin')
        with db() as c:items=[] if template else catalog(c)
        return Response(workbook(items),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="DANH_MUC_CHI_SO.xlsx"','Cache-Control':'no-store'})

    @app.post('/api/lab/catalog-import')
    def import_file(file:UploadFile=File(...),preview:bool=Form(True),u=Depends(principal)):
        require(u,'admin');rows=parse(file.file.read(2*1024*1024+1))
        if preview:return {'count':len(rows),'rows':rows}
        with db(True) as c:
            for row in rows:
                data=TestInput(**row['test']);old=c.execute('SELECT id FROM lab_tests WHERE code=?',(data.code,)).fetchone()
                save_test(c,data,old['id'] if old else None)
            audit(c,u,'lab_catalog_updated','lab_test',None,'Nhập Excel: '+str(len(rows))+' chỉ số; cập nhật theo mã')
        return {'count':len(rows)}
