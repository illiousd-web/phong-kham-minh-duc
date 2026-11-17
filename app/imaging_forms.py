"""A–D imaging layout from pages 1–28, shared by existing imaging form routes."""
from io import BytesIO

from fastapi import HTTPException
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, Image
from docx import Document
from docx.shared import Inches, Pt

from .forms import pdf_safe, fmt_date, format_patient_address


def section_headings(m):
    xray = m['kind']=='xray'
    sections = [('request','YÊU CẦU CHIẾU/CHỤP' if xray else 'YÊU CẦU KIỂM TRA'),
                ('result','KẾT QUẢ CHIẾU/CHỤP' if xray else 'KẾT QUẢ SIÊU ÂM — Mô tả')]
    if m['images']:
        sections.append(('images','HÌNH ẢNH X-QUANG' if xray else 'HÌNH ẢNH SIÊU ÂM'))
    sections.append(('conclusion','KẾT LUẬN'))
    return {key:f'{chr(65+i)}. {title}' for i,(key,title) in enumerate(sections)}


def blocks(m, size):
    from .forms import LOGO, WATERMARK
    from .s2c_forms import print_font
    font = print_font()
    headings = section_headings(m)
    normal = ParagraphStyle('imaging-body',fontName=font,fontSize=size,leading=size*1.18,spaceAfter=2)
    bold = ParagraphStyle('imaging-head',parent=normal,textColor=colors.HexColor('#008249'),fontSize=size+1)
    def p(t, heading=False):
        return Paragraph(('<b>'+pdf_safe(t)+'</b>') if heading else pdf_safe(t), bold if heading else normal)
    profile = m['profile']
    header = '\n'.join(profile.get(k) or '' for k in ('governing_body','name','address'))
    identity = f"MS: {'08' if m['kind']=='xray' else '11'}/BV-02\nSố: {m['number']}\nMã NB: {m['patient']['code']}"
    logo = Image(str(LOGO),width=55,height=35,kind='proportional') if LOGO.exists() else ''
    header_table = Table([[logo,p(header),p(identity)]],colWidths=[65,310,140])
    header_table.setStyle(TableStyle([('LINEBELOW',(0,0),(-1,-1),1,colors.HexColor('#008249'))]))
    title_style = ParagraphStyle('imaging-title',parent=normal,fontSize=size+3,alignment=1)
    title = 'PHIẾU CHIẾU/CHỤP X-QUANG' if m['kind']=='xray' else 'PHIẾU SIÊU ÂM'
    items = [header_table,
             p(' · '.join(profile.get(k) or '' for k in ('phone','email'))),
             Paragraph('<b>'+title+'</b>',title_style),
             p(m['template_name'],True)]
    if m.get('replaces'):
        items.append(p('Đính chính phiếu '+m['replaces']+' — Lý do: '+m['reason']))
    if m.get('successor'):
        items.append(p(m['successor']))
    pat = m['patient']
    patient = [[p('Họ tên'),p(pat['full_name']),p('Ngày sinh'),p(fmt_date(pat['date_of_birth'])+' · Giới: '+pat.get('sex',''))],
               [p('Địa chỉ'),p(format_patient_address(pat)),p('Số BHYT'),p(pat.get('health_insurance_number') or '—')],
               [p('Khoa/Phòng'),p('Ngoại trú'),p('Buồng/giường'),p('Không áp dụng (ngoại trú)')],
               [p('Chẩn đoán'),p(m['diagnosis']),p(''),p('')]]
    patient_table = Table(patient,colWidths=[75,195,90,155])
    patient_table.setStyle(TableStyle([('SPAN',(1,3),(3,3)),('VALIGN',(0,0),(-1,-1),'TOP')]))
    items += [patient_table,p(headings['request'],True),
              p(m['request']),p(headings['result'],True),
              p('Thực hiện lúc: '+fmt_time(m['stamp']))]
    rows = [[p(label),p(text)] for label,text in m['sections']]
    table = Table(rows,colWidths=[115,400])
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.25,colors.HexColor('#B4C6C8')),
                               ('TOPPADDING',(0,0),(-1,-1),1),('BOTTOMPADDING',(0,0),(-1,-1),1)]))
    items.append(table)
    if m['images']:
        from .main import FILES
        pictures = [Image(str(FILES/x['key']),width=230,height=75,kind='proportional') for x in m['images']]
        picture_table = Table([pictures],colWidths=[257.5]*len(pictures))
        picture_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#F0F5F3')),('BOX',(0,0),(-1,-1),.3,colors.HexColor('#B4C6C8'))]))
        items += [p(headings['images'],True),picture_table]
    items.append(p(headings['conclusion'],True))
    left = [p(m['conclusion'])]
    if m['advice']:
        left += [p('Lời dặn của bác sĩ chuyên khoa:',True),p(m['advice'])]
    signature = m.get('signature')
    right = [p(fmt_time(signature['signed_at'] if signature else m['stamp'])),p('BÁC SĨ CHUYÊN KHOA',True)]
    if signature:
        right += [Image(BytesIO(signature['image']),width=100,height=35,kind='proportional')]
    else:
        right += [Spacer(1,35)]
    right.append(p(m['signer_name']))
    if m.get('signature_notice'):
        right.append(p(m['signature_notice']))
    footer = Table([[left,right]],colWidths=[300,215])
    footer.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    items += [footer,p(WATERMARK)]
    return items


def fmt_time(value):
    from datetime import datetime
    from .labels import VN_TZ
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(VN_TZ).strftime('%H:%M, ngày %d/%m/%Y')


def render(m, fmt):
    from .imaging import complete
    complete(m)
    if fmt not in ('pdf','docx'):
        raise HTTPException(422,'Chỉ hỗ trợ PDF hoặc Word')
    if fmt == 'docx':
        return word(m)
    out = BytesIO()
    c = canvas.Canvas(out,pagesize=A4)
    width,height = A4
    for size in (10,9.5,9):
        items = blocks(m,size)
        measured = [(item,item.wrapOn(c,515,height)[1]) for item in items]
        if sum(h for _,h in measured) <= height-70:
            break
    else:
        raise HTTPException(422,'Nội dung quá dài để in đủ trong một trang A4; rút gọn mô tả trước khi in hoặc ký')
    top = height-30
    for item,h in measured:
        item.drawOn(c,40,top-h)
        top -= h
    c.showPage(); c.save()
    return out.getvalue()


def word(m):
    from .forms import LOGO, WATERMARK
    from .main import FILES
    doc = Document()
    headings = section_headings(m)
    section = doc.sections[0]
    section.page_width=Inches(8.2677); section.page_height=Inches(11.6929)
    section.top_margin=section.bottom_margin=Inches(.4)
    section.left_margin=section.right_margin=Inches(.55)
    style=doc.styles['Normal']; style.font.name='Times New Roman'; style.font.size=Pt(9)
    style.paragraph_format.space_after=Pt(1)
    doc.styles['Title'].font.name='Times New Roman'; doc.styles['Title'].font.size=Pt(14)
    header=doc.add_table(rows=1,cols=3)
    if LOGO.exists():
        header.cell(0,0).paragraphs[0].add_run().add_picture(str(LOGO),width=Inches(.6))
    header.cell(0,1).text='\n'.join(m['profile'].get(key) or '' for key in ('governing_body','name','address','phone','email'))
    header.cell(0,2).text=f"MS: {'08' if m['kind']=='xray' else '11'}/BV-02\nSố: {m['number']}\nMã NB: {m['patient']['code']}"
    doc.add_paragraph('PHIẾU CHIẾU/CHỤP X-QUANG' if m['kind']=='xray' else 'PHIẾU SIÊU ÂM','Title')
    doc.add_paragraph(m['template_name']+' · '+m['number'])
    doc.add_paragraph('Họ tên: '+m['patient']['full_name']+' · Mã NB: '+m['patient']['code'])
    doc.add_paragraph('Ngày sinh: '+fmt_date(m['patient']['date_of_birth'])+' · Giới: '+m['patient']['sex'])
    doc.add_paragraph('Địa chỉ: '+format_patient_address(m['patient']))
    doc.add_paragraph('Số BHYT: '+(m['patient'].get('health_insurance_number') or '—'))
    doc.add_paragraph('Chẩn đoán: '+m['diagnosis'])
    if m.get('replaces'):
        doc.add_paragraph('Đính chính '+m['replaces']+' — '+m['reason'])
    if m.get('successor'):
        doc.add_paragraph(m['successor'])
    doc.add_paragraph(headings['request']+': '+m['request'])
    doc.add_paragraph(headings['result']+' · '+fmt_time(m['stamp']))
    table = doc.add_table(rows=0,cols=2)
    table.autofit=False
    table.columns[0].width=Inches(1.5);table.columns[1].width=Inches(5.6)
    for label,text in m['sections']:
        cells=table.add_row().cells; cells[0].text=label; cells[1].text=text
        cells[0].width=Inches(1.5);cells[1].width=Inches(5.6)
    if m['images']:
        doc.add_paragraph(headings['images'])
        cells=doc.add_table(rows=1,cols=2).rows[0].cells
        for cell,item in zip(cells,m['images']):
            from PIL import Image as PILImage
            with PILImage.open(FILES/item['key']) as picture:
                ratio=min(2.2/picture.width,1/picture.height)
                w,h=picture.width*ratio,picture.height*ratio
            cell.paragraphs[0].add_run().add_picture(str(FILES/item['key']),width=Inches(w),height=Inches(h))
    doc.add_paragraph(headings['conclusion']+': '+m['conclusion'])
    if m['advice']:
        doc.add_paragraph('Lời dặn: '+m['advice'])
    p=doc.add_paragraph('BÁC SĨ CHUYÊN KHOA · '+m['signer_name']); p.alignment=2
    if m.get('signature'):
        doc.add_paragraph().add_run().add_picture(BytesIO(m['signature']['image']),width=Inches(1.2))
    if m.get('signature_notice'):
        doc.add_paragraph(m['signature_notice'])
    section.footer.paragraphs[0].text=WATERMARK
    out=BytesIO();doc.save(out)
    return out.getvalue()
