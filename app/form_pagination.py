"""Print pagination shared by S2c and the clinical form; never resize content."""
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Flowable, Table, TableStyle
from docx.enum.section import WD_HEADER_FOOTER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


class NumberedCanvas(Canvas):
    """Replay completed pages to stamp their final x/y count, including images."""
    def __init__(self, *args, counter_font='Helvetica', **kwargs):
        super().__init__(*args, **kwargs)
        self._page_states = []
        self._counter_font = counter_font

    def showPage(self):
        self._page_states.append({k: v for k, v in self.__dict__.items() if k != '_page_states'})
        self._startPage()

    def save(self):
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self.saveState()
            self.setFont(self._counter_font, 7)
            self.setFillColorRGB(.25, .25, .25)
            self.drawRightString(self._pagesize[0]-40, 14, f'Trang {self._pageNumber}/{total}')
            self.restoreState()
            super().showPage()
        super().save()


def build_pdf(output, story, *, font, pagesize, left, right, first_top, later_top, bottom,
              first_header, later_header, **metadata):
    doc = BaseDocTemplate(output, pagesize=pagesize, leftMargin=left, rightMargin=right,
                          topMargin=first_top, bottomMargin=bottom, **metadata)
    w, h = pagesize
    def frame(top, name):
        return Frame(left, bottom, w-left-right, h-top-bottom, id=name)
    doc.addPageTemplates([
        PageTemplate(id='first', frames=[frame(first_top, 'first-frame')], onPage=first_header,
                     autoNextPageTemplate='later'),
        PageTemplate(id='later', frames=[frame(later_top, 'later-frame')], onPage=later_header),
    ])
    doc.build(story, canvasmaker=lambda *a, **kw: NumberedCanvas(*a, counter_font=font, **kw))


def stack(flowables, width):
    table = Table([[list(flowables)]], colWidths=[width], hAlign='LEFT')
    table.setStyle(TableStyle([(key, (0, 0), (-1, -1), 0) for key in
                               ('LEFTPADDING', 'RIGHTPADDING', 'TOPPADDING', 'BOTTOMPADDING')]))
    return table


class KeepEnd(Flowable):
    """Let a long paragraph/table split, retaining its last line with a small end block."""
    def __init__(self, body, ending, gap=6):
        super().__init__()
        self.body, self.ending, self.gap = body, ending, gap

    def wrap(self, width, height):
        self._body_h = self.body.wrapOn(self.canv, width, 1e9)[1]
        self._end_h = self.ending.wrapOn(self.canv, width, 1e9)[1]
        self.width, self.height = width, self._body_h+self.gap+self._end_h
        return self.width, self.height

    def split(self, width, height):
        target = height if self._body_h > height else max(0, self._body_h-12)
        parts = self.body.splitOn(self.canv, width, target)
        if len(parts) < 2:
            return []
        return parts[:-1]+[KeepEnd(parts[-1], self.ending, self.gap)]

    def draw(self):
        self.body.drawOn(self.canv, 0, self._end_h+self.gap)
        self.ending.drawOn(self.canv, 0, 0)

    def getSpaceBefore(self):
        return self.body.getSpaceBefore()


class AdviceWithSignature(Flowable):
    """Continue left-column advice while deferring the entire signature to its final part."""
    def __init__(self, advice, signature, notes):
        super().__init__()
        self.advice, self.signature, self.notes = advice, signature, notes

    def wrap(self, width, height):
        self._left_w = width*.55-8
        self._right_w = width*.45-8
        self._advice_h = self.advice.wrapOn(self.canv, self._left_w, 1e9)[1]
        self._signature_h = self.signature.wrapOn(self.canv, self._right_w, 1e9)[1]
        self._notes_h = self.notes.wrapOn(self.canv, width, 1e9)[1]
        self.width = width
        self.height = max(self._advice_h, self._signature_h)+self._notes_h+6
        return width, self.height

    def split(self, width, height):
        target = height if self._advice_h > height else max(0, self._advice_h-12)
        parts = self.advice.splitOn(self.canv, self._left_w, target)
        if len(parts) < 2:
            return []
        prefix = stack(parts[:-1], self._left_w)
        return [prefix, AdviceWithSignature(parts[-1], self.signature, self.notes)]

    def draw(self):
        base = self._notes_h+6
        tallest = max(self._advice_h, self._signature_h)
        self.advice.drawOn(self.canv, 0, base+tallest-self._advice_h)
        self.signature.drawOn(self.canv, self.width*.55, base+tallest-self._signature_h)
        self.notes.drawOn(self.canv, 0, 0)


def continuation_identity(name, code, number, *, prescription=False):
    label = 'Mã đơn nội bộ' if prescription else 'Số phiếu'
    return f'Họ tên: {name}\nMã NB: {code or "—"} · {label}: {number or "—"}'


def word_pagination(doc, identity, watermark):
    """Use native Word first/continuation headers and PAGE/NUMPAGES fields."""
    doc.settings.odd_and_even_pages_header_footer = False
    for section in doc.sections:
        sect = section._sectPr
        if sect.get_headerReference(WD_HEADER_FOOTER.FIRST_PAGE) is None:
            # Reuse the existing header part, preserving its logo relationships.
            ref = sect.get_headerReference(WD_HEADER_FOOTER.PRIMARY)
            if ref is not None:
                ref.set(qn('w:type'), 'first')
        section.different_first_page_header_footer = True
        header = section.header
        for child in list(header._element):
            header._element.remove(child)
        for line in identity.splitlines():
            p = header.add_paragraph(line)
            p.paragraph_format.space_after = Pt(2)
            for run in p.runs:
                run.font.size = Pt(9)
        section.footer_distance = Pt(10)
        for footer in (section.footer, section.first_page_footer):
            for child in list(footer._element):
                footer._element.remove(child)
            p = footer.add_paragraph(watermark)
            p.alignment = 1
            p.paragraph_format.space_after = Pt(0)
            for run in p.runs:
                run.font.size = Pt(6)
                run.font.color.rgb = RGBColor.from_string('B42318')
            p = footer.add_paragraph()
            p.alignment = 2
            p.paragraph_format.space_after = Pt(0)
            p.add_run('Trang ').font.size = Pt(7)
            for instruction, following in (('PAGE', '/'), ('NUMPAGES', '')):
                field = OxmlElement('w:fldSimple')
                field.set(qn('w:instr'), instruction)
                run = OxmlElement('w:r')
                props = OxmlElement('w:rPr')
                size = OxmlElement('w:sz')
                size.set(qn('w:val'), '14')
                props.append(size)
                run.append(props)
                value = OxmlElement('w:t')
                value.text = '1'
                run.append(value)
                field.append(run)
                p._p.append(field)
                if following:
                    p.add_run(following).font.size = Pt(7)
    update = doc.settings.element.find(qn('w:updateFields'))
    if update is None:
        update = OxmlElement('w:updateFields')
        doc.settings.element.append(update)
    update.set(qn('w:val'), 'true')


def word_keep(paragraph, *, next=True):
    paragraph.paragraph_format.keep_with_next = next
    paragraph.paragraph_format.keep_together = False


def word_repeat_header(row):
    props = row._tr.get_or_add_trPr()
    if props.find(qn('w:tblHeader')) is None:
        props.append(OxmlElement('w:tblHeader'))


def word_keep_row(row):
    props = row._tr.get_or_add_trPr()
    if props.find(qn('w:cantSplit')) is None:
        props.append(OxmlElement('w:cantSplit'))
    for cell in row.cells:
        for paragraph in cell.paragraphs:
            word_keep(paragraph)


def text_chunks(value, limit=240):
    """Short native Word paragraphs/rows let the last fragment stay with its signature.

    Whitespace and characters are retained; only layout breaks are introduced.
    A single giant paragraph's keep-with-next is ignored by some Word renderers.
    """
    from textwrap import TextWrapper
    wrapper = TextWrapper(width=limit, replace_whitespace=False, drop_whitespace=False,
                          break_long_words=True, break_on_hyphens=False)
    return [chunk for line in str(value).split('\n') for chunk in (wrapper.wrap(line) or [''])]
