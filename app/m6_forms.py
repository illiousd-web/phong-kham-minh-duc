"""Word and PDF share one ordered representation of the locked prescription."""
from datetime import datetime
from io import BytesIO
from docx import Document
from docx.shared import Pt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A5
from reportlab.lib import colors
from .forms import font_name, pdf_safe, fmt_date, clean
from .labels import VN_TZ
from .m6 import decimal


def content(p, status):
    f = p['facility']; person = p['patient']; advice = p['advice']
    head = [('Mã đơn thuốc', p['local_code'] or ('MÃ NHÁP – CHƯA KHÓA ĐƠN' if f['clinic_facility_code'] else 'MÃ NHÁP – CHƯA CÓ MÃ CƠ SỞ')),
            ('Tên đơn vị', f['clinic_name']), ('Địa chỉ cơ sở', f['clinic_address']), ('Điện thoại cơ sở', f['clinic_phone'])]
    head.append(('', 'ĐƠN THUỐC'))
    if status == 'draft': head.append(('', 'NHÁP – CHƯA CÓ GIÁ TRỊ'))
    if status == 'cancelled': head.append(('', 'ĐƠN ĐÃ HỦY – ĐÃ ĐƯỢC THAY THẾ BỞI '+p['replaced_by_code'] if p.get('replaced_by_code') else 'ĐƠN ĐÃ HỦY – KHÔNG CÓ GIÁ TRỊ'))
    head += [('Họ tên', person['full_name']), ('Số định danh/CCCD/căn cước/hộ chiếu (nếu có)', person['document_number'] or ''),
             ('Ngày sinh', fmt_date(person['date_of_birth'])), ('Cân nặng', str(person['weight_kg'])+' kg' if person['weight_kg'] else ''),
             ('Giới tính', person['sex']), ('Mã số BHYT', ''), ('Nơi thường trú/tạm trú/ở hiện tại', person['address']),
             ('Chẩn đoán', p['encounter']['diagnosis'])]
    rows = []
    for i, item in enumerate(p['items'], 1):
        amount = item['quantity']; n = decimal(amount)
        if n is not None and n == n.to_integral_value() and n < 10: amount = '0'+str(int(n))
        usage = 'Liều/lần: '+item['dose']+' '+(item.get('dose_unit') or item['unit'])+' × '+item['frequency']+' lần/ngày; '+item['route']
        if item['timing']: usage += '; '+item['timing']
        usage += '; '+item['days']+' ngày'
        if item['notes']: usage += '; '+item['notes']
        if item.get('controlled_label'): usage += '; '+item['controlled_label']
        rows.append([str(i), (item['display_name']+' '+item['strength']).strip(), (amount+' '+item['unit']).strip(), usage])
    tail = [(label, advice[key]) for key, label in [('lifestyle_advice', 'Chế độ dinh dưỡng, sinh hoạt'),
        ('follow_up_advice', 'Lịch tái khám'), ('purchase_advice', 'Thời hạn tốt nhất để mua thuốc')] if advice[key]]
    stamp = datetime.fromisoformat(p['locked_at'] or p['created_at']).astimezone(VN_TZ)
    tail += [('', f'Ngày {stamp.day:02d} tháng {stamp.month:02d} năm {stamp.year}'),
             ('', 'Bác sỹ/Y sỹ khám bệnh'), ('', '(Ký, ghi rõ họ tên)'), ('', p['prescriber']['name']),
             ('', 'Khám lại xin mang theo đơn này.'), ('Số điện thoại liên hệ', person['contact_phone'])]
    if person['age_months'] is not None:
        tail += [('Tuổi', str(person['age_months'])+' tháng'), ('Họ tên người đưa trẻ', person['escort_name'])]
    tail += [('', 'CHƯA LIÊN THÔNG')]
    return head, rows, tail


def render(p, status, fmt):
    head, rows, tail = content(p, status)
    def text(label, value): return (label+': ' if label else '')+clean(value)
    buf = BytesIO()
    if fmt == 'docx':
        doc = Document(); section = doc.sections[0]
        section.page_width = Pt(A5[0]); section.page_height = Pt(A5[1])
        section.left_margin = section.right_margin = Pt(25)
        section.top_margin = section.bottom_margin = Pt(25)
        doc.styles['Normal'].font.name = 'Arial'; doc.styles['Normal'].font.size = Pt(9)
        for label, value in head:
            if not label and value == 'ĐƠN THUỐC': doc.add_heading(value, 0)
            else: doc.add_paragraph(text(label, value))
        doc.add_paragraph('Thuốc điều trị:')
        table = doc.add_table(rows=1, cols=4); table.style = 'Table Grid'
        for cell, value in zip(table.rows[0].cells, ['STT', 'Tên thuốc + hàm lượng', 'Số lượng + đơn vị', 'Cách dùng']): cell.text = clean(value)
        for row in rows:
            for cell, value in zip(table.add_row().cells, row): cell.text = clean(value)
        for label, value in tail:
            paragraph = doc.add_paragraph(text(label, value))
            if value == p['prescriber']['name']:
                paragraph.paragraph_format.space_before = Pt(30)
        doc.save(buf)
    else:
        font = font_name(); style = ParagraphStyle('M6', fontName=font, fontSize=8, leading=11, spaceAfter=5)
        par = lambda value: Paragraph(pdf_safe(value), style)
        title_style = ParagraphStyle('M6Title', parent=style, fontSize=14, leading=18, alignment=1)
        story = [Paragraph('<b>ĐƠN THUỐC</b>', title_style) if not l and v == 'ĐƠN THUỐC' else par(text(l, v)) for l, v in head]+[par('Thuốc điều trị:')]
        values = [[par(x) for x in ['STT', 'Tên thuốc + hàm lượng', 'Số lượng + đơn vị', 'Cách dùng']]]+[[par(v) for v in row] for row in rows]
        table = Table(values, colWidths=[22, 118, 65, A5[0]-255], repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, colors.grey), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        story += [table, Spacer(1, 10)]
        for label, value in tail:
            if value == p['prescriber']['name']: story.append(Spacer(1, 30))
            story.append(par(text(label, value)))
        SimpleDocTemplate(buf, pagesize=A5, leftMargin=25, rightMargin=25, topMargin=25, bottomMargin=25).build(story)
    return buf.getvalue()
