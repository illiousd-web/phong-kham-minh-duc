'use strict';
let workflowVisit=null;
const showTime=value=>showDay(value);
const workflowKeys=new Map();
const cap=r=>auth.user.roles.includes(r);
const wfHidden=(name,value)=>`<input type="hidden" name="${esc(name)}" value="${Number(value)}">`;
const wfButton=(label,action,id,extra='')=>`<button type="button" class="ghost smallbtn" data-action="v050-${action}" data-id="${Number(id)}" ${extra}>${esc(label)}</button>`;
const wfForm=(kind,body,title)=>card(`<form data-form="v050-${kind}" class="fields">${body}<div class="wide"><button class="btn">Xác nhận</button></div></form>`,title);
async function v050Workflows(){
 const visits=await api('/visits');
 const vid=workflowVisit&&visits.some(v=>v.id===workflowVisit)?workflowVisit:(visits[0]?.id||null);workflowVisit=vid;
 const state=vid?await api('/visits/'+vid+'/settlement'):{clinical_status:'none',billing:{},version:0};const b=state.billing;
 let html=vid?card(selectField('Lượt khám','workflow-visit',visits.map(v=>[v.id,`#${v.id} ${v.patient_name||''}`]))+`<div class="cards"><div class="stat"><span>Chuyên môn</span><b>${esc(vi(state.clinical_status))}</b></div><div class="stat"><span>Còn phải thu</span><b>${b.due===null?'Theo phân quyền':money(b.due)}</b></div><div class="stat"><span>Cần hoàn/tiền ứng còn dư</span><b>${b.refund_due===null?'Theo phân quyền':money(b.refund_due)}</b></div><div class="stat"><span>Cấp phát thuốc</span><b>${esc(vi(state.dispensing_status))}</b></div></div>`,'Trạng thái độc lập: chuyên môn — thu ngân — nhà thuốc'):card('Chưa có lượt khám trong phạm vi được phân quyền. Các công cụ danh mục và duyệt độc lập bên dưới vẫn dùng được.','Quy trình v0.5');
 const open=vid&&!['completed','cancelled'].includes(state.clinical_status);
 if(vid&&['doctor','nurse'].includes(role())){
  const care=await api('/visits/'+vid+'/care');
  html+=card(t(care.tasks.map(task=>`<tr><td>#${task.id}</td><td>${esc(task.description)}</td><td>${esc(task.status==='done'?'Đã thực hiện':vi(task.status))}</td><td>${esc(task.execution_content||'')}</td><td>${showTime(task.executed_at||task.created_at)}</td><td>${task.status==='pending'&&open?wfButton(role()==='nurse'?'Ghi nhận thực hiện':'Hủy y lệnh',role()==='nurse'?'execute-task':'cancel-task',task.id):''}</td></tr>`),['Y lệnh','Nội dung được giao','Trạng thái','Ghi nhận thực hiện','Thời gian','Thao tác']),'Y lệnh và thực hiện');
  html+=card(t(care.notes.map(n=>`<tr><td>${esc(n.nurse_name)}</td><td>${esc(n.content)}</td><td>${showTime(n.created_at)}</td></tr>`),['Điều dưỡng','Ghi nhận chăm sóc','Thời gian']),'Lịch sử chăm sóc');
  if(open&&role()==='nurse')html+=wfForm('note',wfHidden('visit_id',vid)+textarea('Nội dung chăm sóc','content'),'Ghi nhận chăm sóc — không thay chẩn đoán');
  if(role()==='doctor'){
   const nurses=await api('/visits/'+vid+'/nurses');
   if(open)html+=wfForm('task',wfHidden('visit_id',vid)+selectField('Điều dưỡng được phân công','nurse_id',nurses.map(n=>[n.nurse_id,n.full_name]))+textarea('Nội dung y lệnh','content'),'Giao y lệnh điều dưỡng');
   const history=await api('/visits/'+vid+'/revisions');
   html+=card(t(history.map(r=>{const old=JSON.parse(r.snapshot);return `<tr><td>${r.version}</td><td>${esc(r.reason)}</td><td>${esc(old.diagnosis||'')}</td><td>${esc(old.vitals||'')}</td><td>${showTime(r.created_at)}</td></tr>`}),['Phiên bản','Lý do/thao tác','Chẩn đoán lưu tại phiên bản','Sinh hiệu','Thời gian']),'Lịch sử nội dung chuyên môn');
   if(open)html+=card(wfButton('Hoàn tất và khóa chuyên môn','complete',vid,`data-version="${state.version}"`),'Hoàn tất độc lập với thu tiền và cấp thuốc');
   if(state.clinical_status==='completed'){
    const addenda=await api('/visits/'+vid+'/addenda');
    html+=card(t(addenda.map(a=>`<tr><td>${a.id}</td><td>${esc(a.reason)}</td><td>${esc(a.content)}</td><td>${esc(vi(a.status))}</td></tr>`),['Phụ lục','Lý do','Nội dung','Duyệt']),'Phụ lục — không sửa bản gốc');
    html+=wfForm('addendum',wfHidden('visit_id',vid)+field('Lý do bổ sung/đính chính','reason','text','',true)+textarea('Nội dung bổ sung','content'),'Đề nghị phụ lục sau khóa');
   }
  }
 }
 if(vid&&open&&role()==='cashier')html+=wfForm('advance',wfHidden('visit_id',vid)+field('Số tiền ứng trước','amount','number','',true)+selectField('Hình thức','method',[['cash','Tiền mặt'],['transfer','Chuyển khoản']]),'Nhận tiền trước khi hoàn tất chỉ định/cấp thuốc');
 if(vid&&['cashier','manager','admin','reception'].includes(role())){
  const lines=await api('/charges/'+vid);
  html+=card(t(lines.map(l=>`<tr><td>${l.id}</td><td>${esc(l.label)}</td><td>${money(l.amount)}</td><td>${esc(l.void_reason||'Còn hiệu lực')}</td></tr>`),['Mã khoản','Bảng kê','Số tiền hiệu lực','Đối soát']),'Bảng kê chung: khám — cận lâm sàng — thuốc');
  if(role()==='manager'){
   html+=wfForm('reprice',selectField('Khoản cần điều chỉnh','charge_id',lines.filter(l=>!l.void_reason).map(l=>[l.id,l.label]))+field('Số tiền mới','amount','number','',true)+field('Lý do','reason','text','Tối thiểu 8 ký tự',true),'Điều chỉnh giá có nhật ký, giữ chứng từ gốc');
   const returns=await api('/medication-returns');
   html+=card(t(returns.filter(r=>r.status==='pending').map(r=>`<tr><td>#${r.id} / lượt ${r.visit_id}</td><td>${esc(r.reason)}</td><td>${wfButton('Duyệt trả vào cách ly','return-approve',r.id)} ${wfButton('Từ chối','return-reject',r.id)}</td></tr>`),['Phiếu trả','Lý do','Phê duyệt độc lập']),'Đối soát trả thuốc và khoản giảm phải thu');
   if(open)html+=wfForm('cancel-visit',wfHidden('visit_id',vid)+field('Lý do hủy lượt','reason','text','',true),'Hủy lượt sau khi xử lý chỉ định, y lệnh và thuốc');
   const adjustments=await api('/adjustments');
   html+=card(t(adjustments.filter(a=>a.kind==='discount'&&a.status==='approved').map(a=>`<tr><td>${a.id}</td><td>${money(a.amount)}</td><td>${wfButton('Hoàn tác giảm phí có lý do','reverse-discount',a.id)}</td></tr>`),['Giảm phí đã duyệt','Số tiền','Đối soát']),'Hoàn tác giảm phí khi cần hủy/trả');
  }
 }
 if(vid&&role()==='pharmacy'){
  const all=await api('/dispensations');const selected=all.filter(d=>d.visit_id===vid);
  for(const dispense of selected){
   const items=await api('/dispensations/'+dispense.id+'/items');
   html+=card(t(items.map(i=>`<tr><td>${i.id}</td><td>${esc(i.name)}</td><td>${esc(i.lot_number)}</td><td>${i.quantity}</td><td>${i.returned}</td><td>${money(i.unit_price)}</td></tr>`),['Dòng cấp','Thuốc','Lô','Đã cấp','Đã trả','Giá cơ sở']),'Phiếu cấp #'+dispense.id);
   html+=wfForm('return',wfHidden('dispensation_id',dispense.id)+selectField('Dòng thuốc trả','item_id',items.filter(i=>i.quantity>i.returned).map(i=>[i.id,`${i.name}, lô ${i.lot_number}, còn ${i.quantity-i.returned}`]))+field('Số lượng trả theo đơn vị cơ sở','quantity','number','',true)+field('Lý do trả/hủy cấp','reason','text','',true),'Trả thuốc: quản lý duyệt, nhập cách ly, không tự hoàn tiền');
  }
  html+=card('Đơn chưa cấp có thể hủy có lý do tại danh sách đơn. Thuốc đã cấp phải đi qua phiếu trả, không sửa tồn trực tiếp.','Nhà thuốc và đối soát');
 }
 if(['manager','admin'].includes(role())){
  const meds=(await api('/catalog')).medicines;
  html+=wfForm('unit',selectField('Thuốc','medicine_id',meds.map(m=>[m.id,m.name]))+field('Tên đơn vị quy đổi','name','text','Hộp / vỉ',true)+field('Số đơn vị cơ sở trong đơn vị này','base_factor','number','10',true),'Khai báo quy đổi — không đổi hệ số của lịch sử');
  const services=(await api('/catalog')).services;
  html+=wfForm('service-update',selectField('Dịch vụ','service_id',services.map(s=>[s.id,`${s.code||''} ${s.name}`]))+field('Mã dịch vụ','code','text','',true)+field('Tên dịch vụ','name','text','',true)+field('Đơn giá mới','price','number','',true)+selectField('Nhóm','category',[['consultation','Khám'],['lab','Xét nghiệm'],['ultrasound','Siêu âm'],['xray','X-quang'],['ecg','Điện tim']])+selectField('Hiệu lực','active',[['1','Đang dùng'],['0','Ngừng dùng']]),'Cập nhật danh mục, không sửa chứng từ cũ');
 }
 if(cap('controlled_reviewer')&&role()==='doctor'){
  const queue=await api('/controlled-review-queue');
  html+=card(t(queue.map(q=>`<tr><td>${q.id} / ${esc(q.patient_code)}</td><td>${esc(q.diagnosis)}</td><td>${esc(q.drug_lines)}</td></tr>`),['Đơn','Chẩn đoán phục vụ duyệt','Thuốc kiểm soát']),'Đơn kiểm soát chờ bác sĩ độc lập');
  html+=wfForm('controlled-approve',selectField('Đơn chờ duyệt','prescription_id',queue.map(q=>[q.id,'#'+q.id]))+field('Lý do duyệt','reason','text','',true)+field('Tham chiếu sổ kiểm soát giả lập','register_ref','text','',true),'Duyệt độc lập thuốc kiểm soát');
 }
 if(cap('controlled_pharmacy')&&role()==='pharmacy'){
  const meds=(await api('/catalog')).medicines.filter(m=>m.controlled);
  html+=wfForm('controlled-receipt',selectField('Thuốc kiểm soát','medicine_id',meds.map(m=>[m.id,m.name]))+field('Số lô','lot_number','text','',true)+dateField('Hạn dùng','expiry_date')+field('Số lượng cơ sở','quantity','number','',true)+field('Tham chiếu sổ','register_ref','text','',true)+field('Lý do nhập','reason','text','',true),'Đề nghị nhập thuốc kiểm soát — hai người');
 }
 if(cap('controlled_reviewer')&&role()==='manager'){
  const cm=(await api('/catalog')).medicines.filter(m=>m.controlled);
  html+=wfForm('controlled-medicine',field('Mã thuốc kiểm soát','code','text','',true)+field('Tên thuốc giả lập','name','text','',true)+field('Đơn vị cơ sở','base_unit','text','viên',true),'Danh mục thuốc kiểm soát riêng');
  html+=wfForm('controlled-price',selectField('Thuốc kiểm soát','medicine_id',cm.map(m=>[m.id,m.name]))+field('Giá mỗi đơn vị cơ sở','unit_price','number','',true)+field('Lý do phê duyệt giá','reason','text','',true),'Giá thuốc kiểm soát');
  const receipts=await api('/controlled-receipts');
  html+=card(t(receipts.filter(r=>r.status==='pending').map(r=>`<tr><td>${r.id}</td><td>${esc(r.lot_number)} / ${r.quantity}</td><td>${esc(r.register_ref)}</td><td>${wfButton('Duyệt','controlled-receipt-approve',r.id)} ${wfButton('Từ chối','controlled-receipt-reject',r.id)}</td></tr>`),['Phiếu nhập','Lô/số lượng','Sổ','Duyệt độc lập']),'Nhập kiểm soát chờ duyệt');
 }
 if(cap('controlled_pharmacy')||cap('controlled_reviewer')){
  const ledger=await api('/controlled-ledger');html+=card(t(ledger.map(l=>`<tr><td>${l.id}</td><td>${esc(l.event)}</td><td>${l.quantity}</td><td>${esc(l.register_ref)}</td><td>${showTime(l.created_at)}</td></tr>`),['Dòng sổ','Nghiệp vụ','Số lượng','Tham chiếu','Thời gian']),'Sổ thuốc kiểm soát riêng — chỉ dữ liệu giả lập');
 }
 return html;
}
async function wfRequest(kind,path,body){
 const fingerprint=kind+JSON.stringify(body);if(!workflowKeys.has(fingerprint))workflowKeys.set(fingerprint,requestId());
 const result=await api(path,{method:'POST',body:{...body,request_key:workflowKeys.get(fingerprint)}});workflowKeys.delete(fingerprint);return result;
}
async function v050Submit(form){
 const f=new FormData(form),value=k=>String(f.get(k)||'').trim(),num=k=>Number(value(k));const kind=form.dataset.form.slice(5);
 if(kind==='note')await wfRequest(kind,'/visits/'+num('visit_id')+'/care-notes',{content:value('content')});
 else if(kind==='task')await wfRequest(kind,'/visits/'+num('visit_id')+'/nursing-tasks',{nurse_id:num('nurse_id'),content:value('content')});
 else if(kind==='addendum')await api('/visits/'+num('visit_id')+'/addenda',{method:'POST',body:{reason:value('reason'),content:value('content')}});
 else if(kind==='advance'){const body={visit_id:num('visit_id'),amount:num('amount'),method:value('method'),prepayment:true};const key=JSON.stringify(body);if(!workflowKeys.has(key))workflowKeys.set(key,requestId());await api('/payments',{method:'POST',body:{...body,idempotency_key:workflowKeys.get(key)}});workflowKeys.delete(key);}
 else if(kind==='reprice')await wfRequest(kind,'/charges/'+num('charge_id')+'/reprice',{amount:num('amount'),reason:value('reason')});
 else if(kind==='unit')await api('/medicines/'+num('medicine_id')+'/units',{method:'POST',body:{name:value('name'),base_factor:num('base_factor')}});
 else if(kind==='service-update')await api('/catalog/services/'+num('service_id'),{method:'PUT',body:{code:value('code'),name:value('name'),price:num('price'),active:value('active')==='1',category:value('category')}});
 else if(kind==='return')await wfRequest(kind,'/dispensations/'+num('dispensation_id')+'/returns',{items:[{dispensation_item_id:num('item_id'),quantity:num('quantity')}],reason:value('reason')});
 else if(kind==='cancel-visit')await api('/visits/'+num('visit_id')+'/cancel',{method:'POST',body:{reason:value('reason')}});
 else if(kind==='controlled-medicine')await api('/catalog/medicines',{method:'POST',body:{code:value('code'),name:value('name'),base_unit:value('base_unit'),controlled:true}});
 else if(kind==='controlled-price')await api('/medicines/'+num('medicine_id')+'/price',{method:'PUT',body:{unit_price:num('unit_price'),reason:value('reason')}});
 else if(kind==='controlled-approve')await api('/prescriptions/'+num('prescription_id')+'/controlled-approval',{method:'POST',body:{reason:value('reason'),register_ref:value('register_ref')}});
 else if(kind==='controlled-receipt')await wfRequest(kind,'/controlled-receipts',{medicine_id:num('medicine_id'),lot_number:value('lot_number'),expiry_date:parseDay(value('expiry_date')),quantity:num('quantity'),reason:value('reason'),register_ref:value('register_ref')});
 notify('Đã ghi nhận, có nhật ký và đối soát');await render();
}
async function v050Click(element){
 const action=element.dataset.action.slice(5),id=Number(element.dataset.id);
 if(action==='complete')await api('/visits/'+id+'/complete',{method:'POST',body:{version:Number(element.dataset.version)}});
 else if(action==='execute-task'){const content=prompt('Nội dung, kết quả thực hiện y lệnh:');if(!content)return;await api('/nursing-tasks/'+id+'/execute',{method:'POST',body:{content}});}
 else if(action==='cancel-task'){const reason=prompt('Lý do hủy y lệnh (ít nhất 8 ký tự):');if(!reason)return;await api('/nursing-tasks/'+id+'/cancel',{method:'POST',body:{reason}});}
 else if(action==='reverse-discount'){const reason=prompt('Lý do hoàn tác giảm phí:');if(!reason)return;await api('/adjustments/'+id+'/reverse',{method:'POST',body:{reason}});}
 else if(action.startsWith('return-'))await api('/medication-returns/'+id+'/review',{method:'POST',body:{approve:action==='return-approve'}});
 else if(action.startsWith('controlled-receipt-'))await api('/controlled-receipts/'+id+'/review',{method:'POST',body:{approve:action==='controlled-receipt-approve'}});
 notify('Đã xử lý theo phân quyền');await render();
}
document.addEventListener('change',async event=>{if(event.target.id==='workflow-visit'){workflowVisit=Number(event.target.value);await render();}});
