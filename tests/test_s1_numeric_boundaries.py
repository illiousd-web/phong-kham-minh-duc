"""No autofill limit or Decimal rounding may bypass an explicit safety gate."""
import pytest
from tests.test_s1_prescription import prescription,create


def test_quantity_over_autofill_limit_still_requires_confirmation(prescription):
    d,vid,line=prescription
    rid=create(d,vid,{**line,'dose':'1000','frequency':'1001','days':'2','quantity':'1'})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==422,response.text
    assert any(error['field']=='quantity_reason' for error in response.json()['detail']['errors'])


def test_combination_must_not_round_down_a_value_above_limit(prescription):
    d,vid,line=prescription
    rid=create(d,vid,{**line,'ingredient':'Codein + Hoạt chất giả lập','brand_name':'Phối hợp giả lập','strength':'100.000000000000000000000000000001 mg + 5 mg'})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==422,response.text
    assert 'vượt ngưỡng' in response.text


@pytest.mark.parametrize('unit',['μg','Μg'])
def test_unicode_microgram_above_threshold_is_rejected(prescription,unit):
    d,vid,line=prescription
    rid=create(d,vid,{**line,'ingredient':'Codein + Hoạt chất giả lập','brand_name':'Phối hợp giả lập','strength':f'101000 {unit} + 5 mg'})
    response=d.post(f'/api/clinical-prescriptions/{rid}/lock',json={'version':0})
    assert response.status_code==422,response.text
    assert 'vượt ngưỡng' in response.text
