import {buildAnalysis} from '../../api/quote_analysis_service.mjs';
export function chartFixture(filters={}){
 const line=(product_code,amount,quantity)=>({product_code,product_name:product_code,amount,quantity});
 const a={scheme_no:'BJ-20261029-000901',status:'CONTRACT',source_kind:'QUOTE',formal_date:'2026-10-21',created_date:'2026-10-20',updated_at:'2026-10-29',customer_code:'A',customer_name:'本机示例客户甲',creator:'本机人员',can_record:true,formal_version:1,amount:'1000',order_nature:'EXTERNAL',products:[line('JP_SINGLE','600',6),line('JP_WIDE_EXP','300',2),line('JE_SINGLE','100',1)]};
 const b={...a,scheme_no:'BJ-20261029-000902',status:'QUOTED',customer_code:'B',customer_name:'本机示例客户乙',formal_date:'2026-10-22',amount:'1100',products:[line('JS_SINGLE','400',4),line('JS_WIDE_EXP','200',1),line('JM_EXP','500',3)]};
 const contracts=[{...a,contract_record_id:'synthetic-contract-a',contract_date:'2026-10-28',amount:'900'},
  {...a,scheme_no:'BJ-20261029-000903',source_kind:'LEDGER_CONTRACT',contract_record_id:'synthetic-ledger-b',products:[],contract_date:'2026-10-29',amount:'99'}];
 return buildAnalysis({schemes:[a,b],contracts,contracts_available:true,outcomes_available:true},filters);
}
