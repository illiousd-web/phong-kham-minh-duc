"""Vietnamese PDF documents for the LOCAL DEMONSTRATION only.

All output contains a prominent non-clinical watermark. Templates are inspired
by clinic-supplied Word layouts; they are not regulatory-valid prescriptions.
"""
from __future__ import annotations
from xml.sax.saxutils import escape
from io import BytesIO
from pathlib import Path
from datetime import datetime
from .labels import vi, CATEGORY, METHOD, show_day, lab_rows

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
LOGO = ASSETS / 'logo' / 'logo_minh_duc.png'
FONT_PATHS = (
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('C:/Windows/Fonts/arial.ttf','C:/Windows/Fonts/arialbd.ttf'),
    ('/Library/Fonts/Arial.ttf','/Library/Fonts/Arial Bold.ttf'),
)
FONT='MinhDucRegular'; BOLD='MinhDucBold'
_registered=False


def register_fonts():
    global _registered
    if _registered: return
    for regular,bold in FONT_PATHS:
        if Path(regular).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont(FONT,regular))
            pdfmetrics.registerFont(TTFont(BOLD,bold))
            pdfmetrics.registerFontFamily(FONT,normal=FONT,bold=BOLD)
            _registered=True
            return
    raise RuntimeError('Không tìm thấy font Unicode hỗ trợ tiếng Việt để tạo PDF (cần DejaVu Sans hoặc Arial).')


def p(value):
    return escape(str(value if value is not None else '—')).replace('\n','<br/>')


def pdf_document(kind:str, d:dict)->bytes:
    register_fonts()
    small=kind in ('rx','follow_up')
    pagesize=A5 if small else A4
    doc_id=str(d.get('code',d.get('id','')))
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=pagesize,topMargin=20*mm,bottomMargin=17*mm,
                          leftMargin=13*mm,rightMargin=13*mm,title='Minh Đức - '+kind+' - bản in thử')
    width=pagesize[0]-26*mm
    primary=colors.HexColor('#087F7A')
    ink=colors.HexColor('#18323C')
    subtitle=ParagraphStyle('sub',fontName=FONT,fontSize=7.5,leading=11,textColor=ink)
    body=ParagraphStyle('body',fontName=FONT,fontSize=9 if small else 9.5,leading=15 if small else 16,textColor=ink,spaceAfter=4)
    title=ParagraphStyle('title',fontName=BOLD,fontSize=13 if small else 15,leading=20,alignment=TA_CENTER,textColor=primary,spaceAfter=9)
    h=ParagraphStyle('h',fontName=BOLD,fontSize=9.2,leading=14,textColor=primary,spaceBefore=9,spaceAfter=4)
    note=ParagraphStyle('note',fontName=BOLD,fontSize=7.3,leading=11,textColor=colors.HexColor('#9E271A'),alignment=TA_CENTER)
    story=[]
    from reportlab.platypus import Image
    header_text=Paragraph('<b>PHÒNG KHÁM ĐA KHOA MINH ĐỨC</b><br/>60 đường Thái Bình, P. Nam Định, tỉnh Ninh Bình<br/>083 862 0553 – 0916 232 369<br/>pkdkminhduc.com.vn',subtitle)
    if LOGO.exists():
        logo=Image(str(LOGO),width=38*mm if not small else 30*mm,height=25*mm if not small else 19*mm)
        head=Table([[logo,header_text]],colWidths=[41*mm if not small else 33*mm,width-(41*mm if not small else 33*mm)])
        head.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,-1),.8,primary)]))
        story.append(head)
    else: story.append(header_text)
    story.append(Spacer(1,5*mm))
    titles={'intake':'PHIẾU TIẾP ĐÓN BỆNH NHÂN','clinical':'PHIẾU KHÁM BỆNH NGOẠI TRÚ',
            'order':'PHIẾU CHỈ ĐỊNH CẬN LÂM SÀNG','result':'PHIẾU KẾT QUẢ CẬN LÂM SÀNG',
            'rx':'ĐƠN THUỐC NGOẠI TRÚ','follow_up':'GIẤY HẸN TÁI KHÁM','receipt':'PHIẾU THU'}
    story.append(Paragraph(titles[kind],title))
    story.append(Paragraph(f'Mã tham chiếu: {p(doc_id)} · Ngày in: {datetime.now().strftime("%d/%m/%Y %H:%M")}',subtitle))
    story.append(Spacer(1,3*mm))
    story.append(Paragraph('BẢN THỬ NGHIỆM — DỮ LIỆU MÔ PHỎNG — KHÔNG CÓ GIÁ TRỊ Y KHOA / KẾ TOÁN',note))
    story.append(Spacer(1,4*mm))
    def line(label,v):story.append(Paragraph('<b>'+p(label)+':</b> '+p(v),body))
    def section(t,v):
        story.append(Paragraph(p(t),h))
        story.append(Paragraph(p(v or 'Chưa có thông tin'),body))
    line('Họ và tên',d.get('patient_name',''))
    line('Mã bệnh nhân',d.get('patient_code',''))
    if d.get('date_of_birth'):line('Ngày sinh',show_day(d['date_of_birth']))
    if d.get('sex'):line('Giới tính',d['sex'])
    if kind in ('intake','clinical','rx','follow_up') and d.get('phone'):line('Điện thoại',d['phone'])
    if kind in ('intake','clinical','rx','follow_up') and d.get('address'):line('Địa chỉ',d['address'])
    if kind=='intake':
        line('Bác sĩ được phân công',d.get('doctor_name',''))
        line('Thời gian tiếp nhận',show_day(d.get('created_at','')))
        line('Tình trạng',vi(d.get('status')))
    elif kind=='clinical':
        line('Bác sĩ phụ trách',d.get('doctor_name',''))
        section('Lý do khám, triệu chứng',d.get('chief_complaint',''))
        section('Bệnh sử, tiền sử',d.get('history',''))
        section('Dấu hiệu sinh tồn',d.get('vitals',''))
        section('Chẩn đoán',d.get('diagnosis',''))
        section('Hướng điều trị',d.get('treatment',''))
        line('Hẹn tái khám',show_day(d.get('follow_up')))
    elif kind=='order':
        line('Bác sĩ chỉ định',d.get('doctor_name',''))
        line('Loại dịch vụ',vi(d.get('category'),CATEGORY))
        line('Tên chỉ định',d.get('name',''))
        line('Ngày chỉ định',show_day(d.get('created_at','')))
        line('Trạng thái',vi(d.get('status')))
    elif kind=='result':
        line('Dịch vụ',d.get('name',''))
        rows,notes,conclusion=lab_rows(d.get('result_text',''))
        if rows:
            story.append(Paragraph('Kết quả',h))
            cell=ParagraphStyle('cell',parent=body,spaceAfter=0)
            data=[[Paragraph('<b>'+x+'</b>',cell) for x in ('Chỉ số','Kết quả','Đơn vị','Tham chiếu','Đánh dấu')]]
            data+=[[Paragraph(p(x),cell) for x in r] for r in rows]
            tbl=Table(data,colWidths=[width*.34,width*.16,width*.14,width*.24,width*.12],repeatRows=1)
            tbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#B4C6C8')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E7F7F4')),('VALIGN',(0,0),(-1,-1),'TOP')]))
            story.append(tbl)
        if notes:section('Mô tả / ghi chú' if rows else 'Kết quả','\n'.join(notes))
        section('Kết luận',conclusion or 'Chưa ghi kết luận')
        line('Trạng thái',vi(d.get('status')))
        line('Người thực hiện',d.get('result_by_name') or '—')
        line('Người duyệt',d.get('approved_name',''))
        line('Thời điểm duyệt',show_day(d.get('approved_at','')))
    elif kind=='rx':
        line('Bác sĩ lập đơn nháp',d.get('doctor_name',''))
        line('Chẩn đoán',d.get('diagnosis',''))
        section('Nội dung thuốc mô phỏng',d.get('drug_lines',''))
        section('Hướng dẫn ghi chú',d.get('instructions',''))
        line('Hẹn tái khám',show_day(d.get('follow_up')))
    elif kind=='follow_up':
        line('Bác sĩ',d.get('doctor_name',''))
        line('Chẩn đoán',d.get('diagnosis',''))
        line('Lịch hẹn dự kiến',show_day(d.get('follow_up')) if d.get('follow_up') else 'Chưa chỉ định')
        section('Lưu ý', 'Giấy hẹn thử nghiệm; thời điểm thực tế do cơ sở khám chữa bệnh xác nhận.')
    elif kind=='receipt':
        line('Mã lượt khám',d.get('visit_id',''))
        line('Số tiền thu',f"{int(d.get('amount',0)):,} đồng".replace(',','.'))
        line('Hình thức',vi(d.get('method'),METHOD))
        line('Người thu',d.get('cashier_name',''))
        line('Thời gian ghi nhận',show_day(d.get('created_at','')))
        line('Mã tham chiếu giao dịch',d.get('external_ref','Không có'))
        section('Lưu ý', 'Phiếu thu demo không thay thế hóa đơn điện tử hợp lệ.')
    if kind=='clinical':
        for a in d.get('addenda',[]):
            section('Phụ lục đã duyệt #'+str(a['id']),a['reason']+'\n'+a['content']+'\n'+str(a['reviewed_at']))
    story.append(Spacer(1,12*mm))
    if kind=='result':
        sign=Table([[Paragraph('<b>NGƯỜI THỰC HIỆN</b><br/>(chưa ký số)<br/><br/><br/>'+p(d.get('result_by_name') or ''),subtitle),
                     Paragraph('<b>NGƯỜI DUYỆT KẾT QUẢ</b><br/>(chưa ký số)<br/><br/><br/>'+p(d.get('approved_name') or ''),subtitle)]],
                   colWidths=[width/2,width/2])
        sign.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'TOP')]))
        story.append(sign)
    else:
        story.append(Paragraph('Người lập / Người xác nhận (chỉ để minh họa, chưa ký số)',subtitle))
    def page(canvas, doc):
        canvas.saveState()
        w,ht=pagesize
        canvas.setFont(BOLD,34 if not small else 23)
        canvas.setFillColor(colors.HexColor('#E7EDEF'))
        canvas.translate(w/2,ht/2)
        canvas.rotate(35)
        canvas.drawCentredString(0,0,'BAN THU NGHIEM')
        canvas.restoreState()
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#D8E5E7'))
        canvas.line(13*mm,14*mm,w-13*mm,14*mm)
        canvas.setFont(FONT,7.0)
        canvas.setFillColor(colors.HexColor('#697B83'))
        canvas.drawString(13*mm,10*mm,'Phòng khám đa khoa Minh Đức · Không dùng cho hồ sơ thật')
        canvas.drawRightString(w-13*mm,10*mm,f'Trang {doc.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return buf.getvalue()
