"""Assertions shared by PDF exports and native Word pagination regressions."""
from io import BytesIO
from pathlib import Path
import shutil
import os
import subprocess
from tempfile import TemporaryDirectory

from docx import Document
from docx.oxml.ns import qn
from pypdf import PdfReader
import pymupdf


def word_text(raw):
    doc = Document(BytesIO(raw))
    return '\n'.join([p.text for p in doc.paragraphs]+[
        cell.text for table in doc.tables for row in table.rows for cell in row.cells])


def assert_word_pagination(raw, *, lab=False):
    doc = Document(BytesIO(raw))
    for section in doc.sections:
        assert section.different_first_page_header_footer
        assert 'Họ tên:' in '\n'.join(p.text for p in section.header.paragraphs)
        for footer in (section.first_page_footer, section.footer):
            fields = footer._element.findall('.//'+qn('w:fldSimple'))
            assert [f.get(qn('w:instr')) for f in fields] == ['PAGE', 'NUMPAGES']
            assert 'Trang ' in '\n'.join(p.text for p in footer.paragraphs)
    if lab:
        tables = [t for t in doc.tables if 'Xét nghiệm' in t.rows[0].cells[0].text]
        assert len(tables) == 1
        assert tables[0].rows[0]._tr.find('.//'+qn('w:tblHeader')) is not None
    sign = doc.tables[-1]
    assert sign.rows[0]._tr.find('.//'+qn('w:cantSplit')) is not None


def assert_paginated_pdf(raw, *, marker, signature, name, code, number, signed=False, lab=False):
    reader = PdfReader(BytesIO(raw))
    texts = [p.extract_text() for p in reader.pages]
    assert len(texts) > 1
    assert marker in '\n'.join(texts)
    assert signature in texts[-1]
    assert all(signature not in text for text in texts[:-1])
    for i, text in enumerate(texts, 1):
        assert f'Trang {i}/{len(texts)}' in text
        if i > 1:
            assert name in text and code in text and number in text
    if lab:
        # Every page carrying a result row repeats its column headings.
        for text in texts:
            if 'INDEX_' in text:
                assert 'Xét nghiệm' in text and 'Kết quả' in text
    if signed:
        with pymupdf.open(stream=raw, filetype='pdf') as doc:
            assert not any('Ký lúc' in page.get_text() for page in doc[:-1])
            assert 'Ký lúc' in doc[-1].get_text()
            assert len(doc[-1].get_image_info()) == 1
            assert not any(page.get_image_info() for page in doc[1:-1])
    return texts


def word_as_pdf(raw):
    """Exercise Word's native layout when LibreOffice is installed; XML always checked."""
    exe = shutil.which('soffice')
    if not exe:
        if os.environ.get('S2C_ALLOW_MISSING_SOFFICE') == '1':
            return None
        raise AssertionError('Cần LibreOffice để kiểm Word sang PDF; máy dev có thể đặt S2C_ALLOW_MISSING_SOFFICE=1')
    with TemporaryDirectory(prefix='s2c-word-layout-') as folder:
        root = Path(folder)
        source = root/'document.docx'
        source.write_bytes(raw)
        result = subprocess.run([exe, '-env:UserInstallation='+ (root/'profile').as_uri(),
                                 '--headless', '--convert-to', 'pdf', '--outdir', folder, str(source)],
                                capture_output=True, text=True, timeout=60)
        target = root/'document.pdf'
        assert result.returncode == 0 and target.exists(), result.stdout+result.stderr
        return target.read_bytes()
