'use strict';
/* global SCREENS, menus, api, esc, money, t, card, stockDownload, render, notify, vietnamToday, showDay, dateField, parseDay, bindStockTables, auth, renderLogin */

// The smoke harness also loads this asset manually after app.js.
if(typeof SCREENS!=='undefined'&&!SCREENS['s2e-reports']){
 const S2E={
  reports:[['revenue','Doanh thu'],['visits','Lượt khám'],['cashier','Sổ thu tiền'],['corrections','Sửa/hủy']],
  periods:new WeakMap(),

  table(key,columns,rows){
   const body=rows.map(row=>{
    const cells=columns.map(([,field,format])=>{
     const value=row[field];
     const display=esc(value===null?'—':format==='money'?money(value):format==='date'?showDay(value):value);
     const align=({money:'r',number:'r',date:'c',center:'c'})[format]||'';
     return `<td class="${align}" title="${display}">${display}</td>`;
    });
    return `<tr>${cells.join('')}</tr>`;
   });
   const formats=columns.map(([, ,format])=>format||'text').join(' ');
   return `<div data-s2e-table="${key}" data-formats="${formats}">${t(body,columns.map(([label])=>label))}</div>`;
  },

  bindTables(root){
   for(const wrapper of root.querySelectorAll('[data-s2e-table]')){
    const box=wrapper.firstElementChild;
    const table=box.querySelector('table');
    const colgroup=document.createElement('colgroup');
    box.className='s2b-table-wrap';
    box.tabIndex=0;
    box.setAttribute('aria-label','Bảng cuộn ngang và dọc');
    table.classList.add('s2b-table');
    table.dataset.stockTable='s2e-'+wrapper.dataset.s2eTable;
    const formats=wrapper.dataset.formats.split(' ');
    table.querySelectorAll('th').forEach((header,index)=>{
     const label=header.textContent;
     const format=formats[index];
     header.title=label;
     if(format==='money'||format==='number')header.classList.add('r');
     if(format==='date'||format==='center')header.classList.add('c');
     const col=document.createElement('col');
     const width=format==='date'?172:format==='text'?200:138;
     col.dataset.stockWidth=String(Math.max(width,9*label.length+30));
     colgroup.append(col);
     const grip=document.createElement('span');
     grip.className='s2b-grip';
     grip.tabIndex=0;
     grip.setAttribute('role','separator');
     grip.setAttribute('aria-orientation','vertical');
     grip.setAttribute('aria-label','Đổi độ rộng cột '+label);
     header.append(grip);
    });
    table.prepend(colgroup);
   }
   bindStockTables(root);
  },

  revenue(data){
   const columns=[
    ['Ngày','day','date'],['Thuốc','medicine','money'],['Cận lâm sàng','clinical','money'],
    ['Thủ thuật','procedure','money'],['Khác','other','money'],['Giảm giá','discount','money'],
    ['Doanh thu','revenue','money'],['Đã thu','paid','money'],['Hoàn tiền','refund','money'],
    ['Chênh lệch trong ngày','outstanding','money'],['Khoản chưa có giá','unpriced_count','number']
   ];
   const unpaid=[
    ['Mã NB','patient_code'],['Họ tên','patient_name'],['Ngày khám','visit_date','date'],
    ['Phải thu','charged','money'],['Đã thu','paid','money'],['Còn thiếu','known_due','money'],
    ['Khoản chưa có giá','unpriced_count','number'],['Ghi chú','note']
   ];
   return '<h3>Theo ngày</h3>'+this.table('revenue',columns,[...data.rows,{...data.totals,day:'Tổng kỳ'}])+
    '<h3>Lượt khám còn thiếu tiền</h3>'+this.table('unpaid',unpaid,data.unpaid_visits);
  },

  visits(data){
   const counts=[['Lượt khám','visits','number'],['Lượt hủy','cancelled','number']];
   return `<p>Tổng lượt khám: <b>${esc(data.total)}</b> · Lượt hủy: <b>${esc(data.cancelled)}</b></p>`+
    '<h3>Theo ngày</h3>'+this.table('visits-day',[['Ngày','day','date'],...counts],data.by_day)+
    '<h3>Theo bác sĩ</h3>'+this.table('visits-doctor',[['Bác sĩ','doctor_name'],...counts],data.by_doctor);
  },

  cashier(data){
   const entries=[
    ['Thời gian thu','collected_at','date'],['Mã NB','patient_code'],['Họ tên','patient_name'],
    ['Số tiền','amount','money'],['Phương thức','method_name'],['Người thu','cashier_name']
   ];
   const totals=[['Số lần','count','number'],['Tổng tiền','amount','money']];
   return `<p>Tổng tiền thu: <b>${esc(money(data.total))}</b></p>`+this.table('cashier',entries,data.rows)+
    '<h3>Tổng theo người thu</h3>'+this.table('cashier-person',[['Người thu','cashier_name'],...totals],data.by_cashier)+
    '<h3>Tổng theo phương thức</h3>'+this.table('cashier-method',[['Phương thức','method_name'],...totals],data.by_method);
  },

  corrections(data){
   return this.table('corrections',[
    ['Loại','type','center'],['Mã NB','patient_code'],['Nội dung','content'],['Người','actor'],
    ['Thời gian','occurred_at','date'],['Lý do','reason']
   ],data.rows);
  },

  filter(period){
   return `<div class="s2b-form">${card(`<form class="fields" data-s2e-form>
    <label class="field">Chọn kỳ<select name="period">
     <option value="month">Tháng</option>
     <option value="range" ${period.date_from?'selected':''}>Từ ngày – đến ngày</option>
    </select></label>
    <label class="field">Tháng<input type="month" name="month" value="${esc(period.month||vietnamToday().slice(0,7))}" required></label>
    ${dateField('Từ ngày','s2e_date_from',true,period.date_from)}
    ${dateField('Đến ngày','s2e_date_to',true,period.date_to)}
    <div class="wide"><button type="submit" class="btn">Xem</button></div>
   </form>`,'Kỳ báo cáo')}</div>`;
  },

  updateFields(form){
   const month=form.elements.period.value==='month';
   for(const [name,visible] of [['month',month],['s2e_date_from',!month],['s2e_date_to',!month]]){
    const input=form.elements.namedItem(name);
    input.disabled=!visible;
    input.closest('.field').classList.toggle('hidden',!visible);
   }
  },

  async report(kind,title,query){
   const download=`<div class="multi-actions"><button type="button" class="ghost" data-s2e-export="${kind}">Tải Excel</button></div>`;
   try{
    const data=await api('/reports/'+kind+'?'+query);
    const warning=data.warning?`<p class="notice error" role="alert">${esc(data.warning).replace(/\r?\n/g,'<br>')}</p>`:'';
    return card(warning+`<p class="hint">${esc(data.note)}</p>`+download+this[kind](data),title);
   }catch(error){
    return card(`<p class="notice error" role="alert">${esc(error.message)}</p>`+download,title);
   }
  },

  async screen(){
   const session=auth;
   const period=this.periods.get(session)||{month:vietnamToday().slice(0,7)};
   const query=new URLSearchParams(period).toString();
   const filenamePeriod=period.month||period.date_from+'_'+period.date_to;
   const cards=await Promise.all(this.reports.map(([kind,title])=>this.report(kind,title,query)));
   if(auth!==session)return {html:'',after(){if(!auth)renderLogin();}};
   return {
    html:`<div class="s2b-standalone" data-s2e-query="${esc(query)}" data-s2e-filename-period="${esc(filenamePeriod)}">
     ${this.filter(period)}${cards.join('')}
    </div>`,
    after(){
     const root=document.querySelector('[data-s2e-query]');
     S2E.updateFields(root.querySelector('[data-s2e-form]'));
     S2E.bindTables(root);
    }
   };
  }
 };

 SCREENS['s2e-reports']=()=>S2E.screen();
 menus.manager.push(['s2e-reports','Báo cáo quản lý']);
 menus.admin.push(['s2e-reports','Báo cáo quản lý']);

 document.addEventListener('change',event=>{
  if(!event.target.matches('[data-s2e-form] [name="period"]'))return;
  S2E.updateFields(event.target.form);
 },true);

 document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-s2e-form]');
  if(!form)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  try{
   const fields=new FormData(form);
   const period=fields.get('period')==='month'?{month:fields.get('month')}:{
    date_from:parseDay(fields.get('s2e_date_from'),'Từ ngày'),
    date_to:parseDay(fields.get('s2e_date_to'),'Đến ngày')
   };
   if(fields.get('period')==='range'){
    if(!period.date_from||!period.date_to)throw new Error('Nhập đủ từ ngày và đến ngày.');
    if(period.date_from>period.date_to)throw new Error('Từ ngày phải trước hoặc bằng đến ngày.');
   }
   S2E.periods.set(auth,period);
   await render();
  }catch(error){
   notify(error.message,true);
  }
 },true);

 document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-s2e-export]');
  if(!button)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const {s2eQuery,s2eFilenamePeriod}=button.closest('[data-s2e-query]').dataset;
  const kind=button.dataset.s2eExport;
  button.disabled=true;
  try{
   await stockDownload(`/reports/${kind}/export?${s2eQuery}`,`Bao_cao_${kind}_${s2eFilenamePeriod}.xlsx`);
  }catch(error){
   notify(error.message,true);
  }finally{
   button.disabled=false;
  }
 },true);
}
