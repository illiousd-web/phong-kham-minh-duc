"""Page 29–33 print models; the same blocks feed A4 PDF and Word."""
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from math import ceil
import re

from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from fastapi import HTTPException
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, Image

from .forms import TEMPLATE_DIR, WATERMARK, pdf_safe, fmt_date, format_patient_address, rx_rows
from .labels import VN_TZ, lab_rows
from .form_pagination import (AdviceWithSignature, KeepEnd, build_pdf, stack, continuation_identity,
                              word_pagination, word_keep, word_keep_row, word_repeat_header, text_chunks)

LOGO = TEMPLATE_DIR.parent/'static'/'MinhDuc_logo_in.png'
GREEN = '#008249'
LABS = {
    'biochemistry': ('PHIẾU XÉT NGHIỆM HÓA SINH MÁU', '22/BV-02', 'Sinh hóa máu và miễn dịch', 'Máu'),
    'hematology': ('PHIẾU XÉT NGHIỆM HUYẾT HỌC', '17/BV-02', '', 'Máu'),
    'urine': ('PHIẾU XÉT NGHIỆM HÓA SINH NƯỚC TIỂU', '23/BV-02', 'Nước tiểu 10 thông số', 'Nước tiểu'),
    'other': ('PHIẾU XÉT NGHIỆM', 'Nội bộ', '', ''),
}
TEMPLATES = {'rx': '08_Don_thuoc_A4.docx', 'order': '03_Phieu_chi_dinh_noi_khoa_A4.docx',
             **{k: '04_Phieu_XN_'+k+'_A4.docx' for k in LABS}}
REFERENCE_NOTE = 'Khoảng tham chiếu chép từ phiếu cũ — Trưởng khoa xét nghiệm xác nhận trước khi dùng thật [CẦN ĐỐI CHIẾU].'


def print_font():
    if 'ClinicPrint' not in pdfmetrics.getRegisteredFontNames():
        from pathlib import Path
        paths=[(Path('C:/Windows/Fonts/times.ttf'),Path('C:/Windows/Fonts/timesbd.ttf')),
               (Path('/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf'),Path('/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf')),
               (Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'))]
        for regular,bold in paths:
            if regular.exists() and bold.exists():
                pdfmetrics.registerFont(TTFont('ClinicPrint',str(regular)))
                pdfmetrics.registerFont(TTFont('ClinicPrint-Bold',str(bold)))
                pdfmetrics.registerFontFamily('ClinicPrint',normal='ClinicPrint',bold='ClinicPrint-Bold')
                break
        else:
            from .forms import font_name
            return font_name()
    return 'ClinicPrint'


def time_text(value):
    if not value:
        return '…… giờ ……, ngày …… / …… / 20……'
    return datetime.fromisoformat(value).astimezone(VN_TZ).strftime('%H:%M %d/%m/%Y')


def check_weight(person, weight):
    from .administrative import months_old
    age = months_old(person.get('date_of_birth'))
    if age is not None and age < 72 and (weight is None or str(weight).strip() in ('', '0')):
        raise HTTPException(422, 'Cần nhập cân nặng cho trẻ dưới 72 tháng trước khi in hoặc ký đơn thuốc')


def base(kind, patient, profile, diagnosis, number='', stamp=None):
    return {'kind': kind, 'profile': profile, 'number': str(number), 'patient_code': patient.get('code', ''),
            'stamp': stamp, 'diagnosis': diagnosis or '', 'rows': [], 'notes': [], 'signature': None,
            'fields': [('Họ tên', patient['full_name'], 'Giới tính' if kind == 'rx' else 'Tuổi',
                        patient.get('sex', '') if kind == 'rx' else age_text(patient)),
                       ('Địa chỉ', format_patient_address(patient), 'Số BHYT', patient.get('health_insurance_number', ''))]}


def age_text(patient):
    from .administrative import months_old
    months = patient.get('age_months')
    if months is None:
        months = months_old(patient.get('date_of_birth'))
    return (str(months)+' tháng' if months < 72 else str(months//12)) if months is not None else ''


def prescription(person, profile, diagnosis, rows, advice, name, stamp, weight=None, escort='', phone='', status='draft', notice=''):
    check_weight(person, weight)
    m = base('rx', person, profile, diagnosis, stamp=stamp)
    m['fields'] = [('Họ tên', person['full_name'], 'Giới tính', person.get('sex', '')),
                   ('Số định danh / CCCD', person.get('document_number') or person.get('citizen_id') or '', 'Ngày sinh', fmt_date(person.get('date_of_birth'))),
                   ('Mã số BHYT', person.get('health_insurance_number', ''), 'Cân nặng', str(weight)+' kg' if weight else ''),
                   ('Địa chỉ', format_patient_address(person), '', ''), ('Chẩn đoán', diagnosis, '', '')]
    m.update(rows=rows, advice=advice, signer_title='BÁC SĨ KHÁM BỆNH', signer_name=name,
             escort=escort or '', phone=phone or '', status=status, notice=notice)
    m['notes'] = ['— Khám lại xin mang theo đơn này.', '— Số điện thoại liên hệ: '+(phone or ''),
                  '— Họ tên người đưa trẻ đến khám: '+(escort or ''),
                  'Theo mẫu đơn thuốc Thông tư 26/2025/TT-BYT (hiệu lực 01/07/2025).']
    return m


def from_m6(p, status):
    rows = []
    for x in p['items']:
        usage = f"{x['dose']} {x.get('dose_unit') or x['unit']} × {x['frequency']} lần/ngày · {x['route']} · {x['timing']} · {x['days']} ngày"
        usage += ('; '+x['notes']) if x['notes'] else ''
        usage += ('; '+x['controlled_label']) if x.get('controlled_label') else ''
        rows.append([(x['display_name']+' – '+x['strength']).strip(' –'), x['quantity']+' '+x['unit'], usage])
    advice = '\n'.join(label+': '+p['advice'][key] for key, label in (
        ('lifestyle_advice', 'Chế độ dinh dưỡng, sinh hoạt'), ('follow_up_advice', 'Lịch tái khám'),
        ('purchase_advice', 'Thời hạn tốt nhất để mua thuốc')) if p['advice'][key])
    person = p['patient']
    notice = 'ĐƠN ĐÃ HỦY – KHÔNG CÓ GIÁ TRỊ' if status == 'cancelled' else ('NHÁP – CHƯA CÓ GIÁ TRỊ' if status == 'draft' else '')
    if p.get('replaced_by_code'):
        notice = 'ĐƠN ĐÃ HỦY – ĐÃ ĐƯỢC THAY THẾ BỞI '+p['replaced_by_code']
    m = prescription(person, p.get('clinic_profile', {}), p['encounter']['diagnosis'], rows, advice,
                     p['prescriber']['name'], p['locked_at'] or p['created_at'], person['weight_kg'],
                     person['escort_name'], person['contact_phone'], status, notice)
    m['notes'].append('CHƯA LIÊN THÔNG')
    m['signature'] = p.get('signature')
    m['print_number'] = p.get('print_number') or p.get('local_code') or ''
    return m


def from_context(kind, ctx):
    from .d0 import diagnosis_text
    p, v = ctx['patient'], ctx['visit']
    diagnosis = diagnosis_text(v)
    if kind == 'rx':
        r = ctx['rx']
        m = prescription(p, ctx.get('clinic_profile', {}), diagnosis, rx_rows(ctx),
                         (r.get('instructions') or '')+'\nHẹn tái khám: '+fmt_date(r.get('follow_up') or v.get('follow_up')),
                         ctx['doctor_name'], r['created_at'], v.get('weight_kg'), v.get('escort_name'),
                         v.get('escort_phone') or p.get('phone'), 'draft', 'NHÁP – CHƯA CÓ GIÁ TRỊ')
        m['notes'].append('CHƯA LIÊN THÔNG')
        m['print_number'] = f"MD-RX-{r['id']:06d}"
    elif kind == 'order':
        o = ctx['order']
        m = base('order', p, ctx.get('clinic_profile', {}), diagnosis, o['id'], o['created_at'])
        m['fields'] = [('Họ tên', p['full_name'], 'Tuổi', age_text(p)+'   Nam/Nữ: '+p.get('sex', '')),
                       ('Địa chỉ', format_patient_address(p), 'Nghề nghiệp', p.get('occupation', '')),
                       ('Số BHYT', p.get('health_insurance_number', ''), 'Mã NB', p.get('code', '')),
                       ('Lý do khám', v.get('chief_complaint', ''), '', ''), ('Chẩn đoán sơ bộ', diagnosis, '', '')]
        m['orders'] = [{key:x[key] for key in ('name','category')} for x in (ctx.get('orders') or [o]) if x['status'] != 'cancelled']
        m.update(signer_title='BÁC SĨ CHỈ ĐỊNH', signer_name=ctx['doctor_name'])
        m['notes'] = ['Phiếu chỉ định nội bộ — Phụ lục XXIX Thông tư 32/2023 không có mẫu riêng cho phiếu chỉ định ngoại trú [CẦN ĐỐI CHIẾU].']
    else:
        o = ctx['order']
        rows, notes, conclusion = lab_rows(o.get('result_text'))
        # Legacy free-text results carry no catalog group. Recognize only explicit names.
        text = (o.get('name', '')+' '+' '.join(x[0] for x in rows)).casefold()
        group = 'urine' if 'nước tiểu' in text else ('hematology' if any(x in text for x in ('huyết học', 'ctm', 'rbc', 'hgb', 'wbc')) else 'biochemistry')
        m = laboratory({'id': o['id'], 'patient': p, 'visit_id': v['id'], 'status': o['status'], 'sample_at': None,
                        'result_at': o.get('approved_at'), 'approved_at': o.get('approved_at'), 'comment': '\n'.join(notes+[conclusion or '']),
                        'approver_name': o.get('approved_by_name', ''), 'performer_name': o.get('result_by_name', ''),
                        'items': [{'name': x[0], 'display_value': x[1], 'unit': x[2], 'reference_text': x[3], 'flag': x[4], 'group_name': group} for x in rows]
                        or [{'name': o['name'], 'display_value': o.get('result_text', ''), 'unit': '', 'reference_text': '', 'flag': '', 'group_name': group}],
                        'clinic_profile': ctx.get('clinic_profile', {}), 'diagnosis': diagnosis}, group)
    m['signature'] = ctx.get('signature')
    return m


def laboratory(p, group):
    m = base(group, p['patient'], p.get('clinic_profile', {}), p.get('diagnosis'), 'XN-'+str(p['id']), p.get('approved_at'))
    m['fields'][0] = ('Họ tên', p['patient']['full_name'], 'Tuổi', age_text(p['patient'])+'   Nam/Nữ: '+p['patient'].get('sex', ''))
    m['fields'] += [('Khoa/Phòng', p.get('ordering_department', ''), 'Buồng/giường', 'Không áp dụng (ngoại trú)'),
                    ('Chẩn đoán', p.get('diagnosis', ''), '', '')]
    m.update(signer_title='TRƯỞNG KHOA XÉT NGHIỆM', signer_name=p.get('approver_name', ''),
             sample_at=p.get('sample_at'), result_at=p.get('result_at'), signature=p.get('signature'))
    m['rows'] = [[x['name']+(' ('+x['abbreviation']+')' if x.get('abbreviation') else '')+('\nGhi chú: '+x['note'] if x.get('note') else ''),
                  (x['reference_text']+' '+x['unit']).strip(), str(x.get('display_value', x.get('value', ''))), x['flag']]
                 for x in p['items'] if x['group_name'] == group]
    m['notes'] = [REFERENCE_NOTE]
    if p['status'] != 'approved':
        m['notes'].append('NHÁP – CHƯA DUYỆT')
    if p.get('replaces_id'):
        m['notes'].append('BẢN ĐIỀU CHỈNH, thay thế phiếu XN-'+str(p['replaces_id'])+'; '+p.get('adjustment_reason', ''))
    if p.get('superseded_by'):
        m['notes'].append('ĐÃ ĐƯỢC THAY THẾ BỞI PHIẾU #'+str(p['superseded_by']))
    if p.get('comment'):
        m['notes'].append('Nhận xét chung: '+p['comment'])
    m['notes'].append('Người thực hiện: '+(p.get('performer_name') or '')+'; Người duyệt: '+m['signer_name'])
    return m


def lab_grid(m):
    def cells(row):
        name, ref, value, flag = row
        arrow = ' ↑' if flag == 'H' else (' ↓' if flag == 'L' else '')
        return [name, ref, ('<b>'+pdf_safe(value+arrow)+'</b>') if flag else pdf_safe(value)]
    rows = [cells(row) for row in m['rows']]
    head = ['Xét nghiệm', 'Trị số bình thường', 'Kết quả']
    if m['kind'] == 'biochemistry':
        half = ceil(len(rows)/2)
        return [head*2]+[rows[i]+(rows[i+half] if i+half < len(rows) else ['', '', '']) for i in range(half)]
    return [head]+rows


def order_checks(m):
    from .m6 import fold
    orders = m['orders']
    names = ' '.join(fold(x['name']) for x in orders if x['category'] == 'lab')
    groups = [('CTM', ('ctm', 'cong thuc mau', 'huyet hoc')), ('Bilirubin', ('bilirubin',)), ('GOT, GPT', ('got', 'gpt', 'ast', 'alt')),
              ('Dengue', ('dengue',)), ('MC – MĐ', ('mau chay', 'mau dong')), ('Cholesterol, Triglycerid', ('cholesterol', 'triglycerid')),
              ('GGT', ('ggt',)), ('AFP', ('afp',)), ('Máu lắng', ('mau lang',)), ('Ure, Creatinin', ('ure', 'creatinin')),
              ('HBsAg', ('hbsag',)), ('Test HP', ('test hp', 'h. pylori')), ('CRP', ('crp',)), ('Glucose', ('glucose',)),
              ('HCV', ('hcv',)), ('β-HCG', ('hcg',)), ('Acid uric', ('acid uric',)), ('HDL / LDL', ('hdl', 'ldl')),
              ('HIV', ('hiv',)), ('Nước tiểu 10 thông số', ('nuoc tieu',))]
    labs = [('☒ ' if any(re.search(r'(?<![a-z0-9])'+re.escape(token)+r'(?![a-z0-9])',names) for token in keys) else '☐ ')+label for label, keys in groups]
    result = [('1. Xét nghiệm', labs)]
    def service_group(order):
        name=fold(order['name'])
        if 'noi soi' in name:
            return 'ent' if 'tai mui hong' in name or 'tmh' in name else 'other'
        return order['category'] if order['category'] in ('lab','ultrasound','xray','ecg','ent') else 'other'
    for index, label, category in [(2, 'Siêu âm', 'ultrasound'), (3, 'X-quang', 'xray'),
                                    (4, 'Nội soi tai mũi họng', 'ent'), (5, 'Điện tim', 'ecg'), (6, 'Dịch vụ khác', 'other')]:
        selected=[x['name'] for x in orders if service_group(x)==category]
        result.append(('☒ ' if selected else '☐ ')+str(index)+'. '+label+(': '+', '.join(selected) if selected else ''))
    # Preserve arbitrary ordered lab names too; checkboxes alone cannot describe every catalog service.
    lab_names = [x['name'] for x in orders if x['category'] == 'lab']
    if lab_names:
        result.append('Chỉ định xét nghiệm: '+', '.join(lab_names))
    return result


def signature_caption(s):
    stamp = datetime.fromisoformat(s['signed_at']).astimezone(VN_TZ).strftime('%H:%M %d/%m/%Y')
    return 'Ký lúc '+stamp+' bởi tài khoản '+s['username']


def render(model, fmt):
    m = deepcopy(model)
    return word(m) if fmt=='docx' else pdf(m)


def pdf(m):
    out = BytesIO()
    font = print_font()
    style = ParagraphStyle('S2c', fontName=font, fontSize=9, leading=11, spaceAfter=2)
    small = ParagraphStyle('S2cSmall', parent=style, fontSize=6.8, leading=8)
    center = ParagraphStyle('S2cCenter', parent=style, alignment=1)
    width = A4[0]-100
    from .forms import font_name
    symbol_font=font_name()
    def par(text, st=style, markup=False):
        text=text if markup else pdf_safe(text)
        for symbol in ('☐','☒'):
            text=text.replace(symbol,'<font name="'+symbol_font+'">'+symbol+'</font>')
        return Paragraph(text, st)
    def grid(rows, widths, border=False):
        table = Table(rows, colWidths=widths, hAlign='LEFT', splitInRow=1)
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 4),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]
        if border:
            commands += [('GRID', (0, 0), (-1, -1), .35, colors.HexColor('#b4c9bf')),
                         ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f4ee'))]
        table.setStyle(TableStyle(commands))
        return table
    profile=m['profile']
    header_parts=[]
    for key in (('name','address') if m['kind']=='rx' else ('governing_body','name','address')):
        if profile.get(key):
            value=pdf_safe(profile[key])
            header_parts.append('<b><font color="'+GREEN+'">'+value+'</font></b>' if key=='name' else value)
    contacts=' · '.join(label+profile[key] for key,label in [('phone','Điện thoại: '),('email','Email: ')] if profile.get(key))
    code = 'Mã đơn thuốc: □□□□□□□□□□□□□□' if m['kind'] == 'rx' else 'MS: '+(LABS[m['kind']][1] if m['kind'] in LABS else '[nội bộ]')+'\nSố: '+m['number']+'\nMã NB: '+m['patient_code']
    logo = Image(str(LOGO), 62, 44, kind='proportional')
    header=grid([[logo, par('<br/>'.join(header_parts),markup=True), par(code, small)]], [82, width-232, 150])
    header_height=header.wrap(width,A4[1])[1]
    story = [header, par(contacts, ParagraphStyle('Contact',parent=small,alignment=1)), Spacer(1, max(8, 66-header_height))]
    title = 'ĐƠN THUỐC' if m['kind'] == 'rx' else ('PHIẾU CHỈ ĐỊNH NỘI KHOA' if m['kind'] == 'order' else LABS[m['kind']][0])
    story += [par('<b>'+title+'</b>', ParagraphStyle('S2cTitle', parent=center, fontSize=13, leading=16, spaceAfter=4), True)]
    if m['kind'] in LABS and LABS[m['kind']][2]:
        story.append(par(LABS[m['kind']][2], center))
    if m['kind'] != 'rx':
        story += [Spacer(1, 7), par('☐ Thường     ☐ Cấp cứu', center)]
    if m.get('notice'):
        story.append(par(m['notice'], center))
    fields=[]
    for a,b,c,d in m['fields']:
        fields.append([par('<b>'+pdf_safe(a)+'</b>',markup=True),par(b),par('<b>'+pdf_safe(c)+'</b>',markup=True),par(d)])
    field_table=grid(fields,[104,180,82,width-366])
    field_table.setStyle(TableStyle([('SPAN',(1,i),(3,i)) for i,(_,_,c,_) in enumerate(m['fields']) if not c]))
    story += [field_table,Spacer(1,5)]
    if m['kind'] == 'rx':
        story.append(par('<b>THUỐC ĐIỀU TRỊ</b>', markup=True))
        for i, (name, qty, usage) in enumerate(m['rows'], 1):
            drug=grid([[par(f'<b>{i}. {pdf_safe(name)}     Số lượng: {pdf_safe(qty)}</b><br/>Cách dùng: {pdf_safe(usage)}', markup=True)]],[width])
            drug.setStyle(TableStyle([('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#b4c9bf'))]))
            story.append(drug)
            story.append(Spacer(1, 3))
    elif m['kind'] == 'order':
        story.append(par('<b>YÊU CẦU KIỂM TRA</b>', markup=True))
        checks = order_checks(m)
        story += [par(checks[0][0]), grid([[par(x) for x in checks[0][1][i:i+4]] for i in range(0, 20, 4)], [width/4]*4)]
        story += [par(x) for x in checks[1:]]
    else:
        story.append(par('Bệnh phẩm: '+LABS[m['kind']][3]+'   Lấy mẫu lúc: '+time_text(m['sample_at'])+'   Trả kết quả lúc: '+time_text(m['result_at']), small))
        rows = lab_grid(m)
        cell = ParagraphStyle('S2cLab', parent=small, fontSize=6.7, leading=8)
        lab_table=grid([[par(v,cell,j%3==2 and i>0) for j,v in enumerate(row)] for i,row in enumerate(rows)],
                       [width*.19,width*.18,width*.13]*2 if m['kind']=='biochemistry' else [width*.40,width*.35,width*.25],True)
        lab_table.repeatRows = 1
        lab_table.setStyle(TableStyle([('TOPPADDING',(0,1),(-1,-1),.8),('BOTTOMPADDING',(0,1),(-1,-1),.8)]))
        story.append(lab_table)
    signature = [par(time_text(m['stamp']), center), par('<b>'+m['signer_title']+'</b>', center, True), par('(Ký, ghi rõ họ tên)', center)]
    s = m.get('signature')
    signature += [Image(BytesIO(s['image']), 105, 38, kind='proportional')] if s else [Spacer(1, 38)]
    signature += [par(m['signer_name'], center)]
    if s:
        signature.append(par(signature_caption(s), small))
    sig_table = grid([['', signature]], [width*.55, width*.45])
    if m['kind'] == 'rx':
        ending = AdviceWithSignature(par('Lời dặn:\n'+m['advice']),
                                     stack(signature, width*.45-8),
                                     stack([par(x, small) for x in m['notes']], width))
        if m['rows'] and ending.wrapOn(None, width, A4[1])[1] < 500:
            story.pop()  # Inter-medicine spacing; the last medicine stays with the ending.
            story.append(KeepEnd(story.pop(), ending))
        else:
            story.append(ending)
    else:
        # Comments can themselves span pages. Only the final comment line and the
        # signature are kept together, never an arbitrarily long entire comment.
        notes = [par(x, small) for x in m['notes']]
        ending = stack(notes+[Spacer(1, 6), sig_table], width)
        if ending.wrapOn(None, width, A4[1])[1] < 500:
            story.append(KeepEnd(story.pop(), ending))
        else:
            # Walk backwards to find the long comment, carrying its short suffix
            # and signature with its final line instead of creating a signature-only page.
            suffix = [Spacer(1, 6), sig_table]
            for i in range(len(notes)-1, -1, -1):
                candidate = stack([notes[i]]+suffix, width)
                if candidate.wrapOn(None, width, A4[1])[1] >= 500:
                    story += notes[:i]
                    story.append(KeepEnd(notes[i], stack(suffix, width)))
                    break
                suffix.insert(0, notes[i])
    identity = par(continuation_identity(m['fields'][0][1], m['patient_code'],
                                        m.get('print_number') or m['number'], prescription=m['kind']=='rx'))
    identity_height = identity.wrap(width, A4[1])[1]
    def frame(canvas, doc):
        canvas.setStrokeColor(colors.HexColor(GREEN))
        if doc.page == 1:
            canvas.line(50, A4[1]-105, A4[0]-50, A4[1]-105)
        else:
            identity.drawOn(canvas, 50, A4[1]-30-identity_height)
            canvas.line(50, A4[1]-38-identity_height, A4[0]-50, A4[1]-38-identity_height)
        canvas.setFont(font, 6)
        canvas.setFillColor(colors.HexColor('#B42318'))
        canvas.drawCentredString(A4[0]/2, 25, WATERMARK)
    build_pdf(out, story, font=font, pagesize=A4, left=50, right=50, first_top=30,
              later_top=max(68, identity_height+45), bottom=35, first_header=frame, later_header=frame)
    return out.getvalue()


def word(m):
    doc = Document(TEMPLATE_DIR/TEMPLATES[m['kind']])
    for child in list(doc._element.body):
        if not child.tag.endswith('}sectPr'):
            doc._element.body.remove(child)
    section = doc.sections[0]
    first_header = section.first_page_header if section.different_first_page_header_footer else section.header
    header = first_header.tables[0]
    profile=m['profile']
    identity=header.cell(0,1)
    identity.text=''
    first=True
    for key in (('name','address') if m['kind']=='rx' else ('governing_body','name','address')):
        if not profile.get(key):
            continue
        p=identity.paragraphs[0] if first else identity.add_paragraph()
        first=False
        run=p.add_run(profile[key])
        run.font.size=Pt(8)
        if key=='name':
            run.bold=True
            run.font.color.rgb=RGBColor.from_string('008249')
    if len(header.rows)==1:
        header.add_row()
    contact=header.cell(1,0).merge(header.cell(1,2))
    contact.text=' · '.join(label+profile[key] for key,label in [('phone','Điện thoại: '),('email','Email: ')] if profile.get(key))
    contact.paragraphs[0].alignment=1
    for run in contact.paragraphs[0].runs:
        run.font.size=Pt(7)
    header.cell(0, 2).text = ('Mã đơn thuốc: □□□□□□□□□□□□□□' if m['kind'] == 'rx' else
                             'MS: '+(LABS[m['kind']][1] if m['kind'] in LABS else '[nội bộ]')+'\nSố: '+m['number']+'\nMã NB: '+m['patient_code'])
    title_border=OxmlElement('w:pBdr')
    border=OxmlElement('w:top')
    for key,value in [('val','single'),('sz','8'),('color','008249'),('space','4')]:
        border.set(qn('w:'+key),value)
    title_border.append(border)
    def paragraph(value, parent=doc, bold=False, size=None):
        p = parent.add_paragraph()
        run = p.add_run(str(value or ''))
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        return p
    title = 'ĐƠN THUỐC' if m['kind'] == 'rx' else ('PHIẾU CHỈ ĐỊNH NỘI KHOA' if m['kind'] == 'order' else LABS[m['kind']][0])
    p = paragraph(title, bold=True, size=14)
    p.alignment = 1
    p._p.get_or_add_pPr().append(title_border)
    if m['kind'] in LABS and LABS[m['kind']][2]:
        paragraph(LABS[m['kind']][2]).alignment = 1
    if m['kind'] != 'rx':
        paragraph('☐ Thường     ☐ Cấp cứu').alignment = 1
    if m.get('notice'):
        paragraph(m['notice']).alignment = 1
    table = doc.add_table(rows=0, cols=4)
    table.autofit = False
    for column,width in zip(table.columns,(104,180,82,129)):
        column.width=Pt(width)
    for a, b, c, d in m['fields']:
        cells = table.add_row().cells
        for i, value in enumerate((a, b, c, d)):
            cells[i].text = str(value or '')
        if not c:
            merged=cells[1].merge(cells[3])
            merged.text=str(b or '')
        for i in ((0,2) if c else (0,)):
            for run in cells[i].paragraphs[0].runs:
                run.bold = True
    if m['kind'] == 'rx':
        paragraph('THUỐC ĐIỀU TRỊ', bold=True)
        for i, (name, qty, usage) in enumerate(m['rows'], 1):
            word_keep(paragraph(f'{i}. {name}     Số lượng: {qty}', bold=True))
            for chunk in text_chunks('Cách dùng: '+usage):
                p = paragraph(chunk)
            rule=OxmlElement('w:pBdr')
            edge=OxmlElement('w:bottom')
            edge.set(qn('w:val'),'single')
            edge.set(qn('w:sz'),'2')
            edge.set(qn('w:color'),'B4C9BF')
            rule.append(edge)
            p._p.get_or_add_pPr().append(rule)
    elif m['kind'] == 'order':
        paragraph('YÊU CẦU KIỂM TRA', bold=True)
        checks = order_checks(m)
        paragraph(checks[0][0])
        t = doc.add_table(rows=0, cols=4)
        for i in range(0, 20, 4):
            for cell, value in zip(t.add_row().cells, checks[0][1][i:i+4]):
                cell.text = value
        for value in checks[1:]:
            for chunk in text_chunks(value):
                paragraph(chunk)
    else:
        paragraph('Bệnh phẩm: '+LABS[m['kind']][3]+'   Lấy mẫu lúc: '+time_text(m['sample_at'])+'   Trả kết quả lúc: '+time_text(m['result_at']), size=7)
        values = lab_grid(m)
        t = doc.add_table(rows=0, cols=len(values[0]))
        t.style = 'Table Grid'
        t.autofit=False
        fractions=([.19,.18,.13]*2 if m['kind']=='biochemistry' else [.40,.35,.25])
        for column,fraction in zip(t.columns,fractions):
            column.width=Pt(495*fraction)
        for i, row in enumerate(values):
            from html import unescape
            contents = []
            for value in row:
                bold = value.startswith('<b>') or i == 0
                value = unescape(value[3:-4] if value.startswith('<b>') else value)
                contents.append((text_chunks(value), bold))
            for part in range(max(len(chunks) for chunks, _ in contents)):
                added = t.add_row()
                if i == 0:
                    word_repeat_header(added)
                for cell, (chunks, bold) in zip(added.cells, contents):
                    cell.text = chunks[part] if part < len(chunks) else ''
                    for run in cell.paragraphs[0].runs:
                        run.bold = bold
                        run.font.size = Pt(7)
    # Keep the final content line (not the whole paragraph/table) with the signature.
    if m['kind'] in LABS:
        for cell in t.rows[-1].cells:
            for p in cell.paragraphs:
                word_keep(p)
                p.paragraph_format.keep_together = True
        word_keep_row(t.rows[-1])
    elif doc.paragraphs:
        word_keep(doc.paragraphs[-1])
        doc.paragraphs[-1].paragraph_format.keep_together = True
    if m['kind'] != 'rx':
        for value in m['notes']:
            chunks = text_chunks(value)
            for i, chunk in enumerate(chunks):
                p = paragraph(chunk, size=7)
                word_keep(p, next=i == len(chunks)-1)
                if i == len(chunks)-1:
                    p.paragraph_format.keep_together = True
    long_advice = m['kind'] == 'rx' and Paragraph(pdf_safe(m['advice']), ParagraphStyle(
        'AdviceMeasure', fontName=print_font(), fontSize=9, leading=11)).wrap(495*.55-12, 1e9)[1] > 240
    if long_advice:
        # A multi-page advice paragraph must start in the remaining space after the medicine.
        if doc.paragraphs:
            word_keep(doc.paragraphs[-1], next=False)
        chunks = text_chunks('Lời dặn:\n'+m['advice'])
        for i, chunk in enumerate(chunks):
            p = paragraph(chunk)
            p.paragraph_format.right_indent = Pt(495*.45)
            word_keep(p, next=i == len(chunks)-1)
        p.paragraph_format.keep_together = True
    t = doc.add_table(rows=1, cols=2)
    t.autofit = False
    t.columns[0].width, t.columns[1].width = Pt(495*.55), Pt(495*.45)
    if m['kind'] == 'rx':
        left = t.cell(0, 0)
        left.text = ('Lời dặn:\n'+m['advice']) if not long_advice else ''
        for value in m['notes']:
            paragraph(value, left, size=7)
    cell = t.cell(0, 1)
    cell.text = time_text(m['stamp'])
    paragraph(m['signer_title'], cell, True).alignment = 1
    paragraph('(Ký, ghi rõ họ tên)', cell).alignment = 1
    s = m.get('signature')
    p = cell.add_paragraph()
    p.alignment = 1
    if s:
        p.add_run().add_picture(BytesIO(s['image']), width=Pt(105), height=Pt(38))
    else:
        p.paragraph_format.space_after = Pt(38)
    paragraph(m['signer_name'], cell).alignment = 1
    if s:
        paragraph(signature_caption(s), cell, size=6.5)
    word_keep_row(t.rows[0])
    word_keep(cell.paragraphs[-1], next=False)
    word_pagination(doc, continuation_identity(m['fields'][0][1], m['patient_code'],
                    m.get('print_number') or m['number'], prescription=m['kind']=='rx'), WATERMARK)
    section._sectPr.set(qn('w:rsidR'), '00000000')
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
