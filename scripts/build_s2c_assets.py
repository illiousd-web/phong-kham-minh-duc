"""Rebuild empty S2c Word frames and the opt-in M5 workbook from PDF pages 29–31.

Run from the repository root. Numerical spelling and textual references are retained;
only mmo/L -> mmol/L and 109/l -> 10⁹/l are corrected. No patient/signature data.
"""
from pathlib import Path
from docx import Document
from docx.shared import Pt
from app.forms import TEMPLATE_DIR
from app.s2c_forms import TEMPLATES, LOGO
from app.m5_import import workbook, parse

# Each line follows the source PDF's column order (left column first).
BIO = '''GLU|Glucose|3.9 – 6.4|mmol/L
HBA1C|HbA1C|< 6.5|%
INSULIN|Insulin|5 – 20|U/mL
CPEPTIDE|C.peptide|0.37 – 1.47|mmol/L
URE|Định lượng Ure|2.5 – 7.5|mmol/L
CRE|Định lượng Creatinin|Nữ 53 – 110 · Nam 62 – 120|µmol/L
UA|Định lượng Acid Uric|Nữ 150 – 360 · Nam 180 – 420|µmol/L
CHOL|Định lượng Cholesterol|3.6 – 5.2|mmol/L
TG|Triglycerid|0.46 – 1.88|mmol/L
HDL|HDL-Cholesterol|0.9 – 1.8|mmol/L
LDL|LDL-Cholesterol|< 3|mmol/L
AST|AST (GOT)|≤ 37|U/L (37 °C)
ALT|ALT (GPT)|≤ 40|U/L (37 °C)
GGT|GGT|≤ 50|U/L (37 °C)
BIL-T|Bilirubin toàn phần|3 – 17|µmol/L
BIL-D|Bilirubin trực tiếp|0.1 – 4.2|µmol/L
BIL-I|Bilirubin gián tiếp|3 – 14|µmol/L
TP|Protein|46 – 82|g/L
ALB|Albumin|38 – 51|g/L
GLOBULIN|Globulin|22 – 32|g/L
AMYLASE|Amylase|20 – 220|U/L
FIBRINOGEN|Fibrinogen|2 – 4|g/L
CK-MB|CK-MB|≤ 24|U/L
CK|CK toàn phần|25 – 220|U/L
NA|Na⁺|135 – 150|mmol/L
K|K⁺|3.5 – 5.0|mmol/L
CL|Cl⁻|96 – 110|mmol/L
CA-ION|Canxi ion|1.17 – 1.29|mmol/L
CA|Canxi toàn phần|2.2 – 2.6|mmol/L
FE|Fe (sắt)|7 – 27|µmol/L
HBSAG|HBsAg|Âm tính|
HBEAG|HBeAg|Âm tính|
HIV|Test nhanh HIV|Âm tính|
HCV|HCV|Âm tính|
CRP-QUAL|CRP (định tính)|Âm tính|
HP|HP (H. pylori)|Âm tính|
HEV|HEV|Âm tính|
HAV|HAV|Âm tính|
T3|T3|1.3 – 3.1|nmol/L
T4|T4|66 – 181|nmol/L
FT3|FT3|3.1 – 6.8|pmol/L
FT4|FT4|9 – 24|pmol/L
TSH|TSH|0.3 – 4.2|µIU/mL
AFP|AFP (marker gan)|< 7|ng/mL
CEA|CEA (marker đường tiêu hóa)|< 7|ng/mL
CA19-9|CA 19-9 (marker tụy, mật)|< 39|U/mL
CA72-4|CA 72-4 (marker dạ dày)|< 6.9|U/mL
CA125|CA 125 (marker buồng trứng)|< 35|U/mL
CA15-3|CA 15-3 (marker vú)|< 34.5|U/mL
CYFRA21-1|CYFRA 21-1 (marker phổi tế bào không nhỏ)|< 3.3|U/L
PSA|PSA (marker tiền liệt tuyến)|0 – 4|ng/mL
CRP|Định lượng CRP|< 10|mg/dl'''
HEM = '''RBC|Số lượng hồng cầu (RBC)|Nam 4.0 – 5.8 · Nữ 3.9 – 5.4|×10¹²/L
HGB|Huyết sắc tố (HGB)|Nam 140 – 160 · Nữ 125 – 145|g/L
HCT|Hematocrit (HCT)|Nam 0.38 – 0.50 · Nữ 0.35 – 0.47|L/L
MCV|MCV|83 – 92|fL
MCH|MCH|27 – 32|pg
MCHC|MCHC|320 – 356|g/L
NRBC|Hồng cầu có nhân|0|×10⁹/L
RET|Hồng cầu lưới|0.1 – 0.5|%
PLT|Số lượng tiểu cầu (PLT)|150 – 400|×10⁹/L
MALARIA|KSV sốt rét|(định tính)|
WBC|Số lượng bạch cầu (WBC)|4 – 10|×10⁹/L
DIFF|Thành phần bạch cầu (%)|Đoạn trung tính · Đoạn ưa axit · Đoạn ưa bazơ · Mono · Lympho · Tế bào bất thường|
ESR|Máu lắng|Giờ 1: < 15 mm · Giờ 2: < 20 mm|
BLEEDING|Thời gian máu chảy|……|phút
CLOTTING|Thời gian máu đông|……|phút
ABO|Nhóm máu hệ ABO||'''
URINE = '''LEU|LEU (bạch cầu)|Âm tính|
NIT|NIT (nitrit)|Âm tính|
URO|URO (urobilinogen)|Âm tính (bình thường)|
PRO|PRO (protein)|Âm tính|
PH|pH|(phiếu mẫu ghi 5.0)|
BLO|BLO (hồng cầu)|Âm tính|
SG|SG (tỷ trọng)|(phiếu mẫu ghi 1.010)|
KET|KET (ceton)|Âm tính|
BIL|BIL (bilirubin)|Âm tính|
GLU|GLU (glucose)|Âm tính|'''


def references(text):
    import re
    values = []
    for part in text.split(' · '):
        sex = 'chung'
        for prefix in ('Nam', 'Nữ'):
            if part.startswith(prefix+' '):
                sex, part = prefix, part[len(prefix)+1:]
        ref = dict(sex=sex, age_from=None, age_to=None, lower_value=None, upper_value=None, normal_value='')
        if re.fullmatch(r'[\d.]+ – [\d.]+', part):
            ref['lower_value'], ref['upper_value'] = part.split(' – ')
        elif re.fullmatch(r'≤ [\d.]+', part):
            ref['upper_value'] = part[2:]
        elif re.fullmatch(r'[\d.]+', part):
            ref['lower_value'] = ref['upper_value'] = part
        else:
            # The current M5 template has inclusive bounds only. Preserve strict '<'
            # and compound/free-text references verbatim, never turn them into '≤'.
            return [dict(sex='chung', age_from=None, age_to=None, lower_value=None, upper_value=None, normal_value=text)] if text else []
        values.append(ref)
    return values


def catalog_items():
    items = []
    for group, source in [('biochemistry', BIO), ('hematology', HEM), ('urine', URINE)]:
        for index, line in enumerate(source.splitlines(), 1):
            code, name, ref, unit = line.split('|')
            refs = references(ref)
            from app.m5 import strict_upper
            textual = any(x['normal_value'] and strict_upper(x['normal_value']) is None for x in refs) or not ref
            items.append(dict(code=group+'-'+code, name=name, abbreviation='', group_name=group,
                              result_type='text' if textual else 'number', unit=unit,
                              decimals=max([len(part.split('.')[1]) for part in ref.split() if '.' in part and part.replace('.', '').isdigit()] or [0]),
                              print_order=index, active=True, choices=[], references=refs))
    return items


def build():
    import pymupdf
    with pymupdf.open('app/static/MinhDuc_logo_mau.svg') as svg:
        svg[0].get_pixmap(matrix=pymupdf.Matrix(.5,.5),alpha=True).save(LOGO)
    for filename in TEMPLATES.values():
        doc = Document()
        section = doc.sections[0]
        section.page_width = Pt(595.276)
        section.page_height = Pt(841.89)
        section.left_margin = section.right_margin = Pt(50)
        section.top_margin = Pt(108)
        section.bottom_margin = Pt(35)
        section.header_distance = Pt(24)
        section.footer_distance = Pt(20)
        normal = doc.styles['Normal']
        normal.font.name = 'Times New Roman'
        normal.font.size = Pt(9)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.space_after = Pt(2)
        normal.paragraph_format.line_spacing = 1
        t = section.header.add_table(rows=1, cols=3, width=Pt(495))
        t.columns[0].width = Pt(82)
        t.columns[1].width = Pt(263)
        t.columns[2].width = Pt(150)
        t.cell(0, 0).paragraphs[0].add_run().add_picture(str(LOGO), width=Pt(62))
        doc.save(TEMPLATE_DIR/filename)
    # The repository templates are reviewable documents, with the exact print blocks.
    # Runtime clears only their body; section/header/footer styles remain the frame.
    from app.s2c_forms import prescription, laboratory, word, base
    person=dict(full_name='[tự điền]',sex='[tự điền]',date_of_birth='',code='[tự điền]',address='[tự điền]')
    profile=dict(name='[Tên cơ sở — từ Cài đặt]',governing_body='[Cơ quan chủ quản — từ Cài đặt]',
                 address='[Địa chỉ — từ Cài đặt]',phone='[từ Cài đặt]',email='[từ Cài đặt]')
    models=[prescription(person,profile,'[tự điền từ phiếu khám]',
                         [['[Tên thuốc – hàm lượng/nồng độ]','[……]','[liều · đường dùng · thời điểm · số ngày]'] for _ in range(5)],
                         '[chế độ ăn, sinh hoạt; ngày tái khám; thời hạn mua thuốc]','',None)]
    order=base('order',person,profile,'[bác sĩ ghi]', '[tự sinh]')
    order.update(signer_title='BÁC SĨ CHỈ ĐỊNH',signer_name='',orders=[],notes=[])
    order['fields'] += [('Số BHYT','[nếu có]','Nghề nghiệp','[tự điền]'),('Lý do khám','[tự điền]','',''),('Chẩn đoán sơ bộ','[bác sĩ ghi]','','')]
    models.append(order)
    items=[]
    for x in catalog_items():
        refs=[]
        for ref in x['references']:
            text=ref['normal_value'] or ' – '.join(v for v in (ref['lower_value'],ref['upper_value']) if v is not None)
            refs.append((ref['sex']+' ' if ref['sex']!='chung' else '')+text)
        items.append(dict(x,reference_text=' · '.join(refs),display_value='',flag=''))
    sample=dict(id='[tự sinh]',patient=person,clinic_profile=profile,diagnosis='[tự điền từ phiếu khám]',status='approved',items=items)
    models += [laboratory(sample,group) for group in ('biochemistry','hematology','urine','other')]
    for model in models:
        (TEMPLATE_DIR/TEMPLATES[model['kind']]).write_bytes(word(model))
    raw = workbook(catalog_items())
    assert len(parse(raw)) == 78
    target = Path('data/danh_muc_goc/chi_so_xet_nghiem_minh_duc.xlsx')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    import hashlib
    manifest=Path('docs/assets-v031.sha256')
    lines=manifest.read_text(encoding='utf-8').splitlines()
    for path in [TEMPLATE_DIR/name for name in TEMPLATES.values()]+[LOGO]:
        relative=path.relative_to(Path.cwd())
        lines=[line for line in lines if not line.endswith('  '+str(relative))]
        lines.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+str(relative))
    manifest.write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__ == '__main__':
    build()
