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
