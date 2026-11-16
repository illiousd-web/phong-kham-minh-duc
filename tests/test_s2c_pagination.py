"""Long printouts flow without changing font sizes or losing their ending."""
from io import BytesIO

from pypdf import PdfReader
import pytest
import pymupdf

from app.s2c_forms import laboratory, prescription, render, base
from tests.s2c_cases import signature_image
from tests.print_pagination_cases import (assert_paginated_pdf, assert_word_pagination,
                                         word_as_pdf, word_text)

PERSON = dict(full_name='Bệnh nhân giả lập phân trang', code='NB-FAKE-123', sex='Nam', date_of_birth='1990-01-01')
SIGNATURE = dict(image=signature_image(), signed_at='2026-11-16T03:04:00+00:00', username='fake-doctor')


def long_model(kind):
    if kind in ('biochemistry', 'hematology', 'urine'):
        items = [dict(name=f'INDEX_{i:03d} chỉ số giả lập dài nhiều dòng kiểm thử', group_name=kind,
                      reference_text='10 – 20 (khoảng tham chiếu giả lập)', unit='g/L', display_value=str(i), flag='')
                 for i in range(1, 61)]
        m = laboratory(dict(id=123, patient=PERSON, status='approved', items=items, approver_name='Người ký giả lập'), kind)
        marker = 'INDEX_060'
    elif kind == 'order':
        m = base('order', PERSON, {}, 'Chẩn đoán giả lập', '123')
        m.update(orders=[dict(category='other', name='Dịch vụ giả lập '+str(i)+(' ORDER_TAIL_MARKER' if i==399 else '')) for i in range(1, 400)],
                 signer_title='BÁC SĨ CHỈ ĐỊNH', signer_name='Người ký giả lập')
        marker = 'ORDER_TAIL_MARKER'
    else:
        advice = ('Lời dặn dài giả lập '*600+' ADVICE_TAIL_MARKER') if kind == 'advice' else 'Lời dặn giả lập'
        usage = ('Cách dùng giả lập '*600+' USAGE_TAIL_MARKER') if kind == 'cell' else '1 viên · Uống · sau ăn · 10 ngày'
        n = 1 if kind in ('advice','cell') else 25
        m = prescription(PERSON, {}, 'Chẩn đoán giả lập',
                         [[f'DRUG_{i:03d} thuốc giả lập 5 mg', '10 viên', usage] for i in range(1, n+1)],
                         advice, 'Người ký giả lập', None)
        m['print_number'] = 'RX-FAKE-123'
        marker = 'ADVICE_TAIL_MARKER' if kind=='advice' else ('USAGE_TAIL_MARKER' if kind=='cell' else 'DRUG_025')
    m['signature'] = SIGNATURE
    return m, marker


@pytest.mark.parametrize('kind', ['biochemistry', 'hematology', 'urine', 'rx', 'advice', 'cell', 'order'])
def test_long_prints_pdf_and_word_preserve_every_row_and_sign_only_last_page(kind, tmp_path):
    m, marker = long_model(kind)
    lab = kind in ('biochemistry','hematology','urine')
    for fmt in ('pdf','docx'):
        raw = render(m, fmt)
        (tmp_path/(kind+'.'+fmt)).write_bytes(raw)
        if fmt == 'docx':
            text = word_text(raw)
            assert marker in text
            assert_word_pagination(raw, lab=lab)
            pdf = word_as_pdf(raw)
        else:
            pdf = raw
        if pdf is not None:
            texts = assert_paginated_pdf(pdf, marker=marker, signature=m['signer_title'],
                name=PERSON['full_name'], code=PERSON['code'], number=m.get('print_number') or m['number'], signed=True, lab=lab)
            text = '\n'.join(texts)
            # A final data row/advice line shares the final signature page.
            assert marker in texts[-1]
            with pymupdf.open(stream=pdf, filetype='pdf') as doc:
                # Exclude repeated headers/footers before rejoining a phrase split by a page.
                body = ' '.join(page.get_text(clip=pymupdf.Rect(0, 68, page.rect.width, page.rect.height-35)) for page in doc)
            normalized = ' '.join(body.split())
            if kind == 'advice':
                assert normalized.count('Lời dặn dài giả lập') == 600
                with pymupdf.open(stream=pdf, filetype='pdf') as doc:
                    for page in doc:
                        lines = [line for block in page.get_text('dict')['blocks'] if 'lines' in block
                                 for line in block['lines'] if any('Lời dặn dài' in s['text'] for s in line['spans'])]
                        if lines:
                            assert all(line['bbox'][0] < 80 for line in lines)
            if kind == 'cell':
                assert normalized.count('Cách dùng giả lập') == 600
            if lab or kind == 'rx':
                with pymupdf.open(stream=pdf, filetype='pdf') as doc:
                    spans = [s for page in doc for block in page.get_text('dict')['blocks'] if 'lines' in block
                             for line in block['lines'] for s in line['spans'] if ('INDEX_' if lab else 'DRUG_') in s['text']]
                    expected = (6.7 if fmt == 'pdf' else 7) if lab else 9
                    assert spans and all(abs(s['size']-expected) < .1 for s in spans)
            for i in range(1, 61 if lab else (26 if kind=='rx' else 1)):
                assert f'{"INDEX" if lab else "DRUG"}_{i:03d}' in text
            assert all(abs(p.mediabox.width-595.276) < 1 for p in PdfReader(BytesIO(pdf)).pages)
