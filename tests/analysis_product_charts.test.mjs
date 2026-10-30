import test from 'node:test';
import assert from 'node:assert/strict';
import {buildAnalysis} from '../api/quote_analysis_service.mjs';

const line=(product_code,amount,quantity)=>({product_code,product_name:product_code,amount,quantity});
const quote=(scheme_no,products,extra={})=>({scheme_no,products,status:'QUOTED',source_kind:'QUOTE',formal_date:'2026-10-21',created_date:'2026-10-01',customer_code:'A',customer_name:'本机示例甲',creator:'本机人员',amount:'1.00',...extra});

test('product bars use frozen line subtotals with cent precision, per-scheme detail and no duplicated whole quotes',()=>{
 const first=quote('A',[line('JP_SINGLE','0.10',2),line('JP_DOUBLE','0.20',3),line('JE','0.30',1)]);
 const second=quote('B',[line('JP_EXP','0.40',4)]);
 const input={schemes:[first,second,quote('D',[line('JP','999',100)],{status:'DRAFT',formal_date:null}),quote('V',[line('JP','999',100)],{status:'VOID'})]};
 const before=JSON.stringify(input),data=buildAnalysis(input);
 const jp=data.product_breakdown.find(p=>p.product_code==='JP'),je=data.product_breakdown.find(p=>p.product_code==='JE');
 assert.equal(jp.amount,'0.70');assert.equal(jp.quantity,9);assert.equal(jp.scheme_count,2);assert.equal(jp.line_count,3);
 assert.equal(jp.items[0].analysis_amount,'0.30');assert.equal(jp.items[0].quantity,5);assert.equal(jp.items[0].products.length,2);
 assert.equal(je.amount,'0.30');assert.equal(jp.amount_share,.7);assert.equal(jp.quantity_share,.9);
 assert.equal(JSON.stringify(input),before,'analysis never rewrites frozen prices, quantities or source keys');
});
test('configured families stay separate, including wide products, and filters keep only each product own amounts',()=>{
 const s=quote('W',[line('JP','10',1),line('JP_WIDE_EXP','20',2),line('JS','30',3),line('JS_WIDE_EXP','40',4)]);
 const all=buildAnalysis({schemes:[s]}).product_breakdown;
 assert.deepEqual(all.map(p=>p.product_code),['JP','JP WIDE','JS','JS WIDE']);
 const filtered=buildAnalysis({schemes:[s]},{product:'JP'}).product_breakdown;
 assert.equal(filtered.length,1);assert.equal(filtered[0].amount,'10.00');assert.equal(filtered[0].quantity,1);
 assert.equal(filtered[0].items[0].products.length,1);
});
test('unknown prices and quantities stay unknown; actual zeros remain known; unclassified lines are not guessed',()=>{
 const data=buildAnalysis({schemes:[quote('M',[line('JP',null,null),line('JP','0',0),line('JS',null,undefined),line(null,'12',1)])]});
 const jp=data.product_breakdown.find(p=>p.product_code==='JP'),js=data.product_breakdown.find(p=>p.product_code==='JS');
 assert.equal(jp.amount,'0.00');assert.equal(jp.quantity,0);assert.equal(jp.amount_coverage,1);assert.equal(jp.line_count,2);
 assert.equal(js.amount,null);assert.equal(js.quantity,null);assert.equal(js.amount_share,null);
 assert.equal(data.product_breakdown.find(p=>p.product_code==='__unclassified__').product_name,'产品待分类');
 const oldCostDefault=buildAnalysis({schemes:[quote('LEGACY',[{...line('JP','12',1),chart_quantity:null}])]}).product_breakdown[0];
 assert.equal(oldCostDefault.quantity,null,'legacy cost multiplier default must not fabricate a quoted cabinet count');
});
test('product classification shares customer, creator, date, nature and state filters with frozen quotation totals',()=>{
 const valid=quote('A',[line('JE','15',2)],{order_nature:'EXTERNAL'});
 const data=buildAnalysis({schemes:[valid,{...valid,scheme_no:'B',customer_code:'B'},{...valid,scheme_no:'C',creator:'他人'},{...valid,scheme_no:'I',order_nature:'INTERNAL'},{...valid,scheme_no:'OLD',formal_date:'2026-09-01'}]},
  {customer:'A',creator:'本机',order_nature:'EXTERNAL',status:'QUOTED',from:'2026-10-01',to:'2026-10-31'});
 assert.equal(data.product_breakdown[0].scheme_count,1);assert.equal(data.product_breakdown[0].amount,'15.00');
});
test('contract and quotation trend use independent event dates, actual records and preserve generated historical contracts during revision',()=>{
 const a=quote('A',[line('JP','100',2)],{formal_date:'2026-09-01',status:'REVISING'});
 const b=quote('B',[line('JE','80',1)],{formal_date:'2026-10-21'});
 const records=[{...a,contract_record_id:'C1',contract_date:'2026-10-22',amount:'90'},
  {...a,contract_record_id:'C2',contract_date:'2026-10-22',amount:'91'},
  {...a,scheme_no:'LEDGER',products:[],contract_record_id:'L',contract_date:'2026-10-23',amount:'10'}];
 const data=buildAnalysis({schemes:[a,b],contracts:records,contracts_available:true},{from:'2026-10-01',to:'2026-10-31'});
 assert.deepEqual(data.contract_quoted_trend,[{date:'2026-10-21',quoted_count:1,contract_count:0},{date:'2026-10-22',quoted_count:0,contract_count:2},{date:'2026-10-23',quoted_count:0,contract_count:1}]);
 assert.equal(data.contract_quoted_details.filter(e=>e.event_kind==='CONTRACT').length,3);
 const product=buildAnalysis({schemes:[a,b],contracts:records},{product:'JP',from:'2026-10-01',to:'2026-10-31'});
 assert.equal(product.contract_quoted_trend.length,1);assert.equal(product.contract_quoted_trend[0].contract_count,2);
 assert.equal(data.discount.sample,0,'contract creation does not manufacture a sale outcome');
});
test('a CONTRACT status alone and draft creation dates cannot manufacture trend events or line prices',()=>{
 const s=quote('STATUS',[line('JP','10',1)],{status:'CONTRACT',contracted_at:'2026-10-29',formal_date:null});
 const result=buildAnalysis({schemes:[s]});
 assert.deepEqual(result.contract_quoted_trend,[]);assert.deepEqual(result.product_breakdown,[]);
 assert.equal(result.contract_trend_available,false);
});
