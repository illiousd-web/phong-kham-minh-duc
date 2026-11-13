'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const moneyFormat=new Intl.NumberFormat('vi-VN');
const money=n=>n===null?'CHƯA CÓ GIÁ':moneyFormat.format(Number(n||0))+' đ';
const servicePrice=s=>s.price_at_collection?'Giá nhập khi thu':money(s.price);
function requestId(){if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID();if(globalThis.crypto?.getRandomValues){const b=new Uint8Array(16);crypto.getRandomValues(b);return [...b].map(v=>v.toString(16).padStart(2,'0')).join('');}return 'demo-'+Date.now()+'-'+Math.random().toString(36).slice(2);}
const roles={controlled_prescriber:'Bác sĩ thuốc kiểm soát',controlled_pharmacy:'Dược kiểm soát',controlled_reviewer:'Duyệt kiểm soát',admin:'Quản trị',manager:'Quản lý',reception:'Lễ tân',doctor:'Bác sĩ',technician:'Kỹ thuật viên',nurse:'Điều dưỡng',pharmacy:'Dược',cashier:'Thu ngân'};
// Mỗi vai trò chỉ thấy menu công việc của mình; mỗi menu là một màn hình bắt đầu bằng hàng chờ.
const menus={
 reception:[['reception','Tiếp đón'],['prices','Bảng giá']],
 doctor:[['doctor','Khám bệnh']],
 nurse:[['nurse','Điều dưỡng']],
 technician:[['lab','Cận lâm sàng']],
 pharmacy:[['pharmacy','Nhà thuốc']],
 cashier:[['cashier','Thu ngân']],
 manager:[['manager','Quản lý']],
 admin:[['admin','Quản trị'],['price-management','Quản lý'],['settings','Cài đặt']]
};
let serverMode='demo',selectedRole=null,auditOffset=0;
const pendingOrderKeys=new Map();
const scopeWarnings=new Map();
let auth=null,active=null,patientList=[],orderList=[],dueList=[],accountList=[];
let priceFile=null,pricePreview=null,priceResult=null,manualReportDay=null;
// Lựa chọn đang mở trên từng màn hình (lượt khám, chỉ định, phiếu cấp...).
const sel={visit:null,patient:null,patientQuery:'',nurseVisit:null,order:null,dispense:null,cashVisit:null,mgrVisit:null,account:null,mgrTab:'approve',adminTab:'accounts'};
// Cài đặt bật/tắt chức năng phụ, đọc từ máy chủ sau khi đăng nhập.
let ui={advance_payment:false,addendum:true,controlled_drugs:true},uiLoaded=false;
let toastTimer=null;
function notify(message,bad=false){if(!message)return;$('toast').textContent=message;$('toast').className='toast'+(bad?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').className='toast hidden',bad?6000:3700)}
function authHeader(){
 const h={'X-Clinic-Request':'1'};
 const csrf=serverMode==='lan' && document.cookie.split('; ').find(v=>v.startsWith('__Host-clinic-csrf='));
 if(csrf)h['X-CSRF-Token']=decodeURIComponent(csrf.split('=')[1]);
 if(auth?.token)h.Authorization='Bearer '+auth.token;
 return h;
}
async function api(path,{method='GET',body=null,isFile=false}={}){
 const options={method,headers:authHeader()};if(body!==null){if(isFile){options.body=body;}else{options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}}
 const canRetry=!isFile&&!['GET','HEAD'].includes(method.toUpperCase())&&typeof body?.idempotency_key==='string'&&body.idempotency_key.length>0;
 for(let attempt=0;attempt<2;attempt++){
  const r=await fetch('/api'+path,options);
  const payload=await r.json().catch(()=>({detail:'Máy chủ không trả được dữ liệu'}));
  if(r.status===503&&canRetry&&attempt===0){
   const after=r.headers.get('Retry-After');
   const seconds=after===null?NaN:(/^\d+(?:\.\d+)?$/.test(after)?Number(after):(Date.parse(after)-Date.now())/1000);
   if(Number.isFinite(seconds)){await new Promise(resolve=>setTimeout(resolve,Math.max(0,seconds)*1000));continue;}
  }
  if(!r.ok){if(r.status===401){auth=null;sessionStorage.removeItem('md_token');renderLogin()}throw new Error(typeof payload.detail==='string'?payload.detail:JSON.stringify(payload.detail))}
  return payload;
 }
}
function field(name,id,type='text',placeholder='',required=false){return `<div class="field"><label for="${esc(id)}">${esc(name)}</label><input id="${esc(id)}" name="${esc(id)}" type="${esc(type)}" placeholder="${esc(placeholder)}" ${required?'required':''}></div>`}
function selectField(name,id,options){return `<div class="field"><label for="${esc(id)}">${esc(name)}</label><select id="${esc(id)}" name="${esc(id)}">${options.map(([v,t])=>`<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></div>`}
function textarea(name,id,placeholder=''){return `<div class="field full"><label for="${esc(id)}">${esc(name)}</label><textarea id="${esc(id)}" name="${esc(id)}" placeholder="${esc(placeholder)}"></textarea></div>`}
function card(content,title=''){return `<section class="card">${title?`<h2>${esc(title)}</h2>`:''}${content}</section>`}
function t(rows,headers){return `<div class="tablebox"><table class="table"><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.join(''):`<tr><td colspan="${headers.length}"><div class="empty">Chưa có dữ liệu</div></td></tr>`}</tbody></table></div>`}
function role(){return selectedRole||auth?.user.roles.find(r=>menus[r])||'reception'}
const cap=r=>!!auth?.user.roles.includes(r);
// Nhãn tiếng Việt cho mã trạng thái lưu trong CSDL; không để mã tiếng Anh lọt ra màn hình.
const LABEL={restricted:'Theo phân quyền',requested:'Chờ bác sĩ duyệt chỉ định',waiting_results:'Chờ kết quả',returned:'Đã trả thuốc',partially_returned:'Đã trả một phần',not_prescribed:'Chưa kê đơn',not_dispensed:'Chưa cấp thuốc',waiting:'Chờ khám',in_progress:'Đang khám',completed:'Đã hoàn tất',dispensed:'Đã cấp phát',done:'Đã khám xong',cancelled:'Đã hủy',booked:'Đã đặt lịch',arrived:'Đã đến khám',
 ordered:'Chờ thực hiện',pending_review:'Chờ duyệt kết quả',approved:'Đã duyệt',draft:'Đơn nháp',pending:'Chờ quản lý duyệt',rejected:'Bị từ chối',
 manual_price_entered:'Nhập giá khoản phải thu',manual_price_change_requested:'Đề nghị sửa giá nhập tay',manual_price_change_approved:'Duyệt sửa giá nhập tay',manual_price_change_rejected:'Từ chối sửa giá nhập tay',charge:'Khoản phải thu',procedure:'Thủ thuật',unpriced:'CHƯA CÓ GIÁ',consultation:'Khám',service:'Dịch vụ',service_import:'Lần nhập bảng giá',service_price_imported:'Đổi giá từ Excel',service_prices_imported:'Nhập bảng giá từ Excel',
 lab:'Xét nghiệm',ultrasound:'Siêu âm',xray:'X-quang',ecg:'Điện tim',cash:'Tiền mặt',transfer:'Chuyển khoản',discount:'Giảm phí',refund:'Hoàn tiền'};
Object.assign(LABEL,{patient_catalog_seeded:'Nạp danh mục có sẵn',patient_document_viewed:'Xem đủ số giấy tờ',patient_administrative_updated:'Sửa hồ sơ hành chính',patient_catalog_imported:'Nạp danh mục hồ sơ',child_visit_updated:'Sửa cân nặng và người đưa trẻ',practitioner_updated:'Sửa hồ sơ người hành nghề',practitioner_scope_warning:'Cảnh báo phạm vi chuyên môn',patient:'Người bệnh',user:'Nhân viên',catalog:'Danh mục'});
Object.assign(LABEL,{clinical_rx_replaced:'Vô hiệu đơn cũ do thay thế',clinical_rx_allergy_acknowledged:'Xác nhận vẫn kê khi đã biết dị ứng',clinical_rx_created:'Tạo đơn thuốc nháp',clinical_rx_updated:'Sửa đơn thuốc nháp',clinical_rx_locked:'Khóa đơn thuốc',clinical_rx_cancelled:'Hủy đơn thuốc',clinical_rx_printed:'In / in lại đơn thuốc',clinical_rx_json_exported:'Xuất dữ liệu đơn thuốc',clinical_prescription:'Đơn thuốc',prescription_settings:'Cài đặt đơn thuốc',prescription_settings_changed:'Đổi thông tin cơ sở kê đơn',drug:'Thuốc',drug_updated:'Rà soát thuốc',drug_merged:'Gộp danh mục thuốc',drugs_imported:'Nhập danh mục thuốc'});
LABEL.results_ready='Đã có kết quả';
LABEL.patient_allergies_updated='Sửa dị ứng thuốc';
LABEL.patient_history_viewed='Xem lịch sử khám';
const vi=code=>code==null?'—':(LABEL[code]||String(code));
const TONE={waiting:'warn',ordered:'warn',pending_review:'warn',pending:'warn',rejected:'error',cancelled:'error'};
const pill=code=>`<span class="status ${TONE[code]||''}">${esc(vi(code))}</span>`;
// Ngày hiển thị và nhập theo dd/mm/yyyy; gửi máy chủ theo ISO yyyy-mm-dd.
function showDay(v){const raw=String(v||'');if(/T\d{2}:\d{2}(:\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})$/.test(raw)){const parsed=new Date(raw);if(!isNaN(parsed)){const d=new Date(parsed.getTime()+7*60*60*1000),z=n=>String(n).padStart(2,'0');return `${z(d.getUTCDate())}/${z(d.getUTCMonth()+1)}/${d.getUTCFullYear()} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}`}}const m=String(v||'').match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);return m?`${m[3]}/${m[2]}/${m[1]}${m[4]?' '+m[4]+':'+m[5]:''}`:esc(v||'')}
function parseDay(v,label='Ngày'){const t=String(v||'').trim();if(!t)return null;let m=t.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);let y,mo,d;
 if(m){d=+m[1];mo=+m[2];y=+m[3]}else if((m=t.match(/^(\d{4})-(\d{2})-(\d{2})$/))){y=+m[1];mo=+m[2];d=+m[3]}else throw new Error(label+' phải theo dạng ngày/tháng/năm, ví dụ 05/12/2026');
 const dt=new Date(Date.UTC(y,mo-1,d));if(dt.getUTCFullYear()!==y||dt.getUTCMonth()!==mo-1||dt.getUTCDate()!==d)throw new Error(label+' không có thật: '+t);
 return `${y}-${String(mo).padStart(2,'0')}-${String(d).padStart(2,'0')}`}
function ageOf(dob){if(!dob)return'';const b=new Date(dob+'T00:00:00'),n=new Date();let a=n.getFullYear()-b.getFullYear();if(n.getMonth()<b.getMonth()||(n.getMonth()===b.getMonth()&&n.getDate()<b.getDate()))a--;return a}
function dateField(name,id,required=false,value=''){return `<div class="field"><label for="${esc(id)}">${esc(name)}</label><input id="${esc(id)}" name="${esc(id)}" class="date-vn" type="text" inputmode="numeric" autocomplete="off" placeholder="dd/mm/yyyy" maxlength="10" value="${esc(value?showDay(value):'')}" ${required?'required':''}></div>`}
// Sinh hiệu có cấu trúc, lưu thành một dòng chuẩn để biểu mẫu in đọc được và đọc ngược lại được.
const VITALS=[['pulse','Mạch','l/p',20,250],['bp','HA','mmHg'],['temp','Nhiệt độ','°C',34,43],['rr','Nhịp thở','l/p',5,60],['weight','Cân nặng','kg',0.5,300],['height','Chiều cao','cm',30,250],['spo2','SpO2','%',50,100]];
function vitalsFields(){return `<div class="field full"><label>Dấu hiệu sinh tồn</label><div class="vitals">${VITALS.map(([k,l,u])=>`<div class="field"><label for="v_${k}">${esc(l)} (${esc(u)})</label><input id="v_${k}" name="v_${k}" inputmode="decimal" autocomplete="off" placeholder="${k==='bp'?'120/80':''}"></div>`).join('')}</div><div id="vitals-flags" class="vitals-flags"></div></div>${textarea('Ghi chú sinh hiệu khác','v_note')}`}
function composeVitals(get){const parts=[];for(const [k,l,u,lo,hi] of VITALS){const raw=get('v_'+k).replace(',','.');if(!raw)continue;
 if(k==='bp'){if(!/^\d{2,3}\/\d{2,3}$/.test(raw))throw new Error('Huyết áp nhập theo dạng tâm thu/tâm trương, ví dụ 120/80');}
 else{const n=Number(raw);if(!Number.isFinite(n)||n<lo||n>hi)throw new Error(`${l} ngoài khoảng hợp lý (${lo}–${hi} ${u})`);}
 parts.push(`${l} ${raw} ${u}`)}const note=get('v_note');if(note)parts.push('Ghi chú: '+note);return parts.join('; ')}
function parseVitals(text){const out={},rest=[];for(const part of String(text||'').split(/;\s*/)){if(!part.trim())continue;let hit=false;
 for(const [k,l,u] of VITALS){const pre=l+' ',suf=' '+u;if(part.startsWith(pre)&&part.endsWith(suf)){out[k]=part.slice(pre.length,part.length-suf.length);hit=true;break}}
 if(!hit)rest.push(part.replace(/^Ghi chú: /,''))}out.note=rest.join('; ');return out}
function vitalsFlags(){const g=k=>String(($('v_'+k)||{}).value||'').replace(',','.');const f=[];const bp=g('bp').match(/^(\d{2,3})\/(\d{2,3})$/);
 if(bp){const s=+bp[1],d=+bp[2];if(s>=140||d>=90)f.push('Huyết áp cao');if(s<90||d<60)f.push('Huyết áp thấp')}
 const p=+g('pulse');if(g('pulse')&&(p>100||p<50))f.push(p>100?'Mạch nhanh':'Mạch chậm');
 if(g('temp')&&+g('temp')>=38)f.push('Sốt');if(g('spo2')&&+g('spo2')<94)f.push('SpO2 thấp');
 const w=+g('weight'),h=+g('height');let bmi='';if(w&&h){const b=w/Math.pow(h/100,2);bmi=`BMI ${b.toFixed(1)}`;if(b>=25)f.push('Thừa cân (BMI ≥ 25)');if(b<18.5)f.push('Thiếu cân (BMI < 18,5)')}
 const box=$('vitals-flags');if(box)box.innerHTML=(bmi?`<span class="status">${bmi}</span> `:'')+f.map(x=>`<span class="status warn">${esc(x)}</span>`).join(' ')}

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
const taskStatus=s=>({pending:'Chưa thực hiện',done:'Đã thực hiện',cancelled:'Đã hủy'})[s]||vi(s);
const OPEN=v=>!['completed','cancelled'].includes(v.status);
const hidden=(name,value)=>`<input type="hidden" name="${esc(name)}" value="${esc(value)}">`;
const btn=(label,action,attrs='',cls='ghost smallbtn')=>`<button type="button" class="${cls}" data-action="${esc(action)}" ${attrs}>${esc(label)}</button>`;
const step=(n,title)=>`<span class="stepno">${n}</span>${esc(title)}`;
function stepCard(n,title,content,extra=''){return `<section class="card" ${extra}><h2>${step(n,title)}</h2>${content}</section>`}
function details(summary,content,open=false){return `<details class="card fold" ${open?'open':''}><summary>${esc(summary)}</summary><div class="fold-body">${content}</div></details>`}
const empty=text=>`<div class="empty">${esc(text)}</div>`;
// Hàng chờ: mỗi dòng là một nút bấm lớn, dùng tốt trên điện thoại.
function queue(items,{kind,current,emptyText}){if(!items.length)return empty(emptyText);
 return `<div class="queue">${items.map(x=>`<button type="button" class="queue-item${x.id===current?' current':''}" data-action="pick" data-kind="${esc(kind)}" data-id="${Number(x.id)}" aria-pressed="${x.id===current}"><span class="queue-main">${x.main}</span><span class="queue-sub">${x.sub||''}</span></button>`).join('')}</div>`}
function stats(list){return `<div class="cards">${list.map(([name,value])=>`<div class="stat"><span>${esc(name)}</span><b>${esc(value)}</b></div>`).join('')}</div>`}
function tabs(current,list,kind){return `<div class="tabs" role="tablist">${list.map(([id,label])=>`<button type="button" role="tab" class="tab" data-action="tab" data-kind="${esc(kind)}" data-tab="${esc(id)}" aria-selected="${current===id}">${esc(label)}</button>`).join('')}</div>`}
function patientHead(v){return `<div class="patient-head"><div><b>${esc(v.patient_name)}</b> <span class="muted">${esc(v.patient_code||'')}</span></div><div class="muted">${esc(v.patient_sex||'—')} · ${v.patient_dob?ageOf(v.patient_dob)+' tuổi · sinh '+showDay(v.patient_dob):'chưa có ngày sinh'} · lượt #${v.id} ngày ${showDay(v.created_at)}</div><div>${pill(v.status)}</div></div>`}
// Bảng tự chuyển thành thẻ trên màn hình hẹp: gắn nhãn cột cho từng ô.
function labelTables(root){root.querySelectorAll('table.table').forEach(table=>{const heads=[...table.querySelectorAll('thead th')].map(th=>th.textContent);table.querySelectorAll('tbody tr').forEach(tr=>[...tr.children].forEach((td,i)=>{if(heads[i]&&td.colSpan<2)td.setAttribute('data-label',heads[i])}))})}

// ---------- Khung trang, menu, số đếm hàng chờ ----------
const shellHeader=document.querySelector('.shell-header');
function stickyOffset(){return (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--shell-h'))||0)+(document.querySelector('.doctor-sticky')?.getBoundingClientRect().height||0)+12;}
let lastDoctorTab={visit:null,target:null};
function measureShellHeader(){
 const height=shellHeader&&!window.matchMedia('(max-width:900px)').matches?shellHeader.getBoundingClientRect().height:0;
 document.documentElement.style.setProperty('--shell-h',height+'px');
}
if(shellHeader){new ResizeObserver(measureShellHeader).observe(shellHeader);window.addEventListener('resize',measureShellHeader);measureShellHeader();}

function pagesFor(r){return [...(menus[r]||menus.reception),['password','Đổi mật khẩu']]}
function viewInit(){if(!auth){renderLogin();return}document.body.classList.remove('login-view');const r=role();const m=pagesFor(r);
 if(!m.some(x=>x[0]===active))active=m[0][0];$('page-title').textContent=m.find(x=>x[0]===active)[1];$('user-label').textContent=auth.user.name+' · '+roles[r];$('logout').classList.remove('hidden');$('change-password').classList.remove('hidden');
 const switcher=auth.user.roles.filter(k=>menus[k]).length>1?selectField('Vai trò đang dùng','role_switch',auth.user.roles.filter(k=>menus[k]).map(k=>[k,roles[k]])):'';
 $('navigation').innerHTML=switcher+(menus[r]||[]).map(([id,label])=>`<button class="navbutton" data-action="navigate" data-page="${esc(id)}" aria-current="${active===id?'page':'false'}"><span>${esc(label)}</span><span class="badge hidden" data-count="${esc(id)}"></span></button>`).join('');
 if($('role_switch'))$('role_switch').value=r;}
async function loadUi(){try{ui=await api('/ui-settings');uiLoaded=true}catch(e){uiLoaded=false}}
// Số việc đang chờ trên menu. /api/queue-counts chỉ trả con số theo vai trò và KHÔNG gia hạn phiên,
// nên hỏi định kỳ không làm mất tự đăng xuất sau 20 phút không thao tác.
const lastCounts={};let countEpoch=0;
async function refreshCounts(){if(!auth)return;const epoch=++countEpoch;let counts;
 try{counts=await api('/queue-counts')}catch(e){return}
 if(epoch!==countEpoch||!auth)return;
 for(const el of document.querySelectorAll('[data-count]')){const page=el.dataset.count,n=counts[page];if(n==null)continue;
  el.textContent=String(n);el.classList.toggle('hidden',!n);el.setAttribute('aria-label',n?n+' việc đang chờ':'');
  // Hàng chờ của màn hình đang mở có thêm việc: báo ngay trên màn hình, không tự vẽ lại để khỏi mất chữ đang gõ.
  const before=lastCounts[page];
  if(page===active&&before!=null&&n>before&&$('workspace').getAttribute('aria-busy')==='false'&&!$('queue-news'))$('workspace').insertAdjacentHTML('afterbegin',`<div id="queue-news" class="queue-news" role="status"><span>Hàng chờ có thêm ${n-before} việc mới.</span><button type="button" class="btn smallbtn" data-action="navigate" data-page="${esc(page)}">Tải lại hàng chờ</button></div>`);
  lastCounts[page]=n}}
const COUNT_EVERY_MS=60000;let countTimer=null;
function scheduleCounts(){clearInterval(countTimer);countTimer=setInterval(()=>{if(auth&&!document.hidden)refreshCounts()},COUNT_EVERY_MS)}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&auth)refreshCounts()});
scheduleCounts();
let renderEpoch=0;
const SCREENS={reception:receptionScreen,prices:pricesScreen,doctor:doctorScreen,nurse:nurseScreen,lab:labScreen,pharmacy:pharmacyScreen,cashier:cashierScreen,manager:managerScreen,'price-management':priceManagementScreen,admin:adminScreen,settings:settingsScreen,password:passwordPage};
async function render(){if(!auth){renderLogin();return}viewInit();const page=active,epoch=++renderEpoch;$('workspace').setAttribute('aria-busy','true');$('workspace').dataset.page=page;$('workspace').innerHTML=card('Đang tải dữ liệu ...');try{
 if(!uiLoaded)await loadUi();
 const out=await SCREENS[page]();if(epoch!==renderEpoch)return;
 const html=typeof out==='string'?out:out.html;$('workspace').innerHTML=html;labelTables($('workspace'));if(out&&out.after)out.after();
 }catch(e){if(epoch!==renderEpoch)return;$('workspace').innerHTML=card(`<div class="empty">Không thể tải trang: ${esc(e.message)}</div>`)}finally{if(epoch===renderEpoch){await refreshCounts();if(epoch===renderEpoch)$('workspace').setAttribute('aria-busy','false')}}}
function renderLogin(){document.body.classList.add('login-view');scopeWarnings.clear();priceFile=null;pricePreview=null;priceResult=null;auth=null;uiLoaded=false;for(const k in lastCounts)delete lastCounts[k];$('navigation').innerHTML='';$('page-title').textContent='Đăng nhập';$('user-label').textContent='Chưa đăng nhập';$('logout').classList.add('hidden');$('change-password').classList.add('hidden');$('workspace').setAttribute('aria-busy','false');
 const users=[['letan','Lễ tân'],['bs_noi','Bác sĩ Nội'],['bs_san','Bác sĩ Sản'],['kythuat','Kỹ thuật viên'],['duoc','Nhân viên dược'],['thungan','Thu ngân'],['quanly','Quản lý'],['quantri','Quản trị viên'],['dieuduong','Điều dưỡng']];
 $('workspace').innerHTML=`<section class="card login-card"><img class="login-logo" src="/assets/MinhDuc_logo_mau.svg" alt="Phòng khám đa khoa Minh Đức"><h1>Phòng khám đa khoa Minh Đức</h1><p class="login-subtitle">Đăng nhập bằng tài khoản của bạn</p><form data-form="login" class="fields">${serverMode==='lan'?field('Tài khoản nhân viên','username','text','',true):selectField('Tài khoản mô phỏng','username',users)}${field('Mật khẩu','password','password','',true)}<div class="field full"><button class="btn" type="submit">Đăng nhập</button><p class="hint">${serverMode==='lan'?'Dùng tài khoản riêng do quản trị cấp. Phiên kết thúc sau 20 phút không hoạt động hoặc tối đa 8 giờ.':'Nhập mật khẩu đã chọn khi khởi động bản demo cục bộ.'}</p></div></form></section>`;}

let patientCatalog=[];
const ADMIN_FIELDS=[['ethnicity','Dân tộc'],['occupation','Nghề nghiệp'],['workplace','Nơi làm việc / học tập'],['province','Tỉnh / thành'],['commune','Xã / phường / đặc khu'],['address_detail','Địa chỉ chi tiết']];
function valueField(label,name,value='',type='text'){return `<div class="field"><label>${esc(label)}<input name="${name}" type="${type}" ${name==='weight_kg'?'step="any" min="0.01" max="500"':''} value="${esc(value??'')}"></label></div>`}
const catalogTimers=new WeakMap(),catalogRequests=new WeakMap();
function catalogCombo(kind,label,p={}){
 const id='catalog-'+kind+'-'+(p.id||'new'),value=p[kind]||'',number=p[kind+'_code']||'';
 const parent=p.province_code||(!p.id&&patientCatalog.some(x=>x.code===ui.default_province_code)?ui.default_province_code:'');
 return `<div class="field catalog-combo" data-catalog-combo="${kind}">${hidden(kind,value)}${hidden(kind+'_code',number)}<label for="${id}">${label}</label><input id="${id}" name="${kind}_search" data-catalog-search="${kind}" value="${esc(value)}" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-results" ${kind==='commune'&&!parent?'disabled':''} placeholder="${kind==='commune'?'Chọn tỉnh rồi gõ tên xã không dấu':'Gõ tên hoặc tên gọi khác không dấu'}"><div id="${id}-results" class="catalog-results hidden" role="listbox"></div><small class="muted" data-catalog-hint>${kind==='commune'?'Mã xã trong danh mục là mã thuế TMS; huyện cũ chỉ để tham khảo.':'Để trống khi chưa có thông tin; không tự chọn dân tộc.'}</small></div>`
}
function patientAdministrative(p={}){
 const type=p.document_type||(p.citizen_id?'identity':'none'),provinceCode=p.province_code||(!p.id&&patientCatalog.some(x=>x.code===ui.default_province_code)?ui.default_province_code:'')||'';
 const provinceName=p.province||patientCatalog.find(x=>x.code===provinceCode)?.name||'';
 const province=`<div class="field">${hidden('province',provinceName)}<label>Tỉnh / thành<select name="province_code" data-catalog="province"><option value="">${esc(p.province&&!provinceCode?p.province+' (hồ sơ cũ)':'— Chọn —')}</option>${provinceCode&&!patientCatalog.some(x=>x.code===provinceCode)?`<option value="${esc(provinceCode)}" selected>${esc(provinceName)} (ngừng dùng)</option>`:''}${patientCatalog.map(x=>`<option value="${esc(x.code)}" data-name="${esc(x.name)}" ${x.code===provinceCode?'selected':''}>${esc(p.id&&p.province_code===x.code&&p.province?p.province+(p.province!==x.name?' (hiện nay: '+x.name+')':''):x.name)}</option>`).join('')}</select></label></div>`;
 return `<div class="field"><label>Loại giấy tờ<select name="document_type">${[['none','Không có'],['identity','CCCD / số định danh'],['passport','Hộ chiếu']].map(([k,v])=>`<option value="${k}" ${type===k?'selected':''}>${v}</option>`).join('')}</select></label></div>`+valueField('Số giấy tờ (nếu có)','document_number',p.document_number||p.citizen_id||'')+catalogCombo('ethnicity','Dân tộc',p)+D0.occupation(p)+valueField('Nơi làm việc / học tập','workplace',p.workplace)+province+catalogCombo('commune','Xã / phường / đặc khu',p)+valueField('Địa chỉ chi tiết','address_detail',p.address_detail);
}
function patientAdministrativeForm(p){return `<form class="fields" data-form="patient-administrative">${hidden('patient_id',p.id)}${patientAdministrative(p)}<p class="hint wide">Địa chỉ cũ: ${esc(p.address||'Chưa có')}</p><div class="wide"><button class="btn">Lưu hồ sơ hành chính</button></div></form>`}
function administrativeBody(value){const b={document_type:value('document_type'),document_number:value('document_number')||null};for(const [k,label] of ADMIN_FIELDS){b[k]=value(k)||null;if(['province','commune','ethnicity'].includes(k)){b[k+'_code']=value(k+'_code')||null;if(k!=='province'&&value(k+'_search')&&!b[k])throw new Error('Chọn '+label+' từ kết quả tìm kiếm')}}b.occupation_code=value('occupation_code')||null;return b}
async function lookupCatalog(input){
 if(!input.isConnected||input.disabled)return;
 const kind=input.dataset.catalogSearch,box=input.closest('[data-catalog-combo]'),list=box.querySelector('[role=listbox]');
 const serial=(catalogRequests.get(input)||0)+1;catalogRequests.set(input,serial);
 const province=input.form.querySelector('[name=province_code]')?.value||'';
 const rows=await api('/patient-catalog?'+new URLSearchParams({kind,province_code:kind==='commune'?province:'',q:input.value,limit:'30'}));
 if(!input.isConnected||catalogRequests.get(input)!==serial)return;
 list.innerHTML=rows.length?rows.map((x,i)=>`<button type="button" role="option" tabindex="-1" id="${input.id}-option-${i}" data-action="catalog-pick" data-code="${esc(x.code)}" data-name="${esc(x.name)}" data-reference="${esc(kind==='ethnicity'?x.aliases:x.legacy_district)}"><span>${esc(x.name)}</span>${(kind==='ethnicity'?x.aliases:x.legacy_district)?`<small class="muted">${esc(kind==='ethnicity'?x.aliases:'Huyện cũ (tham khảo): '+x.legacy_district)}</small>`:''}</button>`).join(''):'<p>Không có kết quả. Kiểm tra tỉnh hoặc từ khóa.</p>';
 list.classList.remove('hidden');input.setAttribute('aria-expanded','true');input.dataset.optionIndex='-1';
}
function chooseCatalog(button){const box=button.closest('[data-catalog-combo]'),kind=box.dataset.catalogCombo,input=box.querySelector('[data-catalog-search]');box.querySelector(`[name="${kind}"]`).value=button.dataset.name;box.querySelector(`[name="${kind}_code"]`).value=button.dataset.code;input.value=button.dataset.name;box.querySelector('[role=listbox]').classList.add('hidden');input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');box.querySelector('[data-catalog-hint]').textContent=kind==='ethnicity'?(button.dataset.reference||''):'Mã thuế TMS: '+button.dataset.code+(button.dataset.reference?' · Huyện cũ (tham khảo): '+button.dataset.reference:'');input.focus();}
function patientAge(birthday,months){if(months!=null&&months<72)return months+' tháng';return (birthday?ageOf(birthday):'Chưa rõ')+' tuổi'}
function childDetails(v){return `<form class="fields" data-form="child-details">${hidden('visit_id',v.id)}${hidden('version',v.version)}${valueField('Cân nặng khi khám (kg)','weight_kg',v.weight_kg,'number')}${valueField('Họ tên người đưa trẻ đi khám','escort_name',v.escort_name)}${valueField('Quan hệ với trẻ','escort_relationship',v.escort_relationship)}${valueField('Điện thoại người đưa trẻ','escort_phone',v.escort_phone,'tel')}<p class="hint wide">Trẻ dưới 72 tháng phải có đủ các thông tin này trước khi kê đơn.</p><div class="wide"><button class="btn">Lưu cân nặng và người đưa trẻ</button></div></form>`}
function practitionerForm(u,scopes){return `<form class="fields" data-form="practitioner">${hidden('uid',u.id)}${[['printed_name','Họ tên in trên giấy tờ'],['printed_title','Chức danh in'],['practice_license','Số giấy phép hành nghề'],['certificate_provider','Nhà cung cấp chứng thư số'],['certificate_serial','Số sê-ri chứng thư số']].map(([k,l])=>valueField(l,k,u[k])).join('')}${valueField('Hạn dùng chứng thư số (dd/mm/yyyy)','certificate_expiry',u.certificate_expiry?showDay(u.certificate_expiry):'')}<fieldset class="wide"><legend>Phạm vi chuyên môn</legend>${scopes.map(x=>`<label class="check"><input type="checkbox" name="practice_scopes" value="${esc(x)}" ${u.practice_scopes.includes(x)?'checked':''}>${esc(x)}</label>`).join('')}</fieldset><p class="hint wide">Thông tin mô tả; chưa ký số.</p><div class="wide"><button class="btn">Lưu hồ sơ người hành nghề</button></div></form>`}
function catalogImport(){return card(`<p>Phần mềm đã có sẵn danh mục tỉnh/xã và 54 dân tộc. Nạp lại cập nhật theo mã; mục bị bỏ được ngừng dùng, hồ sơ cũ giữ nguyên. Bỏ trống tệp để nạp lại bản đi kèm.</p><form data-form="patient-catalog" class="fields">${selectField('Danh mục cần nạp lại','catalog_kind',[['all','Cả hai bản đi kèm'],['geography','Tỉnh/xã'],['ethnicity','Dân tộc']])}<label>Tệp công khai cập nhật (CSV UTF-8 hoặc Excel .xlsx)<input type="file" name="file" accept=".csv,.xlsx"></label><div class="wide"><button class="btn">Nạp lại danh mục</button></div></form>`,'Nạp lại danh mục')}


// ---------- Lễ tân: tìm/tạo bệnh nhân → tạo lượt ----------
function patientTable(list){return t(list.slice(0,30).map(p=>`<tr><td>${esc(p.code)}</td><td>${esc(p.full_name)}</td><td>${showDay(p.date_of_birth)}</td><td>${esc(p.phone||'')}</td><td>${esc(p.document_number||p.citizen_id||'')}</td><td>${btn(sel.patient===p.id?'Đang chọn':'Chọn','pick',`data-kind="patient" data-id="${p.id}"`,sel.patient===p.id?'btn smallbtn':'ghost smallbtn')}</td></tr>`),['Mã','Bệnh nhân','Ngày sinh','Điện thoại','Giấy tờ (4 số cuối)',''])}
async function receptionScreen(){
 const q=sel.patientQuery;patientCatalog=await api('/patient-catalog?kind=province&limit=100');
 const [patients,doctors,services,visits,appts]=await Promise.all([api('/patients'+(q?'?q='+encodeURIComponent(q):'')),api('/staff'),api('/services'),api('/visits'),api('/appointments')]);
 patientList=patients;let chosen=null;
 if(sel.patient){chosen=patients.find(p=>p.id===sel.patient)||await api('/patients/'+sel.patient).catch(()=>null);if(!chosen)sel.patient=null;else chosen=await api('/patients/'+chosen.id)}
 const waiting=visits;
 const search=`<form data-form="patient-search" class="searchbar"><input name="q" id="search-patients" value="${esc(q)}" placeholder="Tên, mã, điện thoại hoặc đủ số giấy tờ" aria-label="Tìm bệnh nhân"><button class="btn">Tìm</button>${q?btn('Xóa tìm','clear-search','','ghost'):''}</form>`;
 const newPatient=`<form class="fields" data-form="patient">${field('Họ và tên','full_name','text','',true)}${dateField('Ngày sinh','date_of_birth',true)}<div class="field"><label for="sex">Giới tính</label><select id="sex" name="sex" required><option value="">— Chọn —</option><option value="Nam">Nam</option><option value="Nữ">Nữ</option><option value="Khác">Khác</option></select></div>${field('Điện thoại','phone','tel','0912345678',true)}${patientAdministrative()}${field('Địa chỉ','address')}<div class="wide"><button class="btn" type="submit">Lưu bệnh nhân mới</button></div></form>`;
 const visitForm=chosen?`<div class="patient-head"><div><b>${esc(chosen.full_name)}</b> <span class="muted">${esc(chosen.code)}</span></div><div class="muted">${esc(chosen.sex||'')} · sinh ${showDay(chosen.date_of_birth)} · ${esc(chosen.phone||'')}</div></div>${patientAdministrativeForm(chosen)}${allergyEditor(chosen)}<form class="fields" data-form="visit">${hidden('patient_id',chosen.id)}${selectField('Bác sĩ phụ trách','doctor_id',doctors.map(d=>[d.id,d.full_name]))}${selectField('Dịch vụ khám','service_id',services.map(s=>[s.id,`${s.name} – ${servicePrice(s)}`]))}<div class="wide"><button class="btn" type="submit">Tạo lượt khám</button></div></form>`:empty('Chọn bệnh nhân ở bước 1 hoặc thêm bệnh nhân mới.');
 const queueHtml=t(waiting.map(v=>`<tr><td>#${v.id}</td><td>${esc(v.patient_name)}<div class="muted">${showDay(v.created_at)}</div></td><td>${pill(v.status)}</td><td>${formButtons('intake',v.id)}${btn('Đóng lượt bỏ dở','close-abandoned',`data-id="${v.id}"`)}</td></tr>`),['Lượt','Bệnh nhân','Trạng thái','Phiếu tiếp đón']);
 const apptForm=`<form data-form="appointment" class="fields">${selectField('Bệnh nhân','patient_id',patients.map(p=>[p.id,p.code+' – '+p.full_name]))}${selectField('Bác sĩ','doctor_id',doctors.map(d=>[d.id,d.full_name]))}${dateField('Ngày hẹn','appt_day',true)}${field('Giờ hẹn (24 giờ)','appt_time','text','08:30',true)}${field('Lý do khám','reason')}<div class="wide"><button class="btn" ${patients.length?'':'disabled'}>Đặt lịch</button></div></form>`+t(appts.map(x=>`<tr><td>${esc(x.patient_name)}</td><td>${esc(x.doctor_name)}</td><td>${showDay(x.scheduled_at)}</td><td>${pill(x.status)}</td></tr>`),['Bệnh nhân','Bác sĩ','Thời gian','Trạng thái']);
 return {html:stepCard(1,'Tìm bệnh nhân',search+patientTable(patients)+`<details class="inline-fold" ${q&&!patients.length?'open':''}><summary>Thêm bệnh nhân mới</summary>${newPatient}</details>`)+
  stepCard(2,'Tạo lượt khám',visitForm,'id="visit-step"')+
  card(queueHtml,`Lượt đang chờ (${waiting.length})`)+details('Lịch hẹn',apptForm),
  after(){if(chosen)setAllergyState(chosen);if(chosen&&$('patient_id'))$('patient_id').value=String(chosen.id);const ap=document.querySelector('[data-form="appointment"] [name="patient_id"]');if(ap&&chosen)ap.value=String(chosen.id)}}}

// Bảng giá dịch vụ chỉ đọc, để lễ tân báo giá cho người bệnh.
async function pricesScreen(){const list=await api('/services');
 return card(`<div class="searchbar"><input id="price-filter" placeholder="Gõ tên hoặc mã dịch vụ để lọc" aria-label="Lọc bảng giá"></div>`+t(list.map(x=>`<tr data-search="${esc(((x.code||'')+' '+x.name).toLowerCase())}"><td>${esc(x.code||'')}</td><td>${esc(x.name)}</td><td class="price">${servicePrice(x)}</td></tr>`),['Mã','Dịch vụ','Giá'])+'<p class="hint">Chỉ xem. Giá do quản lý cập nhật trong menu Quản lý › Danh mục.</p>',`Bảng giá dịch vụ (${list.length})`)}
function allergyEditor(p){return `<form class="fields" data-form="allergies">${hidden('patient_id',p.id)}${selectField('Khai thác dị ứng thuốc','allergy_state',[['unknown','Chưa khai thác'],['none','Không dị ứng'],['known','Có dị ứng (ghi tên thuốc)']])}<div class="field"><label for="allergy_text">Thuốc / phản ứng đã biết</label><textarea id="allergy_text" name="allergy_text" maxlength="2000">${esc(p.allergies==='Không dị ứng'?'':p.allergies||'')}</textarea></div><div class="wide"><button class="btn">Lưu dị ứng thuốc</button></div></form>`}
function setAllergyState(p){const input=document.querySelector('[data-form="allergies"] [name="allergy_state"]');if(input)input.value=p.allergies==='Không dị ứng'?'none':p.allergies?'known':'unknown'}
function showM0Dialog(content){document.getElementById('m0-dialog')?.remove();document.body.insertAdjacentHTML('beforeend',`<dialog id="m0-dialog"><button class="ghost" type="button" data-action="close-m0-dialog">Đóng (Esc)</button>${content}</dialog>`);$('m0-dialog').showModal()}
// ---------- Bác sĩ: hàng chờ → phiếu khám, chỉ định, đơn thuốc, hoàn tất ----------
function rxItemRow(meds){return `<div class="rx-line fields">${selectField('Thuốc trong danh mục','medicine_id',meds.map(x=>[x.id,`${x.name} (${x.base_unit})`]))}${selectField('Đơn vị kê','unit_id',[['','Đơn vị cơ sở'],...(meds[0]?.units||[]).map(u=>[u.id,u.name+' = '+u.base_factor+' đơn vị cơ sở'])])}${field('Số lượng','quantity','number','1',true)}${field('Cách dùng','directions','text','Ví dụ: uống sau ăn')}<div class="wide"><button class="ghost smallbtn" type="button" data-action="remove-rx-row">Xóa dòng</button></div></div>`}
function prescribable(meds){return meds.filter(x=>!x.controlled||(ui.controlled_drugs&&cap('controlled_prescriber')))}
async function controlledReviewCard(){
 if(!(ui.controlled_drugs&&cap('controlled_reviewer')))return '';
 const list=await api('/controlled-review-queue');
 return card(t(list.map(q=>`<tr><td>#${q.id} / ${esc(q.patient_code)}</td><td>${esc(q.diagnosis)}</td><td>${esc(q.drug_lines)}</td></tr>`),['Đơn','Chẩn đoán','Thuốc kiểm soát'])+
  `<form data-form="controlled-approve" class="fields">${selectField('Đơn chờ duyệt','prescription_id',list.map(q=>[q.id,'#'+q.id]))}${field('Lý do duyệt','reason','text','',true)}${field('Tham chiếu sổ kiểm soát','register_ref','text','',true)}<div class="wide"><button class="btn" ${list.length?'':'disabled'}>Duyệt đơn kiểm soát</button></div></form>`,`Đơn thuốc kiểm soát chờ bác sĩ thứ hai duyệt (${list.length})`)}
async function doctorScreen(){
 const [open,visitHistory,daily]=await Promise.all([api('/visits'),api('/visits?history=true'),api('/doctor/queue?'+new URLSearchParams({day:sel.doctorDay||'',q:sel.doctorQuery||''}))]);
 const visits=[...open,...visitHistory,...daily.visits];
 if(!daily.visits.some(v=>v.id===sel.visit))sel.visit=null;
 const review=(await M5.reviewQueue())+await controlledReviewCard();
 const filter=`<form data-form="doctor-filter" class="fields">${dateField('Ngày tiếp đón (bỏ trống: mọi lượt chờ)','doctor_day',false,daily.day)}${field('Tìm tên không dấu','doctor_query')}<div class="wide"><button class="btn">Tìm người bệnh (F4)</button></div></form>`;
 const doctorStatus=s=>`<span class="status ${({waiting_results:'results-pending',results_ready:'ready',in_progress:'progress',completed:'complete'})[s]||TONE[s]||''}">${esc(s==='waiting_results'?'Chờ kết quả cận lâm sàng':vi(s))}</span>`;
 const head=card(filter+queue(daily.visits.map(v=>({id:v.id,main:`${v.daily_number}. ${esc(v.patient_name)}`,sub:`${esc(patientAge(v.date_of_birth,v.age_months))} · ${esc(v.sex||'')} · ${doctorStatus(v.queue_status)} · ${showDay(v.created_at)}`})),{kind:'visit',current:sel.visit,emptyText:'Không có lượt trong ngày đã chọn.'}),`Danh sách khám · ${open.length} lượt chưa hoàn tất`)+
  details('Lượt đã kết thúc (100 gần nhất)',(visitHistory.length?`<div class="toolbar-actions">${selectField('Mở lượt khác (đã xong)','visit_choose',[['','— Chọn —'],...visitHistory.map(v=>[v.id,`#${v.id} – ${v.patient_name} (${vi(v.status)})`])])}</div>`:empty('Chưa có lượt đã kết thúc.')));
 if(!sel.visit)return {html:review+`<div class="doctor-layout"><aside>${head}</aside><section class="card">Chọn một lượt khám</section></div>`,after(){if($('doctor_query'))$('doctor_query').value=sel.doctorQuery||''}};
 const vid=sel.visit;
 const [v,ords,rxs,cls,meds,care]=await Promise.all([api('/visits/'+vid),api('/orders?visit_id='+vid),api('/prescriptions?visit_id='+vid),api('/cls-services'),api('/dispensable-medicines'),api('/visits/'+vid+'/care')]);
 const done=!OPEN(v);
 const [nurses,assigned,history,addenda]=await Promise.all([done?[]:api('/nurses'),done?[]:api('/visits/'+vid+'/nurses'),api('/visits/'+vid+'/revisions'),done&&ui.addendum?api('/visits/'+vid+'/addenda'):[]]);
 const mine=ords.filter(o=>o.visit_id===vid),rx=rxs.find(x=>x.visit_id===vid&&x.status!=='cancelled')||rxs.find(x=>x.visit_id===vid);
 const codesForm=await D0.clinical(v);
 const exam=codesForm+`<form data-form="clinical" class="fields">${hidden('visit_id',vid)}${hidden('version',v.version)}${textarea('Lý do khám và triệu chứng','chief_complaint')}${textarea('Bệnh sử, tiền sử','history')}${vitalsFields()}${textarea('Chẩn đoán','diagnosis','Mô tả chẩn đoán của bác sĩ; mã bệnh chọn riêng phía trên')}${textarea('Hướng điều trị, lời dặn','treatment')}${dateField('Hẹn tái khám','follow_up')}<div class="wide actions"><button class="btn">Lưu phiếu khám (F2)</button> <button class="ghost" type="button" data-action="export-form" data-kind="visit" data-id="${vid}" data-format="pdf">Phiếu khám PDF</button> <button class="ghost" type="button" data-action="export-form" data-kind="visit" data-id="${vid}" data-format="docx">Phiếu khám Word</button> <button class="ghost" type="button" data-action="export-form" data-kind="followup" data-id="${vid}" data-format="pdf">Giấy hẹn tái khám</button></div></form>`;
 const orderRows=mine.map(o=>`<tr><td>${esc(o.name)}${scopeWarnings.has(o.id)?`<div class="notice" role="alert" data-scope-warning="${o.id}">${esc(scopeWarnings.get(o.id))}</div>`:''}${o.unpriced?' <span class="status warn">CHƯA CÓ GIÁ</span>':''}<div class="muted">${esc(vi(o.category))}</div>${o.result_text?`<div class="result-text">${esc(o.result_text).replace(/\n/g,'<br>')}</div>`:''}</td><td>${pill(o.status)}</td><td><div class="multi-actions">${o.status==='requested'?btn('Duyệt chỉ định / ghi phí','authorize-order',`data-id="${o.id}"`,'btn smallbtn'):''}${o.lab_report_status==='pending_review'&&o.lab_report_id?`<button data-m5="review" data-id="${o.lab_report_id}">Duyệt phiếu theo chỉ số</button>`:o.status==='pending_review'?btn('Duyệt kết quả','approve',`data-id="${o.id}"`,'btn smallbtn'):''}${o.file_name?btn('Tệp đính kèm','file',`data-id="${o.id}"`):''}${o.lab_report_id?`<button data-m5="view" data-id="${o.lab_report_id}">Xem phiếu theo chỉ số</button>`:o.status==='approved'&&['lab','ultrasound','xray','ecg'].includes(o.category)?formButtons(o.category,o.id):formButtons('order',o.id)}${!done&&!['cancelled'].includes(o.status)?btn('Đề nghị hủy','cancel-order',`data-id="${o.id}"`):''}</div></td></tr>`);
 const orders=(done?'':`<form class="fields" data-form="order">${hidden('visit_id',vid)}${selectField('Dịch vụ theo bảng giá','service_id',cls.map(x=>[x.id,`${vi(x.category)} – ${x.name} (${servicePrice(x)})`]))}${selectField('Ghi phí','defer_approval',[['0','Xác nhận và ghi phí ngay'],['1','Lưu nháp, chưa phát sinh tiền']])}<div class="wide"><button class="btn" ${cls.length?'':'disabled'}>Thêm chỉ định</button></div></form>`)+t(orderRows,['Chỉ định / kết quả','Trạng thái','Thao tác']);
 const pmeds=prescribable(meds);
 const warehouseRxHtml=rx?`<div class="rx-view"><p>${esc(rx.drug_lines).replace(/\n/g,'<br>')}</p><p>${pill(rx.status)}</p><div class="multi-actions">${formButtons('rx',rx.id)}${rx.status==='draft'?btn('Hủy đơn nháp','cancel-rx',`data-id="${rx.id}"`,'btn-danger smallbtn'):''}</div>${rx.status==='cancelled'?'<p class="hint">Đơn đã hủy được lưu, không lập lại đơn mới cho lượt này.</p>':''}</div>`:
  done?empty('Lượt này không có đơn thuốc.'):`<form data-form="rx" class="fields">${hidden('visit_id',vid)}<div class="field full"><div class="rx-items" id="rx-items">${rxItemRow(pmeds)}</div><button class="ghost" type="button" data-action="add-rx-row">Thêm dòng thuốc</button></div>${textarea('Lời dặn','instructions')}${dateField('Ngày hẹn tái khám','rx_follow_up')}<p class="hint wide">Lưu chẩn đoán ở bước 1 trước khi lưu đơn. Nhà thuốc cấp đúng theo đơn này.</p><div class="wide"><button class="btn" ${pmeds.length?'':'disabled'}>Lưu đơn thuốc</button></div></form>`;
 const rxHtml=await M6.visit(vid,done)+details('Kê / cấp thuốc từ kho (quy trình hiện có)',warehouseRxHtml,!!rx);
 const tasks=t(care.tasks.map(task=>`<tr><td>${esc(task.description)}</td><td>${esc(taskStatus(task.status))}</td><td>${esc(task.execution_content||'')}<div class="muted">${showDay(task.executed_at||task.created_at)}</div></td><td>${task.status==='pending'&&!done?btn('Hủy y lệnh','cancel-task',`data-id="${task.id}"`,'btn-danger smallbtn'):''}</td></tr>`),['Y lệnh','Trạng thái','Ghi nhận','']);
 const nursing=(done?'':`<form class="fields" data-form="assign-nurse">${hidden('visit_id',vid)}${selectField('Phân công điều dưỡng','nurse_id',nurses.map(n=>[n.id,n.full_name]))}<div class="wide"><button class="ghost" ${nurses.length?'':'disabled'}>Phân công</button></div></form>`+
  (assigned.length?`<form class="fields" data-form="nursing-task">${hidden('visit_id',vid)}${selectField('Điều dưỡng thực hiện','nurse_id',assigned.map(n=>[n.nurse_id,n.full_name]))}${textarea('Nội dung y lệnh','content')}<div class="wide"><button class="btn">Giao y lệnh</button></div></form>`:'<p class="hint">Phân công điều dưỡng trước khi giao y lệnh.</p>'))+tasks+
  (care.notes.length?t(care.notes.map(n=>`<tr><td>${esc(n.nurse_name)}</td><td>${esc(n.content)}</td><td>${showDay(n.created_at)}</td></tr>`),['Điều dưỡng','Ghi nhận chăm sóc','Thời gian']):'');
 const finish=done?(ui.addendum&&v.status==='completed'?`<p class="hint">Hồ sơ đã khóa. Bổ sung hoặc đính chính phải lập phụ lục, quản lý khác duyệt.</p>${addenda.length?t(addenda.map(a=>`<tr><td>${esc(a.reason)}</td><td>${esc(a.content)}</td><td>${pill(a.status)}</td></tr>`),['Lý do','Nội dung','Duyệt']):''}<form data-form="addendum" class="fields">${hidden('visit_id',vid)}${field('Lý do bổ sung/đính chính','reason','text','',true)}${textarea('Nội dung bổ sung','content')}<div class="wide"><button class="btn">Gửi phụ lục chờ duyệt</button></div></form>`:'<p class="hint">Hồ sơ đã khóa.</p>'):
  `<button type="button" class="btn" data-action="complete-visit" data-id="${vid}" data-version="${v.version}">Hoàn tất và khóa phiếu khám (F8)</button><p class="hint">Cần có chẩn đoán, không còn chỉ định hoặc y lệnh đang chờ. Hoàn tất khám không có nghĩa đã thu tiền hay đã cấp thuốc.</p>`;
 const hist=details('Lịch sử sửa phiếu khám',t(history.map(r=>{let old={};try{old=JSON.parse(r.snapshot)}catch(e){}return `<tr><td>${r.version}</td><td>${esc(r.reason)}</td><td>${esc(old.diagnosis||'')}</td><td>${showDay(r.created_at)}</td></tr>`}),['Phiên bản','Thao tác','Chẩn đoán','Thời gian']));
 const banner=`<div class="doctor-patient patient-head"><div><b>${esc(v.patient_name)}</b> · ${esc(v.patient_code)} · ${esc(patientAge(v.patient_dob,v.age_months))} · ${esc(v.patient_sex)} · ${esc(v.patient_phone||'Chưa có điện thoại')}</div><div class="allergy-warning" tabindex="0" aria-label="Dị ứng thuốc"><b>DỊ ỨNG THUỐC:</b> ${esc(v.patient_allergies||'Chưa khai thác')}</div>${btn('Xem hồ sơ hành chính','patient-details',`data-id="${v.patient_id}"`)}${btn('Sửa dị ứng','edit-allergies',`data-id="${v.patient_id}"`,'allergy-edit smallbtn')}</div>`;
 const parts=[['exam','Khám',stepCard(1,'Phiếu khám',exam+(!done?childDetails(v):''))+details('Điều dưỡng',nursing,true)+card(finish,done?'Hồ sơ đã khóa':'Hoàn tất khám')+(!done?btn('Đóng lượt bỏ dở','close-abandoned',`data-id="${vid}"`):'')+hist],
 ['orders','Chỉ định',stepCard(2,`Chỉ định cận lâm sàng (${mine.length})`,orders)],
 ['rx','Đơn thuốc',`<div class="allergy-warning notice" role="note"><b>DỊ ỨNG THUỐC:</b> ${esc(v.patient_allergies||'Chưa khai thác')}<br>Cảnh báo để bác sĩ kiểm tra trước khi kê đơn.</div>`+stepCard(3,'Đơn thuốc',rxHtml)],
 ['results','Kết quả cận lâm sàng','<h2>Kết quả cận lâm sàng</h2>'+(await M5.visit(vid))+card(t(mine.filter(o=>o.result_text).map(o=>`<tr><td>${esc(o.name)}</td><td>${esc(o.result_text)}</td><td>${pill(o.status)}</td></tr>`),['Dịch vụ','Kết quả / kết luận','Trạng thái']),'Kết quả cận lâm sàng')],
 ['history','Lịch sử khám','<div id="patient-history">Chọn Lịch sử khám để tải các lượt trước trong phạm vi được phân quyền.</div>'],
 ['payment','Thanh toán','<h2>Thanh toán</h2><div id="doctor-payment-status">Chọn Thanh toán để xem trạng thái.</div>']];
 const navigation=`<nav class="doctor-tabs" aria-label="Các phần hồ sơ">${parts.map(([id,label])=>btn(label,'doctor-tab',`data-target="${id}"`)).join('')}</nav>`;
 return {html:review+`<div class="doctor-layout"><aside class="doctor-waiting">${head}</aside><div class="doctor-record"><div class="doctor-sticky">${banner}${navigation}</div>${parts.map(([id,label,body])=>`<section id="doctor-${id}" class="doctor-section" aria-label="${label}">${body}</section>`).join('')}</div></div>`,
  after(){setClinicalForm(v);if($('doctor_query'))$('doctor_query').value=sel.doctorQuery||'';if(done)document.querySelectorAll('[data-form="clinical"] input,[data-form="clinical"] textarea,[data-form="clinical"] button.btn').forEach(e=>e.disabled=true)}}}


// ---------- Kỹ thuật viên: chỉ định chờ làm → nhập kết quả ----------
async function labScreen(){
 orderList=await api('/orders');const todo=orderList.filter(o=>o.status==='ordered'),sent=orderList.filter(o=>o.status==='pending_review');
 const editable=[...todo,...sent];if(!editable.some(o=>o.id===sel.order))sel.order=todo[0]?.id??null;
 const o=orderList.find(x=>x.id===sel.order);
 const form=o?`<div class="patient-head"><div><b>${esc(o.name)}</b> <span class="muted">${esc(vi(o.category))}</span></div><div class="muted">${esc(o.patient_name)} · ${esc(o.patient_code)} · chỉ định #${o.id}</div><div>${pill(o.status)}</div></div><button type="button" data-s1-result-history="${o.id}">Xem các phiên bản kết quả</button><form data-form="result" class="fields">${hidden('order_id',o.id)}${hidden('result_version',o.result_version||0)}${textarea('Nội dung kết quả','result_text','Mỗi chỉ số một dòng: Tên | Kết quả | Đơn vị | Tham chiếu | Đánh dấu\nVí dụ: Glucose | 9,2 | mmol/L | 3,9–5,6 | H\nDòng cuối: Kết luận: ...')}<p class="hint wide">Xét nghiệm: mỗi chỉ số một dòng, ngăn bằng dấu |. Siêu âm, X-quang, điện tim: mô tả tự do. Dòng bắt đầu bằng "Kết luận:" được in vào mục Kết luận.</p><div class="wide"><button class="btn">Gửi kết quả cho bác sĩ duyệt</button></div></form><form data-form="attach" class="fields" enctype="multipart/form-data">${hidden('attach_order',o.id)}<div class="field"><label for="attachment">Tệp kết quả PDF/PNG/JPG (tối đa 5 MB)</label><input id="attachment" type="file" name="attachment" accept=".pdf,.png,.jpg,.jpeg" required></div><div class="field"><button class="ghost">Đính kèm tệp</button></div></form>`:empty('Chọn một chỉ định trong hàng chờ.');
 const item=x=>({id:x.id,main:`${esc(x.name)} · ${esc(x.patient_name)}`,sub:`${esc(x.patient_code)} · ${pill(x.status)}${x.file_name?' · có tệp':''}`});
 return {html:card(queue(todo.map(item),{kind:'order',current:sel.order,emptyText:'Không còn chỉ định chờ làm.'}),`Chỉ định chờ làm (${todo.length})`)+
  card(form,'Nhập kết quả')+(sent.length?details(`Đã gửi, chờ bác sĩ duyệt (${sent.length}) — vẫn sửa được`,queue(sent.map(item),{kind:'order',current:sel.order,emptyText:''})):''),
  after(){if(o&&$('result_text'))$('result_text').value=o.result_text||''}}}

// ---------- Điều dưỡng: lượt được giao → sinh hiệu, y lệnh ----------
async function nurseScreen(){
 const open=await api('/visits');const visits=open;
 if(!visits.some(v=>v.id===sel.nurseVisit))sel.nurseVisit=open[0]?.id??null;
 const head=card(queue(open.map(v=>({id:v.id,main:`#${v.id} · ${esc(v.patient_name)}`,sub:pill(v.status)})),{kind:'nurse-visit',current:sel.nurseVisit,emptyText:'Chưa có lượt nào được bác sĩ phân công.'}),`Lượt được giao (${open.length})`);
 if(!sel.nurseVisit)return head;
 const vid=sel.nurseVisit;const [v,care,cls,orders]=await Promise.all([api('/visits/'+vid),api('/visits/'+vid+'/care'),api('/cls-services'),api('/orders?visit_id='+vid)]);const done=!OPEN(v);
 const pending=care.tasks.filter(x=>x.status==='pending');
 const nursingOrders=(done?'':`<form data-form="order" class="fields">${hidden('visit_id',vid)}${selectField('Dịch vụ theo bảng giá','service_id',cls.map(x=>[x.id,`${vi(x.category)} – ${x.name} (${servicePrice(x)})`]))}<div class="wide"><button class="btn" ${cls.length?'':'disabled'}>Thêm chỉ định</button></div></form>`)+t(orders.filter(o=>o.visit_id===vid).map(o=>`<tr><td>${esc(o.name)}</td><td>${pill(o.status)}${o.unpriced?' · CHƯA CÓ GIÁ':''}</td></tr>`),['Chỉ định','Trạng thái']);
 const vitals=`<form class="fields" data-form="nurse-vitals">${hidden('visit_id',vid)}${hidden('version',v.version)}${vitalsFields()}<div class="wide"><button class="btn" ${done?'disabled':''}>Lưu sinh hiệu</button><p class="hint">Điều dưỡng không xem, không sửa chẩn đoán và đơn thuốc.</p></div></form>`;
 const tasks=t(care.tasks.map(task=>`<tr><td>${esc(task.description)}</td><td>${esc(taskStatus(task.status))}</td><td>${esc(task.execution_content||'')}<div class="muted">${showDay(task.executed_at||task.created_at)}</div></td><td>${task.status==='pending'&&!done?btn('Ghi nhận đã làm','execute-task',`data-id="${task.id}"`,'btn smallbtn'):''}</td></tr>`),['Y lệnh','Trạng thái','Ghi nhận','']);
 const notes=(done?'':`<form data-form="care-note" class="fields">${hidden('visit_id',vid)}${textarea('Nội dung chăm sóc','content')}<div class="wide"><button class="btn">Lưu ghi nhận chăm sóc</button></div></form>`)+t(care.notes.map(n=>`<tr><td>${esc(n.nurse_name)}</td><td>${esc(n.content)}</td><td>${showDay(n.created_at)}</td></tr>`),['Điều dưỡng','Ghi nhận','Thời gian']);
 return {html:head+`<div class="patient-head"><div><b>${esc(v.patient_name)}</b> <span class="muted">${esc(v.patient_code||'')}</span></div><div class="muted">lượt #${v.id}</div><div>${pill(v.status)}</div></div>`+stepCard(1,'Sinh hiệu',vitals)+stepCard(2,`Y lệnh (${pending.length} chưa làm)`,tasks)+stepCard(3,'Ghi nhận chăm sóc',notes)+stepCard(4,'Chỉ định dịch vụ',nursingOrders),
  after(){setVitals(v.vitals)}}}

// ---------- Nhà thuốc: đơn chờ cấp → cấp → in ----------
async function pharmacyScreen(){
 const offset=sel.rxOffset||0;
 const [rxs,disp,stockList,meds]=await Promise.all([api('/prescriptions?status=draft&limit=101&offset='+offset),api('/dispensations'),api('/stock'),api('/medicines')]);
 if(!rxs.length&&offset){sel.rxOffset=Math.max(0,offset-100);return pharmacyScreen()}
 const waiting=rxs.slice(0,100);
 const pager=`<div class="toolbar-actions"><span>Trang ${1+offset/100}</span>${offset?btn('Trang trước','rx-page',`data-id="${Math.max(0,offset-100)}"`):''}${rxs.length>100?btn('Trang sau','rx-page',`data-id="${offset+100}"`):''}</div>`;
 const rxRow=x=>`<tr><td><b>${esc(x.patient_name)}</b><div class="muted">${esc(x.patient_code)} · đơn #${x.id} · lượt #${x.visit_id}</div></td><td>${esc(x.drug_lines).replace(/\n/g,'<br>')}</td><td><div class="multi-actions">${x.status==='draft'?btn('Cấp thuốc','dispense',`data-id="${x.id}"`,'btn smallbtn'):''}${formButtons('rx',x.id)}${x.status==='draft'?btn('Hủy đơn','cancel-rx',`data-id="${x.id}"`,'btn-danger smallbtn'):''}</div></td></tr>`;
 let returnHtml='';
 if(sel.dispense&&disp.some(d=>d.id===sel.dispense)){const items=await api('/dispensations/'+sel.dispense+'/items');const left=items.filter(i=>i.quantity>i.returned);
  returnHtml=card(t(items.map(i=>`<tr><td>${esc(i.name)}</td><td>${esc(i.lot_number)}</td><td>${i.quantity}</td><td>${i.returned}</td></tr>`),['Thuốc','Lô','Đã cấp','Đã trả'])+
  (left.length?`<form data-form="return" class="fields">${hidden('dispensation_id',sel.dispense)}${selectField('Dòng thuốc trả','item_id',left.map(i=>[i.id,`${i.name}, lô ${i.lot_number}, còn ${i.quantity-i.returned}`]))}${field('Số lượng trả (đơn vị cơ sở)','quantity','number','',true)}${field('Lý do trả','reason','text','',true)}<div class="wide"><button class="btn">Gửi phiếu trả chờ quản lý duyệt</button><p class="hint">Thuốc trả vào lô cách ly, không tự hoàn tiền.</p></div></form>`:'<p class="hint">Đã trả hết.</p>'),`Trả thuốc — phiếu cấp #${sel.dispense}`)}
 const recent=disp.slice(0,15);
 const plain=meds.filter(x=>!x.controlled);
 const stockHtml=`<form data-form="stock-receipt" class="fields">${selectField('Mặt hàng','medicine_id',plain.map(x=>[x.id,x.name]))}${field('Số lô','lot_number','text','LO-001',true)}${dateField('Hạn sử dụng','expiry_date',true)}${field('Số lượng (đơn vị cơ sở)','quantity','number','',true)}<div class="wide"><button class="btn">Nhập lô</button></div></form>`+
  `<form data-form="stock-issue" class="fields">${selectField('Xuất dùng nội bộ','medicine_id',plain.map(x=>[x.id,x.name]))}${field('Số lượng (đơn vị cơ sở)','quantity','number','',true)}${field('Mục đích','purpose','text','Sử dụng nội bộ',true)}<div class="wide"><button class="ghost">Xuất theo hạn dùng (FEFO)</button></div></form>`+
  t(stockList.filter(x=>ui.controlled_drugs||!x.controlled).map(x=>`<tr><td>${esc(x.name)}${x.controlled?' <span class="status warn">Kiểm soát</span>':''}</td><td>${esc(x.lot_number)}</td><td>${showDay(x.expiry_date)}</td><td>${esc(x.quantity)} ${esc(x.base_unit)}</td><td>${x.quarantined?'<span class="status error">Cách ly</span>':'<span class="status">Bán được</span>'}</td></tr>`),['Thuốc','Số lô','Hạn dùng','Tồn','Trạng thái'])+
  `<form data-form="medicine" class="fields">${field('Thêm thuốc/vật tư mới','name','text','',true)}${field('Đơn vị cơ sở','base_unit','text','viên / cái',true)}<div class="wide"><button class="ghost">Thêm vào danh mục</button></div></form>`;
 let controlled='';
 if(ui.controlled_drugs&&cap('controlled_pharmacy')){const cm=meds.filter(m=>m.controlled);const ledger=await api('/controlled-ledger');
  controlled=details('Thuốc kiểm soát đặc biệt',`<form data-form="controlled-receipt" class="fields">${selectField('Thuốc kiểm soát','medicine_id',cm.map(m=>[m.id,m.name]))}${field('Số lô','lot_number','text','',true)}${dateField('Hạn dùng','expiry_date')}${field('Số lượng cơ sở','quantity','number','',true)}${field('Tham chiếu sổ','register_ref','text','',true)}${field('Lý do nhập','reason','text','',true)}<div class="wide"><button class="btn">Đề nghị nhập (quản lý duyệt)</button></div></form>`+t(ledger.map(l=>`<tr><td>${l.id}</td><td>${esc(l.event)}</td><td>${l.quantity}</td><td>${esc(l.register_ref)}</td><td>${showDay(l.created_at)}</td></tr>`),['Dòng sổ','Nghiệp vụ','Số lượng','Tham chiếu','Thời gian']))}
 return card(t(waiting.map(rxRow),['Bệnh nhân','Thuốc','Thao tác'])+pager,`Đơn chờ cấp — trang ${1+offset/100}`)+
  card(t(recent.map(d=>`<tr><td>#${d.id}</td><td>${esc(d.patient_name)}<div class="muted">${showDay(d.dispensed_at)}</div></td><td><div class="multi-actions">${formButtons('rx',d.prescription_id)}${btn(sel.dispense===d.id?'Đang mở':'Trả thuốc','pick',`data-kind="dispense" data-id="${d.id}"`)}</div></td></tr>`),['Phiếu cấp','Bệnh nhân','In / trả']),'Đã cấp gần đây')+returnHtml+
  details('Kho thuốc',stockHtml)+controlled}

// ---------- Thu ngân: lượt còn nợ → thu → in phiếu thu ----------
function manualChargeForms(lines){
 return lines.filter(x=>x.price_at_collection&&!x.void_reason).map(x=>{
  const initial=x.amount===null;
  const body=`<p><b>${esc(x.label)}</b> · ${money(x.amount)}${x.description?' · '+esc(x.description):''}</p><form data-form="${initial?'manual-price':'manual-price-change'}" class="fields">${hidden('charge_id',x.id)}${field('Số tiền (đồng, số nguyên > 0)','amount','number','',true)}${field('Nội dung dịch vụ cụ thể','description','text','Ví dụ: tên thủ thuật cụ thể',true)}${initial?'':field('Lý do đề nghị sửa giá','reason','text','Tối thiểu 8 ký tự',true)}<div class="wide"><button class="btn">${initial?'Nhập giá khoản này':'Gửi đề nghị sửa giá'}</button></div></form>`;
  return initial?card(body,'CHƯA CÓ GIÁ — nhập trước khi thu đủ'):details('Đề nghị sửa giá: '+x.label,body);
 }).join('');
}
// Nút in theo LOẠI ĐÃ LƯU lúc thu; máy chủ cũng chỉ in theo loại đã lưu.
const RECEIPT_LABEL={provisional:'In phiếu thu tạm (PDF)',advance:'In phiếu ứng trước (PDF)',regular:'In phiếu thu (PDF)'};
const PAYMENT_KIND={provisional:'Thu tạm',advance:'Ứng trước',regular:'Thu thường'};
function receiptButton(x,small=false){return btn(RECEIPT_LABEL[x.kind]||RECEIPT_LABEL.regular,'export-receipt',`data-id="${x.id}"`,small?'ghost smallbtn':'btn smallbtn')}
const CAP={total:5000000,multiple:3};
// Thu tạm cộng dồn của lượt vượt 5.000.000 đ hoặc 3 lần tổng khoản đã có giá thì phải xác nhận trong trang.
function capCheck(form){if(!form||form.dataset.unpriced!=='1')return false;const amount=Number(form.querySelector('[name="amount"]').value)||0;
 const total=Number(form.dataset.before)+amount,priced=Number(form.dataset.priced),over=form.dataset.forceCap==='1'||total>CAP.total||total>CAP.multiple*priced;
 const box=form.querySelector('[data-cap-confirm]');box.classList.toggle('hidden',!over);if(!over)box.querySelector('[name="confirm_over_limit"]').checked=false;
 box.querySelector('[data-cap-text]').textContent=`Tổng thu tạm của lượt sẽ là ${money(total)}, vượt trần (5.000.000 đ hoặc 3 lần ${money(priced)} đã có giá). `;return over}
async function cashierScreen(){
 const [dues,pays,adj,manualRequests,adjHistory,manualHistory]=await Promise.all([api('/dues'),api('/payments'),api('/adjustments'),manualPending(),api('/adjustments?history=true'),api('/manual-price-requests?limit=50')]);dueList=dues;
 const owing=dues.filter(d=>d.charged-d.paid>0||d.unpriced_count>0);
 const pages=Math.max(1,Math.ceil(owing.length/100)),page=Math.min(sel.cashPage||1,pages);sel.cashPage=page;
 const visible=owing.slice((page-1)*100,page*100);
 const pager=`<div class="toolbar-actions"><span>Trang ${page}/${pages} · ${owing.length} lượt</span>${page>1?btn('Trang trước','cash-page',`data-id="${page-1}"`):''}${page<pages?btn('Trang sau','cash-page',`data-id="${page+1}"`):''}</div>`;
 if(!dues.some(d=>d.visit_id===sel.cashVisit))sel.cashVisit=owing[0]?.visit_id??null;
 const head=card(queue(visible.map(d=>({id:d.visit_id,main:`#${d.visit_id} · ${esc(d.patient_name)}`,sub:`${esc(d.patient_code)} · ${d.unpriced_count?`CHƯA CÓ GIÁ (${d.unpriced_count} khoản)`:'còn '+money(d.charged-d.paid)}`})),{kind:'cash',current:sel.cashVisit,emptyText:'Không còn lượt cần thu tiền.'})+pager+
  `<div class="toolbar-actions">${selectField('Chọn lượt khác','cash_choose',[['','— Chọn —'],...dues.map(d=>[d.visit_id,`#${d.visit_id} – ${d.patient_name} (${d.unpriced_count?'CHƯA CÓ GIÁ':'còn '+money(d.charged-d.paid)})`])])}</div>`,`Lượt còn nợ (${owing.length})`);
 const payHistory=details('Lịch sử thu',t(pays.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.patient_name)}<div class="muted">lượt #${x.visit_id} · ${showDay(x.created_at)}</div></td><td>${money(x.amount)}<div class="muted">${PAYMENT_KIND[x.kind]||''}</div></td><td>${esc(vi(x.method))}</td><td>${receiptButton(x,true)}</td></tr>`),['Mã thu','Bệnh nhân','Số tiền','Hình thức','']));
 const myRequests=details('Đề nghị giảm phí / hoàn tiền đang chờ',t(adj.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.patient_name)}<div class="muted">lượt #${x.visit_id}</div></td><td>${esc(vi(x.kind))} — ${money(x.amount)}</td><td>${pill(x.status)}</td></tr>`),['Mã','Bệnh nhân','Loại','Trạng thái']))+
  details('Đề nghị sửa giá nhập tay đang chờ',t(manualRequests.map(x=>`<tr><td>#${x.id} · lượt #${x.visit_id}</td><td>${esc(x.description)}</td><td>${money(x.previous_amount)} → ${money(x.new_amount)}</td><td>${pill(x.status)}</td></tr>`),['Đề nghị','Nội dung','Giá','Trạng thái']));
 const requestHistory=details('Lịch sử đề nghị đã xử lý',t([...adjHistory,...manualHistory.filter(x=>x.status!=='pending')].map(x=>`<tr><td>#${x.id}</td><td>${esc(x.reason)}</td><td>${pill(x.status)}</td></tr>`),['Mã','Lý do','Trạng thái']));
 if(!sel.cashVisit)return {html:head+myRequests+requestHistory+payHistory};
 const vid=sel.cashVisit,d=dues.find(x=>x.visit_id===vid);
 const [lines,state]=await Promise.all([api('/charges/'+vid),api('/visits/'+vid+'/settlement')]);
 const due=Math.max(0,d.charged-d.paid),unpriced=d.unpriced_count>0,mine=pays.filter(p=>p.visit_id===vid);
 const bill=t(lines.map(x=>`<tr><td>${esc(x.label)}<div>${esc(x.description||'')}</div></td><td>${money(x.amount)}</td><td>${x.void_reason?`<span class="status error">Đã hủy – ${esc(x.void_reason)}</span>`:'Còn hiệu lực'}</td></tr>`),['Khoản','Số tiền','Trạng thái'])+stats([[unpriced?'Phải thu đã biết':'Phải thu',money(d.charged)],['Đã thu',money(d.paid)],['Còn phải thu',unpriced?'CHƯA CÓ GIÁ':money(due)],...(state.billing.refund_due?[['Cần hoàn',money(state.billing.refund_due)]]:[])])+manualChargeForms(lines);
 const priced=lines.reduce((s,x)=>s+(x.amount==null?0:Number(x.amount)),0),provisionalBefore=mine.filter(x=>x.kind==='provisional').reduce((s,x)=>s+Number(x.amount),0);
 const pay=(due>0||unpriced)&&state.clinical_status!=='cancelled'?`<form data-form="payment" class="fields" data-unpriced="${unpriced?'1':'0'}" data-priced="${priced}" data-before="${provisionalBefore}">${hidden('visit_id',vid)}<div class="approve-box hidden wide" data-cap-confirm><span data-cap-text></span><label class="check"><input type="checkbox" name="confirm_over_limit" value="1"> <b>Tôi xác nhận thu tạm vượt trần cho lượt này</b></label></div>${unpriced?'<p class="hint wide">Còn khoản CHƯA CÓ GIÁ: chỉ thu tạm; chưa thể xác định tổng tiền hoặc hết nợ.</p>':''}${field(unpriced?'Số tiền thu tạm (VNĐ)':'Số tiền thu (VNĐ)','amount','number','',true)}${selectField('Hình thức','method',[['cash','Tiền mặt'],['transfer','Chuyển khoản (đã đối chiếu)']])}${field('Mã giao dịch (nếu chuyển khoản)','external_ref')}<div class="wide"><button class="btn">${unpriced?'Thu tạm một phần':'Thu tiền'}</button></div></form>`:'<p class="hint">Lượt này không còn khoản phải thu.</p>';
 const advance=ui.advance_payment&&!unpriced&&OPEN({status:state.clinical_status})?details('Nhận tiền ứng trước',`<form data-form="advance" class="fields">${hidden('visit_id',vid)}${field('Số tiền ứng trước','amount','number','',true)}${selectField('Hình thức','method',[['cash','Tiền mặt'],['transfer','Chuyển khoản']])}<div class="wide"><button class="btn">Nhận ứng trước</button></div></form>`):'';
 const receipts=t(mine.map(x=>`<tr><td>#${x.id}</td><td>${money(x.amount)}<div class="muted">${PAYMENT_KIND[x.kind]||''} · ${showDay(x.created_at)}</div></td><td>${esc(vi(x.method))}</td><td>${receiptButton(x)}</td></tr>`),['Mã thu','Số tiền','Hình thức','']);
 const adjust=card(`<form data-form="adjustment" class="fields" data-patient="${esc(d.patient_name)}" data-visit="${vid}">${hidden('visit_id',vid)}<div class="wide adjust-for">Cho bệnh nhân <b>${esc(d.patient_name)}</b> · lượt <b>#${vid}</b></div>${selectField('Loại đề nghị','kind',[['discount','Giảm phí'],['refund','Hoàn phần trả thừa']])}${field('Số tiền (VNĐ)','amount','number','',true)}${selectField('Phiếu thu cần hoàn (chỉ khi hoàn tiền)','payment_id',[['','Không áp dụng'],...mine.map(x=>[x.id,`#${x.id}: ${money(x.amount)}`])])}${field('Lý do','reason','text','Tối thiểu 5 ký tự',true)}<div class="approve-box hidden wide" data-adjust-confirm></div><div class="wide"><button class="btn">Xem lại đề nghị</button></div></form>`,'Đề nghị giảm phí / hoàn tiền cho lượt này');
 return {html:head+`<div class="patient-head"><div><b>${esc(d.patient_name)}</b> <span class="muted">${esc(d.patient_code)}</span></div><div class="muted">lượt #${vid}</div><div>${pill(state.clinical_status)}</div></div>`+stepCard(1,'Bảng kê',bill)+stepCard(2,'Thu tiền',pay)+advance+stepCard(3,'In phiếu thu',receipts)+adjust+myRequests+requestHistory+payHistory,
  after(){const a=document.querySelector('[data-form="payment"] [name="amount"]');if(a)a.value=unpriced?'':due}}}

// ---------- Quản lý: duyệt, lượt khám, danh mục, báo cáo ----------
async function manualPending(){
 const {count}=await api('/manual-price-requests/count?status=pending');const rows=[];
 for(let offset=0;offset<count;offset+=200)rows.push(...await api('/manual-price-requests?status=pending&limit=200&offset='+offset));
 return rows}
async function pendingApprovals(){
 const tasks=[api('/adjustments'),api('/orders/cancellation-requests'),ui.addendum?api('/visits/addenda/pending'):[],api('/medication-returns'),ui.controlled_drugs&&cap('controlled_reviewer')?api('/controlled-receipts'):[]];
 tasks.push(manualPending(),api('/manual-price-requests/count?status=pending'));
 const [adj,cancel,addenda,returns,receipts,manual,manualCount]=await Promise.all(tasks);
 const r={manual,manualCount:manualCount.count,adj:adj.filter(x=>x.status==='pending'),allAdj:adj,cancel:cancel.filter(x=>x.status==='pending'),addenda,returns:returns.filter(x=>x.status==='pending'),receipts:receipts.filter(x=>x.status==='pending')};
 r.total=r.manualCount+r.adj.length+r.cancel.length+r.addenda.length+r.returns.length+r.receipts.length;return r}
const decide=(action,id,yes='Duyệt',no='Từ chối')=>`<div class="multi-actions">${btn(yes,action,`data-id="${id}" data-value="approve"`,'btn smallbtn')}${btn(no,action,`data-id="${id}" data-value="reject"`)}</div>`;
async function catalogSection(){
 const [data,meds]=await Promise.all([api('/catalog'),api('/dispensable-medicines')]);const manager=role()==='manager';
 const cats=[['consultation','Khám bệnh'],['lab','Xét nghiệm'],['ultrasound','Siêu âm'],['xray','X-quang'],['ecg','Điện tim'],['procedure','Thủ thuật']];
 let html=card(`<form data-form="service" class="fields">${field('Tên dịch vụ','name','text','',true)}${field('Đơn giá VNĐ (để trống nếu giá nhập khi thu)','price','number')}${selectField('Cách tính giá','price_at_collection',[['0','Giá cố định'],['1','Giá nhập khi thu']])}${selectField('Nhóm','category',cats)}<div class="wide"><button class="btn">Thêm dịch vụ</button><p class="hint">Mã dịch vụ tự sinh.</p></div></form>`+
  t(data.services.map(x=>`<tr><td>${esc(x.code||'')}</td><td>${esc(x.name)}</td><td>${servicePrice(x)}</td><td>${esc(vi(x.category))}</td><td>${x.active===0||x.active===false?'Ngừng dùng':'Đang dùng'}</td></tr>`),['Mã','Dịch vụ','Giá','Nhóm','Hiệu lực']),'Dịch vụ')+
  details('Sửa dịch vụ (không đổi chứng từ cũ)',`<form data-form="service-update" class="fields">${selectField('Dịch vụ','service_id',data.services.map(s=>[s.id,`${s.code||''} ${s.name}`]))}${field('Mã dịch vụ','code','text','',true)}${field('Tên dịch vụ','name','text','',true)}${field('Đơn giá mới (để trống nếu giá nhập khi thu)','price','number')}${selectField('Cách tính giá','price_at_collection',[['0','Giá cố định'],['1','Giá nhập khi thu']])}${selectField('Nhóm','category',cats)}${selectField('Hiệu lực','active',[['1','Đang dùng'],['0','Ngừng dùng']])}<div class="wide"><button class="btn">Lưu thay đổi</button></div></form>`);
 html+=card(`<form data-form="medicine" class="fields">${field('Tên thuốc/vật tư','name','text','',true)}${field('Đơn vị cơ sở','base_unit','text','viên / cái',true)}<div class="wide"><button class="btn">Thêm thuốc/vật tư</button></div></form>`+
  t(data.medicines.filter(x=>ui.controlled_drugs||!x.controlled).map(x=>`<tr><td>${esc(x.name)}${x.controlled?' <span class="status warn">Kiểm soát</span>':''}</td><td>${esc(x.base_unit)}</td><td>${x.unit_price?money(x.unit_price):'Chưa có giá'}</td></tr>`),['Mặt hàng','Đơn vị','Giá bán']),'Thuốc và vật tư')+
  details('Giá bán và đơn vị quy đổi',`<form data-form="medicine-price" class="fields">${selectField('Thuốc','medicine_id',meds.filter(x=>!x.controlled).map(x=>[x.id,x.name]))}${field('Giá một đơn vị cơ sở (VNĐ)','unit_price','number','',true)}<div class="wide"><button class="btn">Cập nhật giá</button></div></form><form data-form="unit" class="fields">${selectField('Thuốc','medicine_id',data.medicines.filter(x=>!x.controlled).map(m=>[m.id,m.name]))}${field('Tên đơn vị quy đổi','name','text','Hộp / vỉ',true)}${field('Số đơn vị cơ sở','base_factor','number','10',true)}<div class="wide"><button class="btn">Thêm quy đổi</button><p class="hint">Hệ số chụp lại lúc kê, không đổi đơn cũ.</p></div></form>`);
 if(manager&&ui.controlled_drugs&&cap('controlled_reviewer')){const cm=data.medicines.filter(m=>m.controlled);
  html+=details('Thuốc kiểm soát đặc biệt',`<form data-form="controlled-medicine" class="fields">${field('Mã thuốc kiểm soát','code','text','',true)}${field('Tên thuốc','name','text','',true)}${field('Đơn vị cơ sở','base_unit','text','viên',true)}<div class="wide"><button class="btn">Thêm thuốc kiểm soát</button></div></form><form data-form="controlled-price" class="fields">${selectField('Thuốc kiểm soát','medicine_id',cm.map(m=>[m.id,m.name]))}${field('Giá mỗi đơn vị cơ sở','unit_price','number','',true)}${field('Lý do phê duyệt giá','reason','text','',true)}<div class="wide"><button class="btn">Duyệt giá</button></div></form>`)}
 return html}
function priceManagementScreen(){return tabs('import',[['import','Nhập bảng giá']],'mgr')+priceImportSection()}
function priceImportSection(){
 let html=stepCard(1,'Tải tệp bảng giá',`<p>Chỉ nhận .xlsx, tối đa 2 MB và 2.000 dòng. Nhóm: Khám, Xét nghiệm, Siêu âm, X-quang, Điện tim, Thủ thuật. Giá trống = giá nhập khi thu; giá 0 vẫn là 0. Không dùng công thức. Tệp tổng hợp chỉ nhập BANG_GIA; CAN_XEM_LAI là ghi chú.</p>${btn('Tải tệp mẫu','price-template','','ghost')}<form data-form="price-preview" class="fields"><div class="field full"><span>Tệp bảng giá (.xlsx)</span><label for="price-file" class="price-file-picker"><span class="ghost">Chọn tệp Excel</span><input id="price-file" name="price_file" type="file" accept=".xlsx" aria-label="Chọn tệp Excel"></label><span id="price-file-name" class="muted">${esc(priceFile?.name||'Chưa chọn tệp')}</span></div><div class="wide"><button class="btn">Xem trước</button></div></form>`);
 if(priceResult)html+=card(`<p role="status">Đã nhập ${priceResult.rows} dòng: ${priceResult.added} thêm mới, ${priceResult.changed} đổi giá, ${priceResult.unchanged} không đổi.</p>`,'Kết quả nhập bảng giá');
 if(!pricePreview)return html;
 const p=pricePreview;
 html+='<div id="price-review">'+stepCard(2,'Xem trước từng dòng',`<p>${esc(priceFile.name)} · ${p.rows.length} dòng. ${p.can_confirm?'Đã kiểm tra, có thể xác nhận.':'Có dòng lỗi: chưa nhập dòng nào. Sửa tệp rồi tải lại.'}</p>`+t(p.rows.map(r=>`<tr><td>${r.row}</td><td>${esc(r.code||r.matched_code||'Tự cấp mã')}</td><td>${esc(r.name)}</td><td>${esc(r.group)}</td><td>${r.service_id?(r.old_price_at_collection?'Giá nhập khi thu':money(r.old_price)):'—'} → ${r.price_at_collection?'Giá nhập khi thu':money(r.price)}</td><td><b>${esc(r.status)}</b><div>${r.errors.map(esc).join('; ')}</div></td></tr>`),['Dòng','Mã','Tên dịch vụ','Nhóm','Giá cũ → giá mới','Kết quả / lý do']));
 html+=details('Dịch vụ trong hệ thống không có trong tệp ('+p.missing.length+')',`<p>Các dịch vụ này được giữ nguyên.</p>`+t(p.missing.map(s=>`<tr><td>${esc(s.code||'')}</td><td>${esc(s.name)}</td><td>${servicePrice(s)}</td></tr>`),['Mã','Dịch vụ','Giá hiện có']));
 if(p.can_confirm)html+=stepCard(3,'Xác nhận nhập',`<p>Nhập toàn bộ trong một lần. Giá mới chỉ áp dụng cho khoản phát sinh mới; khoản phải thu, phiếu thu và chỉ định đã có giữ giá cũ. Không xóa dịch vụ.</p>${btn('Xác nhận nhập bảng giá','price-confirm','','btn')}`);
 return html+'</div>';
}
async function uploadPriceFile(confirm=false){
 const headers={...authHeader(),'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','X-File-Name':encodeURIComponent(priceFile.name)};
 if(confirm)headers['X-Preview-Id']=pricePreview.preview_id;
 const r=await fetch('/api/catalog/services/import/'+(confirm?'confirm':'preview'),{method:'POST',headers,body:priceFile});
 const result=await r.json();if(!r.ok)throw new Error(result.detail||'Không nhập được bảng giá');return result;
}
function manualReport(r){
 return card(`<form data-form="manual-report" class="fields">${dateField('Ngày báo cáo (giờ Việt Nam)','report_day',true,r.day)}<div class="wide"><button class="btn">Xem báo cáo ngày</button></div></form>`+stats([['Thu thường',money(r.payments.regular.total)+' · '+r.payments.regular.count+' phiếu'],['Thu tạm',money(r.payments.provisional.total)+' · '+r.payments.provisional.count+' phiếu'],['Ứng trước',money(r.payments.advance.total)+' · '+r.payments.advance.count+' phiếu']])+stats([['Nhập giá lần đầu',money(r.total_entered)],['Điều chỉnh tăng / giảm',money(r.adjustment_delta)],['Khoản chưa có giá trong ngày',r.unpriced.length]])+t(r.entries.map(x=>`<tr><td>${showDay(x.occurred_at)}</td><td>#${x.charge_id} · lượt #${x.visit_id}<div>${esc(x.patient_name)}</div></td><td>${esc(x.label)}<div>${esc(x.description)}</div></td><td>${x.previous_amount==null?money(x.amount):money(x.previous_amount)+' → '+money(x.amount)}</td><td>${esc(x.actor_name)}${x.reviewer_name?'<div>Duyệt: '+esc(x.reviewer_name)+'</div>':''}</td><td>${x.kind==='entry'?'Nhập lần đầu':'Sửa đã duyệt'}${x.void_reason?'<div>Đã hủy: '+esc(x.void_reason)+'</div>':''}</td></tr>`),['Thời gian','Khoản / người bệnh','Nội dung cụ thể','Số tiền','Người nhập / người duyệt','Nghiệp vụ'])+(r.unpriced.length?t(r.unpriced.map(x=>`<tr><td>#${x.charge_id} · lượt #${x.visit_id}</td><td>${esc(x.patient_name)}</td><td>${esc(x.label)}</td><td>CHƯA CÓ GIÁ</td></tr>`),['Khoản','Người bệnh','Dịch vụ','Trạng thái']):''),'Khoản giá nhập tay — '+r.day)
}
// Quản lý → Lượt khám: tìm theo khoảng ngày (mặc định 7 ngày gần nhất, giờ Việt Nam), mã/tên/điện thoại,
// trạng thái lượt, tình trạng tiền; 50 dòng một trang. Không dùng /api/dues (hàng chờ thu ngân chỉ có lượt còn việc).
const MONEY_STATUS={owing:'Còn nợ',settled:'Đã đủ',unpriced:'Có khoản chưa có giá',refund:'Cần hoàn'};
const MONEY_TONE={owing:'warn',unpriced:'warn',refund:'error'};
let mgrSearch={date_from:'',date_to:'',q:'',status:'',money:'',page:1};
function moneyCell(x){const label=`<span class="status ${MONEY_TONE[x.money_status]||''}">${esc(MONEY_STATUS[x.money_status])}</span>`;
 const detail=x.money_status==='unpriced'?`đã biết ${money(x.charged)} · đã thu ${money(x.paid)}`:x.money_status==='owing'?`còn ${money(x.due)}`:x.money_status==='refund'?`hoàn ${money(x.refund_due)}`:`đã thu ${money(x.paid)}`;
 return `${label}<div class="muted">${detail}</div>`}
async function managerVisitsTab(head){
 const qs=new URLSearchParams();for(const k of ['date_from','date_to','q','status','money'])if(mgrSearch[k])qs.set(k,mgrSearch[k]);qs.set('page',String(mgrSearch.page));
 const res=await api('/manager/visits?'+qs.toString());
 const form=`<form data-form="mgr-visit-search" class="fields">${dateField('Từ ngày','vs_from',true,res.date_from)}${dateField('Đến ngày','vs_to',true,res.date_to)}${field('Mã, tên hoặc số điện thoại bệnh nhân','vs_q')}${selectField('Trạng thái lượt','vs_status',[['','Tất cả'],...['waiting','in_progress','waiting_results','completed','cancelled'].map(s=>[s,vi(s)])])}${selectField('Tình trạng tiền','vs_money',[['','Tất cả'],...Object.entries(MONEY_STATUS)])}<div class="wide"><button class="btn">Tìm lượt khám</button><p class="hint">Mặc định 7 ngày gần nhất. Tìm lượt cũ hơn: sửa ô Từ ngày (dd/mm/yyyy).</p></div></form>`;
 const rows=res.items.map(x=>`<tr><td>#${x.visit_id}<div class="muted">${showDay(x.created_at)}</div></td><td>${esc(x.patient_name)}<div class="muted">${esc(x.patient_code||'')}</div></td><td>${pill(x.status)}</td><td>${moneyCell(x)}</td><td>${btn(sel.mgrVisit===x.visit_id?'Đang xem':'Xem lượt này','pick',`data-kind="mgr-visit" data-id="${x.visit_id}" aria-pressed="${sel.mgrVisit===x.visit_id}"`,sel.mgrVisit===x.visit_id?'btn smallbtn':'ghost smallbtn')}</td></tr>`);
 const pager=`<div class="toolbar-actions"><span id="mgr-visit-count">Trang ${res.page}/${res.pages} · ${res.total} lượt</span>${res.page>1?btn('Trang trước','mgr-page',`data-id="${res.page-1}"`):''}${res.page<res.pages?btn('Trang sau','mgr-page',`data-id="${res.page+1}"`):''}</div>`;
 let html=head+card(form,'Tìm lượt khám')+card((res.items.length?t(rows,['Lượt / ngày','Bệnh nhân','Trạng thái lượt','Tiền','']):empty('Không có lượt khám phù hợp. Lượt cũ hơn: sửa ô Từ ngày.'))+pager,'Kết quả');
 const after=()=>{if($('vs_q'))$('vs_q').value=mgrSearch.q;if($('vs_status'))$('vs_status').value=mgrSearch.status;if($('vs_money'))$('vs_money').value=mgrSearch.money};
 if(!sel.mgrVisit)return {html,after};
 const vid=sel.mgrVisit;const [lines,state,info]=await Promise.all([api('/charges/'+vid),api('/visits/'+vid+'/settlement'),api('/manager/visits/'+vid)]);
 const v=info.visit;
 // Mọi thứ của lượt đang xem nằm trong một khung có tiêu đề và nút Đóng; chuyển trang, đổi bộ lọc, tìm mới đều đóng khung này.
 html+=`<div id="mgr-visit-detail"><div class="patient-head"><div><b id="mgr-visit-title">Đang xem lượt #${v.id} – ${esc(v.patient_name)}</b> <span class="muted">${esc(v.patient_code||'')}</span></div><div class="muted">ngày ${showDay(v.created_at)}</div><div class="multi-actions">${pill(v.status)}${btn('Đóng','mgr-close')}</div></div>`;
 html+=stats([['Chuyên môn',vi(state.clinical_status)],['Còn phải thu',money(state.billing.due)],['Cần hoàn',money(state.billing.refund_due)],['Cấp thuốc',vi(state.dispensing_status)]]);
 html+=card(t(lines.map(l=>`<tr><td>${esc(l.label)}</td><td>${money(l.amount)}</td><td>${esc(l.void_reason||'Còn hiệu lực')}</td></tr>`),['Khoản','Số tiền','Trạng thái'])+`<form data-form="reprice" class="fields">${selectField('Khoản cần điều chỉnh','charge_id',lines.filter(l=>!l.void_reason&&!l.price_at_collection).map(l=>[l.id,l.label]))}${field('Số tiền mới','amount','number','',true)}${field('Lý do','reason','text','Tối thiểu 8 ký tự',true)}<div class="wide"><button class="btn" ${lines.some(l=>!l.void_reason&&!l.price_at_collection)?'':'disabled'}>Điều chỉnh giá</button><p class="hint">Có nhật ký, giữ chứng từ gốc.</p></div></form>`,'Bảng kê và điều chỉnh giá');
 html+=manualChargeForms(lines);
 html+=card(t(info.payments.map(x=>`<tr><td>#${x.id}</td><td>${money(x.amount)}<div class="muted">${PAYMENT_KIND[x.kind]||''} · ${showDay(x.created_at)}</div></td><td>${esc(vi(x.method))}<div class="muted">${esc(x.cashier_name)}</div></td><td>${receiptButton(x,true)}</td></tr>`),['Mã thu','Số tiền','Hình thức / người thu','']),'Phiếu thu của lượt');
 const discounts=info.adjustments.filter(a=>a.kind==='discount'&&a.status==='approved'&&!a.reversed);
 if(discounts.length)html+=card(t(discounts.map(a=>`<tr><td>#${a.id}</td><td>${money(a.amount)}</td><td>${esc(a.reason)}</td><td>${btn('Hoàn tác giảm phí','reverse-discount',`data-id="${a.id}"`)}</td></tr>`),['Mã','Số tiền','Lý do','']),'Giảm phí đã duyệt');
 if(OPEN({status:state.clinical_status}))html+=details('Hủy lượt khám',`<form data-form="cancel-visit" class="fields">${hidden('visit_id',vid)}${field('Lý do hủy lượt','reason','text','',true)}<div class="wide"><button class="btn-danger">Hủy lượt</button><p class="hint">Chỉ hủy được khi chỉ định đã hủy, y lệnh đã xử lý và thuốc đã đối soát.</p></div></form>`);
 return {html:html+'</div>',after}}
// Bỏ lượt đang xem ngay trên trang (không vẽ lại, để khỏi mất chữ đang gõ trong ô lọc).
function closeMgrVisit(){sel.mgrVisit=null;const box=$('mgr-visit-detail');if(box)box.remove();
 document.querySelectorAll('[data-action="pick"][data-kind="mgr-visit"]').forEach(b=>{b.setAttribute('aria-pressed','false');b.textContent='Xem lượt này';b.className='ghost smallbtn'})}
async function managerScreen(){
 const p=await pendingApprovals();
 const head=tabs(sel.mgrTab,[['approve',`Cần duyệt (${p.total})`],['visits','Lượt khám'],['catalog','Danh mục'],['import','Nhập bảng giá'],['report','Báo cáo']],'mgr');
 if(sel.mgrTab==='import')return head+priceImportSection();
 if(sel.mgrTab==='catalog')return head+await catalogSection();
 if(sel.mgrTab==='report'){const [o,stockList,dues,manual]=await Promise.all([api('/overview'),api('/stock'),api('/dues'),api('/reports/manual-prices'+(manualReportDay?'?day='+encodeURIComponent(manualReportDay):''))]);
  return head+manualReport(manual)+(o.unpriced_count?card(`<p>Còn ${o.unpriced_count} khoản CHƯA CÓ GIÁ. Tổng phải thu hiện chỉ gồm phần đã biết, chưa phải tổng cuối.</p>`):'')+stats([['Lượt khám',o.visits],[o.unpriced_count?'Phải thu đã biết':'Phải thu',money(o.charged)],['Đã thu',money(o.paid)],['Còn phải thu',money(o.outstanding)],['Lô thuốc cần chú ý',o.stock_warning]])+
   card('<p class="hint">Số liệu phục vụ kiểm thử, chưa dùng cho kế toán hoặc khai thuế.</p>'+t(dues.filter(d=>d.charged-d.paid!==0||d.unpriced_count>0).map(d=>`<tr><td>#${d.visit_id}</td><td>${esc(d.patient_name)}</td><td>${money(d.charged)}</td><td>${money(d.paid)}</td><td>${d.unpriced_count?'CHƯA CÓ GIÁ':money(d.charged-d.paid)}</td></tr>`),['Lượt','Bệnh nhân','Phải thu','Đã thu','Chênh lệch (âm là trả thừa)']),'Công nợ theo lượt')+
   card(t(stockList.filter(x=>ui.controlled_drugs||!x.controlled).map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.lot_number)}</td><td>${showDay(x.expiry_date)}</td><td>${esc(x.quantity)} ${esc(x.base_unit)}</td><td>${x.quarantined?'<span class="status error">Cách ly</span>':'<span class="status">Bán được</span>'}</td></tr>`),['Thuốc','Số lô','Hạn dùng','Tồn','Trạng thái']),'Tồn kho')}
 if(sel.mgrTab==='visits')return managerVisitsTab(head);
 let html=head+card(t(p.manual.map(x=>`<tr><td>#${x.id} · lượt #${x.visit_id}</td><td>${esc(x.patient_name)}<div>${esc(x.description)}</div></td><td>${money(x.previous_amount)} → ${money(x.new_amount)}</td><td>${esc(x.reason)}<div>${esc(x.proposed_name)}</div></td><td>${decide('review-manual-price',x.id,'Duyệt sửa giá')}</td></tr>`),['Đề nghị','Dịch vụ','Giá','Lý do / người đề nghị','Quyết định']),`Sửa giá nhập tay (${p.manualCount})`);
 html+=card(t(p.adj.map(x=>`<tr><td>#${x.id} · lượt #${x.visit_id}</td><td>${esc(x.patient_name)}</td><td>${esc(vi(x.kind))} — ${money(x.amount)}</td><td>${esc(x.reason)}<div class="muted">${esc(x.proposed_name||'')}</div></td><td>${decide('review-adjustment',x.id)}</td></tr>`),['Mã','Bệnh nhân','Loại','Lý do','Quyết định']),`Giảm phí / hoàn tiền (${p.adj.length})`);
 html+=card(t(p.cancel.map(x=>`<tr><td>#${x.order_id} · lượt #${x.visit_id}</td><td>${esc(x.order_name)}</td><td>${esc(x.reason)}</td><td>${decide('review-cancel',x.id,'Duyệt hủy')}</td></tr>`),['Chỉ định','Dịch vụ','Lý do','Quyết định']),`Hủy chỉ định (${p.cancel.length})`);
 html+=card(t(p.returns.map(r=>`<tr><td>#${r.id} · lượt #${r.visit_id}</td><td>${esc(r.reason)}</td><td>${decide('review-return',r.id,'Duyệt trả vào cách ly')}</td></tr>`),['Phiếu trả','Lý do','Quyết định']),`Trả thuốc (${p.returns.length})`);
 if(ui.addendum)html+=card(t(p.addenda.map(x=>`<tr><td>#${x.visit_id}</td><td>${esc(x.reason)}</td><td>${esc(x.content)}</td><td>${decide('review-addendum',x.id,'Duyệt phụ lục')}</td></tr>`),['Lượt','Lý do','Nội dung','Quyết định']),`Phụ lục hồ sơ (${p.addenda.length})`);
 if(ui.controlled_drugs&&cap('controlled_reviewer'))html+=card(t(p.receipts.map(r=>`<tr><td>#${r.id}</td><td>${esc(r.lot_number)} / ${r.quantity}</td><td>${esc(r.register_ref)}</td><td>${decide('review-controlled-receipt',r.id)}</td></tr>`),['Phiếu nhập','Lô / số lượng','Sổ','Quyết định']),`Nhập thuốc kiểm soát (${p.receipts.length})`);
 return html}

// ---------- Quản trị và cài đặt ----------
function auditDetails(entry){
 if(entry.event==='clinical_rx_replaced'){try{const d=JSON.parse(entry.details);return 'Thay thế bởi đơn '+(d.code||'#'+d.replacement_id)}catch{return 'Đơn đã được thay thế'}}
 if(entry.event==='clinical_rx_allergy_acknowledged'){try{const d=JSON.parse(entry.details);return 'Dòng '+d.row+': '+d.reason}catch{return 'Xác nhận dị ứng thuốc'}}
 if(entry.event==='prescription_settings_changed'){try{const d=JSON.parse(entry.details);return 'Mã cơ sở: '+(d.old_facility_code||'Chưa khai')+' → '+(d.new_facility_code||'Chưa khai')}catch{return 'Đổi cài đặt đơn thuốc'}}
 if(entry.event==='drug_updated')return 'Cập nhật thông tin danh mục thuốc';
 if(entry.event==='drug_merged'){try{return 'Gộp vào mục #'+JSON.parse(entry.details).keep_id}catch{return 'Gộp danh mục thuốc'}}
 if(entry.event==='drugs_imported'){try{const d=JSON.parse(entry.details);return `Thêm ${d.added}, cập nhật ${d.updated} mục`}catch{return 'Nhập danh mục thuốc'}}
 if(entry.event==='patient_administrative_updated'){try{const d=JSON.parse(entry.details);const labels={document_type:'Loại giấy tờ',document_number:'Số giấy tờ',citizen_id:'Số căn cước / định danh',ethnicity:'Dân tộc',ethnicity_code:'Mã dân tộc',occupation:'Nghề nghiệp',workplace:'Nơi làm việc / học tập',province:'Tỉnh / thành',province_code:'Mã tỉnh',commune:'Xã / phường / đặc khu',commune_code:'Mã xã',address_detail:'Địa chỉ chi tiết'};return d.fields.length?d.fields.map(k=>{const change=d.changes?.[k];return (labels[k]||'Trường hồ sơ')+(change?' ['+(change.old||'Chưa khai')+' → '+(change.new||'Chưa khai')+']':'')}).join('; '):'Không có trường thay đổi'}catch{return 'Không đọc được chi tiết thay đổi'}}
 if(['patient_catalog_seeded','patient_catalog_imported'].includes(entry.event)){try{const d=JSON.parse(entry.details);return `Nạp ${d.provinces||0} tỉnh, ${d.communes||0} xã, ${d.ethnicities||0} dân tộc; thêm ${d.added||0}, cập nhật ${d.updated||0}, ngừng dùng ${d.inactive||0} mục`}catch{return entry.details}}
 if(entry.event==='practitioner_updated'){try{const d=JSON.parse(entry.details);return [['printed_name','Họ tên in'],['printed_title','Chức danh'],['practice_license','Giấy phép'],['practice_scopes','Phạm vi'],['certificate_provider','Nhà cung cấp chứng thư'],['certificate_serial','Sê-ri chứng thư'],['certificate_expiry','Hạn chứng thư']].map(([k,l])=>{const fmt=v=>k==='certificate_expiry'?showDay(v):Array.isArray(v)?v.join(', '):v||'Chưa khai';return l+': '+fmt(d.old[k])+' → '+fmt(d.new[k])}).join('; ')}catch{return 'Không đọc được chi tiết thay đổi'}}
 if(['manual_price_entered','manual_price_change_requested','manual_price_change_approved','manual_price_change_rejected'].includes(entry.event)){try{const d=JSON.parse(entry.details);return `${d.amount!=null?money(d.amount):money(d.old_price)+' → '+money(d.new_price)}; ${d.description}`;}catch{return entry.details}}
 if(!['service_price_imported','service_prices_imported'].includes(entry.event))return entry.details;
 try{const d=JSON.parse(entry.details);return entry.event==='service_price_imported'?`Dòng ${d.row}: ${d.code} — ${d.name}; ${money(d.old_price)} → ${money(d.new_price)}`:`${d.rows} dòng: ${d.added} thêm mới, ${d.changed} đổi giá, ${d.unchanged} không đổi`;}catch{return entry.details}
}
async function adminScreen(){
 const head=tabs(sel.adminTab,[['accounts','Tài khoản'],['audit','Nhật ký'],['catalog','Danh mục']],'admin');
 if(sel.adminTab==='catalog')return head+await D0.admin()+catalogImport()+await catalogSection();
 if(sel.adminTab==='audit'){const entries=await api('/audit?offset='+auditOffset+'&limit=100');return head+card(t(entries.map(x=>`<tr><td>${x.id}</td><td>${esc(x.username||x.user_id||'Hệ thống')}</td><td>${esc(vi(x.event))}</td><td>${esc(vi(x.object_type))} #${esc(x.object_id??'')}</td><td>${esc(auditDetails(x))}</td><td>${showDay(x.created_at)}</td></tr>`),['ID','Nhân viên','Sự kiện','Đối tượng','Chi tiết','Thời gian (giờ Việt Nam)'])+`<div class="toolbar-actions"><button class="ghost" data-action="audit-prev" ${auditOffset===0?'disabled':''}>Trang trước</button><span>Từ dòng ${auditOffset+1}</span><button class="ghost" data-action="audit-next" ${entries.length<100?'disabled':''}>Trang sau</button></div>`,'Nhật ký sự kiện')}
 const users=accountList=await api('/accounts');const practitioners=await api('/practitioners');const practitioner=practitioners.items.find(x=>x.id===sel.account);const certWarnings=practitioners.items.filter(x=>x.certificate_warning).map(x=>`<p class="notice">${esc(x.full_name)}: ${esc(x.certificate_warning)}</p>`).join('');
 if(!users.some(u=>u.id===sel.account))sel.account=null;
 const u=users.find(x=>x.id===sel.account);
 const create=`<form data-form="account" class="fields">${field('Tài khoản (chữ thường, không dấu)','username','text','',true)}${field('Họ tên nhân viên','full_name','text','',true)}${field('Mật khẩu riêng (ít nhất 12 ký tự)','password','password','',true)}${roleChecks([],'new')}<div class="wide"><button class="btn">Tạo tài khoản</button></div></form>`;
 const pick=`<div class="toolbar-actions">${selectField('Chọn nhân viên cần sửa','account_choose',[['','— Chọn nhân viên —'],...users.map(x=>[x.id,`${x.full_name} (${x.username})`])])}</div>`;
 const edit=u?`<div class="patient-head"><div><b>${esc(u.full_name)}</b> <span class="muted">${esc(u.username)}</span></div><div class="muted">Quyền hiện có: ${u.roles.map(r=>esc(roles[r])).join(', ')}</div><div>${u.active?'<span class="status">Hoạt động</span>':'<span class="status error">Đã khóa</span>'}</div></div>`+
  `<form data-form="account-edit" class="fields" data-had-admin="${u.roles.includes('admin')?'1':'0'}">${hidden('uid',u.id)}<div class="field full"><label for="edit_full_name">Họ tên</label><input id="edit_full_name" name="full_name" value="${esc(u.full_name)}" required></div>${roleChecks(u.roles,'edit')}<div class="wide"><button class="btn">Lưu họ tên và quyền</button><p class="hint">Đổi quyền sẽ đăng xuất mọi phiên cũ của người đó.${ui.controlled_drugs?'':' Quyền thuốc kiểm soát hiện có được giữ nguyên.'}</p></div></form>`+
  practitionerForm(practitioner,practitioners.scopes)+`<form data-form="account-lock" class="fields">${hidden('uid',u.id)}${hidden('active',u.active?'0':'1')}<div class="wide"><button class="${u.active?'btn danger':'btn'}">${u.active?'Khóa tài khoản':'Mở khóa tài khoản'}</button><p class="hint">Khóa/mở chỉ đổi trạng thái, giữ nguyên mọi quyền.</p></div></form>`+
  `<form data-form="account-reset" class="fields">${hidden('uid',u.id)}${field('Mật khẩu mới (ít nhất 12 ký tự)','password','password','',true)}<div class="wide"><button class="ghost">Đặt lại mật khẩu</button></div></form>`:empty('Chọn một nhân viên để sửa họ tên, quyền, khóa/mở hoặc đặt lại mật khẩu.');
 return {html:head+certWarnings+card(create,'Tạo tài khoản')+card(pick+edit,'Sửa tài khoản')+card(t(users.map(x=>`<tr><td>${esc(x.username)}</td><td>${esc(x.full_name)}</td><td>${x.roles.map(r=>esc(roles[r])).join(', ')}</td><td>${x.active?'Hoạt động':'Đã khóa'}</td></tr>`),['Tài khoản','Họ tên','Quyền','Trạng thái']),'Nhân viên'),
  after(){if(u&&$('account_choose'))$('account_choose').value=String(u.id)}}}
// Ô chọn vai trò: không chọn sẵn gì khi tạo mới; khi sửa thì đánh dấu đúng quyền hiện có.
function roleChecks(current,prefix){
 const base=Object.entries(roles).filter(([r])=>!r.startsWith('controlled_')),extra=Object.entries(roles).filter(([r])=>r.startsWith('controlled_'));
 const box=([r,n])=>`<label class="check"><input type="checkbox" name="roles" value="${r}" ${current.includes(r)?'checked':''}> ${esc(n)}</label>`;
 return `<fieldset class="field full roles"><legend>Vai trò (chọn ít nhất một)</legend>${base.map(box).join('')}</fieldset>`+
  (ui.controlled_drugs?`<fieldset class="field full roles"><legend>Quyền phụ thuốc kiểm soát</legend>${extra.map(box).join('')}</fieldset>`:'')+
  `<div class="approve-box hidden wide" data-admin-confirm><label class="check"><input type="checkbox" name="confirm_admin" value="1"> <b>Tôi xác nhận <span data-admin-verb>cấp</span> quyền Quản trị</b> (toàn quyền tài khoản, cài đặt, nhật ký).</label></div>`}
// Cấp hoặc bỏ quyền Quản trị phải đánh dấu ô xác nhận ngay trong trang.
function adminChange(form){const had=form.dataset.hadAdmin==='1',has=!!form.querySelector('[name="roles"][value="admin"]:checked');
 const box=form.querySelector('[data-admin-confirm]');if(box){box.classList.toggle('hidden',had===has);box.querySelector('[data-admin-verb]').textContent=has?'cấp':'bỏ';if(had===has)box.querySelector('[name="confirm_admin"]').checked=false}
 return had!==has}
const SETTINGS=[['block_practitioner_scope','Chặn duyệt ngoài phạm vi chuyên môn','Mặc định tắt: vẫn duyệt nhưng hiện cảnh báo và ghi nhật ký. Bật sẽ chặn ở API.'],['advance_payment','Ứng trước tiền','Thu ngân nhận tiền trước khi có chỉ định hoặc cấp thuốc.'],['addendum','Phụ lục đính chính','Bác sĩ bổ sung hồ sơ đã khóa, quản lý duyệt.'],['controlled_drugs','Thuốc kiểm soát đặc biệt','Kê, duyệt, nhập, cấp và sổ theo dõi thuốc kiểm soát.']];
async function settingsScreen(){await loadUi();const provinces=await api('/patient-catalog?kind=province&limit=100');
 const warn=ui.source&&ui.source!=='file'?`<div class="notice">${ui.source==='missing'?'Chưa có tệp cài đặt trên máy chủ':'Tệp cài đặt trên máy chủ bị hỏng'}: đang dùng giá trị mặc định. Kiểm tra rồi bấm Lưu cài đặt để ghi lại.</div>`:'';
 return warn+card(`<form data-form="ui-settings" class="settings">${selectField('Tỉnh / thành mặc định của phòng khám','default_province_code',[['','— Chưa đặt —'],...provinces.map(x=>[x.code,x.name])]).replace('value="'+esc(ui.default_province_code||'')+'"','value="'+esc(ui.default_province_code||'')+'" selected')}${SETTINGS.map(([k,label,hint])=>`<label class="switch"><input type="checkbox" name="${k}" ${ui[k]?'checked':''}><span><b>${esc(label)}</b><small>${esc(hint)}</small></span></label>`).join('')}<button class="btn">Lưu cài đặt</button><p class="hint">Cài đặt chặn phạm vi áp dụng tại API duyệt kết quả. Các công tắc chức năng khác điều khiển hiển thị; quyền trên máy chủ giữ nguyên.</p></form>`,'Chức năng phụ')}
function passwordPage(){return card(`<form data-form="password" class="fields">${field('Mật khẩu hiện tại','current_password','password','',true)}${field('Mật khẩu mới (ít nhất 12 ký tự)','new_password','password','',true)}<div class="wide"><button class="btn">Đổi mật khẩu và đăng xuất các phiên</button></div></form>`,'Đổi mật khẩu cá nhân')}

// ---------- Biểu mẫu, sinh hiệu ----------
function setVitals(text){const vt=parseVitals(text);for(const [k] of VITALS){const el=$('v_'+k);if(el)el.value=vt[k]||''}if($('v_note'))$('v_note').value=vt.note||'';vitalsFlags()}
function setClinicalForm(data){for(const name of ['chief_complaint','history','diagnosis','treatment']){const el=document.querySelector(`[data-form="clinical"] [name="${name}"]`);if(el)el.value=data[name]||'';}
 const fu=document.querySelector('[data-form="clinical"] [name="follow_up"]');if(fu)fu.value=data.follow_up?showDay(data.follow_up):'';setVitals(data.vitals)}
const actionKeys=new Map();
async function keyed(kind,path,body,keyName='request_key'){const fingerprint=kind+JSON.stringify(body);if(!actionKeys.has(fingerprint))actionKeys.set(fingerprint,requestId());
 const result=await api(path,{method:'POST',body:{...body,[keyName]:actionKeys.get(fingerprint)}});actionKeys.delete(fingerprint);return result}
// Mỗi thao tác trả về câu thông báo; màn hình được tải lại xong mới hiện thông báo.
async function handleForm(form){const kind=form.dataset.form;const f=new FormData(form);const value=k=>String(f.get(k)||'').trim();const num=k=>Number(value(k));let msg='';
 if(kind==='login'){
  const res=await api('/login',{method:'POST',body:{username:value('username'),password:value('password')}});auth={token:res.access_token,user:res.user};selectedRole=null;uiLoaded=false;if(res.access_token)sessionStorage.setItem('md_token',res.access_token);active=null;await render();notify('Đăng nhập thành công');return;}
 if(kind==='password'){await api('/password',{method:'POST',body:{current_password:value('current_password'),new_password:value('new_password')}});sessionStorage.removeItem('md_token');selectedRole=null;renderLogin();notify('Đã đổi mật khẩu. Hãy đăng nhập lại');return;}
 if(kind==='mgr-visit-search'){const from=parseDay(value('vs_from'),'Từ ngày'),to=parseDay(value('vs_to'),'Đến ngày');if(from&&to&&from>to)throw new Error('Từ ngày phải trước hoặc bằng Đến ngày');
  mgrSearch={date_from:from||'',date_to:to||'',q:value('vs_q'),status:value('vs_status'),money:value('vs_money'),page:1};sel.mgrVisit=null;await render();return;}
 if(kind==='manual-report'){manualReportDay=value('report_day');parseDay(manualReportDay);await render();return;}
 if(kind==='doctor-filter'){sel.doctorDay=parseDay(value('doctor_day'));sel.doctorQuery=value('doctor_query');await render();return;}
 if(kind==='allergies'){const state=value('allergy_state'),text=value('allergy_text');if(state==='known'&&!text)throw new Error('Cần ghi tên thuốc / phản ứng đã biết');await api('/patients/'+num('patient_id')+'/allergies',{method:'PUT',body:{allergies:state==='none'?'Không dị ứng':state==='unknown'?null:text}});$('m0-dialog')?.close();await render();notify('Đã lưu dị ứng thuốc');return;}
 if(kind==='close-abandoned'){try{await api('/visits/'+num('visit_id')+'/close-abandoned',{method:'POST',body:{reason:value('close_reason'),note:value('close_note')}});}catch(error){if(error.message.includes('hủy/hoàn')){showM0Dialog('<h2>Lượt đã phát sinh phí; hãy gửi yêu cầu hủy lượt cho Quản lý</h2><p>Vai trò hiện tại không có quyền tạo yêu cầu hủy lượt. Liên hệ Quản lý xử lý theo quy trình hiện có.</p>');return;}throw error;}$('m0-dialog')?.close();sel.visit=null;await render();notify('Đã đóng lượt bỏ dở');return;}
 if(kind==='patient-search'){sel.patientQuery=value('q');await render();return;}
 if(kind==='price-preview'){
  pricePreview=null;priceResult=null;const picked=f.get('price_file');priceFile=picked?.name?picked:priceFile;
  if(!priceFile||!priceFile.name.toLowerCase().endsWith('.xlsx'))throw new Error('Chỉ nhận tệp .xlsx');
  if(priceFile.size>2*1024*1024)throw new Error('Tệp vượt giới hạn 2 MB');
  const selected=priceFile,preview=await uploadPriceFile();if(priceFile!==selected)return;
  pricePreview=preview;await render();notify('Đã kiểm tra tệp; hãy xem từng dòng');return;
 }
 if(kind==='manual-price'||kind==='manual-price-change'){await keyed(kind,'/charges/'+num('charge_id')+(kind==='manual-price'?'/manual-price':'/manual-price-requests'),{amount:num('amount'),description:value('description'),...(kind==='manual-price-change'?{reason:value('reason')}:{})});await render();notify(kind==='manual-price'?'Đã nhập giá khoản phải thu':'Đã gửi đề nghị sửa giá, chờ quản lý duyệt');return;}
 if((kind==='service'||kind==='service-update')&&value('price_at_collection')!=='1'&&!value('price'))throw new Error('Giá cố định không được để trống; nhập 0 nếu giá bằng 0 hoặc chọn Giá nhập khi thu');
 if(kind==='service'){await api('/catalog/services',{method:'POST',body:{name:value('name'),price:value('price_at_collection')==='1'?null:num('price'),price_at_collection:value('price_at_collection')==='1',category:value('category')}});msg='Đã thêm dịch vụ';}
 else if(kind==='medicine-price'){await api('/medicines/'+num('medicine_id')+'/price',{method:'PUT',body:{unit_price:num('unit_price')}});msg='Đã đặt giá thuốc';}
 else if(kind==='medicine'){await api('/catalog/medicines',{method:'POST',body:{name:value('name'),base_unit:value('base_unit')}});msg='Đã thêm thuốc/vật tư';}
 else if(kind==='account'){const picked=f.getAll('roles').map(String);if(!picked.length)throw new Error('Chọn ít nhất một vai trò cho tài khoản mới');
  if(adminChange(form)&&!f.get('confirm_admin'))throw new Error('Đánh dấu ô xác nhận cấp quyền Quản trị trước khi tạo');
  await api('/accounts',{method:'POST',body:{username:value('username'),full_name:value('full_name'),password:value('password'),roles:picked}});msg='Đã tạo tài khoản riêng';}
 else if(kind==='account-edit'){const u=accountList.find(x=>x.id===num('uid'));if(!u)throw new Error('Không tìm thấy nhân viên');
  let picked=f.getAll('roles').map(String);if(!ui.controlled_drugs)picked=[...picked,...u.roles.filter(r=>r.startsWith('controlled_'))];
  if(!picked.length)throw new Error('Chọn ít nhất một vai trò');
  const body={};if(value('full_name')!==u.full_name)body.full_name=value('full_name');
  if([...picked].sort().join()!==[...u.roles].sort().join())body.roles=picked;
  if(!Object.keys(body).length)throw new Error('Chưa có thay đổi nào');
  if(adminChange(form)&&!f.get('confirm_admin'))throw new Error('Đánh dấu ô xác nhận '+(picked.includes('admin')?'cấp':'bỏ')+' quyền Quản trị trước khi lưu');
  await api('/accounts/'+u.id,{method:'PUT',body});msg=body.roles?'Đã cập nhật quyền và thu hồi các phiên cũ':'Đã cập nhật họ tên';}
 else if(kind==='account-lock'){const active=value('active')==='1';await api('/accounts/'+num('uid'),{method:'PUT',body:{active}});msg=active?'Đã mở khóa tài khoản, giữ nguyên quyền':'Đã khóa tài khoản, giữ nguyên quyền';}
 else if(kind==='account-reset'){await api('/accounts/'+num('uid')+'/password',{method:'POST',body:{password:value('password')}});msg='Đã đặt mật khẩu và thu hồi phiên';}
 else if(kind==='ui-settings'){const body={default_province_code:value('default_province_code')||null};for(const [k] of SETTINGS)body[k]=!!form.querySelector(`[name="${k}"]`).checked;ui=await api('/ui-settings',{method:'PUT',body});msg='Đã lưu cài đặt';}
 else if(kind==='patient-administrative'){const r=await api('/patients/'+num('patient_id')+'/administrative',{method:'PATCH',body:administrativeBody(value)});msg='Đã lưu hồ sơ hành chính. '+(r.warnings||[]).join(' ');if(r.warnings?.length)showM0Dialog('<h2>Cảnh báo trùng giấy tờ</h2><p>'+r.warnings.map(esc).join('<br>')+'</p>');}
 else if(kind==='child-details'){await api('/visits/'+num('visit_id')+'/child-details',{method:'PUT',body:{version:num('version'),weight_kg:value('weight_kg')?num('weight_kg'):null,escort_name:value('escort_name')||null,escort_relationship:value('escort_relationship')||null,escort_phone:value('escort_phone')||null}});msg='Đã lưu cân nặng và người đưa trẻ';}
 else if(kind==='practitioner'){const body={practice_scopes:f.getAll('practice_scopes')};for(const k of ['printed_name','printed_title','practice_license','certificate_provider','certificate_serial','certificate_expiry'])body[k]=value(k)||null;const r=await api('/practitioners/'+num('uid'),{method:'PUT',body});msg='Đã lưu hồ sơ người hành nghề';if(r.certificate_warning)showM0Dialog('<h2>Chứng thư số</h2><p>'+esc(r.certificate_warning)+'</p>');}
 else if(kind==='patient-catalog'){const fd=new FormData();if(f.get('file')?.size)fd.append('file',f.get('file'));fd.append('kind',value('catalog_kind'));if(f.get('file')?.size&&value('catalog_kind')==='all')throw new Error('Chọn Tỉnh/xã hoặc Dân tộc cho tệp cập nhật');const r=await api('/patient-catalog/import',{method:'POST',body:fd,isFile:true});msg='Đã nạp '+[r.provinces?r.provinces+' tỉnh':'',r.communes?r.communes.toLocaleString('vi-VN')+' xã':'',r.ethnicities?r.ethnicities+' dân tộc (kèm 2 lựa chọn ngoài danh mục)':''].filter(Boolean).join(', ')+'. Ngừng dùng: '+r.inactive+' mục.';}
 else if(kind==='patient'){const res=await api('/patients',{method:'POST',body:{full_name:value('full_name'),date_of_birth:parseDay(value('date_of_birth'),'Ngày sinh'),sex:value('sex'),phone:value('phone'),...administrativeBody(value),address:value('address')||null}});sel.patient=res.id;sel.patientQuery='';msg='Đã lưu bệnh nhân '+res.code+'. '+(res.warnings||[]).join(' ');if(res.warnings?.length)showM0Dialog('<h2>Cảnh báo trùng giấy tờ</h2><p>'+res.warnings.map(esc).join('<br>')+'</p>');}
 else if(kind==='visit'){const res=await api('/visits',{method:'POST',body:{patient_id:num('patient_id'),doctor_id:num('doctor_id'),service_id:num('service_id')}});sel.patient=null;msg='Đã tiếp nhận lượt khám #'+res.id;}
 else if(kind==='appointment'){const day=parseDay(value('appt_day'),'Ngày hẹn');const tm=value('appt_time').match(/^(\d{1,2})[:hH.](\d{2})$/);if(!tm||+tm[1]>23||+tm[2]>59)throw new Error('Giờ hẹn nhập theo dạng giờ:phút, ví dụ 08:30');
  await api('/appointments',{method:'POST',body:{patient_id:num('patient_id'),doctor_id:num('doctor_id'),scheduled_at:`${day}T${tm[1].padStart(2,'0')}:${tm[2]}`,reason:value('reason')}});msg='Đã đặt lịch';}
 else if(kind==='clinical'){const payload={version:num('version')};for(const k of ['chief_complaint','history','diagnosis','treatment'])payload[k]=value(k);
  payload.vitals=composeVitals(value);payload.follow_up=parseDay(value('follow_up'),'Ngày hẹn tái khám');
  await api('/visits/'+num('visit_id')+'/clinical',{method:'PUT',body:payload});msg='Đã lưu phiếu khám';}
 else if(kind==='order'){const cls=await api('/cls-services');const service=cls.find(x=>x.id===num('service_id'));if(!service)throw Error('Dịch vụ chưa có trong bảng giá');const key=`${num('visit_id')}:${service.id}`;if(!pendingOrderKeys.has(key))pendingOrderKeys.set(key,requestId());await api('/orders',{method:'POST',body:{visit_id:num('visit_id'),category:service.category,service_id:service.id,request_key:pendingOrderKeys.get(key),defer_approval:value('defer_approval')==='1'}});pendingOrderKeys.delete(key);msg=value('defer_approval')==='1'?'Đã lưu nháp chỉ định, chưa phát sinh tiền':service.price_at_collection?'Đã lập chỉ định; khoản phải thu CHƯA CÓ GIÁ':'Đã lập chỉ định và ghi phí theo bảng giá';}
 else if(kind==='result'){await api('/orders/'+num('order_id')+'/result',{method:'PUT',body:{result_text:value('result_text'),version:num('result_version')}});sel.order=null;msg='Đã chuyển kết quả cho bác sĩ duyệt';}
 else if(kind==='attach'){const data=new FormData();data.set('file',f.get('attachment'));await api('/orders/'+num('attach_order')+'/attachment',{method:'POST',body:data,isFile:true});msg='Đã tải tệp kết quả';}
 else if(kind==='rx'){if(form.querySelector('[name="unit_id"]:disabled'))throw Error('Đang tải đơn vị thuốc, vui lòng chờ trước khi lưu');const items=[...form.querySelectorAll('.rx-line')].map(row=>({medicine_id:Number(row.querySelector('[name="medicine_id"]').value),quantity:Number(row.querySelector('[name="quantity"]').value),unit_id:Number(row.querySelector('[name="unit_id"]')?.value)||null,directions:row.querySelector('[name="directions"]').value.trim()}));await api('/prescriptions',{method:'POST',body:{visit_id:num('visit_id'),items,instructions:value('instructions'),follow_up:parseDay(value('rx_follow_up'),'Ngày hẹn tái khám')}});msg='Đã lưu đơn thuốc';}
 else if(kind==='nurse-vitals'){await api('/visits/'+num('visit_id')+'/vitals',{method:'PUT',body:{version:num('version'),vitals:composeVitals(value)}});msg='Đã lưu sinh hiệu';}
 else if(kind==='assign-nurse'){await api('/visits/'+num('visit_id')+'/nurses',{method:'POST',body:{nurse_id:num('nurse_id')}});msg='Đã phân công điều dưỡng';}
 else if(kind==='nursing-task'){await keyed(kind,'/visits/'+num('visit_id')+'/nursing-tasks',{nurse_id:num('nurse_id'),content:value('content')});msg='Đã giao y lệnh';}
 else if(kind==='care-note'){await keyed(kind,'/visits/'+num('visit_id')+'/care-notes',{content:value('content')});msg='Đã lưu ghi nhận chăm sóc';}
 else if(kind==='addendum'){await api('/visits/'+num('visit_id')+'/addenda',{method:'POST',body:{reason:value('reason'),content:value('content')}});msg='Đã gửi phụ lục chờ quản lý duyệt';}
 else if(kind==='stock-receipt'){await api('/stock/receipts',{method:'POST',body:{medicine_id:num('medicine_id'),lot_number:value('lot_number'),expiry_date:parseDay(value('expiry_date'),'Hạn sử dụng'),quantity:num('quantity')}});msg='Đã nhập lô vào kho';}
 else if(kind==='stock-issue'){await api('/stock/issues',{method:'POST',body:{medicine_id:num('medicine_id'),quantity:num('quantity'),purpose:value('purpose')}});msg='Đã xuất lô theo hạn dùng';}
 else if(kind==='payment'){const over=capCheck(form);if(over&&!f.get('confirm_over_limit'))throw new Error('Thu tạm vượt trần: đánh dấu ô xác nhận trong trang rồi thu lại');
  let res;try{res=await keyed(kind,'/payments',{visit_id:num('visit_id'),amount:num('amount'),method:value('method'),external_ref:value('external_ref')||null,confirm_over_limit:!!f.get('confirm_over_limit')},'idempotency_key');}
  catch(e){if(/vượt trần/.test(e.message)){form.dataset.forceCap='1';capCheck(form)}throw e}
  msg=res.kind==='provisional'?'Đã thu tạm, phiếu thu tạm #'+res.id+'. Lượt vẫn còn khoản chưa có giá':'Đã thu tiền, phiếu thu #'+res.id+'. Bấm "In phiếu thu".';}
 else if(kind==='advance'){await keyed(kind,'/payments',{visit_id:num('visit_id'),amount:num('amount'),method:value('method'),prepayment:true},'idempotency_key');msg='Đã nhận tiền ứng trước';}
 else if(kind==='adjustment'){const body={visit_id:num('visit_id'),kind:value('kind'),amount:num('amount'),payment_id:value('payment_id')?num('payment_id'):null,reason:value('reason')};
  const box=form.querySelector('[data-adjust-confirm]'),summary=`${vi(body.kind)} ${money(body.amount)} cho ${form.dataset.patient}, lượt #${body.visit_id}`;
  if(form.dataset.confirmed!==summary+body.reason){if(!(body.amount>0))throw new Error('Nhập số tiền');
   box.innerHTML=`<b>Kiểm tra trước khi gửi:</b> ${esc(summary)}. Lý do: ${esc(body.reason)}. Đúng thì bấm <b>Xác nhận gửi đề nghị</b>.`;box.classList.remove('hidden');
   form.dataset.confirmed=summary+body.reason;form.querySelector('button.btn').textContent='Xác nhận gửi đề nghị';return;}
  await api('/adjustments',{method:'POST',body});msg='Đã gửi đề nghị '+summary+' cho quản lý duyệt';}
 else if(kind==='reprice'){await keyed(kind,'/charges/'+num('charge_id')+'/reprice',{amount:num('amount'),reason:value('reason')});msg='Đã điều chỉnh giá, có nhật ký';}
 else if(kind==='unit'){await api('/medicines/'+num('medicine_id')+'/units',{method:'POST',body:{name:value('name'),base_factor:num('base_factor')}});msg='Đã thêm đơn vị quy đổi';}
 else if(kind==='service-update'){await api('/catalog/services/'+num('service_id'),{method:'PUT',body:{code:value('code'),name:value('name'),price:value('price_at_collection')==='1'?null:num('price'),price_at_collection:value('price_at_collection')==='1',active:value('active')==='1',category:value('category')}});msg='Đã cập nhật dịch vụ';}
 else if(kind==='return'){await keyed(kind,'/dispensations/'+num('dispensation_id')+'/returns',{items:[{dispensation_item_id:num('item_id'),quantity:num('quantity')}],reason:value('reason')});msg='Đã gửi phiếu trả thuốc chờ quản lý duyệt';}
 else if(kind==='cancel-visit'){await api('/visits/'+num('visit_id')+'/cancel',{method:'POST',body:{reason:value('reason')}});msg='Đã hủy lượt khám';}
 else if(kind==='controlled-medicine'){await api('/catalog/medicines',{method:'POST',body:{code:value('code'),name:value('name'),base_unit:value('base_unit'),controlled:true}});msg='Đã thêm thuốc kiểm soát';}
 else if(kind==='controlled-price'){await api('/medicines/'+num('medicine_id')+'/price',{method:'PUT',body:{unit_price:num('unit_price'),reason:value('reason')}});msg='Đã duyệt giá thuốc kiểm soát';}
 else if(kind==='controlled-approve'){await api('/prescriptions/'+num('prescription_id')+'/controlled-approval',{method:'POST',body:{reason:value('reason'),register_ref:value('register_ref')}});msg='Đã duyệt đơn thuốc kiểm soát';}
 else if(kind==='controlled-receipt'){await keyed(kind,'/controlled-receipts',{medicine_id:num('medicine_id'),lot_number:value('lot_number'),expiry_date:parseDay(value('expiry_date')),quantity:num('quantity'),reason:value('reason'),register_ref:value('register_ref')});msg='Đã gửi đề nghị nhập thuốc kiểm soát';}
 await render();notify(msg);}
async function downloadPdfReceipt(id){const r=await fetch(`/api/print/receipt/${id}`,{headers:authHeader()});if(!r.ok){const m=await r.json().catch(()=>({detail:'Lỗi xuất chứng từ'}));throw new Error(m.detail)}const blob=await r.blob();if(blob.type!=='application/pdf')throw new Error('Không nhận được PDF');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`MinhDuc_PhieuThu_${id}.pdf`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);notify('Đã tạo phiếu thu PDF');}
const PICK={visit:'visit','nurse-visit':'nurseVisit',order:'order',dispense:'dispense',cash:'cashVisit',patient:'patient','mgr-visit':'mgrVisit'};
async function handleClick(element){const action=element.dataset.action,id=Number(element.dataset.id),approve=element.dataset.value==='approve';let msg='';
 if(action==='close-m0-dialog'){$('m0-dialog')?.close();return;}
 if(action==='catalog-pick'){chooseCatalog(element);return;}
 if(action==='patient-details'){const p=await api('/patients/'+id);showM0Dialog('<h2>Hồ sơ hành chính · '+esc(p.full_name)+'</h2>'+stats([['Giấy tờ',esc(p.document_number||p.citizen_id||'Không có')],...ADMIN_FIELDS.map(([k,l])=>[l,esc(p[k]||'Chưa khai')]),['Địa chỉ cũ',esc(p.address||'Chưa khai')]]));return;}
 if(action==='edit-allergies'){const vid=sel.visit,patient=await api('/patients/'+id);if(active!=='doctor'||sel.visit!==vid)return;showM0Dialog('<h2>Dị ứng thuốc · '+esc(patient.full_name)+' ('+esc(patient.code)+')</h2>'+allergyEditor(patient));setAllergyState(patient);return;}
 if(action==='close-abandoned'){showM0Dialog(`<h2>Đóng lượt bỏ dở #${id}</h2><p>Lượt có tiền thu, khoản phí hoặc thuốc đã cấp phải qua quy trình hủy/hoàn hiện có.</p><form class="fields" data-form="close-abandoned">${hidden('visit_id',id)}${selectField('Lý do bắt buộc','close_reason',[['Người bệnh bỏ về','Người bệnh bỏ về'],['Tạo nhầm','Tạo nhầm'],['Khác','Khác (phải ghi chú)']])}${textarea('Ghi chú','close_note')}<div class="wide"><button class="btn-danger">Xác nhận đóng lượt</button></div></form>`);return;}
 if(action==='doctor-tab'){
  const target=element.dataset.target,vid=sel.visit;
  lastDoctorTab={visit:vid,target};
  document.querySelectorAll('.doctor-tabs button').forEach(b=>b.setAttribute('aria-current',String(b===element)));
  if(target==='history'){
   const rows=await api('/visits/'+vid+'/patient-history');
   if(active!=='doctor'||sel.visit!==vid)return;
   $('patient-history').innerHTML=card(t(rows.map(v=>`<tr><td>${showDay(v.created_at)}</td><td>${esc(v.diagnosis||'Chưa có')}${v.adjusted_after_close?'<p class="notice">'+M5.afterCloseLabel+'</p>':''}</td><td>${v.prescriptions.map(r=>esc(r.drug_lines)).join('<br>')}</td><td>${v.results.map(r=>esc(r.name)+': '+esc(r.result_text)).join('<br>')}</td></tr>`),['Ngày khám','Chẩn đoán','Đơn thuốc','Kết luận CLS']),'Lịch sử khám trong phạm vi phân quyền');
  }
  if(target==='payment'){
   const payment=await api('/visits/'+vid+'/payment-status');
   if(active!=='doctor'||sel.visit!==vid)return;
   $('doctor-payment-status').textContent=payment.status+' · Phải thu: '+money(payment.charged)+' · Đã thu: '+money(payment.paid)+' · Còn lại: '+money(payment.due)+(payment.refund_due>0?' · Cần hoàn: '+Number(payment.refund_due).toLocaleString('vi-VN')+' đồng':'');
  }
  const section=document.getElementById('doctor-'+target);
  section.style.scrollMarginTop=stickyOffset()+'px';
  section.scrollIntoView({block:'start'});return;
 }
 if(action==='price-template'){
  const r=await fetch('/api/catalog/services/import/template',{headers:authHeader()});if(!r.ok)throw new Error('Không tải được tệp mẫu');
  const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='BANG_GIA.xlsx';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);return;
 }
 if(action==='price-confirm'){
  if(!pricePreview?.can_confirm||!priceFile)throw new Error('Cần xem trước tệp trước khi xác nhận');
  element.disabled=true;$('price-file').disabled=true;
  try{priceResult=await uploadPriceFile(true);pricePreview=null;priceFile=null;await render();notify('Đã nhập bảng giá');}
  catch(e){pricePreview=null;priceFile=null;await render();throw e}return;
 }
 if(action==='navigate'){active=element.dataset.page;uiLoaded=false;await render();return}
 if(action==='pick'){sel[PICK[element.dataset.kind]]=id;await render();if(element.dataset.kind==='patient')$('visit-step')?.scrollIntoView({block:'start'});if(element.dataset.kind==='mgr-visit')$('mgr-visit-detail')?.scrollIntoView({block:'start'});return}
 if(action==='mgr-page'){mgrSearch.page=id;sel.mgrVisit=null;await render();return}
 if(action==='mgr-close'){closeMgrVisit();return}
 if(action==='tab'){sel[element.dataset.kind==='mgr'?'mgrTab':'adminTab']=element.dataset.tab;await render();return}
 if(action==='clear-search'){sel.patientQuery='';await render();return}
 if(action==='audit-prev'||action==='audit-next'){auditOffset=Math.max(0,auditOffset+(action==='audit-next'?100:-100));await render();return}
 if(action==='rx-page'){sel.rxOffset=id;await render();return}
 if(action==='cash-page'){sel.cashPage=id;await render();return}
 if(action==='export-receipt'){await downloadPdfReceipt(id);return}
 if(action==='export-form'){await exportMedicalForm(element.dataset.kind,element.dataset.id,element.dataset.format||'pdf');return}
 if(action==='file'){const r=await fetch('/api/orders/'+id+'/attachment',{headers:authHeader()});if(!r.ok)throw new Error('Không tải được tệp');const url=URL.createObjectURL(await r.blob());let a=document.createElement('a');a.href=url;a.download='ket_qua_mo_phong';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);return}
 if(action==='add-rx-row'){const med=prescribable(await api('/dispensable-medicines'));$('rx-items').insertAdjacentHTML('beforeend',rxItemRow(med));return}
 if(action==='remove-rx-row'){if(document.querySelectorAll('.rx-line').length>1)element.closest('.rx-line').remove();return}
 if(action==='review-manual-price'){await api('/manual-price-requests/'+id+'/review',{method:'POST',body:{approve}});await render();notify('Đã xử lý đề nghị sửa giá nhập tay');return;}
 if(action==='review-adjustment'){await api('/adjustments/'+id+'/review',{method:'POST',body:{approve}});msg='Đã xử lý đề nghị';}
 else if(action==='review-cancel'){await api('/orders/cancellation-requests/'+id+'/review',{method:'POST',body:{approve}});msg='Đã xử lý yêu cầu hủy';}
 else if(action==='review-addendum'){await api('/visits/addenda/'+id+'/review',{method:'POST',body:{approve}});msg='Đã xử lý phụ lục hồ sơ';}
 else if(action==='review-return'){await api('/medication-returns/'+id+'/review',{method:'POST',body:{approve}});msg='Đã xử lý phiếu trả thuốc';}
 else if(action==='review-controlled-receipt'){await api('/controlled-receipts/'+id+'/review',{method:'POST',body:{approve}});msg='Đã xử lý phiếu nhập kiểm soát';}
 else if(action==='authorize-order'){await api('/orders/'+id+'/authorize',{method:'POST'});msg='Đã duyệt chỉ định và ghi phí';}
 else if(action==='approve'){const r=await api('/orders/'+id+'/approve',{method:'POST'});msg='Đã duyệt kết quả';if(r.warnings?.length)scopeWarnings.set(id,r.warnings.join(' '));}
 else if(action==='cancel-rx'){const reason=prompt('Lý do hủy đơn (ít nhất 8 ký tự):');if(!reason)return;await api('/prescriptions/'+id+'/cancel',{method:'POST',body:{reason}});msg='Đã hủy đơn chưa cấp';}
 else if(action==='dispense'){if(!confirm('Cấp thuốc đúng theo đơn? Hệ thống sẽ xuất kho và ghi tiền thuốc.'))return;await api('/prescriptions/'+id+'/dispense',{method:'POST'});msg='Đã cấp thuốc và ghi tiền thuốc. Bấm "Tải PDF" để in đơn.';}
 else if(action==='complete-visit'){if(!confirm('Hoàn tất và khóa phiếu khám?'))return;await api('/visits/'+id+'/complete',{method:'POST',body:{version:Number(element.dataset.version)}});if(active==='doctor'){const v=await api('/visits/'+id);sel.doctorDay=parseDay(showDay(v.created_at).split(' ')[0]);}msg='Đã hoàn tất, khóa phiếu khám';}
 else if(action==='cancel-order'){const reason=prompt('Lý do đề nghị hủy chỉ định (ít nhất 8 ký tự):');if(!reason)return;await api('/orders/'+id+'/request-cancel',{method:'POST',body:{reason}});msg='Đã gửi quản lý duyệt hủy chỉ định';}
 else if(action==='execute-task'){const content=prompt('Nội dung, kết quả thực hiện y lệnh:');if(!content)return;await api('/nursing-tasks/'+id+'/execute',{method:'POST',body:{content}});msg='Đã ghi nhận thực hiện y lệnh';}
 else if(action==='cancel-task'){const reason=prompt('Lý do hủy y lệnh (ít nhất 8 ký tự):');if(!reason)return;await api('/nursing-tasks/'+id+'/cancel',{method:'POST',body:{reason}});msg='Đã hủy y lệnh';}
 else if(action==='reverse-discount'){const reason=prompt('Lý do hoàn tác giảm phí:');if(!reason)return;await api('/adjustments/'+id+'/reverse',{method:'POST',body:{reason}});msg='Đã hoàn tác giảm phí';}
 else return;
 await render();notify(msg);}
document.addEventListener('submit',async ev=>{const form=ev.target.closest('[data-form]');if(!form)return;ev.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{await handleForm(form)}catch(err){notify(err.message,true)}finally{delete form.dataset.busy;buttons.forEach(b=>b.disabled=false)}});
document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-action]');if(!b||b.disabled)return;if(b.dataset.busy)return;b.dataset.busy='1';try{await handleClick(b)}catch(err){notify(err.message,true)}finally{delete b.dataset.busy}});
document.addEventListener('change',async ev=>{const el=ev.target;
 if(el.closest('[data-form="mgr-visit-search"]')){closeMgrVisit();return;}
 if(el.id==='price-file'){pricePreview=null;priceFile=null;priceResult=null;$('price-review')?.remove();$('price-file-name').textContent=el.files[0]?.name||'Chưa chọn tệp';return;}
 if(el.closest('.rx-line')&&el.name==='medicine_id'){const unit=el.closest('.rx-line').querySelector('[name="unit_id"]');if(unit)unit.disabled=true;try{const med=(await api('/dispensable-medicines')).find(m=>m.id===Number(el.value));if(unit)unit.innerHTML='<option value="">Đơn vị cơ sở</option>'+(med?.units||[]).map(u=>`<option value="${u.id}">${esc(u.name)} = ${u.base_factor}</option>`).join('');}catch(e){notify(e.message,true)}finally{if(unit)unit.disabled=false;}return;}
 try{
  if(el.id==='role_switch'){selectedRole=el.value;active=null;await render();}
  else if(el.id==='visit_choose'&&el.value){sel.visit=Number(el.value);const v=await api('/visits/'+sel.visit);sel.doctorDay=parseDay(showDay(v.created_at).split(' ')[0]);sel.doctorQuery='';await render();}
  else if(el.id==='cash_choose'&&el.value){sel.cashVisit=Number(el.value);await render();}
  else if(el.dataset.catalog==='province'){const form=el.form;form.querySelector('[name=province]').value=el.selectedOptions[0]?.dataset.name||'';const box=form.querySelector('[data-catalog-combo=commune]');if(box){for(const name of ['commune','commune_code','commune_search'])box.querySelector(`[name="${name}"]`).value='';const input=box.querySelector('[data-catalog-search]');input.disabled=!el.value;catalogRequests.set(input,(catalogRequests.get(input)||0)+1);box.querySelector('[role=listbox]').classList.add('hidden');input.setAttribute('aria-expanded','false');}}

  else if(el.id==='account_choose'){sel.account=el.value?Number(el.value):null;await render();}
  else if(el.name==='roles'&&el.closest('form'))adminChange(el.closest('form'));
 }catch(e){notify(e.message,true)}});
// Tự chèn dấu / khi gõ ngày; cập nhật cảnh báo sinh hiệu khi gõ.
document.addEventListener('input',ev=>{const el=ev.target;
 if(el.closest('[data-form="mgr-visit-search"]'))closeMgrVisit();
 if(el.name==='amount'&&el.closest('[data-form="payment"]'))capCheck(el.closest('form'));
 {const af=el.closest&&el.closest('[data-form="adjustment"]');if(af&&af.dataset.confirmed){delete af.dataset.confirmed;af.querySelector('[data-adjust-confirm]').classList.add('hidden');af.querySelector('button.btn').textContent='Xem lại đề nghị'}}
 if(el.id==='price-filter'){const q=el.value.trim().toLowerCase();document.querySelectorAll('tr[data-search]').forEach(tr=>tr.classList.toggle('hidden',!!q&&!tr.dataset.search.includes(q)));return}
 if(el.classList?.contains('date-vn')&&ev.inputType!=='deleteContentBackward'){const d=el.value.replace(/[^\d]/g,'').slice(0,8);if(/^\d+$/.test(el.value.replace(/\//g,''))){el.value=d.length>4?`${d.slice(0,2)}/${d.slice(2,4)}/${d.slice(4)}`:d.length>2?`${d.slice(0,2)}/${d.slice(2)}`:d}}
 if(el.id?.startsWith('v_'))vitalsFlags();});
$('logout').addEventListener('click',async()=>{try{await api('/logout',{method:'POST'})}catch{}sessionStorage.removeItem('md_token');auth=null;selectedRole=null;renderLogin()});
$('change-password').addEventListener('click',async()=>{active='password';try{await render()}catch(e){notify(e.message,true)}});
async function boot(){
 try{const health=await api('/health');serverMode=health.mode||'demo';}catch(e){notify(e.message,true);return;}
 const token=sessionStorage.getItem('md_token');
 if(serverMode==='lan')sessionStorage.removeItem('md_token');
 if(serverMode==='lan'||token){try{auth={token:serverMode==='lan'?null:token,user:null};const user=await api('/me');auth={token:serverMode==='lan'?null:token,user};await render();return}catch{}sessionStorage.removeItem('md_token');auth=null}
 renderLogin();
}

// Only the doctor workspace handles these keys; modified browser shortcuts pass through.
document.addEventListener('keydown',event=>{
 if(event.defaultPrevented||event.repeat||event.ctrlKey||event.altKey||event.metaKey||event.shiftKey||event.isComposing)return;
 if(active!=='doctor'||$('workspace')?.getAttribute('aria-busy')==='true'||document.querySelector('dialog[open]'))return;
 if(event.key==='F4'){event.preventDefault();$('doctor_query')?.focus();return;}
 if(!document.querySelector('[data-action="pick"][data-kind="visit"][aria-pressed="true"]'))return;
 if(event.key==='F2'){const form=document.querySelector('[data-form="clinical"]');const save=form?.querySelector('button.btn');if(save&&!save.disabled){event.preventDefault();form.requestSubmit(save)}}
 if(event.key==='F8'){const finish=document.querySelector('[data-action="complete-visit"]');if(finish&&!finish.disabled){event.preventDefault();finish.click()}}
});

window.addEventListener('scroll',()=>{if(active!=='doctor')return;const sections=[...document.querySelectorAll('.doctor-section')];const offset=stickyOffset();const top=offset+4;const atBottom=scrollY+innerHeight>=document.documentElement.scrollHeight-2;const clicked=lastDoctorTab.visit===sel.visit?sections.find(s=>s.id==='doctor-'+lastDoctorTab.target):null;const nearClicked=clicked&&Math.abs(clicked.getBoundingClientRect().top-offset)<=8;const current=atBottom?(clicked||sections[sections.length-1]):(nearClicked?clicked:(sections.filter(s=>s.getBoundingClientRect().top<=top).pop()||sections[0]));document.querySelectorAll('.doctor-tabs button').forEach(b=>b.setAttribute('aria-current',String(current?.id==='doctor-'+b.dataset.target)));},{passive:true});

// Bounded asynchronous comboboxes: province is mandatory before searching communes.
document.addEventListener('input',event=>{const input=event.target;if(!input.matches('[data-catalog-search]'))return;const box=input.closest('[data-catalog-combo]'),kind=box.dataset.catalogCombo;box.querySelector(`[name="${kind}"]`).value='';box.querySelector(`[name="${kind}_code"]`).value='';catalogRequests.set(input,(catalogRequests.get(input)||0)+1);clearTimeout(catalogTimers.get(input));catalogTimers.set(input,setTimeout(()=>lookupCatalog(input).catch(e=>notify(e.message,true)),180));});
document.addEventListener('focusin',event=>{document.querySelectorAll('[data-catalog-combo]').forEach(box=>{if(!box.contains(event.target)){box.querySelector('[role=listbox]').classList.add('hidden');box.querySelector('[data-catalog-search]').setAttribute('aria-expanded','false')}})});
document.addEventListener('keydown',event=>{const input=event.target;if(!input.matches('[data-catalog-search]'))return;const list=input.closest('[data-catalog-combo]').querySelector('[role=listbox]');if(event.key==='Escape'){list.classList.add('hidden');input.setAttribute('aria-expanded','false');return}if(event.key==='ArrowDown'&&list.classList.contains('hidden')){event.preventDefault();lookupCatalog(input).catch(e=>notify(e.message,true));return}if(list.classList.contains('hidden'))return;const options=[...list.querySelectorAll('[role=option]')];if(!options.length)return;let index=Number(input.dataset.optionIndex||'-1');if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();index=(index+(event.key==='ArrowDown'?1:-1)+options.length)%options.length;input.dataset.optionIndex=String(index);options.forEach((x,i)=>x.classList.toggle('catalog-active',i===index));input.setAttribute('aria-activedescendant',options[index].id);options[index].scrollIntoView({block:'nearest'});}else if(event.key==='Enter'){event.preventDefault();chooseCatalog(options[index<0?0:index]);}});

// D0 catalog UI shares this asset to keep the existing connection budget.
/* D0: bounded catalog search and proof-bound source imports. Chrome 109. */
Object.assign(LABEL,{standard_catalog_previewed:'Xem trước danh mục chuẩn',standard_catalog_imported:'Nạp danh mục chuẩn',icd10_requirement_changed:'Đổi quy tắc mã bệnh chính',diagnosis_codes_updated:'Sửa mã chẩn đoán',service_standard_linked:'Gắn mã kỹ thuật dịch vụ',lab_standard_linked:'Gắn mã dùng chung xét nghiệm',official_address_linked:'Ghép mã ĐVHC chính thức'});
const D0={names:{icd10:'ICD-10',tech_catalog:'Kỹ thuật PL01 (đến 30/06/2026)',tech_catalog_pl02:'Kỹ thuật PL02 (từ 01/07/2026)',shared_lab_codes:'Mã chỉ số CLS',official_addresses:'ĐVHC chính thức',occupation_catalog:'Nghề nghiệp'},proofs:new WeakMap(),timer:null,
 async admin(){const cfg=await api('/standards/config');this.columns=cfg.columns;const imports=await api('/standards/imports');const services=(await api('/standards/links/services')).items;const tests=(await api('/standards/links/lab-tests')).items;const unmatched=await api('/standards/geography/unmatched');const review=await api('/standards/pl02/review');return card(`<form data-d0="settings"><label><input type="checkbox" name="required" ${cfg.require_primary_icd10?'checked':''}> Bắt buộc mã bệnh chính khi hoàn tất / khóa đơn</label><button>Lưu quy tắc ICD-10</button></form><form data-d0="import" class="fields"><label>Danh mục<select name="kind">${Object.entries({icd10:'ICD-10',tech_catalog:'Kỹ thuật PL01 (đến 30/06/2026)',tech_catalog_pl02:'Kỹ thuật PL02 (từ 01/07/2026)',shared_lab_codes:'Mã chỉ số CLS',official_addresses:'ĐVHC chính thức',occupation_catalog:'Nghề nghiệp'}).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>${this.input('Số văn bản','document_number')}${this.input('Ngày văn bản (dd/mm/yyyy; trống nếu cần đối chiếu)','document_date').replace(' required','')}${this.input('Nguồn file gốc','source')}${this.input('Phiên bản','version')}${this.input('Dòng tiêu đề','header_row','1')}<label>Ánh xạ cột/giá trị/sheet (JSON, để {} dùng tên mẫu)<textarea name="mapping">{}</textarea></label><label>Tệp CSV UTF-8 / Excel<input name="file" type="file" accept=".xlsx,.csv" required></label><button name="action" value="preview">Xem trước</button><div class="wide d0-preview"></div><div class="wide d0-confirm hidden"><label><input type="checkbox" name="confirm"> Đã đối chiếu file gốc và xem trước</label><button name="action" value="commit">Nạp danh mục</button></div></form><p>Chỉ nạp file gốc đã đối chiếu nguồn. Không tự sinh mã; mục bỏ khỏi bản nạp mới được ngừng dùng.</p>`+t(imports.map(x=>`<tr><td>${esc(this.names[x.kind]||x.kind)} ${esc(x.version)}</td><td>${esc(x.document_number)} · ${x.document_date?showDay(x.document_date):'Chưa đối chiếu ngày'}</td><td>${esc(x.source)}</td><td>${x.row_count} dòng<br><small class="d0-hash">${esc(x.fingerprint)}</small></td></tr>`),['Danh mục/phiên bản','Văn bản/ngày','Nguồn','Số dòng / SHA-256']),'Danh mục chuẩn D0')+card(this.linkForm('services',services,'Mã kỹ thuật (nhiều mã cách nhau bằng dấu phẩy)')+this.linkForm('lab-tests',tests,'Mã chỉ số dùng chung'),'Quản lý toàn bộ liên kết mã')+card(`<p>${review.total} mảnh mã PL02 cần rà soát tay; giữ nguyên, không tự sửa.</p>`+t(review.items.map(x=>`<tr><td>STT ${esc(x.pl02_stt)}</td><td>${esc(x.raw_token)}</td><td>Cần rà soát tay</td></tr>`),['Dòng PL02','Mảnh nguyên văn','Trạng thái']),'Đối chiếu PL02 → PL01')+card(`<p>${unmatched.length} mục chưa ghép duy nhất theo tên tỉnh + tên xã</p>`+t(unmatched.slice(0,30).map(x=>`<tr><td>${esc(x.province)} / ${esc(x.name)}</td><td>${esc(x.tms_code)}</td></tr>`),['Tên chưa ghép','Mã TMS'])+`<form data-d0="geo" class="fields">${this.input('Mã xã TMS','tms_code')}${this.input('Mã xã chính thức từ file đã nạp','official_code')}<label><input type="checkbox" name="exception_confirmed"> Xác nhận ngoại lệ khác tỉnh</label><label>Lý do ngoại lệ<input name="reason" minlength="8"></label><button>Ghép thủ công</button></form>`,'Đối chiếu ĐVHC')},
 input(label,name,value=''){return `<label>${label}<input name="${name}" value="${esc(value)}" required></label>`},
 linkForm(kind,rows,label){const service=kind==='services';return `<form data-d0="link" data-kind="${kind}" class="fields"><label>${service?'Dịch vụ':'Chỉ số xét nghiệm'}<select data-d0-link-filter><option value="all">Tất cả</option><option value="unlinked">Chưa gắn</option><option value="inactive">Mã ngừng dùng / không tồn tại</option></select><select name="id">${rows.map(x=>`<option value="${x.id}" data-links="${esc(JSON.stringify(x.links))}" data-link-state="${!x.links.length?'unlinked':x.links.some(l=>l.status!=='active')?'inactive':'active'}">${esc(x.name+' · '+x.links.map(l=>l.catalog+' '+l.code+' ('+({active:'Còn dùng',inactive:'Ngừng dùng',missing:'Không tồn tại'}[l.status])+')').join('; '))}</option>`).join('')}</select></label>${service?'<label>Chế độ sửa<select name="mode"><option value="replace">Thay toàn bộ phần đang sửa</option><option value="add">Thêm mã</option><option value="remove">Bỏ từng mã đã chọn</option></select></label>':'<input type="hidden" name="mode" value="replace">'}<div class="d0-existing wide"></div><div class="d0-operations wide"></div><input type="hidden" name="codes"><p class="d0-before wide"></p><p class="d0-chosen wide">Chưa chọn mã</p><label>Gợi ý theo tên — bấm chọn, không tự gắn<input data-d0-link-search="${service?'tech_catalog':'shared_lab_codes'}" autocomplete="off"><span class="d0-link-results"></span></label>${service?'<input type="hidden" name="pl02_ids"><label>Gợi ý dòng PL02 theo tên (STT gốc, không phải mã kỹ thuật mới)<input data-d0-link-search="tech_catalog_pl02" autocomplete="off"><span class="d0-link-results"></span></label><label><input type="checkbox" name="package"> Dịch vụ gói (cho phép nhiều mã kỹ thuật)</label>':''}<label>Lý do sửa/bỏ liên kết<input name="reason" minlength="8"></label><label><input type="checkbox" name="confirmed"> Xác nhận sửa/bỏ liên kết</label><label><input type="checkbox" name="exception_confirmed"> Xác nhận rà soát ngoại lệ PL02</label><button>Gắn các mục đã chọn</button><button type="button" data-d0-clear>Chọn bỏ toàn bộ liên kết</button></form>`},
 async clinical(v){const items=JSON.parse(v.diagnosis_codes||'[]');if(['completed','cancelled'].includes(v.status))return `<p>${items.length?items.map(x=>esc(x.code+' – '+x.name)).join('; '):'Chưa mã hóa'}</p>`;return `<form data-d0="diagnosis" data-id="${v.id}" data-version="${v.version}" class="fields"><p class="wide">${v.primary_icd10?'Đã mã hóa':'Chưa mã hóa'} · ${items.map(x=>esc(x.code+' – '+x.name)).join('; ')}</p><label class="wide">Tìm ICD-10 theo mã hoặc tên không dấu<input data-d0-search="icd10" autocomplete="off"><span class="d0-results"></span></label>${this.input('Mã bệnh chính','primary',v.primary_icd10||'')}<label>Mã bệnh kèm (phân cách dấu phẩy)<input name="secondary" value="${esc(items.filter(x=>!x.primary).map(x=>x.code).join(','))}"></label><button>Lưu mã chẩn đoán</button><p class="wide">Chọn kết quả tìm kiếm để điền bệnh chính; dùng nút “Bệnh kèm” cho bệnh đi kèm. Mô tả chữ của bác sĩ giữ ở phiếu khám.</p></form>`},
 occupation(p){return `<label>Nghề nghiệp<input name="occupation" data-d0-search="occupation_catalog" value="${esc(p.occupation||'')}" autocomplete="off"><input type="hidden" name="occupation_code" value="${esc(p.occupation_code||'')}"><span class="d0-results"></span><small>${p.occupation_code?'Đã chuẩn hóa':'Chưa chuẩn hóa — cho phép chữ tự do khi chưa có danh mục'}</small></label>`}
};
document.addEventListener('input',e=>{const form=e.target.closest('[data-d0="import"]');if(form){D0.proofs.delete(form);form.querySelector('.d0-confirm').classList.add('hidden');form.querySelector('[name=confirm]').checked=false}const el=e.target.closest('[data-d0-search]');if(!el)return;if(el.name==='occupation')el.parentElement.querySelector('[name=occupation_code]').value='';clearTimeout(D0.timer);D0.timer=setTimeout(async()=>{try{const value=el.value;const q=await api('/standards/'+el.dataset.d0Search+'?q='+encodeURIComponent(value)+'&limit=20');if(el.value!==value||!el.isConnected)return;el.parentElement.querySelector('.d0-results').innerHTML=q.items.map(x=>`<button type="button" data-d0-code="${esc(x.code)}" data-name="${esc(x.name_vi||x.name)}">${esc(x.code+' – '+(x.name_vi||x.name))}</button>`+(el.dataset.d0Search==='icd10'?`<button type="button" data-d0-secondary="${esc(x.code)}">Bệnh kèm</button>`:'')).join('')}catch(err){notify(err.message,true)}},200)});
document.addEventListener('click',e=>{const b=e.target.closest('[data-d0-code],[data-d0-secondary]');if(!b)return;const f=b.closest('form');if(b.dataset.d0Secondary){const x=f.querySelector('[name=secondary]');x.value=[...new Set(x.value.split(',').map(x=>x.trim()).filter(Boolean).concat(b.dataset.d0Secondary))].join(',');return}if(f.querySelector('[name=primary]'))f.querySelector('[name=primary]').value=b.dataset.d0Code;else {const label=b.closest('label');label.querySelector('[name=occupation]').value=b.dataset.name;label.querySelector('[name=occupation_code]').value=b.dataset.d0Code}b.parentElement.innerHTML=''});
document.addEventListener('submit',async e=>{const f=e.target.closest('[data-d0]');if(!f)return;e.preventDefault();e.stopImmediatePropagation();if(f.dataset.d0==='link'){const id=f.querySelector('[name=id]').value;if(!id){notify('Không có mục phù hợp',true);return}if(f.dataset.hydratedFor!==id){D0.hydrateLinks(f);notify('Mục đang chọn đã thay đổi. Vui lòng xem lại mã trước khi lưu.',true);return}}const d=new FormData(f),v=k=>String(d.get(k)||'');try{switch(f.dataset.d0){case 'settings':await api('/standards/settings',{method:'PUT',body:{require_primary_icd10:d.has('required')}});break;case 'diagnosis':{const r=await api('/visits/'+f.dataset.id+'/diagnosis-codes',{method:'PUT',body:{version:+f.dataset.version,primary:v('primary')||null,secondary:v('secondary').split(',').map(x=>x.trim()).filter(Boolean)}});if(r.warnings.length)notify(r.warnings.join('; '),true);break}case 'link':{const old=JSON.parse(f.querySelector('[name=id]').selectedOptions[0].dataset.links||'[]');const codes=v('codes').split(',').filter(Boolean),ids=v('pl02_ids').split(',').filter(Boolean);const removing=x=>v('mode')==='remove'?(x.catalog==='PL02'?ids.includes(String(x.id)):codes.includes(x.code)):v('mode')==='replace'?(x.catalog==='PL02'?!ids.includes(String(x.id)):!codes.includes(x.code)):false;const gone=old.filter(removing);if(gone.length&&!window.confirm('Xác nhận bỏ các mã: '+gone.map(x=>x.catalog+' '+x.code).join('; ')))return;f.dataset.removedCodes=JSON.stringify(gone.filter(x=>x.catalog!=='PL02').map(x=>x.code));f.dataset.removedPl02=JSON.stringify(gone.filter(x=>x.catalog==='PL02').map(x=>String(x.id)));await api('/standards/'+f.dataset.kind+'/'+v('id'),{method:'PUT',body:f.dataset.kind==='services'?{mode:v('mode'),removed_codes:JSON.parse(f.dataset.removedCodes),removed_pl02_ids:JSON.parse(f.dataset.removedPl02),codes:v('codes').split(',').map(x=>x.trim()).filter(Boolean),confirmed:d.has('confirmed'),exception_confirmed:d.has('exception_confirmed'),reason:v('reason'),package:d.has('package'),pl02_ids:v('pl02_ids').split(',').filter(Boolean)}:{code:v('codes')||null,confirmed:d.has('confirmed'),reason:v('reason')}});break;}case 'geo':await api('/standards/geography/link',{method:'PUT',body:{tms_code:v('tms_code'),official_code:v('official_code'),exception_confirmed:d.has('exception_confirmed'),reason:v('reason')}});break;case 'import':{const preview=e.submitter.value==='preview';if(!preview&&(!D0.proofs.has(f)||!d.has('confirm')))throw Error('Cần xem trước và xác nhận đúng tệp');d.set('metadata',JSON.stringify({document_number:v('document_number'),document_date:parseDay(v('document_date'),'Ngày văn bản'),source:v('source'),version:v('version')}));d.set('preview',String(preview));d.set('proof',D0.proofs.get(f)||'');const r=await api('/standards/'+v('kind')+'/import',{method:'POST',body:d,isFile:true});if(preview){D0.proofs.set(f,r.fingerprint);f.querySelector('.d0-preview').innerHTML='<p>'+r.total+' dòng; hiển thị tối đa 30 dòng xem trước.</p>'+t(r.rows.map(row=>'<tr>'+Object.keys(r.columns||D0.columns[v('kind')]).map(k=>'<td>'+esc(row[k])+'</td>').join('')+'</tr>'),Object.values(r.columns||D0.columns[v('kind')]));f.querySelector('.d0-confirm').classList.remove('hidden');return}notify('Đã nạp '+r.imported+' dòng; chưa ghép: '+(r.unmatched||[]).length);break}}await render()}catch(err){notify(typeof err.message==='string'?err.message:'Không thể lưu danh mục',true)}},true);

// Separate bounded suggestions for catalog links: choosing a row is always explicit.
document.addEventListener('input',event=>{const el=event.target.closest('[data-d0-link-search]');if(!el)return;clearTimeout(D0.linkTimer);D0.linkTimer=setTimeout(async()=>{try{const value=el.value;const kind=el.dataset.d0LinkSearch;const q=await api('/standards/'+kind+'?q='+encodeURIComponent(value)+'&limit=20');if(el.disabled||el.value!==value||!el.isConnected)return;el.parentElement.querySelector('.d0-link-results').innerHTML=q.items.map(x=>`<button type="button" data-d0-link-pick="${esc(kind==='tech_catalog_pl02'?x.id:x.code)}" data-kind="${kind}" data-source-code="${esc(x.code)}" data-name="${esc(x.name||'(Tên rỗng trong file gốc)')}">${kind==='tech_catalog_pl02'?'STT PL02 ':''}${esc(x.code+' – '+(x.name||'(Tên rỗng trong file gốc)'))}${x.loinc?' · LOINC '+esc(x.loinc):''}</button>`).join('')}catch(e){notify(e.message,true)}},200)});

D0.linkCurrent=f=>JSON.parse(f.querySelector('[name=id]').selectedOptions[0]?.dataset.links||'[]');
D0.linkKey=x=>x.catalog+':'+String(x.catalog==='PL02'?x.id:x.code);
D0.linkLabel=x=>(x.catalog==='PL02'?'STT ':'')+x.code+(x.name?' – '+x.name:'');
D0.drawLinkOperations=function(f){
 const current=D0.linkCurrent(f),mode=f.querySelector('[name=mode]').value,ops=f.d0Operations||[];
 f.querySelector('[name=codes]').value=ops.filter(x=>x.catalog!=='PL02').map(x=>x.code).join(',');
 const ids=f.querySelector('[name=pl02_ids]');if(ids)ids.value=ops.filter(x=>x.catalog==='PL02').map(x=>x.id).join(',');
 const keys=new Set(ops.map(D0.linkKey));let final=ops;
 if(mode==='add')final=current.concat(ops.filter(x=>!current.some(y=>D0.linkKey(y)===D0.linkKey(x))));
 if(mode==='remove')final=current.filter(x=>!keys.has(D0.linkKey(x)));
 f.querySelector('.d0-operations').innerHTML='<p>Mã thao tác</p>'+ops.map((x,i)=>'<span>'+esc(D0.linkLabel(x))+(mode==='replace'?'<button type="button" data-d0-operation-remove="'+i+'">Bỏ khỏi danh sách thay thế</button>':'')+'</span>').join('');
 f.querySelector('.d0-chosen').textContent='Sau: '+(final.map(D0.linkLabel).join('; ')||'Không gắn mã');
};
D0.resetLinkMode=function(f){
 clearTimeout(D0.linkTimer);
 const current=D0.linkCurrent(f),mode=f.querySelector('[name=mode]').value;
 f.d0Operations=mode==='replace'?current.map(x=>({...x})):[];
 f.querySelector('.d0-existing').innerHTML='<p>Mã đang có</p>'+(current.length?current.map((x,i)=>'<label><input type="checkbox" data-d0-existing="'+i+'" '+(mode==='remove'?'':'disabled')+'>'+esc(x.catalog+' '+D0.linkLabel(x))+'</label>').join(''):'<p>Chưa gắn mã</p>');
 for(const el of f.querySelectorAll('[data-d0-link-search]')){el.value='';el.disabled=mode==='remove';el.parentElement.querySelector('.d0-link-results').innerHTML=''}
 D0.drawLinkOperations(f);
};
D0.hydrateLinks=function(f){
 const id=f.querySelector('[name=id]').value;f.dataset.hydratedFor=id;
 const save=f.querySelector('button:not([type]),button[type=submit]');save.disabled=!id;
 for(const el of f.querySelectorAll('[name=confirmed],[name=exception_confirmed]'))el.checked=false;
 f.querySelector('[name=reason]').value='';
 const current=D0.linkCurrent(f),pack=f.querySelector('[name=package]');if(pack)pack.checked=Math.max(current.filter(x=>x.catalog==='PL01').length,current.filter(x=>x.catalog==='PL02').length)>1;
 f.querySelector('.d0-before').textContent=id?'Trước: '+(current.map(D0.linkLabel).join('; ')||'Chưa gắn mã'):'Không có mục phù hợp';
 D0.resetLinkMode(f);
};
document.addEventListener('click',event=>{
 const b=event.target.closest('[data-d0-link-pick]');if(b){const f=b.closest('form');if(f.querySelector('[name=mode]').value==='remove')return;
 const x={catalog:b.dataset.kind==='tech_catalog_pl02'?'PL02':f.dataset.kind==='services'?'PL01':'CLS',code:b.dataset.sourceCode,name:b.dataset.name,id:b.dataset.d0LinkPick};
 if(f.dataset.kind==='lab-tests')f.d0Operations=[x];else if(!f.d0Operations.some(y=>D0.linkKey(y)===D0.linkKey(x)))f.d0Operations.push(x);
 b.parentElement.innerHTML='';D0.drawLinkOperations(f);return}
 const remove=event.target.closest('[data-d0-operation-remove]');if(remove){const f=remove.closest('form');f.d0Operations.splice(+remove.dataset.d0OperationRemove,1);D0.drawLinkOperations(f);return}
 if(event.target.matches('[data-d0-clear]')){const f=event.target.closest('form');f.querySelector('[name=mode]').value='replace';D0.resetLinkMode(f);f.d0Operations=[];D0.drawLinkOperations(f)}
});
document.addEventListener('change',e=>{
 const f=e.target.closest('[data-d0="link"]');if(!f)return;
 if(e.target.matches('[data-d0-link-filter]')){for(const o of f.querySelector('[name=id]').options)o.hidden=e.target.value!=='all'&&o.dataset.linkState!==e.target.value;const first=Array.from(f.querySelector('[name=id]').options).find(o=>!o.hidden);f.querySelector('[name=id]').value=first?first.value:'';D0.hydrateLinks(f)}
 else if(e.target.matches('[name=id]'))D0.hydrateLinks(f);
 else if(e.target.matches('[name=mode]'))D0.resetLinkMode(f);
 else if(e.target.matches('[data-d0-existing]')){const current=D0.linkCurrent(f);f.d0Operations=Array.from(f.querySelectorAll('[data-d0-existing]:checked')).map(x=>current[+x.dataset.d0Existing]);D0.drawLinkOperations(f)}
});
new MutationObserver(()=>{for(const f of document.querySelectorAll('[data-d0="link"]'))if(!f.dataset.hydrated){f.dataset.hydrated='1';D0.hydrateLinks(f)}}).observe(document.getElementById('workspace'),{childList:true,subtree:true});

function s1ResultTime(x){return x.legacy_time_unknown?'Kết quả nhập trước nâng cấp – không rõ thời điểm gửi':showDay(x.created_at);}
document.addEventListener('click',async event=>{const button=event.target.closest('[data-s1-result-history]');if(!button)return;event.preventDefault();event.stopImmediatePropagation();try{const result=await api('/orders/'+button.dataset.s1ResultHistory+'/result/versions');const dialog=document.createElement('dialog');dialog.innerHTML='<h2>Các phiên bản kết quả</h2>'+t(result.items.map(x=>`<tr><td>${x.version}</td><td>${esc(x.result_text)}</td><td>${esc(x.created_by_name||'—')}</td><td>${s1ResultTime(x)}</td><td>${x.snapshot?'Đã duyệt':'Chưa duyệt'}</td></tr>`),['Phiên bản','Nội dung','Người gửi','Thời điểm','Trạng thái'])+'<button type="button">Đóng</button>';dialog.querySelector('button').addEventListener('click',()=>dialog.remove());document.body.append(dialog);dialog.showModal()}catch(error){notify(error.message,true)}},true);

// Presentation only: keep startup connections available to the workflow scripts.
window.addEventListener('load',async()=>{
 try{
  for(const face of document.fonts){
   if(face.family.replace(/["']/g,'')==='Be Vietnam Pro'){
    try{await face.load()}catch(error){console.warn('Không tải được font nội bộ:',error.message)}
   }
  }
 }finally{document.documentElement.classList.remove('fonts-pending')}
},{once:true});
