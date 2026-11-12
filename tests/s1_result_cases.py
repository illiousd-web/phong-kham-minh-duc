import secrets

def check_text_versions(c,ids):
    r,d,t=c['reception'],c['doctor'],c['technician']
    patient=r.post('/api/patients',json={'full_name':'Giả lập phiên bản '+secrets.token_hex(5),'sex':'Nam','date_of_birth':'1990-01-01','phone':'0900000000'}).json()['id']
    vid=r.post('/api/visits',json={'patient_id':patient,'doctor_id':ids['doctor'],'service_id':1}).json()['id']
    order=d.post('/api/orders',json={'visit_id':vid,'category':'ultrasound','name':'Siêu âm giả lập S1','request_key':'s1-'+secrets.token_hex(8)}).json()['id']
    url=f'/api/orders/{order}/result'
    first=t.put(url,json={'version':0,'result_text':'Phiên bản một giả lập'})
    assert first.status_code==200,first.text
    stale=t.put(url,json={'version':0,'result_text':'Không được ghi đè'})
    assert stale.status_code==409,stale.text
    history=t.get(url+'/versions');assert history.status_code==200,history.text
    assert history.json()['items'][0]['result_text']=='Phiên bản một giả lập'
    assert d.get(url+'/versions').json()['items']==[]
    updated=t.put(url,json={'version':1,'result_text':'Phiên bản hai giả lập'})
    assert updated.status_code==200,updated.text
    assert [x['version'] for x in t.get(url+'/versions').json()['items']]==[1,2]
    pending=d.post(f'/api/orders/{order}/request-cancel',json={'reason':'Yêu cầu trước duyệt giả lập'})
    assert pending.status_code==201,pending.text
    assert d.post(f'/api/orders/{order}/approve').status_code==200
    assert d.get(url+'/versions').json()['items'][0]['result_text']=='Phiên bản hai giả lập'
    review=c['manager'].post('/api/orders/cancellation-requests/'+str(pending.json()['id'])+'/review',json={'approve':True})
    assert review.status_code==409,review.text
    denied=d.post(f'/api/orders/{order}/request-cancel',json={'reason':'Lý do giả lập đủ dài'})
    assert denied.status_code==409,denied.text
    assert 'giảm phí' in denied.text
