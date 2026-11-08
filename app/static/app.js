'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=n=>Number(n||0).toLocaleString('vi-VN')+' đ';
function requestId(){if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID();if(globalThis.crypto?.getRandomValues){const b=new Uint8Array(16);crypto.getRandomValues(b);return [...b].map(v=>v.toString(16).padStart(2,'0')).join('');}return 'demo-'+Date.now()+'-'+Math.random().toString(36).slice(2);}
const roles={admin:'Quản trị',manager:'Quản lý',reception:'Lễ tân',doctor:'Bác sĩ',technician:'Kỹ thuật viên',nurse:'Điều dưỡng',pharmacy:'Dược',cashier:'Thu ngân'};
const menus={
 admin:[['dashboard','Tổng quan'],['accounts','Tài khoản'],['catalog','Danh mục'],['audit','Nhật ký']],
 manager:[['dashboard','Tổng quan'],['finance','Tài chính'],['catalog','Danh mục'],['stock','Kho thuốc']],
 reception:[['dashboard','Tổng quan'],['reception','Tiếp đón'],['appointments','Lịch hẹn'],['patients','Bệnh nhân']],
 doctor:[['dashboard','Công việc'],['clinical','Khám bệnh'],['orders','Chỉ định / kết quả'],['rx','Đơn thuốc']],
 technician:[['dashboard','Công việc'],['orders','Nhập kết quả']],
 nurse:[['dashboard','Công việc']],
 pharmacy:[['dashboard','Công việc'],['rx','Đơn thuốc nháp'],['catalog','Danh mục'],['stock','Kho thuốc']],
 cashier:[['dashboard','Công việc'],['cashier','Thu ngân']]
};
let serverMode='demo',selectedRole=null,auditOffset=0;
const pendingPaymentKeys=new Map();
let auth=null,active='dashboard',doctorList=[],patientList=[],visitList=[],orderList=[],rxList=[],dueList=[],chosenVisit=null,chosenPatient=null;
function notify(message,bad=false){$('toast').textContent=message;$('toast').className='toast'+(bad?' error':'');setTimeout(()=>$('toast').className='toast hidden',3700)}
function authHeader(){
 const h={'X-Clinic-Request':'1'};
 const csrf=serverMode==='lan' && document.cookie.split('; ').find(v=>v.startsWith('__Host-clinic-csrf='));
 if(csrf)h['X-CSRF-Token']=decodeURIComponent(csrf.split('=')[1]);
 if(auth?.token)h.Authorization='Bearer '+auth.token;
 return h;
}
async function api(path,{method='GET',body=null,isFile=false}={}){
 const options={method,headers:authHeader()};if(body!==null){if(isFile){options.body=body;}else{options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}}
 const r=await fetch('/api'+path,options);let payload=await r.json().catch(()=>({detail:'Máy chủ không trả được dữ liệu'}));if(!r.ok){if(r.status===401){auth=null;sessionStorage.removeItem('md_token');renderLogin()}throw new Error(typeof payload.detail==='string'?payload.detail:JSON.stringify(payload.detail))}return payload;
}
function field(name,id,type='text',placeholder='',required=false){return `<div class="field"><label for="${esc(id)}">${esc(name)}</label><input id="${esc(id)}" name="${esc(id)}" type="${esc(type)}" placeholder="${esc(placeholder)}" ${required?'required':''}></div>`}
function selectField(name,id,options){return `<div class="field"><label for="${esc(id)}">${esc(name)}</label><select id="${esc(id)}" name="${esc(id)}">${options.map(([v,t])=>`<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></div>`}
function textarea(name,id,placeholder=''){return `<div class="field full"><label for="${esc(id)}">${esc(name)}</label><textarea id="${esc(id)}" name="${esc(id)}" placeholder="${esc(placeholder)}"></textarea></div>`}
function card(content,title=''){return `<section class="card">${title?`<h2>${esc(title)}</h2>`:''}${content}</section>`}
function t(rows,headers){return `<div class="tablebox"><table class="table"><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.join(''):`<tr><td colspan="${headers.length}"><div class="empty">Chưa có dữ liệu</div></td></tr>`}</tbody></table></div>`}
function role(){return selectedRole||auth?.user.roles[0]||'reception'}

async function exportMedicalForm(kind,id,fmt='pdf'){
  const url=`/api/forms/${encodeURIComponent(kind)}/${Number(id)}?fmt=${encodeURIComponent(fmt)}`;
  const response=await fetch(url,{headers:authHeader(),cache:'no-store'});
  if(!response.ok){let e=await response.json().catch(()=>({detail:'Không xuất được biểu mẫu'}));throw new Error(e.detail||'Không xuất được biểu mẫu')}
  const blob=await response.blob();
  const expected=fmt==='pdf'?'application/pdf':'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  if(blob.size<500||!blob.type.includes(expected))throw new Error('Máy chủ không trả về biểu mẫu đúng định dạng');
  const fileUrl=URL.createObjectURL(blob);
  let a=document.createElement('a');a.href=fileUrl;a.download=`MinhDuc_DEMO_${kind}_${id}.${fmt}`;document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(fileUrl),10000);
  notify('Đã tải biểu mẫu '+fmt.toUpperCase()+' từ cơ sở dữ liệu');
}
function formButtons(kind,id){return `<span class="printactions"><button type="button" class="ghost smallbtn" data-action="export-form" data-kind="${esc(kind)}" data-id="${Number(id)}" data-format="pdf">Tải PDF</button> <button type="button" class="ghost smallbtn" data-action="export-form" data-kind="${esc(kind)}" data-id="${Number(id)}" data-format="docx">Tải Word</button></span>`}

function printHtml(markup){$('print-overlay').innerHTML=markup;$('print-overlay').classList.remove('hidden');document.body.classList.add('printing');window.print()}
window.addEventListener('afterprint',()=>{document.body.classList.remove('printing');$('print-overlay').classList.add('hidden');$('print-overlay').innerHTML=''})
function viewInit(){if(!auth){renderLogin();return}const r=role();const m=[...(menus[r]||menus.reception),['password','Đổi mật khẩu']];
 if(!m.some(x=>x[0]===active))active=m[0][0];$('page-title').textContent=m.find(x=>x[0]===active)[1];$('user-label').textContent=auth.user.name+' · '+roles[r];$('logout').classList.remove('hidden');
 $('navigation').innerHTML=(auth.user.roles.length>1?selectField('Vai trò đang dùng','role_switch',auth.user.roles.map(k=>[k,roles[k]])):'')+m.map(([id,label])=>`<button class="navbutton" data-action="navigate" data-page="${esc(id)}" aria-current="${active===id?'page':'false'}">${esc(label)}</button>`).join('');}
async function render(){if(!auth){renderLogin();return}viewInit();$('workspace').innerHTML=card('Đang tải dữ liệu ...');try{
 let html='';if(active==='dashboard')html=await dashboard();
 else if(active==='reception')html=await reception();else if(active==='appointments')html=await appointments();
 else if(active==='patients')html=await patients();else if(active==='clinical')html=await clinical();
 else if(active==='orders')html=await orders();else if(active==='rx')html=await prescription();
 else if(active==='cashier')html=await cashier();else if(active==='finance')html=await finance();
 else if(active==='catalog')html=await catalog();else if(active==='accounts')html=await accounts();else if(active==='password')html=passwordPage();
 else if(active==='stock')html=await stock();else if(active==='audit')html=await audit();
 $('workspace').innerHTML=html;
 if(active==='clinical' && chosenVisit){if($('visit_choose'))$('visit_choose').value=String(chosenVisit);setClinicalForm(await api('/visits/'+chosenVisit));}
 }catch(e){$('workspace').innerHTML=card(`<div class="empty">Không thể tải trang: ${esc(e.message)}</div>`)} }
function renderLogin(){auth=null;$('navigation').innerHTML='';$('page-title').textContent='Đăng nhập thử nghiệm';$('user-label').textContent='Chưa đăng nhập';$('logout').classList.add('hidden');
 const users=[['letan','Lễ tân'],['bs_noi','Bác sĩ Nội'],['bs_san','Bác sĩ Sản'],['kythuat','Kỹ thuật viên'],['duoc','Nhân viên dược'],['thungan','Thu ngân'],['quanly','Quản lý'],['quantri','Quản trị viên'],['dieuduong','Điều dưỡng']];
 $('workspace').innerHTML=card(`<form data-form="login" class="fields">${serverMode==='lan'?field('Tài khoản nhân viên','username','text','',true):selectField('Tài khoản mô phỏng','username',users)}${field('Mật khẩu','password','password','',true)}<div class="field full"><button class="btn" type="submit">Đăng nhập</button><p class="hint">${serverMode==='lan'?'Dùng tài khoản riêng do quản trị cấp. Phiên kết thúc sau 20 phút không hoạt động hoặc tối đa 8 giờ.':'Nhập mật khẩu đã chọn khi khởi động bản demo cục bộ.'}</p></div></form>`,'Đăng nhập theo vai trò');}
async function dashboard(){const o=await api('/overview');const r=role();let cards=[['Lượt khám đã tạo',o.visits],['Chỉ định chưa duyệt',o.pending_orders]];
 if(r==='manager')cards.push(['Phải thu',money(o.charged)],['Đã thu',money(o.paid)],['Còn phải thu',money(o.outstanding)],['Lô cần chú ý',o.stock_warning]);
 return `<div class="cards">${cards.map(([name,value])=>`<div class="stat"><span>${esc(name)}</span><b>${esc(value)}</b></div>`).join('')}</div>`+
 card(`<p>Xin chào <strong>${esc(auth.user.name)}</strong>. Bạn đang sử dụng phân hệ <strong>${esc(roles[r])}</strong>.</p><p class="hint">Số liệu chỉ nhằm kiểm thử. Quyền được kiểm tra ở phía máy chủ; đổi vai trò bằng cách đăng xuất và đăng nhập tài khoản khác.</p>${['reception','doctor','technician','cashier','pharmacy'].includes(r)?'<button class="btn" data-action="go-primary">Mở công việc của tôi</button>':''}`,'Công việc hiện tại')}
async function reception(){[doctorList,patientList]=await Promise.all([api('/staff'),api('/patients')]);const services=await api('/services');const visits=await api('/visits');
 let patOptions=patientList.map(p=>[p.id,`${p.code} – ${p.full_name}`]);let doctors=doctorList.map(d=>[d.id,d.full_name]);
 return `<div class="cols">${card(`<form class="fields" data-form="patient">${field('Họ và tên bệnh nhân','full_name','text','Nhập tên giả lập',true)}${field('Ngày sinh','date_of_birth','date')}${selectField('Giới tính','sex',[['Chưa rõ','Chưa rõ'],['Nam','Nam'],['Nữ','Nữ'],['Khác','Khác']])}${field('Điện thoại','phone','text','Không bắt buộc')}${field('Số căn cước (nếu có)','citizen_id')}${field('Địa chỉ','address')}<div class="wide"><button class="btn" type="submit">Lưu hồ sơ</button></div></form>`,'Thêm bệnh nhân')}${card(`<form class="fields" data-form="visit">${selectField('Bệnh nhân có sẵn','patient_id',patOptions)}${selectField('Bác sĩ phụ trách','doctor_id',doctors)}${selectField('Dịch vụ','service_id',services.map(s=>[s.id,`${s.name} – ${money(s.price)}`]))}<div class="wide"><button class="btn" type="submit" ${patientList.length?'':'disabled'}>Tạo lượt khám</button></div></form><p class="hint">Giá dịch vụ hoàn toàn là giá giả lập.</p>`,'Tạo lượt khám')}</div>`+card(patientTable(patientList),'Danh sách bệnh nhân')+card(t(visits.map(v=>`<tr><td>#${v.id}</td><td>${esc(v.patient_name)}</td><td>${esc(v.status)}</td><td>${formButtons('intake',v.id)}</td></tr>`),['Lượt khám','Bệnh nhân','Trạng thái','Phiếu tiếp đón']),'Biểu mẫu đã có dữ liệu')}
function patientTable(list){return t(list.map(p=>`<tr><td>${esc(p.code)}</td><td>${esc(p.full_name)}</td><td>${esc(p.date_of_birth||'')}</td><td>${esc(p.phone||'')}</td><td><button class="ghost smallbtn" data-action="select-patient" data-id="${p.id}">Chọn</button></td></tr>`),['Mã','Bệnh nhân','Ngày sinh','Điện thoại','Thao tác'])}
async function patients(){patientList=await api('/patients');return card(`<div class="toolbar-actions"><input id="search-patients" placeholder="Tên, mã, số điện thoại" aria-label="Tìm bệnh nhân"><button class="ghost" data-action="search-patients">Tìm kiếm</button></div><div id="patient-list">${patientTable(patientList)}</div>`,'Tra cứu hồ sơ')}
async function appointments(){[doctorList,patientList]=await Promise.all([api('/staff'),api('/patients')]);let list=await api('/appointments');
 return card(`<form data-form="appointment" class="fields">${selectField('Bệnh nhân','patient_id',patientList.map(p=>[p.id,p.code+' – '+p.full_name]))}${selectField('Bác sĩ','doctor_id',doctorList.map(d=>[d.id,d.full_name]))}${field('Ngày giờ hẹn','scheduled_at','datetime-local','',true)}${field('Lý do khám','reason')}<div class="wide"><button class="btn" ${patientList.length?'':'disabled'}>Đặt lịch</button></div></form>`,'Lịch hẹn mới')+
 card(t(list.map(x=>`<tr><td>${esc(x.patient_name)}</td><td>${esc(x.doctor_name)}</td><td>${esc(x.scheduled_at)}</td><td><span class="status">${esc(x.status)}</span></td></tr>`),['Bệnh nhân','Bác sĩ','Thời gian','Trạng thái']),'Lịch hẹn đã tạo')}
async function clinical(){visitList=await api('/visits');if(!visitList.length)return card('<div class="empty">Chưa có lượt khám được phân công. Đăng nhập lễ tân để tạo lượt khám giả lập.</div>','Hồ sơ khám');
 let vid=chosenVisit && visitList.some(v=>v.id===chosenVisit)?chosenVisit:visitList[0].id;chosenVisit=vid;const v=await api('/visits/'+vid);return card(`<div class="toolbar-actions">${selectField('Lượt khám được giao','visit_choose',visitList.map(x=>[x.id,`#${x.id} – ${x.patient_name}`]))}</div><form data-form="clinical" class="fields"><input type="hidden" name="visit_id" value="${vid}"><input type="hidden" name="version" value="${v.version}">${textarea('Lý do khám và triệu chứng','chief_complaint')}${textarea('Bệnh sử, tiền sử','history')}${field('Dấu hiệu sinh tồn – bản ghi dạng văn bản','vitals')}${textarea('Chẩn đoán / nhận định','diagnosis')}${textarea('Hướng điều trị','treatment')}${field('Hẹn tái khám','follow_up','text','Ví dụ: 7 ngày')}<div class="wide"><button class="btn">Lưu phiếu khám</button> <button class="ghost" type="button" data-action="export-form" data-kind="visit" data-id="${vid}" data-format="pdf">Xem phiếu khám PDF</button> <button class="ghost" type="button" data-action="export-form" data-kind="visit" data-id="${vid}" data-format="docx">Tải phiếu Word</button> <button class="ghost" type="button" data-action="export-form" data-kind="followup" data-id="${vid}" data-format="pdf">Giấy hẹn tái khám</button></div></form><div id="clinical-print" class="hidden print-sheet"></div>`,'Phiếu khám chi tiết – '+v.patient_name)+`<div class="hint">Quy trình chưa có chữ ký số, khóa hồ sơ sau xác nhận hoặc quy chuẩn biểu mẫu y tế.</div>`;
}
async function orders(){orderList=await api('/orders');let doctor=role()==='doctor';let items=[];
 if(doctor){visitList=await api('/visits');items.push(card(`<form class="fields" data-form="order">${selectField('Lượt khám','visit_id',visitList.map(v=>[v.id,`#${v.id} – ${v.patient_name}`]))}${selectField('Loại dịch vụ','category',[['lab','Xét nghiệm'],['ultrasound','Siêu âm'],['xray','X-quang'],['ecg','Điện tim']])}${field('Tên chỉ định','name','text','Ví dụ: Siêu âm tổng quát',true)}<div class="wide"><button class="btn" ${visitList.length?'':'disabled'}>Tạo chỉ định</button></div></form>`,'Lập chỉ định'));}
 let body=orderList.map(o=>`<tr><td>${esc(o.patient_code)}<div class="muted">${esc(o.patient_name)}</div></td><td>${esc(o.name)}</td><td>${esc(o.category)}</td><td><span class="status ${o.status==='pending_review'?'warn':''}">${esc(o.status)}</span></td><td>${doctor?(o.status==='pending_review'?`<button class="btn smallbtn" data-action="approve" data-id="${o.id}">Duyệt mô phỏng</button>`:'—'):(o.status!=='approved'?`<button class="ghost smallbtn" data-action="edit-result" data-id="${o.id}">Nhập kết quả</button>`:'—')}${o.file_name?` <button class="ghost smallbtn" data-action="file" data-id="${o.id}">Tệp</button>`:''}${doctor?` ${formButtons('order',o.id)}`:''}${o.status==='approved'?` ${formButtons(o.category,o.id)}`:''}</td></tr>`);
 items.push(card(t(body,['Bệnh nhân','Chỉ định','Loại','Trạng thái','Thao tác']),'Chỉ định và kết quả'));
 if(role()==='technician')items.push(card(`<form data-form="result" class="fields">${selectField('Chỉ định','order_id',orderList.filter(o=>o.status!=='approved').map(o=>[o.id,`#${o.id} – ${o.name} (${o.patient_code})`]))}${textarea('Nội dung kết quả','result_text','Nhập dữ liệu giả lập; không dùng trong chẩn đoán')}<div class="field full"><button class="btn">Gửi chờ duyệt</button></div></form><hr><form data-form="attach" class="fields" enctype="multipart/form-data">${selectField('Chỉ định cần đính kèm','attach_order',orderList.filter(o=>o.status!=='approved').map(o=>[o.id,`#${o.id} – ${o.name}`]))}<div class="field"><label for="attachment">Tệp kết quả PDF/PNG/JPG (tối đa 5 MB)</label><input id="attachment" type="file" name="attachment" accept=".pdf,.png,.jpg,.jpeg" required></div><div class="field"><button class="btn">Tải tệp giả lập</button></div></form>`,'Nhập kết quả và đính kèm'));
 return items.join('')+'<div id="result-print" class="hidden print-sheet"></div>'}
async function prescription(){rxList=await api('/prescriptions');let parts=[];
 if(role()==='doctor'){
 visitList=await api('/visits');parts.push(card(`<form data-form="rx" class="fields">${selectField('Lượt khám','visit_id',visitList.map(v=>[v.id,`#${v.id} – ${v.patient_name}`]))}${textarea('Dòng thuốc (chỉ mô phỏng)','drug_lines','Tuyệt đối không dùng để hướng dẫn dùng thuốc thật')}${textarea('Hướng dẫn / lưu ý','instructions')}${field('Ngày hẹn tái khám','follow_up','text','Chưa bắt buộc')}<div class="wide"><button class="btn" ${visitList.length?'':'disabled'}>Lưu đơn nháp</button></div></form>`,'Lập đơn thuốc nháp'));}
 parts.push(card(t(rxList.map(x=>`<tr><td>${esc(x.patient_name)}</td><td>${esc(x.drug_lines)}</td><td>${esc(x.status)}</td><td>${formButtons('rx',x.id)}</td></tr>`),['Bệnh nhân','Nội dung đơn nháp','Trạng thái','In']),'Đơn thuốc đã tạo'));
 parts.push('<div id="rx-print" class="hidden print-sheet"></div>');return parts.join('')}
async function cashier(){dueList=await api('/dues');const pays=await api('/payments');const adj=await api('/adjustments');return card(`<form data-form="payment" class="fields">${selectField('Lượt khám','visit_id',dueList.map(v=>[v.visit_id,`#${v.visit_id} – ${v.patient_name} – còn ${money(v.charged-v.paid)}`]))}${field('Số tiền (VNĐ)','amount','number','',true)}${selectField('Hình thức','method',[['cash','Tiền mặt'],['transfer','Chuyển khoản (đã đối chiếu thủ công)']])}${field('Tham chiếu giao dịch','external_ref')}<div class="wide"><button class="btn" ${dueList.length?'':'disabled'}>Ghi khoản thu thử nghiệm</button></div></form>`,'Thanh toán quỹ chung')+
 card(t(dueList.map(x=>`<tr><td>#${x.visit_id}</td><td>${esc(x.patient_name)}</td><td>${money(x.charged)}</td><td>${money(x.paid)}</td><td>${money(x.charged-x.paid)}</td></tr>`),['Lượt','Bệnh nhân','Phải thu','Đã thu','Còn lại (âm = trả thừa)']),'Đối soát công nợ')+
 card(t(pays.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.patient_name)}</td><td>${money(x.amount)}</td><td>${esc(x.method)}</td><td><button class="ghost smallbtn" data-action="export-receipt" data-id="${x.id}">Tải phiếu thu PDF</button></td></tr>`),['Mã thu','Bệnh nhân','Số tiền','Phương thức','Chứng từ']),'Lịch sử thanh toán')+
 card(`<form data-form="adjustment" class="fields">${selectField('Lượt khám','visit_id',dueList.map(v=>[v.visit_id,`#${v.visit_id} – ${v.patient_name}`]))}${selectField('Loại đề nghị','kind',[['discount','Giảm phí'],['refund','Hoàn phần trả thừa']])}${field('Số tiền (VNĐ)','amount','number','',true)}${selectField('Phiếu thu cần hoàn (chỉ áp dụng hoàn tiền)','payment_id',[['','Không áp dụng'],...pays.map(x=>[x.id,`#${x.id}: ${x.patient_name}, ${money(x.amount)}`])])}${field('Lý do','reason','text','Tối thiểu 5 ký tự',true)}<div class="wide"><button class="btn">Gửi quản lý phê duyệt</button></div></form>`,'Đề nghị giảm giá / hoàn tiền')+
 card(t(adj.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.kind)}</td><td>${money(x.amount)}</td><td>${esc(x.status)}</td></tr>`),['Mã','Loại','Số tiền','Trạng thái']),'Đề nghị do tôi tạo');}
async function finance(){const o=await api('/overview'),adj=await api('/adjustments');return `<div class="cards">${[['Phí đã ghi nhận (demo)',money(o.charged)],['Tiền thu sau hoàn (demo)',money(o.paid)],['Chênh lệch cần thu',money(o.outstanding)],['Lô cần chú ý',o.stock_warning]].map(([name,value])=>`<div class="stat"><span>${esc(name)}</span><b>${esc(value)}</b></div>`).join('')}</div>`+
 card('<p>Chưa có chi phí vận hành, giá vốn đầy đủ hoặc đối chiếu ngân hàng thật. Các số liệu chỉ phục vụ kiểm thử giao dịch và không dùng kế toán/khai thuế.</p>','Báo cáo mô phỏng')+
 card(t(adj.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.patient_name)}</td><td>${esc(x.kind)} — ${money(x.amount)}</td><td>${esc(x.reason)}</td><td>${esc(x.status)}</td><td>${x.status==='pending'?`<div class="multi-actions"><button class="btn smallbtn" data-action="review-adjustment" data-id="${x.id}" data-value="approve">Duyệt</button> <button class="ghost smallbtn" data-action="review-adjustment" data-id="${x.id}" data-value="reject">Từ chối</button></div>`:'—'}</td></tr>`),['Mã','Bệnh nhân','Loại - tiền','Lý do','Trạng thái','Thao tác']),'Đề nghị điều chỉnh và phê duyệt');}
async function stock(){const list=await api('/stock');const medications=role()==='pharmacy'?await api('/medicines'):[];
 const receive=role()==='pharmacy'?card(`<form data-form="stock-receipt" class="fields">${selectField('Mặt hàng','medicine_id',medications.filter(x=>!x.controlled).map(x=>[x.id,x.name]))}${field('Số lô','lot_number','text','LO-MAU-004',true)}${field('Hạn sử dụng','expiry_date','date','',true)}${field('Số lượng (đơn vị cơ sở)','quantity','number','',true)}<div class="wide"><button class="btn">Nhập lô mô phỏng</button></div></form>`,'Nhập kho'):'';
 const issue=role()==='pharmacy'?card(`<form data-form="stock-issue" class="fields">${selectField('Mặt hàng','medicine_id',medications.filter(x=>!x.controlled).map(x=>[x.id,x.name]))}${field('Số lượng (đơn vị cơ sở)','quantity','number','',true)}${field('Mục đích sử dụng','purpose','text','Sử dụng nội bộ mô phỏng',true)}<div class="wide"><button class="btn">Xuất kho theo hạn dùng (FEFO)</button></div></form>`,'Xuất kho mô phỏng'):'';
 return receive+issue+card(t(list.map(x=>`<tr><td>${esc(x.name)}${x.controlled?' <span class="status warn">Kiểm soát đặc biệt</span>':''}</td><td>${esc(x.lot_number)}</td><td>${esc(x.expiry_date)}</td><td>${esc(x.quantity)} ${esc(x.base_unit)}</td><td>${x.quarantined?'<span class="status error">Cách ly</span>':'<span class="status">Theo dõi</span>'}</td></tr>`),['Thuốc/Vật tư','Số lô','Hạn dùng','Tồn','Trạng thái']),'Kho thử nghiệm')+'<p class="hint">Không xuất thuốc phải kiểm soát đặc biệt; không thay quy trình dược thực tế.</p>';
}
async function audit(){const entries=await api('/audit?offset='+auditOffset+'&limit=100');return card(t(entries.map(x=>`<tr><td>${x.id}</td><td>${esc(x.username||x.user_id||'Hệ thống')}</td><td>${esc(x.event)}</td><td>${esc(x.object_type)} #${esc(x.object_id)}</td><td>${esc(x.details)}</td><td>${esc(x.created_at)}</td></tr>`),['ID','Nhân viên','Sự kiện','Đối tượng','Chi tiết','Thời gian UTC'])+`<div class="toolbar-actions"><button class="ghost" data-action="audit-prev" ${auditOffset===0?'disabled':''}>Trang trước</button><span>Từ dòng ${auditOffset+1}</span><button class="ghost" data-action="audit-next" ${entries.length<100?'disabled':''}>Trang sau</button></div>`,'Nhật ký sự kiện')}

function setClinicalForm(data){for(const name of ['chief_complaint','history','vitals','diagnosis','treatment','follow_up']){const el=document.querySelector(`[name="${name}"]`);if(el)el.value=data[name]||'';}}
async function handleForm(form){const kind=form.dataset.form;const f=new FormData(form);const value=k=>String(f.get(k)||'').trim();const num=k=>Number(value(k));
 if(kind==='login'){
 const res=await api('/login',{method:'POST',body:{username:value('username'),password:value('password')}});auth={token:res.access_token,user:res.user};selectedRole=null;if(res.access_token)sessionStorage.setItem('md_token',res.access_token);active='dashboard';await render();notify('Đăng nhập thành công');return;
 }
 if(kind==='service'){await api('/catalog/services',{method:'POST',body:{name:value('name'),price:num('price')}});notify('Đã thêm dịch vụ');
 }else if(kind==='medicine'){await api('/catalog/medicines',{method:'POST',body:{name:value('name'),base_unit:value('base_unit')}});notify('Đã thêm thuốc/vật tư');
 }else if(kind==='account'){
 await api('/accounts',{method:'POST',body:{username:value('username'),full_name:value('full_name'),password:value('password'),roles:[value('role')]}});notify('Đã tạo tài khoản riêng');
 }else if(kind==='account-update'){
 await api('/accounts/'+num('uid'),{method:'PUT',body:{active:value('active')==='1',roles:[value('role')]}});notify('Đã cập nhật quyền và thu hồi các phiên cũ');
 }else if(kind==='account-reset'){
 await api('/accounts/'+num('uid')+'/password',{method:'POST',body:{password:value('password')}});notify('Đã đặt mật khẩu và thu hồi phiên');
 }else if(kind==='password'){
 await api('/password',{method:'POST',body:{current_password:value('current_password'),new_password:value('new_password')}});sessionStorage.removeItem('md_token');selectedRole=null;renderLogin();notify('Đã đổi mật khẩu. Hãy đăng nhập lại');return;
 }else if(kind==='patient'){const res=await api('/patients',{method:'POST',body:{full_name:value('full_name'),date_of_birth:value('date_of_birth')||null,sex:value('sex'),phone:value('phone')||null,citizen_id:value('citizen_id')||null,address:value('address')||null}});notify('Đã lưu bệnh nhân '+res.code);}
 else if(kind==='visit'){const res=await api('/visits',{method:'POST',body:{patient_id:num('patient_id'),doctor_id:num('doctor_id'),service_id:num('service_id')}});notify('Đã tiếp nhận lượt khám #'+res.id);}
 else if(kind==='appointment'){await api('/appointments',{method:'POST',body:{patient_id:num('patient_id'),doctor_id:num('doctor_id'),scheduled_at:value('scheduled_at'),reason:value('reason')}});notify('Đã đặt lịch');}
 else if(kind==='clinical'){const payload={version:num('version')};for(const k of ['chief_complaint','history','vitals','diagnosis','treatment','follow_up'])payload[k]=value(k)||null;
 for(const k of ['chief_complaint','history','vitals','diagnosis','treatment'])payload[k]=payload[k]||'';
 await api('/visits/'+num('visit_id')+'/clinical',{method:'PUT',body:payload});notify('Đã lưu phiếu khám vào cơ sở dữ liệu');}
 else if(kind==='order'){await api('/orders',{method:'POST',body:{visit_id:num('visit_id'),category:value('category'),name:value('name')}});notify('Đã lập chỉ định');}
 else if(kind==='result'){await api('/orders/'+num('order_id')+'/result',{method:'PUT',body:{result_text:value('result_text')}});notify('Đã chuyển kết quả chờ duyệt');}
 else if(kind==='attach'){const data=new FormData();data.set('file',f.get('attachment'));await api('/orders/'+num('attach_order')+'/attachment',{method:'POST',body:data,isFile:true});notify('Đã tải tệp kết quả');}
 else if(kind==='rx'){await api('/prescriptions',{method:'POST',body:{visit_id:num('visit_id'),drug_lines:value('drug_lines'),instructions:value('instructions'),follow_up:value('follow_up')||null}});notify('Đã tạo đơn nháp (không hợp lệ để cấp thuốc)');}
 else if(kind==='stock-receipt'){await api('/stock/receipts',{method:'POST',body:{medicine_id:num('medicine_id'),lot_number:value('lot_number'),expiry_date:value('expiry_date'),quantity:num('quantity')}});notify('Đã nhập lô vào kho demo');}
 else if(kind==='payment'){
 const payment={visit_id:num('visit_id'),amount:num('amount'),method:value('method'),external_ref:value('external_ref')||null};
 const fingerprint=JSON.stringify(payment);if(!pendingPaymentKeys.has(fingerprint))pendingPaymentKeys.set(fingerprint,requestId());
 await api('/payments',{method:'POST',body:{...payment,idempotency_key:pendingPaymentKeys.get(fingerprint)}});
 pendingPaymentKeys.delete(fingerprint);notify('Đã ghi khoản thu vào cơ sở dữ liệu demo');
 }
 else if(kind==='stock-issue'){await api('/stock/issues',{method:'POST',body:{medicine_id:num('medicine_id'),quantity:num('quantity'),purpose:value('purpose')}});notify('Đã xuất lô theo hạn dùng');}
 else if(kind==='adjustment'){await api('/adjustments',{method:'POST',body:{visit_id:num('visit_id'),kind:value('kind'),amount:num('amount'),payment_id:value('payment_id')?num('payment_id'):null,reason:value('reason')}});notify('Đã gửi đề nghị cho quản lý');}
 await render();}
async function downloadPdfReceipt(id){const r=await fetch(`/api/print/receipt/${id}`,{headers:authHeader()});if(!r.ok){const m=await r.json().catch(()=>({detail:'Lỗi xuất chứng từ'}));throw new Error(m.detail)}const blob=await r.blob();if(blob.type!=='application/pdf')throw new Error('Không nhận được PDF');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`MinhDuc_PhieuThu_${id}.pdf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);notify('Đã tạo phiếu thu nháp');}
async function handleClick(element){const action=element.dataset.action;if(action==='audit-prev'||action==='audit-next'){auditOffset=Math.max(0,auditOffset+(action==='audit-next'?100:-100));await render();}else if(action==='export-receipt'){await downloadPdfReceipt(Number(element.dataset.id))}else if(action==='review-adjustment'){await api('/adjustments/'+element.dataset.id+'/review',{method:'POST',body:{approve:element.dataset.value==='approve'}});notify('Đã xử lý đề nghị');await render();}else if(action==='export-form'){await exportMedicalForm(element.dataset.kind,element.dataset.id,element.dataset.format||'pdf')}else if(action==='navigate'){active=element.dataset.page;await render();}
 else if(action==='go-primary'){active=({reception:'reception',doctor:'clinical',technician:'orders',cashier:'cashier',pharmacy:'rx'})[role()]||'dashboard';await render();}
 else if(action==='select-patient'){chosenPatient=Number(element.dataset.id);active='reception';await render();let el=document.getElementById('patient_id');if(el)el.value=chosenPatient;notify('Đã chọn bệnh nhân để tạo lượt khám');}
 else if(action==='search-patients'){patientList=await api('/patients?q='+encodeURIComponent($('search-patients').value));$('patient-list').innerHTML=patientTable(patientList);}
 else if(action==='approve'){await api('/orders/'+element.dataset.id+'/approve',{method:'POST'});notify('Đã duyệt quy trình mô phỏng');await render();}
 else if(action==='edit-result'){let o=orderList.find(x=>x.id===Number(element.dataset.id));if(o){$('order_id').value=o.id;$('result_text').value=o.result_text||'';document.getElementById('result_text').focus();}}
 else if(action==='file'){const r=await fetch('/api/orders/'+element.dataset.id+'/attachment',{headers:authHeader()});if(!r.ok)throw new Error('Không tải được tệp');const url=URL.createObjectURL(await r.blob());let a=document.createElement('a');a.href=url;a.download='ket_qua_mo_phong';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}

}
document.addEventListener('submit',async ev=>{const form=ev.target.closest('[data-form]');if(!form)return;ev.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{await handleForm(form)}catch(err){notify(err.message,true)}finally{delete form.dataset.busy;buttons.forEach(b=>b.disabled=false)}});
document.addEventListener('click',async ev=>{const btn=ev.target.closest('[data-action]');if(!btn)return;try{await handleClick(btn)}catch(err){notify(err.message,true)}});
document.addEventListener('change',async ev=>{if(ev.target.id==='role_switch'){selectedRole=ev.target.value;active='dashboard';await render();return;}if(ev.target.id==='visit_choose'){chosenVisit=Number(ev.target.value);try{const v=await api('/visits/'+chosenVisit);setClinicalForm(v);document.querySelector('[name="visit_id"]').value=v.id;document.querySelector('[name="version"]').value=v.version;}catch(e){notify(e.message,true)}}});
$('logout').addEventListener('click',async()=>{try{await api('/logout',{method:'POST'})}catch{}sessionStorage.removeItem('md_token');auth=null;selectedRole=null;renderLogin()});
async function catalog(){
 const data=await api('/catalog');
 return (role()!=='pharmacy'?card(`<form data-form="service" class="fields">${field('Tên dịch vụ','name','text','Dịch vụ giả lập',true)}${field('Đơn giá VNĐ','price','number','',true)}<div class="wide"><button class="btn">Thêm dịch vụ</button></div></form>`,'Danh mục dịch vụ'):'')+
 card(t(data.services.map(x=>`<tr><td>${esc(x.name)}</td><td>${money(x.price)}</td></tr>`),['Dịch vụ','Giá']),'Dịch vụ hiện có')+
 card(`<form data-form="medicine" class="fields">${field('Tên thuốc/vật tư giả lập','name','text','',true)}${field('Đơn vị cơ sở','base_unit','text','viên / cái',true)}<div class="wide"><button class="btn">Thêm thuốc/vật tư</button><p class="hint">Chưa hỗ trợ thuốc kiểm soát đặc biệt.</p></div></form>`,'Danh mục kho')+
 card(t(data.medicines.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.base_unit)}</td></tr>`),['Mặt hàng','Đơn vị']),'Mặt hàng hiện có');
}
async function accounts(){
 const users=await api('/accounts');
 const options=Object.entries(roles);
 return card(`<form data-form="account" class="fields">${field('Tài khoản (chữ thường, không dấu)','username','text','',true)}${field('Họ tên nhân viên','full_name','text','',true)}${field('Mật khẩu riêng (ít nhất 12 ký tự)','password','password','',true)}${selectField('Vai trò','role',options)}<div class="wide"><button class="btn">Tạo tài khoản</button></div></form>`,'Tạo tài khoản nhân viên')+
 card(t(users.map(u=>`<tr><td>${esc(u.username)}</td><td>${esc(u.full_name)}</td><td>${u.roles.map(r=>esc(roles[r])).join(', ')}</td><td>${u.active?'Hoạt động':'Đã khóa'}</td></tr>`),['Tài khoản','Họ tên','Quyền','Trạng thái']),'Nhân viên')+
 card(`<form data-form="account-update" class="fields">${selectField('Nhân viên','uid',users.map(u=>[u.id,u.full_name+' ('+u.username+')']))}${selectField('Vai trò thay thế','role',options)}${selectField('Trạng thái','active',[['1','Hoạt động'],['0','Khóa']])}<div class="wide"><button class="btn">Cập nhật quyền / trạng thái</button><p class="hint">Thay quyền sẽ thu hồi mọi phiên cũ. Biểu mẫu này thay toàn bộ vai trò bằng một vai trò đã chọn.</p></div></form>`,'Phân quyền và khóa tài khoản')+
 card(`<form data-form="account-reset" class="fields">${selectField('Nhân viên','uid',users.map(u=>[u.id,u.full_name]))}${field('Mật khẩu mới (ít nhất 12 ký tự)','password','password','',true)}<div class="wide"><button class="btn">Đặt lại mật khẩu</button></div></form>`,'Khôi phục truy cập');
}
function passwordPage(){return card(`<form data-form="password" class="fields">${field('Mật khẩu hiện tại','current_password','password','',true)}${field('Mật khẩu mới (ít nhất 12 ký tự)','new_password','password','',true)}<div class="wide"><button class="btn">Đổi mật khẩu và đăng xuất các phiên</button></div></form>`,'Đổi mật khẩu cá nhân')}
async function boot(){
 try{const health=await api('/health');serverMode=health.mode||'demo';}catch(e){notify(e.message,true);return;}
 const token=sessionStorage.getItem('md_token');
 if(serverMode==='lan')sessionStorage.removeItem('md_token');
 if(serverMode==='lan'||token){try{auth={token:serverMode==='lan'?null:token,user:null};const user=await api('/me');auth={token:serverMode==='lan'?null:token,user};await render();return}catch{}sessionStorage.removeItem('md_token');auth=null}
 renderLogin();
}
boot();
