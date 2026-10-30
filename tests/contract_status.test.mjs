import test from 'node:test';
import assert from 'node:assert/strict';
import {buildAnalysis} from '../api/quote_analysis_service.mjs';
import {assertTransition} from '../api/quote_scheme_service.mjs';

test('contract filters include actual contracts without manufacturing quotation costs or outcomes',()=>{
  const quote={scheme_no:'Q',status:'CONTRACT',source_kind:'QUOTE',formal_date:'2026-10-29',created_date:'2026-10-29',amount:'100.10',contract_amount:'90.10',products:[]};
  const ledger={scheme_no:'L',status:'CONTRACT',source_kind:'LEDGER_CONTRACT',created_date:'2026-10-29',amount:'200.20',contract_amount:'200.20',products:[{product_name:'本机台账产品',quote_method:'LEDGER'}]};
  const draft={scheme_no:'D',status:'DRAFT',created_date:'2026-10-29',products:[]};
  const result=buildAnalysis({schemes:[quote,ledger,draft]}, {status:'CONTRACT'});
  assert.equal(result.summary.contracts,2);assert.equal(result.summary.schemes,2);
  assert.equal(result.summary.quoted,1);assert.equal(result.summary.amount,'100.10');
  assert.equal(result.summary.contract_amount,'290.30');assert.equal(result.cost_coverage,0);
  assert.equal(result.discount.sample,0);
  assert.deepEqual(result.details.map(s=>s.scheme_no),['Q','L']);
  const product={...quote,products:[{product_code:'JP',amount:'100.10'}]};
  assert.equal(buildAnalysis({schemes:[product]},{product:'JP'}).summary.contract_amount,null);
});
test('contract state retains explicit archive and void transitions',()=>{
  assert.doesNotThrow(()=>assertTransition('CONTRACT','ARCHIVED'));
  assert.doesNotThrow(()=>assertTransition('CONTRACT','VOID'));
  assert.throws(()=>assertTransition('DRAFT','CONTRACT'));
});
