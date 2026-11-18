'use strict';
/* global SCREENS, menus, api, esc, money, t, card, stockDownload, stats, labelTables, notify, vietnamToday, showDay, dateField, parseDay, bindStockTables, auth */

// The smoke harness also loads this asset manually after app.js.
if(typeof SCREENS!=='undefined'&&!SCREENS['s2e-reports']){
 const S2E={
  reports:[['revenue','Doanh thu'],['visits','Lượt khám'],['cashier','Sổ thu tiền'],['corrections','Sửa/hủy']],
  periods:new WeakMap(),
  rowLimit:500,

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
    ['Doanh thu','revenue','money'],['Đã thu thuần (sau hoàn tiền)','paid','money'],['Hoàn tiền','refund','money'],
    ['Chênh lệch trong ngày','outstanding','money'],['Khoản chưa có giá','unpriced_count','number']
   ];
   const unpaid=[
    ['Mã NB','patient_code'],['Họ tên','patient_name'],['Ngày khám','visit_date','date'],
    ['Phải thu','charged','money'],['Đã thu thuần (sau hoàn tiền)','paid','money'],['Còn thiếu','known_due','money'],
    ['Khoản chưa có giá','unpriced_count','number'],['Ghi chú','note']
   ];
   return stats([
    ['Chưa thu – lượt khám trong kỳ',money(data.totals.known_due)],
    ['Chênh lệch thu – phát sinh trong kỳ',money(data.totals.outstanding)]
   ])+'<h3>Theo ngày</h3>'+this.table('revenue',columns,[...data.rows,{...data.totals,day:'Tổng kỳ'}])+
    '<h3>Lượt khám còn thiếu tiền</h3>'+this.limitedTable('unpaid',unpaid,data.unpaid_visits);
  },

  visits(data){
   const counts=[['Lượt khám','visits','number'],['Lượt hủy','cancelled','number']];
   return `<p>Tổng lượt khám: <b>${esc(data.total)}</b> · Lượt hủy: <b>${esc(data.cancelled)}</b></p>`+
    '<h3>Theo ngày</h3>'+this.table('visits-day',[['Ngày','day','date'],...counts],data.by_day)+
    '<h3>Theo bác sĩ</h3>'+this.table('visits-doctor',[['Bác sĩ','doctor_name'],...counts],data.by_doctor)+
    '<h3>Theo trạng thái</h3>'+this.table('visits-status',[
     ['Trạng thái','status_name'],['Số lượt','count','number']
    ],data.by_status);
  },

  cashier(data){
   const entries=[
    ['Thời gian thu','collected_at','date'],['Mã NB','patient_code'],['Họ tên','patient_name'],
    ['Số tiền','amount','money'],['Phương thức','method_name'],['Người thu','cashier_name']
   ];
   const totals=[['Số lần','count','number'],['Tổng tiền','amount','money']];
   return `<p>Tổng tiền thu: <b>${esc(money(data.total))}</b></p>`+this.limitedTable('cashier',entries,data.rows)+
    '<h3>Tổng theo người thu</h3>'+this.table('cashier-person',[['Người thu','cashier_name'],...totals],data.by_cashier)+
    '<h3>Tổng theo phương thức</h3>'+this.table('cashier-method',[['Phương thức','method_name'],...totals],data.by_method);
  },

  corrections(data){
   return this.limitedTable('corrections',[
    ['Loại','type','center'],['Mã NB','patient_code'],['Nội dung','content'],['Người','actor'],
    ['Thời gian','occurred_at','date'],['Lý do','reason']
   ],data.rows);
  },

  limitedTable(key,columns,rows){
   const hint=rows.length>this.rowLimit
    ?`<p class="hint">Hiển thị ${this.rowLimit}/${rows.length} dòng mới nhất, tải Excel để xem đủ</p>`:'';
   return hint+this.table(key,columns,rows.slice(-this.rowLimit).reverse());
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
    <div class="wide"><button type="submit" class="btn" disabled>Xem</button></div>
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
    return card(`<p class="notice error" role="alert">${esc(error.message)}</p>`,title);
   }
  },

  bindControls(root,session,period){
   const form=root.querySelector('[data-s2e-form]');
   const submit=form.querySelector('button[type="submit"]');
   const tabs=[...root.querySelectorAll('[data-s2e-tab]')];
   const result=root.querySelector('[data-s2e-result]');
   let selected=tabs[0];
   let loading=false;
   const load=async ()=>{
    loading=true;
    submit.disabled=true;
    for(const tab of tabs){
     tab.disabled=true;
     tab.className=tab===selected?'btn':'ghost';
     tab.setAttribute('aria-pressed',String(tab===selected));
    }
    result.setAttribute('aria-busy','true');
    result.textContent='Đang tải báo cáo…';
    const kind=selected.dataset.s2eTab;
    const query=new URLSearchParams(period).toString();
    const filenamePeriod=period.month||period.date_from+'_'+period.date_to;
    try{
     const html=await this.report(kind,selected.textContent,query);
     if(!root.isConnected||auth!==session)return;
     result.replaceChildren();
     result.insertAdjacentHTML('afterbegin',html);
     labelTables(result);
     this.bindTables(result);
     const download=result.querySelector('[data-s2e-export]');
     download?.addEventListener('click',async ()=>{
      download.disabled=true;
      try{
       await stockDownload(`/reports/${kind}/export?${query}`,`Bao_cao_${kind}_${filenamePeriod}.xlsx`);
      }catch(error){
       notify(error.message,true);
      }finally{
       download.disabled=false;
      }
     });
    }finally{
     loading=false;
     result.setAttribute('aria-busy','false');
     submit.disabled=false;
     for(const tab of tabs)tab.disabled=false;
    }
   };

   this.updateFields(form);
   form.elements.period.addEventListener('change',()=>{
    this.updateFields(form);
   });
   form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(loading)return;
    try{
     const fields=new FormData(form);
     if(fields.get('period')==='month'){
      period={month:fields.get('month')};
     }else{
      const date_from=parseDay(fields.get('s2e_date_from'),'Từ ngày');
      const date_to=parseDay(fields.get('s2e_date_to'),'Đến ngày');
      if(!date_from||!date_to)throw new Error('Nhập đủ từ ngày và đến ngày.');
      if(date_from>date_to)throw new Error('Từ ngày phải trước hoặc bằng đến ngày.');
      period={date_from,date_to};
     }
     this.periods.set(session,period);
     await load();
    }catch(error){
     notify(error.message,true);
    }
   });
   for(const tab of tabs){
    tab.addEventListener('click',async ()=>{
     if(loading||selected===tab)return;
     selected=tab;
     await load().catch(error=>notify(error.message,true));
    });
   }
   return load();
  },

  screen(){
   const session=auth;
   const period=this.periods.get(session)||{month:vietnamToday().slice(0,7)};
   const tabs=this.reports.map(([kind,title],index)=>
    `<button type="button" class="${index===0?'btn':'ghost'}" data-s2e-tab="${kind}" aria-pressed="${index===0}" disabled>${esc(title)}</button>`
   ).join('');
   return {
    html:`<div class="s2b-standalone" data-s2e-screen>
     ${this.filter(period)}
     <div class="tabs" role="group" aria-label="Loại báo cáo">${tabs}</div>
     <div data-s2e-result aria-busy="true">Đang tải báo cáo…</div>
    </div>`,
    after(){
     S2E.bindControls(document.querySelector('[data-s2e-screen]'),session,period)
      .catch(error=>notify(error.message,true));
    }
   };
  }
 };

 SCREENS['s2e-reports']=()=>S2E.screen();
 menus.manager.push(['s2e-reports','Báo cáo quản lý']);
 menus.admin.push(['s2e-reports','Báo cáo quản lý']);
}
