"""Tạo biểu mẫu giả lập từ 9 Word đã được duyệt về giao diện.
Không phát hành đơn thuốc/bệnh án hợp pháp; in bản nháp để kiểm thử dữ liệu.
"""
from __future__ import annotations
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
import re

from docx import Document
from docx.shared import Pt, RGBColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

TEMPLATE_DIR = Path(__file__).resolve().parent / 'templates'
LOGO = Path(__file__).resolve().parent / 'static' / 'images' / 'logo_minh_duc.png'
CLINIC = 'PHÒNG KHÁM ĐA KHOA MINH ĐỨC'
CONTACT = '60 đường Thái Bình, phường Nam Định, tỉnh Ninh Bình  |  083 862 0553 - 0916 232 369'
WATERMARK = 'BẢN THỬ NGHIỆM - KHÔNG DÙNG CHO NGƯỜI BỆNH THẬT'
TEMPLATE_BY_TYPE = {
 'intake':'01_Phieu_tiep_don_A4.docx',
 'visit':'02_Phieu_kham_ngoai_tru_A4.docx',
 'order':'03_Phieu_chi_dinh_CLS_A4.docx',
 'lab':'04_Phieu_ket_qua_xet_nghiem_A4.docx',
 'ultrasound':'05_Phieu_ket_qua_sieu_am_A4.docx',
 'xray':'06_Phieu_ket_qua_Xquang_A4.docx',
 'ecg':'07_Phieu_ket_qua_dien_tim_A4.docx',
 'rx':'08_Don_thuoc_ngoai_tru_A5.docx',
 'followup':'09_Giay_hen_tai_kham_A5.docx',
}
TITLES = {
 'intake':'PHIẾU ĐĂNG KÝ KHÁM BỆNH','visit':'PHIẾU KHÁM BỆNH NGOẠI TRÚ',
 'order':'PHIẾU CHỈ ĐỊNH CẬN LÂM SÀNG','lab':'PHIẾU KẾT QUẢ XÉT NGHIỆM',
 'ultrasound':'PHIẾU KẾT QUẢ SIÊU ÂM','xray':'PHIẾU KẾT QUẢ X-QUANG',
 'ecg':'PHIẾU KẾT QUẢ ĐIỆN TIM','rx':'ĐƠN THUỐC NGOẠI TRÚ – BẢN NHÁP',
 'followup':'GIẤY HẸN TÁI KHÁM',
}

def clean(value, limit=None):
    text = str(value or '').replace('\x00','').strip()
    return text[:limit] if limit is not None else text

def fmt_date(s):
    s=clean(s,40)
    try:return datetime.fromisoformat(s.replace('Z','+00:00')).strftime('%d/%m/%Y')
    except Exception:return s

def doc_text(p,text):
    """Use the first existing run to retain visual styles of original template."""
    if p.runs:
        p.runs[0].text=str(text)
        for run in p.runs[1:]:run.text=''
    else:p.add_run(str(text))

def line(p,label,value):
    if p.text.strip().startswith(label):
        doc_text(p,f'{label}: {clean(value)}')
        return True
    return False

def all_paragraphs(doc):
    for p in doc.paragraphs:yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:yield p

def multiline(doc,header,content,lines=4):
    ps=doc.paragraphs
    found=False
    for i,p in enumerate(ps):
        if p.text.strip().startswith(header):
            found=True
            rows=clean(content).splitlines() if content else ['Chưa nhập']
            # Keep all provided text. Let Word wrap. Do not truncate silently.
            body=' '.join(rows)
            for j in range(i+1,min(i+1+lines,len(ps))):
                if re.fullmatch(r'[.\s]+',ps[j].text.strip()):
                    if j==i+1:doc_text(ps[j],body)
                    else:doc_text(ps[j],'')
            break
    return found

def fill_common(doc,ctx):
    p=ctx['patient'];v=ctx['visit'];
    for table in doc.tables:
        if len(table.rows)>=3 and len(table.columns)==2 and 'Họ và tên:' in table.cell(0,0).text:
            vals={
                (0,0):f"Họ và tên: {p['full_name']}",
                (0,1):f"Ngày sinh: {fmt_date(p['date_of_birth'])}   Giới tính: {p['sex']}",
                (1,0):f"Mã bệnh nhân: {p['code']}",
                (1,1):f"Mã lượt khám: {v['id']}",
                (2,0):f"Điện thoại: {p['phone'] or '—'}",
                (2,1):f"Bác sĩ phụ trách: {ctx['doctor_name']}",
            }
            for (r,c),x in vals.items():doc_text(table.cell(r,c).paragraphs[0],x)
            break

def rx_rows(ctx):
    prescription=ctx.get('rx') or {}
    lines=clean(prescription.get('drug_lines',''),6000).splitlines()
    # For demonstration accepts `name | quantity | dosage` on each line.
    result=[]
    for x in lines:
        if not x.strip():continue
        p=[clean(z) for z in x.split('|')]
        result.append([p[0],p[1] if len(p)>1 else 'Chưa khai báo',p[2] if len(p)>2 else 'Chưa khai báo'])
    return result

def generate_docx(kind, ctx):
    if kind not in TEMPLATE_BY_TYPE:raise ValueError('Biểu mẫu không hợp lệ')
    doc=Document(TEMPLATE_DIR/TEMPLATE_BY_TYPE[kind])
    doc.core_properties.title=TITLES[kind]+' (thử nghiệm)'
    doc.core_properties.subject='Dữ liệu giả lập, không phát hành hồ sơ y tế'
    p=ctx['patient'];v=ctx['visit'];o=ctx.get('order') or {}
    doc_body=doc.paragraphs
    if kind in ('intake','visit','order','lab','ultrasound','xray','ecg'):
        fill_common(doc,ctx)
    if kind=='intake':
        if doc.tables:
            t=doc.tables[0]
            doc_text(t.cell(0,0).paragraphs[0],f"Họ và tên: {p['full_name']}")
            doc_text(t.cell(0,1).paragraphs[0],f"Ngày sinh: {fmt_date(p['date_of_birth'])}")
            doc_text(t.cell(1,0).paragraphs[0],f"Giới tính: {p['sex']}")
            doc_text(t.cell(1,1).paragraphs[0],f"Số điện thoại: {p['phone'] or '—'}")
            doc_text(t.cell(2,0).paragraphs[0],f"Số căn cước / định danh: {p['citizen_id'] or '—'}")
            doc_text(t.cell(2,1).paragraphs[0],f"Mã bệnh nhân: {p['code']}")
            doc_text(t.cell(3,0).paragraphs[0],f"Địa chỉ liên hệ: {p['address'] or '—'}")
        t=doc.tables[1]
        doc_text(t.cell(1,0).paragraphs[0],'Khám dịch vụ (mô phỏng)')
        doc_text(t.cell(1,1).paragraphs[0],ctx['doctor_name'])
        doc_text(t.cell(1,2).paragraphs[0],f"Lượt: {v['id']}")
        doc_text(t.cell(2,0).paragraphs[0],f"Dịch vụ đăng ký: {ctx['service_label']}")
        for x in doc_body:
            if x.text.startswith('Mã phiếu:'):doc_text(x,f"Mã phiếu: MD-TD-{v['id']:06d}     Ngày tiếp đón: {fmt_date(v['created_at'])}")
            if x.text.startswith('Hình thức đến khám:'):doc_text(x,'Hình thức: Trực tiếp hoặc theo lịch hẹn (xem màn hình đặt lịch)')
            if x.text.startswith('Lý do đến khám / yêu cầu'):doc_text(x,'Lý do đến khám / yêu cầu của người bệnh:')
        multiline(doc,'Lý do đến khám / yêu cầu','Nội dung chuyên môn được quản lý tại phiếu khám theo phân quyền.',2)
    elif kind=='visit':
        for x in doc_body:
            if x.text.startswith('Mã phiếu:'):doc_text(x,f"Mã phiếu: MD-KB-{v['id']:06d}    Ngày khám: {fmt_date(v['created_at'])}")
            if x.text.startswith('Mã bệnh nhân:'):doc_text(x,f"Mã bệnh nhân: {p['code']}   Mã lượt khám: {v['id']}")
            for label,key in [('Lý do đến khám','chief_complaint'),('Bệnh sử trước đây, bệnh nền / phẫu thuật','history'),('Chẩn đoán sơ bộ','diagnosis'),('Chẩn đoán xác định','diagnosis'),('Hướng điều trị','treatment'),('Hẹn tái khám','follow_up')]:
                if x.text.strip().startswith(label):line(x,label,v.get(key) or 'Chưa nhập')
        multiline(doc,'Diễn biến bệnh / triệu chứng chính',v.get('chief_complaint'),3)
        if len(doc.tables)>1:
            cells=doc.tables[1]
            raw=clean(v.get('vitals'))
            doc_text(cells.cell(1,0).paragraphs[0],raw or 'Chưa nhập')
        if len(doc.tables)>2:
            for i,o1 in enumerate(ctx.get('orders',[]),1):
                if i>=len(doc.tables[2].rows):doc.tables[2].add_row()
                for j,val in enumerate([o1['name'],str(o1['id']),o1['result_text'] or 'Chưa có'],0):
                    doc_text(doc.tables[2].cell(i,j).paragraphs[0],clean(val))
    elif kind=='order':
        for x in doc_body:
            if x.text.startswith('Mã chỉ định:'):doc_text(x,f"Mã chỉ định: MD-CD-{o['id']:06d}    Ngày lập: {fmt_date(o['created_at'])}")
            if x.text.startswith('Lý do / chẩn đoán lâm sàng:'):doc_text(x,f"Lý do / chẩn đoán lâm sàng: {v['diagnosis'] or 'Chưa nhập'}")
        t=doc.tables[1]
        positions={'lab':1,'ultrasound':2,'xray':3,'ecg':4}
        idx=positions.get(o.get('category'),1)
        doc_text(t.cell(idx,2).paragraphs[0],o['name'])
        doc_text(t.cell(idx,3).paragraphs[0],f"Mã {o['id']} · {o['status']}")
    elif kind in ('lab','ultrasound','xray','ecg'):
        for x in doc_body:
            if x.text.startswith('Mã kết quả:'):doc_text(x,f"Mã kết quả: MD-KQ-{o['id']:06d}   Mã chỉ định: MD-CD-{o['id']:06d}")
            if x.text.startswith('Ngày / giờ') and '...' in x.text:doc_text(x,f"Ngày tạo chỉ định: {fmt_date(o['created_at'])}")
        if kind=='lab':
            # Keep laboratory table structure while inserting free-text result as an explicit note.
            multiline(doc,'Ghi chú xét nghiệm / yếu tố ảnh hưởng đến kết quả',o.get('result_text'),2)
            if len(doc.tables)>1 and len(doc.tables[1].rows)>1:
                t=doc.tables[1]
                for j,val in enumerate(['1',o['name'],clean(o.get('result_text'),180),'—','—'][:len(t.columns)]):
                    doc_text(t.cell(1,j).paragraphs[0],val)
        else:
            for label in ['B. MÔ TẢ HÌNH ẢNH','B. MÔ TẢ SIÊU ÂM','B. THÔNG SỐ VÀ PHÂN TÍCH']:
                if multiline(doc,label,o.get('result_text'),5):break
            # If no exact header found, replace first dotted paragraph in body.
            if not any(o.get('result_text','') in x.text for x in doc_body):
                for x in doc_body:
                    if x.text.strip().startswith('....'):
                        doc_text(x,clean(o.get('result_text')) or 'Chưa nhập')
                        break
    elif kind=='rx':
        rx=ctx.get('rx') or {};rws=rx_rows(ctx)
        for x in doc_body:
            for label,val in [
              ('Mã đơn thuốc',f"MD-RX-{rx['id']:06d} (MÃ NHÁP, CHƯA LIÊN THÔNG)"),
              ('Họ tên',p['full_name']),('Số định danh / căn cước / hộ chiếu (nếu có)',p['citizen_id'] or '—'),
              ('Ngày sinh',f"{fmt_date(p['date_of_birth'])}   Giới tính: {p['sex']}"),
              ('Nơi thường trú / tạm trú / ở hiện tại',p['address'] or '—'),
              ('Chẩn đoán',v.get('diagnosis') or 'Chưa nhập'),
              ('Số điện thoại liên hệ',p.get('phone') or '—')
            ]:
                if x.text.startswith(label+':'):line(x,label,val)
        if len(doc.tables):
            t=doc.tables[0]
            for idx,(name,qty,dosage) in enumerate(rws[:5],1):
                for j,val in enumerate([str(idx),name,qty,dosage]):doc_text(t.cell(idx,j).paragraphs[0],val)
            if len(rws)>5:
                # Never silently drop lines: add more table rows; page may extend to A5 page 2.
                for idx,(name,qty,dosage) in enumerate(rws[5:],6):
                    c=t.add_row().cells
                    for j,val in enumerate([str(idx),name,qty,dosage]):doc_text(c[j].paragraphs[0],val)
        for x in doc_body:
            if x.text.startswith('Lời dặn ('):doc_text(x,'Lời dặn: '+clean(rx.get('instructions')))
            if x.text.startswith('Ngày ......'):doc_text(x,f"Ngày {fmt_date(rx.get('created_at'))}")
    elif kind=='followup':
        for x in doc_body:
            for label,val in [('Mã hẹn',f"MD-HEN-{v['id']:06d}"),('Họ và tên người bệnh',p['full_name']),
               ('Ngày sinh',f"{fmt_date(p['date_of_birth'])}    Mã bệnh nhân: {p['code']}"),
               ('Điện thoại liên hệ',p['phone'] or '—'),
               ('Ngày khám gần nhất',f"{fmt_date(v['created_at'])}    Mã lượt khám: {v['id']}"),
               ('Ngày hẹn',v.get('follow_up') or (ctx.get('rx') or {}).get('follow_up') or 'Chưa ghi ngày'),
               ('Bác sĩ hẹn khám',ctx['doctor_name']),
               ('Chuyên khoa','Theo bác sĩ phụ trách')]:
                if x.text.startswith(label+':'):line(x,label,val)
        multiline(doc,'Lý do / mục đích tái khám','Theo kết luận bác sĩ, xem phiếu khám',2)
    # Visible draft label on every generated document, including rx.
    footer=doc.sections[0].footer
    ptag=footer.add_paragraph(WATERMARK)
    ptag.style='Normal';ptag.alignment=1
    for run in ptag.runs:
        run.font.size=Pt(7);run.font.bold=True;run.font.color.rgb=RGBColor(168,35,24)
    bio=BytesIO();doc.save(bio);return bio.getvalue()

_FONT=None

def font_name():
    global _FONT
    if _FONT:return _FONT
    paths=[
      Path('C:/Windows/Fonts/arial.ttf'),Path('C:/Windows/Fonts/Arial.ttf'),
      Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
      Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf')
    ]
    for p in paths:
        if p.exists():
            pdfmetrics.registerFont(TTFont('ClinicVietnamese',str(p)));_FONT='ClinicVietnamese';return _FONT
    raise RuntimeError('Không tìm thấy phông Unicode hỗ trợ tiếng Việt để tạo PDF')

def pdf_safe(s):return xml_escape(clean(s)).replace('\n','<br/>')

def generate_pdf(kind,ctx):
    if kind not in TEMPLATE_BY_TYPE:raise ValueError('Biểu mẫu không hợp lệ')
    p=ctx['patient'];v=ctx['visit'];o=ctx.get('order') or {};r=ctx.get('rx') or {}
    font=font_name();size=A5 if kind in ('rx','followup') else A4
    buf=BytesIO();pdf=SimpleDocTemplate(buf,pagesize=size,rightMargin=39,leftMargin=39,topMargin=91,bottomMargin=54,
                                      title=TITLES[kind]+' – BẢN NHÁP',author=CLINIC)
    styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='VnBody',fontName=font,fontSize=9.2,leading=13,spaceAfter=7))
    styles.add(ParagraphStyle(name='VnTitle',fontName=font,fontSize=12 if size==A5 else 14,leading=19,spaceAfter=13,alignment=1,textColor=colors.HexColor('#087F7A')))
    styles.add(ParagraphStyle(name='VnHeading',fontName=font,fontSize=10,leading=14,spaceBefore=11,spaceAfter=7,textColor=colors.HexColor('#17665F')))
    story=[]
    def add(label,val):story.append(Paragraph(f'<b>{pdf_safe(label)}:</b> {pdf_safe(val or "—")}',styles['VnBody']))
    def heading(text):story.append(Paragraph(pdf_safe(text),styles['VnHeading']))
    story.append(Paragraph(pdf_safe(TITLES[kind]),styles['VnTitle']))
    add('Mã bệnh nhân',p['code']);add('Họ tên người bệnh',p['full_name']);add('Ngày sinh - Giới tính',f"{fmt_date(p['date_of_birth'])} – {p['sex']}")
    add('Mã lượt khám',v['id'])
    if kind in ('intake','visit','order','rx','followup'):
        add('Bác sĩ',ctx['doctor_name'])
    if kind=='intake':
        add('Địa chỉ',p.get('address'));add('Điện thoại',p.get('phone'))
        add('Ngày tiếp đón',fmt_date(v['created_at']));add('Dịch vụ',ctx['service_label'])
    if kind=='visit':
        for label,key in [('Lý do khám','chief_complaint'),('Bệnh sử','history'),('Sinh hiệu','vitals'),('Chẩn đoán','diagnosis'),('Điều trị','treatment'),('Hẹn tái khám','follow_up')]:add(label,v.get(key))
        if ctx.get('orders'):
            heading('Chỉ định và tóm tắt kết quả')
            for item in ctx['orders']:add(item['name'],item['result_text'] or 'Chưa có kết quả')
    if kind=='order':
        add('Mã chỉ định',o.get('id'));add('Ngày chỉ định',fmt_date(o.get('created_at')))
        add('Chẩn đoán lâm sàng',v.get('diagnosis'));add('Dịch vụ yêu cầu',o.get('name'));add('Trạng thái',o.get('status'))
    if kind in ('lab','ultrasound','xray','ecg'):
        add('Mã chỉ định',o.get('id'));add('Dịch vụ',o.get('name'));add('Ngày chỉ định',fmt_date(o.get('created_at')))
        heading('Nội dung kết quả mô phỏng')
        add('Kết quả',o.get('result_text'));add('Trạng thái',o.get('status'))
        if o.get('file_name'):add('Tệp đính kèm',o['file_name'])
    if kind=='rx':
        add('Mã đơn nháp',r.get('id'));add('Số định danh (nếu có)',p.get('citizen_id'))
        add('Địa chỉ',p.get('address'));add('Chẩn đoán',v.get('diagnosis'))
        heading('Danh sách thuốc - chưa có hiệu lực kê đơn')
        rows=[[Paragraph('Tên thuốc (giả lập)',styles['VnBody']),Paragraph('SL',styles['VnBody']),Paragraph('Cách dùng',styles['VnBody'])]]
        for name,qty,dosage in rx_rows(ctx):rows.append([Paragraph(pdf_safe(name),styles['VnBody']),Paragraph(pdf_safe(qty),styles['VnBody']),Paragraph(pdf_safe(dosage),styles['VnBody'])])
        t=Table(rows,colWidths=([147,37,105] if size==A5 else [240,50,200]),repeatRows=1,hAlign='LEFT',splitInRow=1)
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#B4C6C8')),('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E7F7F4')),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]))
        story.append(t);story.append(Spacer(1,10));add('Lời dặn',r.get('instructions'));add('Hẹn tái khám',r.get('follow_up'))
    if kind=='followup':
        add('Ngày khám gần nhất',fmt_date(v.get('created_at')));add('Ngày hẹn theo chỉ định',v.get('follow_up') or r.get('follow_up') or 'Chưa ghi');add('Điện thoại',p.get('phone'))
        add('Lưu ý','Liên hệ cơ sở y tế khi có diễn biến bất thường; không chờ đến lịch hẹn.')
    story.append(Spacer(1,20))
    story.append(Paragraph('Người ghi nhận / bác sĩ (chưa ký số, bản thử nghiệm)',styles['VnBody']))
    def page_header(c,d):
        w,h=size
        c.saveState()
        if LOGO.exists():
            c.drawImage(ImageReader(str(LOGO)),39,h-67,width=72,height=43,preserveAspectRatio=True,mask='auto')
        c.setFont(font,9.2);c.setFillColor(colors.HexColor('#087F7A'));c.drawString(115,h-37,CLINIC)
        c.setFont(font,7);c.setFillColor(colors.black);c.drawString(115,h-51,'60 đường Thái Bình, P. Nam Định, Ninh Bình')
        c.setStrokeColor(colors.HexColor('#087F7A'));c.line(39,h-73,w-39,h-73)
        c.setFont(font,7);c.setFillColor(colors.HexColor('#B42318'))
        c.drawCentredString(w/2,33,WATERMARK)
        c.setFont(font,7);c.setFillColor(colors.grey);c.drawRightString(w-39,19,f'Trang {d.page}')
        c.restoreState()
    pdf.build(story,onFirstPage=page_header,onLaterPages=page_header)
    return buf.getvalue()
