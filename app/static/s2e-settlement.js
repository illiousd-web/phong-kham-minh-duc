'use strict';
/* global LABEL, SCREENS, menus, api, esc, money, card, stats, r4Queue, auth, role, render, notify, sel, showDay */

Object.assign(LABEL,{
 visit:'Lượt khám',
 visit_settled:'Kết thúc lượt khi đã thu đủ',
 visit_settlement_waived:'Duyệt miễn thu và kết thúc lượt',
 visit_settlement_reopened:'Mở lại tài chính của lượt',
});

const S2ESettlement={
 cashPage:1,
 offset:0,
 closed:false,

 cashierQueue(dues, selected){
  const pending=dues.filter(item=>item.financial_pending);
  const pageSize=25;
  const pages=Math.max(1,Math.ceil(pending.length/pageSize));
  this.cashPage=Math.min(this.cashPage,pages);
  const rows=pending.slice((this.cashPage-1)*pageSize,this.cashPage*pageSize).map(item=>{
   const bill={unpriced_count:item.unpriced_count,due:Math.max(0,item.charged-item.paid),
    refund_due:Math.max(0,item.paid-item.charged)};
   return {id:item.visit_id,name:item.patient_name,
    sub:item.patient_code+' · '+(this.blockReason(bill)||'Đã thu đủ')};
  });
  const pager=pages>1?this.pager(this.cashPage>1?this.cashPage-1:0,this.cashPage<pages?this.cashPage+1:0,'cash','Trang '+this.cashPage+'/'+pages):'';
  return card(r4Queue(rows,'cash-settlement',selected,'Không còn lượt chờ kết thúc tài chính.')+pager,
   'Chờ kết thúc tài chính · '+pending.length+' lượt');
 },

 blockReason(bill, waiver=false){
  if(bill.unpriced_count)return 'Còn khoản chưa có giá';
  if(bill.refund_due)return 'Còn phải hoàn '+money(bill.refund_due).replace(/ đ$/,' đồng');
  if(!waiver&&bill.due)return 'Còn phải thu '+money(bill.due).replace(/ đ$/,' đồng');
  return '';
 },

 button(label, action, id, reason){
  const reasonId='s2e-reason-'+action+'-'+id;
  const disabled=reason?`disabled aria-describedby="${reasonId}"`:'';
  return `<div><button type="button" class="btn" data-s2e-settlement="${action}" data-visit="${id}" ${disabled}>${label}</button>${
   reason?`<p class="hint" id="${reasonId}">${esc(reason)}</p>`:''}</div>`;
 },

 actions(id,state){
  if(state.clinical_status!=='completed')return '';
  const admin=role()==='admin';
  const closure=state.financial_settlement;
  if(closure){
   const note=closure.kind==='mien_thu'?'Miễn thu đã duyệt · '+money(closure.waived_amount):'Đã thu đủ';
   return card(`<p>${esc(note)} · ${esc(showDay(closure.created_at))}</p>`+
    (admin?this.button('Mở lại','settlement-reopen',id,''):''),'Lượt đã kết thúc tài chính');
  }
  if(!admin&&role()!=='cashier')return '';
  const actions=this.button('Kết thúc lượt','settle',id,this.blockReason(state.billing))+
   (admin?this.button('Duyệt miễn thu','settlement-waiver',id,this.blockReason(state.billing,true)):'');
  return card(`<div class="multi-actions">${actions}</div>`,'Kết thúc tài chính');
 },

 pager(previous,next,scope,caption){
  const button=(label,index)=>`<button type="button" class="ghost" data-s2e-settlement-page="${scope}" data-index="${index}">${label}</button>`;
  return `<div class="toolbar-actions"><span>${esc(caption)}</span>${previous?button('Trang trước',previous):''}${
   next?button('Trang sau',next):''}</div>`;
 },

 async screen(){
  const admin=role()==='admin';
  const closed=admin&&this.closed;
  const title=closed?'Lượt đã kết thúc tài chính':'Lượt bác sĩ đã khóa nhưng chưa kết thúc tài chính';
  const list=await api('/financial-settlements?closed='+closed+'&offset='+this.offset);
  const selected=list.items.find(item=>item.visit_id===sel.financialVisit);
  const rows=list.items.map(item=>({id:item.visit_id,name:item.patient_name,
   sub:item.patient_code+' · Lượt #'+item.visit_id+' · '+showDay(item.created_at)}));
  const page=Math.floor(this.offset/50)+1;
  const pager=this.pager(page>1?page-1:0,list.has_more?page+1:0,'management','Trang '+page);
  const tabs=admin?`<nav class="r4-tabs" aria-label="Trạng thái tài chính">
   <button type="button" data-s2e-settlement-view="open" aria-pressed="${!closed}">Chờ kết thúc</button>
   <button type="button" data-s2e-settlement-view="closed" aria-pressed="${closed}">Đã kết thúc</button>
   </nav>`:'';
  let detail='';
  if(selected){
   const state=await api('/visits/'+selected.visit_id+'/settlement');
   const closure=state.financial_settlement;
   const amounts=[['Phải thu',money(state.billing.charged)],['Đã thu',money(state.billing.paid)]];
   if(!closure)amounts.push(['Còn phải thu',money(state.billing.due)],['Còn phải hoàn',money(state.billing.refund_due)]);
   detail=card(stats(amounts),selected.patient_name+' · Lượt #'+selected.visit_id)+this.actions(selected.visit_id,state);
  }
  const queue=card(r4Queue(rows,'financial-visit',selected?.visit_id,'Không có lượt nào.')+pager,title);
  return {html:tabs+`<div class="r4-layout"><aside>${queue}</aside><div>${detail}</div></div>`};
 },

 async submit(button){
  const action=button.dataset.s2eSettlement;
  const waiver=action==='settlement-waiver';
  const labels={
   settle:'Đã kết thúc tài chính',
   'settlement-waiver':'Đã duyệt miễn thu và kết thúc lượt',
   'settlement-reopen':'Đã mở lại lượt để xử lý tài chính',
  };
  const options={method:'POST'};
  if(action!=='settle'){
   const reason=prompt(waiver?'Lý do miễn thu (ít nhất 10 ký tự)':'Lý do mở lại lượt')?.trim();
   if(reason===undefined)return;
   if(reason.length<(waiver?10:1)){
    notify(waiver?'Lý do miễn thu cần ít nhất 10 ký tự':'Cần nhập lý do mở lại',true);
    return;
   }
   options.body={reason};
  }
  button.disabled=true;
  try{
   await api('/visits/'+button.dataset.visit+'/'+action,options);
   notify(labels[action]);
   if(role()==='admin')this.offset=0;
   await render();
  }catch(error){
   notify(error.message,true);
  }finally{
   button.disabled=false;
  }
 },
};

SCREENS['financial-settlements']=()=>S2ESettlement.screen();
menus.admin.push(['financial-settlements','Kết thúc tài chính']);

document.addEventListener('click',async event=>{
 if(!auth)return;
 const action=event.target.closest('[data-s2e-settlement]:not(:disabled)');
 if(action){
  await S2ESettlement.submit(action);
  return;
 }
 const page=event.target.closest('[data-s2e-settlement-page]');
 const view=event.target.closest('[data-s2e-settlement-view]');
 if(page){
  const index=Number(page.dataset.index);
  if(page.dataset.s2eSettlementPage==='cash')S2ESettlement.cashPage=index;
  else S2ESettlement.offset=(index-1)*50;
 }else if(view){
  S2ESettlement.closed=view.dataset.s2eSettlementView==='closed';
  S2ESettlement.offset=0;
 }else{
  return;
 }
 await render();
});
