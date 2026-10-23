import test from 'node:test';
import assert from 'node:assert/strict';
import {buildAnalysis} from '../api/quote_analysis_service.mjs';

const scheme=(name,customer,products=[{product_code:'JP',product_name:'JP',amount:'100.10'}])=>({scheme_no:name,customer_code:customer,customer_name:customer,status:'QUOTED',
  formal_date:'2026-10-21',created_date:'2026-10-01',updated_at:'2026-10-21',creator:'测试',amount:'100.10',products});
const outcome=(s,discount,result,extra={})=>({scheme_no:s.scheme_no,customer_code:s.customer_code,product_code:'JP',discount,result,result_date:'2026-10-21',quote_method:'QUICK',...extra});
const a=scheme('A','customer-a'),b=scheme('B','customer-b');
const outcomes=[...Array.from({length:20},()=>outcome(a,'.80','WON')),...Array.from({length:20},()=>outcome(b,'.90','LOST')),
  ...Array.from({length:20},()=>outcome(b,'.85','WON'))];

test('same product is independent by customer; comparison keeps other customer results',()=>{
  const data=buildAnalysis({schemes:[a,b],outcomes,outcomes_available:true},{customer:'customer-a',product:'JP'});
  assert.equal(data.discount.sample,20);
  assert.equal(data.discount.best[0].label,'0.80–<0.85');
  assert.equal(data.discount.customer_comparison[1].best[0].label,'0.85–<0.90');
  assert.equal(data.summary.schemes,1);
  const all=buildAnalysis({schemes:[a,b],outcomes});
  assert.equal(all.discount.sample,60);
  assert.equal(all.discount.bands.reduce((n,b)=>n+b.sample,0),60);
});
test('product subtotal does not duplicate whole-quote amounts; cent sums and averages',()=>{
  const multi=scheme('M','a',[{product_code:'JP',amount:'0.10'},{product_code:'JE',amount:'0.20'}]);
  multi.amount='0.30';
  const result=buildAnalysis({schemes:[multi]}, {product:'JP'});
  assert.equal(result.summary.amount,'0.10');
  assert.equal(buildAnalysis({schemes:[multi]}).summary.amount,'0.30');
  assert.equal(buildAnalysis({schemes:[multi,structuredClone(multi)]}).summary.average,'0.30');
  const missing=buildAnalysis({schemes:[{...a,amount:null}]});
  assert.equal(missing.summary.amount,null);
  assert.equal(missing.ranking[0].amount,null);
  assert.equal(missing.ranking[0].amount_coverage,0);
});
test('result date is distinct from quote date; pending and void excluded; no fake current prices',()=>{
  const draft={...a,scheme_no:'D',formal_date:null,status:'DRAFT',created_date:'2026-10-21'};
  const hidden={...a,scheme_no:'VOID',status:'VOID'};
  const future={...a,formal_date:'2026-09-01'};
  const d=buildAnalysis({schemes:[future,draft,hidden],outcomes:[outcome(future,'.8','WON'),outcome(future,'.8','PENDING'),outcome(hidden,'.8','WON')]},{from:'2026-10-01',to:'2026-10-31'});
  assert.equal(d.summary.quoted,0);
  assert.equal(d.summary.drafts,1);
  assert.equal(d.summary.amount,null);
  assert.equal(d.discount.sample,1);
  assert.deepEqual(d.discount.best,[]);
});
test('boundary, unknown, outside, zero counts, tied best and sample threshold',()=>{
  const rows=[...Array.from({length:20},()=>outcome(a,'.8','WON')),...Array.from({length:20},()=>outcome(a,'1','WON')),
    outcome(a,'1.2','LOST'),outcome(a,null,'WON')];
  const d=buildAnalysis({schemes:[a],outcomes:rows}).discount;
  assert.equal(d.best.length,2);
  assert.equal(d.bands.find(b=>b.key==='outside').sample,1);
  assert.equal(d.bands.find(b=>b.key==='unknown').sample,1);
  assert.equal(d.bands.find(b=>b.key==='1').rate,100);
  assert.equal(d.bands.find(b=>b.key==='0').rate,null);
  assert.deepEqual(buildAnalysis({schemes:[a],outcomes:[]}).discount.best,[]);
});
test('invalid dates/statuses are rejected rather than broadening the scope',()=>{
  for(const filters of [{from:'2026-02-30'},{from:'nonsense'},{from:'2026-10-23',to:'2026-10-01'},{status:'ALL_INVALID'}])
    assert.throws(()=>buildAnalysis({},filters),{statusCode:400});
});
test('new-scheme and formal-quote trend series use their own dates within the same customer scope',()=>{
  const result=buildAnalysis({schemes:[a,b]},{customer:'customer-a',from:'2026-10-01',to:'2026-10-10'});
  assert.equal(result.summary.quoted,0);
  assert.equal(result.trend.length,1);
  assert.equal(result.trend[0].date,'2026-10-01');
  assert.equal(result.trend[0].created_count,1);
  assert.equal(result.trend[0].count,0);
  assert.equal(result.trend_details.length,1);
  assert.equal(result.trend_details[0].scheme_no,'A');
});

test('configuration product types group old calculation codes without changing frozen rows or keys',()=>{
  const multi=scheme('M','customer-a',[
    {product_code:'JP_SINGLE',amount:'10.10',quantity:1,costs:{material_cost:'1.00'}},
    {product_code:'JP_DOUBLE',amount:'20.20',quantity:2,costs:{material_cost:'2.00'}},
    {product_code:'JP',amount:'3.30'},
    {product_code:'JP_WIDE_EXP',amount:'40.40'},
    {product_code:'JQ_EXP',amount:'50.50'},
    {product_code:'OP_TABLE_EXP',amount:'60.60'}]);
  multi.amount='185.10';
  const records=[outcome(multi,'.8','WON',{product_code:'JP_SINGLE',opportunity_key:'one'}),
    outcome(multi,'.9','LOST',{product_code:'JP_DOUBLE',opportunity_key:'two'}),
    outcome(multi,'.8','WON',{product_code:'JP_WIDE_EXP',opportunity_key:'wide'})];
  const input={schemes:[multi],outcomes:records,outcomes_available:true};
  const before=structuredClone(input);
  const jp=buildAnalysis(input,{product:'JP'});
  assert.equal(jp.product_filter_mode,'family-v1');
  assert.equal(jp.summary.quoted,1);
  assert.equal(jp.summary.amount,'33.60');
  assert.equal(jp.costs.material_cost,'5.00');
  assert.equal(jp.discount.sample,2);
  assert.deepEqual(jp.discount.records.map(r=>r.product_code),['JP_SINGLE','JP_DOUBLE']);
  assert.deepEqual(jp.outcome_records.map(({order_nature,...row})=>row),records,'immutable registration keys are not rekeyed by analysis');
  assert.ok(jp.outcome_records.every(row=>row.order_nature==='UNCLASSIFIED'));
  assert.equal(buildAnalysis(input,{product:'JP_SINGLE'}).summary.amount,'33.60');
  const wide=buildAnalysis(input,{product:'JP WIDE'});
  assert.equal(wide.summary.amount,'40.40');
  assert.equal(wide.discount.sample,1);
  assert.equal(wide.discount.bands[0].label,'0.75–<0.80');
  assert.equal(buildAnalysis(input,{product:'JQ'}).summary.amount,'50.50');
  assert.equal(buildAnalysis(input,{product:'操作台'}).summary.amount,'60.60');
  assert.equal(buildAnalysis(input).summary.amount,'185.10');
  assert.deepEqual(jp.products.map(p=>p.name),['JP','JP WIDE','JQ','操作台']);
  const empty=buildAnalysis(input,{product:'JC'});
  assert.equal(empty.summary.schemes,0);
  assert.equal(empty.summary.amount,null);
  assert.equal(empty.discount.product_code,'JC');
  assert.equal(empty.discount.sample,0);
  assert.deepEqual(input,before);
});

test('all configured types retain display order and wide variants remain independent',()=>{
  const codes=['OP_TABLE_EXP','JS_WIDE_EXP','JS_SINGLE','JQ_EXP','JP_WIDE_EXP',
    'JP_SINGLE','JM','JK','JE_DOUBLE','JC_EXP','JA_SINGLE'];
  const names=['JA','JC','JE','JK','JM','JP','JP WIDE','JQ','JS','JS WIDE','操作台'];
  const input={schemes:[scheme('M','a',codes.map(product_code=>({product_code,amount:'1.00'})))]};
  const data=buildAnalysis(input);
  assert.deepEqual(data.products.map(p=>p.name),names);
  assert.deepEqual(data.discount.product_comparison.map(p=>p.name),names);
  for(const product of names)assert.equal(buildAnalysis(input,{product}).summary.amount,'1.00');
  for(const product of ['JP_WIDE','JP_WIDE_EXP','超宽JP','JP超宽柜','JS_WIDE','JS_WIDE_EXP','超宽JS'])
    assert.equal(buildAnalysis(input,{product}).summary.amount,'1.00');
  const unknown=buildAnalysis({schemes:[scheme('U','a',[{product_code:'UNKNOWN_EXP',amount:'4.00'}])]},{product:'JQ'});
  assert.equal(unknown.summary.schemes,0,'unknown products must not be guessed into a known family');
});
