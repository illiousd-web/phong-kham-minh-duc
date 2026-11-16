"""Warehouse XLSX/PDF renderers consume only the caller's projected data."""
from io import BytesIO
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .labels import show_day
from .print_forms import BOLD, FONT, p, register_fonts

WORDS = ('không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín')


def amount_words(value):
    if value is None:
        return 'chưa có giá'
    if value == 0:
        return 'Không đồng'

    def group(n, full):
        h, rem = divmod(n, 100)
        t, u = divmod(rem, 10)
        result = [WORDS[h], 'trăm'] if h or full else []
        if t > 1:
            result += [WORDS[t], 'mươi']
        elif t == 1:
            result += ['mười']
        elif u and result:
            result += ['lẻ']
        if u:
            result += ['mốt' if u == 1 and t > 1 else 'lăm' if u == 5 and t else WORDS[u]]
        return ' '.join(result)

    chunks, n = [], int(value)
    while n:
        chunks.append(n % 1000)
        n //= 1000
    parts = []
    for i in range(len(chunks) - 1, -1, -1):
        if chunks[i]:
            suffix = ('', 'nghìn', 'triệu')[i % 3] + (' tỷ' * (i // 3))
            parts.append((group(chunks[i], bool(parts)) + ' ' + suffix).strip())
    return (' '.join(parts) + ' đồng').capitalize()


def monetary(value):
    return 'chưa có giá' if value is None else f'{Decimal(str(value)):,.0f}'.replace(',', '.') + ' đ'


def xlsx(columns, rows, title):
    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append([label for _, label, _ in columns])
    for row in rows:
        sheet.append([('chưa có giá' if row[key] is None else row[key]) for key, _, _ in columns])
    sheet.freeze_panes = 'B2'
    sheet.auto_filter.ref = sheet.dimensions
    for index, (_, _, kind) in enumerate(columns, 1):
        from openpyxl.utils import get_column_letter
        sheet.column_dimensions[get_column_letter(index)].width = 42 if index == 1 else 23
        for cell in list(sheet.columns)[index - 1]:
            cell.alignment = Alignment(horizontal='right' if kind == 'r' else 'center' if kind == 'c' else 'left')
            if cell.row == 1:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='008249')
            elif kind == 'r' and isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0'
            elif isinstance(cell.value, str) and cell.value.startswith(('=', '+', '-', '@')):
                # User-supplied names/invoice strings are always text, never formulas.
                cell.data_type = 's'
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def stock_xlsx(rows):
    cols = [('name', 'Thuốc', ''), ('lot_number', 'Số lô', ''), ('expiry_date', 'Hạn dùng', 'c'), ('quantity', 'Tồn', 'r')]
    if rows and 'unit_cost' in rows[0]:
        cols.append(('unit_cost', 'Giá nhập', 'r'))
    cols.append(('sale_price', 'Giá bán', 'r'))
    if rows and 'inventory_value' in rows[0]:
        cols.append(('inventory_value', 'Giá trị tồn', 'r'))
    data = [dict(r, expiry_date=show_day(r['expiry_date'])) for r in rows]
    return xlsx(cols, data, 'Tồn theo lô')


def report_columns(data):
    cols = [('name', 'Thuốc', ''), ('opening', 'Tồn đầu', 'r'), ('received', 'Nhập', 'r'), ('issued', 'Xuất', 'r'), ('closing', 'Tồn cuối', 'r')]
    if data['rows'] and 'cogs_sold' in data['rows'][0]:
        cols += [('cogs_sold', 'Giá vốn bán', 'r'), ('cost_internal', 'Xuất nội bộ', 'r'),
                 ('cost_supplier_return', 'Trả NCC', 'r'), ('cost_expired', 'Hủy hết hạn', 'r')]
    cols += [('returns_revenue', 'Trả lại (giảm doanh thu)', 'r'), ('revenue', 'Doanh thu thuần', 'r')]
    if data['rows'] and 'gross_profit' in data['rows'][0]:
        cols.append(('gross_profit', 'Lãi gộp', 'r'))
    return cols


def pdf_setup(profile, title):
    register_fonts()
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=10*mm, bottomMargin=12*mm, title=title)
    style = ParagraphStyle('stock', fontName=FONT, fontSize=9, leading=14)
    heading = ParagraphStyle('stock-heading', parent=style, fontName=BOLD, fontSize=16, leading=22, alignment=TA_CENTER)
    story = [Paragraph('Đơn vị: ' + p(profile['name'] or 'Chưa khai tên đơn vị'), style),
             Paragraph('Địa chỉ: ' + p(profile['address'] or 'Chưa khai địa chỉ'), style),
             Paragraph('Bộ phận: Kho dược', style), Paragraph(title, heading),
             Paragraph('BẢN THỬ NGHIỆM — CHƯA CÓ GIÁ TRỊ KẾ TOÁN', style)]
    return output, doc, style, story


def pdf_table(headers, rows, widths, style, right=(), *, warehouse=False):
    header_rows = [headers]
    if warehouse:
        # 01/02-VT: shared quantity heading, requested/actual subcolumns, A..F/1..4.
        first = list(headers)
        first[6:8] = ['Số lượng', '']
        second = [''] * len(headers)
        second[6:8] = headers[6:8]
        header_rows = [first, second, ['A', 'B', 'C', 'D', 'E', 'F', '1', '2'] + (['3', '4'] if len(headers) == 10 else [])]
    cells = [[Paragraph(p(v), style) for v in row] for row in header_rows + rows]
    table = Table(cells, colWidths=widths, repeatRows=len(header_rows), hAlign='LEFT')
    commands = [('GRID', (0, 0), (-1, -1), .4, colors.grey), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, len(header_rows)-1), colors.HexColor('#F2F5F3'))]
    if warehouse:
        commands.append(('SPAN', (6, 0), (7, 0)))
        for col in list(range(6)) + list(range(8, len(headers))):
            commands.append(('SPAN', (col, 0), (col, 1)))
    for column in right:
        for row in range(len(header_rows), len(cells)):
            cells[row][column].style = ParagraphStyle('right', parent=style, alignment=2)
    table.setStyle(TableStyle(commands))
    return table


def document_pdf(kind, data, profile):
    receipt = kind == 'receipts'
    title = 'PHIẾU NHẬP KHO' if receipt else 'PHIẾU XUẤT KHO'
    output, doc, style, story = pdf_setup(profile, title)
    heading = ParagraphStyle('stock-document-title', parent=style, fontName=BOLD, fontSize=16, leading=22, alignment=TA_CENTER)
    centered = ParagraphStyle('stock-document-date', parent=style, alignment=TA_CENTER)
    identity = '<b>Đơn vị:</b> ' + p(profile['name'] or 'Chưa khai tên đơn vị') + '<br/>Địa chỉ: ' + p(profile['address'] or 'Chưa khai địa chỉ') + '<br/>Bộ phận: Kho dược'
    model = '<b>Mẫu số ' + ('01' if receipt else '02') + ' - VT</b><br/>(Theo biểu mẫu trong phần mềm — bản thử nghiệm)'
    story = [Table([[Paragraph(identity, style), Paragraph(model, centered)]], colWidths=[doc.width*.6, doc.width*.4]),
             Spacer(1, 5*mm), Paragraph(title, heading),
             Paragraph('Ngày ' + show_day(data['created_at']), centered),
             Table([[Paragraph('Số: ' + p(data['document_no']), centered),
                     Paragraph('Nợ: ....................................<br/>Có: ....................................', style)]], colWidths=[doc.width*.7, doc.width*.3]),
             Paragraph('BẢN THỬ NGHIỆM — CHƯA CÓ GIÁ TRỊ KẾ TOÁN', style)]
    if receipt:
        story += [Paragraph('Họ và tên người giao: ....................................', style),
                  Paragraph('Theo: Hóa đơn số ' + p(data['invoice_no']) + ' ngày ' + show_day(data['invoice_date']) + ' của ' + p(data['supplier']), style),
                  Paragraph('Nhập tại kho: Kho dược', style)]
    else:
        story += [Paragraph('Họ và tên người nhận hàng: ' + p(data['recipient']), style),
                  Paragraph('Lý do xuất kho: ' + p(data['purpose']), style), Paragraph('Xuất tại kho: Kho dược', style)]
    headers = ['STT', 'Tên, nhãn hiệu, quy cách, phẩm chất vật tư, dụng cụ, sản phẩm, hàng hóa', 'Mã số', 'Số lô', 'Hạn dùng', 'ĐVT',
               'Theo chứng từ' if receipt else 'Yêu cầu', 'Thực nhập' if receipt else 'Thực xuất']
    widths = [10, 64, 21, 26, 25, 17, 20, 20]
    financial = 'total_amount' in data
    if financial:
        headers += ['Đơn giá', 'Thành tiền']
        widths += [28, 42]
    else:
        widths[1] += 70
    rows = []
    for index, item in enumerate(data['items'], 1):
        row = [index, item['name'], item['code'] or '', item['lot_number'], show_day(item['expiry_date']), item['base_unit'], item['quantity'], item['quantity']]
        if financial:
            row += [monetary(item['unit_cost']), monetary(item['total_amount'])]
        rows.append(row)
    while len(rows) < 4:
        rows.append([''] * len(headers))
    if financial:
        rows.append(['', 'Cộng', 'x', 'x', 'x', 'x', 'x', 'x', 'x', monetary(data['total_amount'])])
    story += [Spacer(1, 4*mm), pdf_table(headers, rows, [v*mm for v in widths], style, range(6, len(headers)), warehouse=True), Spacer(1, 4*mm)]
    if financial:
        story.append(Paragraph('Tổng số tiền (viết bằng chữ): ' + p(amount_words(data['total_amount'])), style))
        if receipt:
            story.append(Paragraph('Đơn giá trước VAT; thành tiền gồm VAT theo từng lô: ' + p(', '.join(str(i.get('vat_rate') or 0) + '%' for i in data['items'])), style))
    story.append(Paragraph('Số chứng từ gốc kèm theo: ....................................', style))
    names = ['Người lập phiếu', 'Người giao hàng' if receipt else 'Người nhận hàng', 'Thủ kho', 'Kế toán trưởng']
    if not receipt:
        names.append('Giám đốc')
    story += [Paragraph('Ngày …… tháng …… năm 20……', ParagraphStyle('signed-date', parent=style, alignment=2)),
              Spacer(1, 7*mm), Table([[Paragraph(p(n) + '<br/>(Ký, họ tên)', centered) for n in names]], colWidths=[doc.width/len(names)]*len(names)),
              Spacer(1, 12*mm), Paragraph('Người lập phiếu: ' + p(data['creator']), style)]
    doc.build(story)
    return output.getvalue()


def report_export(data, fmt, profile):
    cols = report_columns(data)
    if fmt == 'xlsx':
        return xlsx(cols, data['rows'], 'Xuất nhập tồn')
    output, doc, style, story = pdf_setup(profile, 'BÁO CÁO XUẤT NHẬP TỒN')
    story += [Paragraph('Từ ' + show_day(data['date_from']) + ' đến ' + show_day(data['date_to']), style), Spacer(1, 4*mm)]
    widths = [doc.width*.28] + [doc.width*.72/(len(cols)-1)]*(len(cols)-1)
    rows = [[('chưa có giá' if row[key] is None else row[key]) for key, _, _ in cols] for row in data['rows']]
    story.append(pdf_table([label for _, label, _ in cols], rows, widths, style, range(1, len(cols))))
    doc.build(story)
    return output.getvalue()
