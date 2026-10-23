import test from 'node:test';
import assert from 'node:assert/strict';
import {snapshotWithOrderNature,documentWithOrderNature,orderNatureLabel} from '../quote_order_nature.mjs';
import {buildAnalysis} from '../api/quote_analysis_service.mjs';

test('legacy stays unclassified; malformed, missing formal and conflicting metadata are rejected',()=>{
 assert.equal(snapshotWithOrderNature({}).document.order_nature,'UNCLASSIFIED');
 assert.equal(orderNatureLabel(null),'待分类');
 assert.throws(()=>snapshotWithOrderNature({},true),{statusCode:400});
 assert.throws(()=>snapshotWithOrderNature({document:{order_nature:'bad'}}),{statusCode:400});
 assert.throws(()=>snapshotWithOrderNature({document:{order_nature:'INTERNAL'},quote_management:{current:1,versions:[{version:1,order_nature:'EXTERNAL'}]}}),{statusCode:400});
 const items=[{quote_order_nature:'INTERNAL',quote_display:{total:350}}];
 assert.equal(documentWithOrderNature({items},true).order_nature,'INTERNAL');
 assert.equal(items[0].quote_display.total,350);
 assert.throws(()=>documentWithOrderNature({order_nature:'EXTERNAL',items},true),{statusCode:400});
 assert.throws(()=>documentWithOrderNature({items:[...items,{quote_order_nature:'EXTERNAL'}]},true),{statusCode:400});
});

test('same customer/product has independent internal and external discount outcomes and formal amounts',()=>{
 const schemes=['INTERNAL','EXTERNAL'].map((order_nature,index)=>({scheme_no:'S'+index,order_nature,customer_code:'A',customer_name:'客户A',status:'QUOTED',formal_date:'2026-10-23',created_date:'2026-10-23',amount:'350.00',products:[{product_code:'JP',amount:'350.00'}]}));
 const outcomes=schemes.flatMap((s,index)=>Array.from({length:20},(_,i)=>({scheme_no:s.scheme_no,order_nature:s.order_nature,customer_code:'A',product_code:'JP',result_date:'2026-10-23',discount:index?.9:.8,result:index?'LOST':'WON',quote_method:'QUICK',opportunity_key:s.scheme_no+i})));
 const data={schemes,outcomes,outcomes_available:true},before=structuredClone(data);
 const internal=buildAnalysis(data,{order_nature:'INTERNAL',customer:'A',product:'JP'});
 assert.equal(internal.summary.amount,'350.00');assert.equal(internal.discount.sample,20);assert.equal(internal.discount.best[0].rate,100);
 assert.equal(internal.discount.customer_comparison[0].sample,20);assert.equal(internal.discount.product_comparison[0].sample,20);
 const external=buildAnalysis(data,{order_nature:'EXTERNAL',customer:'A',product:'JP'});
 assert.equal(external.summary.amount,'350.00');assert.equal(external.discount.sample,20);assert.equal(external.discount.best[0].rate,0);
 const all=buildAnalysis(data,{customer:'A',product:'JP'});
 assert.equal(all.summary.amount,'700.00');assert.equal(all.discount.requires_order_nature,true);assert.deepEqual(all.discount.best,[]);assert.deepEqual(all.discount.bands,[]);
 assert.deepEqual(all.order_nature_summary.map(r=>r.count),[1,1,0]);
 assert.equal(all.discount.by_order_nature.find(r=>r.order_nature==='INTERNAL').best[0].rate,100);
 assert.equal(all.discount.by_order_nature.find(r=>r.order_nature==='EXTERNAL').best[0].rate,0);
 assert.throws(()=>buildAnalysis(data,{order_nature:'BAD'}),{statusCode:400});
 assert.deepEqual(data,before);
});
