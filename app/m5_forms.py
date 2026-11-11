"""A4 laboratory frame, one ordered content model for Word and PDF."""
from io import BytesIO
from docx import Document
from docx.shared import Pt,RGBColor
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from .forms import TEMPLATE_DIR,doc_text,font_name,pdf_safe,fmt_date
from .m5 import GROUPS
from .labels import VN_TZ
from datetime import datetime


def stamp(v):
    return datetime.fromisoformat(v).astimezone(VN_TZ).strftime('%d/%m/%Y %H:%M') if v else '—'


def content(p,group):
    person=p['patient'];head=[('Mã kết quả',f"XN-{p['id']}"),('Mã chỉ định',str(p['order_id'])),('Nhóm xét nghiệm',GROUPS[group])]
    if p['status']!='approved':head.append(('', 'NHÁP – CHƯA DUYỆT'))
    if p.get('superseded_by'):head.append(('', 'ĐÃ ĐƯỢC THAY THẾ BỞI PHIẾU #'+str(p['superseded_by'])))
    if p['replaces_id']:head.append(('', 'BẢN ĐIỀU CHỈNH, thay thế phiếu XN-'+str(p['replaces_id'])))
    head += [('Họ và tên',person['full_name']),('Mã người bệnh',person['code']),('Mã lượt khám',str(p['visit_id'])),('Điện thoại',person['phone'] or '—'),('Bác sĩ phụ trách',p['ordering_doctor_name']),('Ngày sinh',fmt_date(person['date_of_birth'])),('Giới tính',person['sex']),('Địa chỉ',person['address']),('Lấy mẫu',stamp(p['sample_at']))]
    items=[x for x in p['items'] if x['group_name']==group]
    rows=[[x['name']+(' ('+x['abbreviation']+')' if x['abbreviation'] else '')+('\nGhi chú: '+x['note'] if x['note'] else ''),x.get('display_value',x['value']),x['flag'],x['reference_text'],x['unit']] for x in items]
    tail=[('Nhận xét chung',p['comment'] or '—'),('Thời điểm có kết quả',stamp(p['result_at'])),('Người thực hiện',p['performer_name'] or '—'),('Người duyệt',p['approver_name'] or '—'),('Thời điểm duyệt',stamp(p['approved_at']))]
    if p['replaces_id']:tail.append(('Lý do điều chỉnh',p['adjustment_reason']))
    return head,rows,tail


def render(p,group,fmt):
    head,rows,tail=content(p,group);out=BytesIO();headers=['Tên chỉ số','Kết quả','Cờ','Khoảng tham chiếu','Đơn vị']
    text=lambda k,v:(k+': ' if k else '')+str(v or '—')
    if fmt=='docx':
        doc=Document(TEMPLATE_DIR/'04_Phieu_ket_qua_xet_nghiem_A4.docx')
        # Preserve the approved A4 page setup, header/footer/logo. Fill patient area
        # before the result table, remove the old placeholder body (not header/footer).
        body=doc._element.body
        for child in list(body):
            if child.tag.endswith('}sectPr'):continue
            body.remove(child)
        doc.styles['Normal'].font.name='Arial';doc.styles['Normal'].font.size=Pt(10)
        doc.add_heading('PHIẾU KẾT QUẢ XÉT NGHIỆM – '+GROUPS[group].upper(),0)
        for k,v in head:doc.add_paragraph(text(k,v))
        table=doc.add_table(rows=1,cols=5);table.style='Table Grid'
        for c,v in zip(table.rows[0].cells,headers):c.text=v
        from docx.oxml import OxmlElement
        repeat=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(repeat)
        for row in rows:
            cells=table.add_row().cells
            for c,v in zip(cells,row):
                c.text=str(v)
                if row[2]:
                    for run in c.paragraphs[0].runs:run.font.bold=True;run.font.color.rgb=RGBColor(180,0,0)
        for k,v in tail:doc.add_paragraph(text(k,v))
        doc.save(out)
    else:
        style=ParagraphStyle('M5',fontName=font_name(),fontSize=9,leading=12,spaceAfter=5)
        def par(v):return Paragraph(pdf_safe(v).replace('\n','<br/>'),style)
        template=Document(TEMPLATE_DIR/'04_Phieu_ket_qua_xet_nghiem_A4.docx')
        header=template.sections[0].header;footer=template.sections[0].footer
        frame_head=[x.text for x in header.paragraphs if x.text.strip()]+[c.text for t in header.tables for r in t.rows for c in r.cells if c.text.strip()]
        frame_foot=[x.text for x in footer.paragraphs if x.text.strip()]
        story=[par(x) for x in frame_head]+[par('PHIẾU KẾT QUẢ XÉT NGHIỆM – '+GROUPS[group].upper())]+[par(text(k,v)) for k,v in head]
        table=Table([[par(v) for v in row] for row in [headers]+rows],colWidths=[180,65,55,145,A4[0]-505],repeatRows=1,splitInRow=1)
        commands=[('GRID',(0,0),(-1,-1),.4,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')]
        for i,row in enumerate(rows,1):
            if row[2]:commands.append(('BACKGROUND',(0,i),(-1,i),colors.HexColor('#ffe6e6')))
        table.setStyle(TableStyle(commands));story += [table,Spacer(1,12)]+[par(text(k,v)) for k,v in tail]+[par(x) for x in frame_foot]
        SimpleDocTemplate(out,pagesize=A4,leftMargin=30,rightMargin=30,topMargin=30,bottomMargin=30).build(story)
    return out.getvalue()
