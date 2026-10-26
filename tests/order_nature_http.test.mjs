/** Actual API + own loopback PostgreSQL. Synthetic quote and Office fixtures. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import {wordTemplate,mapped,sampleQuote} from './helpers/contract_fixtures.mjs';

test('order nature survives save/reopen/output/analysis and cannot bypass contracts',{timeout:180000},async t=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'quote-nature-http-'));
 const state=path.join(directory,'host.json');
 const host=spawn(process.execPath,[fileURLToPath(new URL('./helpers/contract_test_host.mjs',import.meta.url)),state],{cwd:new URL('../',import.meta.url),windowsHide:true,stdio:['pipe','pipe','pipe']});
 let errors='';host.stderr.on('data',data=>errors+=data.toString());
 try{
  let config;
  for(let i=0;i<1100;i++){
   try{config=JSON.parse(await fs.readFile(state,'utf8'));break;}catch{}
   if(host.exitCode!==null)throw Error('Local fixture stopped: '+errors.slice(-1500));
   await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(config,'local API ready');
  let token;
  const request=async(route,body,method=body?'POST':'GET')=>{
   const response=await fetch(config.base+route,{method,headers:{'X-AI-Quote-Key':config.key,'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
   return {status:response.status,data:await response.json()};
  };
  const login=await request('/api/name-login',{name:'本机人员甲'});assert.equal(login.status,200);token=login.data.token;
  const snapshot=type=>({company:'本机测试客户 A',analysis_customer:{customer_code:'LOCAL-A'},document:{order_nature:type,quote_date:'2026-10-23'},scheme_summary:{company:'本机测试客户 A',quoted_amount:650.3},
   draft_items:sampleQuote.items.map(row=>({name:row.name,product_code:'JP',quantity:row.quantity,attachments:[],formula:{material_cost:row.unit_price,auxiliary_cost:0,labor_cost:0,attachment_fee:0,spray_cost:0,management_fee:0},formula_discount:1,quote_display:{...row,discount:.8}}))});
  const rows={};
  await t.test('draft allows unclassified, formal output rejects missing and invalid classification',async()=>{
   const created=await request('/api/quote-schemes',{snapshot:snapshot(undefined)});assert.equal(created.status,201);
   const route='/api/quote-schemes/'+created.data.scheme_no;
   const opened=await request(route);assert.equal(opened.data.order_nature,'UNCLASSIFIED');
   for(const kind of ['PRINT','XLSX'])assert.equal((await request(route+'/export-result',{expected_version:1,kind,succeeded:true,snapshot:snapshot(undefined)})).status,400);
   assert.equal((await request(route)).data.status,'DRAFT');
   assert.equal((await request('/api/quote-schemes',{snapshot:snapshot('BAD')})).status,400);
   assert.equal((await request('/api/quote-schemes?order_nature=BAD')).status,400);
   // Direct older confirmation/export calls cannot omit nature and make formal files.
   for(const endpoint of ['confirm','export']){
    const result=await request('/api/quotes/'+endpoint,{quote_id:randomUUID(),company_name:'本机测试客户 A',items:[{name:'无分类测试',product_code:'JP'}]});
    assert.equal(result.status,400,JSON.stringify(result.data));
   }
  });
  for(const type of ['INTERNAL','EXTERNAL'])await t.test(type+' save, reopen, formal snapshot and revision lock',async()=>{
   const created=await request('/api/quote-schemes',{snapshot:snapshot(undefined)});assert.equal(created.status,201);
   const route='/api/quote-schemes/'+created.data.scheme_no;
   const saved=await request(route,{expected_version:1,snapshot:snapshot(type)},'PUT');assert.equal(saved.status,200,JSON.stringify(saved.data));
   const opened=await request(route);assert.equal(opened.data.snapshot.document.order_nature,type);assert.equal(opened.data.order_nature,type);assert.equal(opened.data.quoted_amount,650.3);
   const formal=await request(route+'/export-result',{expected_version:saved.data.lock_version,kind:type==='INTERNAL'?'PRINT':'XLSX',succeeded:true,snapshot:opened.data.snapshot});assert.equal(formal.status,200,JSON.stringify(formal.data));
   const frozen=await request(route);assert.equal(frozen.data.status,'QUOTED');assert.equal(frozen.data.snapshot.document.order_nature,type);assert.equal(frozen.data.quoted_amount,650.3);
   const listed=await request('/api/quote-schemes?order_nature='+type);assert.ok(listed.data.items.some(row=>row.scheme_no===created.data.scheme_no&&row.order_nature===type));
   assert.ok(listed.data.items.every(row=>row.order_nature===type));
   const spoof=snapshot(type==='INTERNAL'?'EXTERNAL':'INTERNAL');
   assert.equal((await request(route+'/export-result',{expected_version:frozen.data.lock_version,kind:'PRINT',succeeded:true,snapshot:spoof})).status,409);
   const revision=await request(route+'/revision',{expected_version:frozen.data.lock_version});assert.equal(revision.status,200);
   const latest=await request(route);
   assert.equal((await request(route,{expected_version:latest.data.lock_version,snapshot:spoof},'PUT')).status,409);
   assert.equal((await request(route)).data.snapshot.document.order_nature,type);
   rows[type]={no:created.data.scheme_no,version:1};
  });
  await t.test('overview and customer/product outcomes separate internal, external and unclassified',async()=>{
   for(const type of ['INTERNAL','EXTERNAL']){
    const outcome=await request('/api/quote-analysis/outcomes',{scheme_no:rows[type].no,version_no:1,customer_code:'LOCAL-A',product_code:'JP',opportunity_key:'NATURE-'+type,result:type==='INTERNAL'?'LOST':'WON',result_date:'2026-10-23',expected_revision:0});
    assert.equal(outcome.status,200,JSON.stringify(outcome.data));
    const result=await request('/api/quote-analysis?order_nature='+type+'&customer=LOCAL-A&product=JP');
    assert.equal(result.status,200,JSON.stringify(result.data));assert.equal(result.data.summary.amount,'650.30');assert.equal(result.data.summary.quoted,1);
    assert.ok(result.data.details.every(row=>row.order_nature===type));assert.equal(result.data.discount.sample,1);assert.equal(result.data.discount.records[0].order_nature,type);
   }
   const all=await request('/api/quote-analysis?customer=LOCAL-A&product=JP');assert.equal(all.data.discount.requires_order_nature,true);assert.deepEqual(all.data.discount.best,[]);
   assert.equal(all.data.discount.by_order_nature.find(row=>row.order_nature==='INTERNAL').sample,1);
   assert.equal(all.data.discount.by_order_nature.find(row=>row.order_nature==='EXTERNAL').sample,1);
   const legacy=await request('/api/quote-analysis?order_nature=UNCLASSIFIED');assert.ok(legacy.data.details.every(row=>row.order_nature==='UNCLASSIFIED'));
  });
  await t.test('internal source is absent and direct quote/template/draft/generation requests are rejected',async()=>{
   const bootstrap=await request('/api/contracts/bootstrap');assert.ok(bootstrap.data.sources.every(row=>row.order_nature==='EXTERNAL'));assert.ok(!bootstrap.data.sources.some(row=>row.scheme_no===rows.INTERNAL.no));
   const external={scheme_no:rows.EXTERNAL.no,version_no:1};
   const upload=await request('/api/contracts/templates',{...external,customer_code:'LOCAL-A',template_name:'分类测试模板',filename:'test.docx',format:'docx',content:wordTemplate().toString('base64')});assert.equal(upload.status,201,JSON.stringify(upload.data));
   const inspection=await request('/api/contracts/templates/'+upload.data.template_version_id);
   const configured=await request('/api/contracts/templates/'+upload.data.template_version_id+'/configure',{expected_version:1,mapping:mapped(inspection.data.inspection,'docx')});assert.equal(configured.status,200);
   const input={...external,template_version_id:configured.data.template_version_id,method:'QUICK',fields:{contract_no:'NATURE-EXTERNAL',seller_name:'本机供方',sign_date:'2026-10-23'},request_id:randomUUID()};
   const denied={...input,scheme_no:rows.INTERNAL.no};
   for(const endpoint of ['quote','drafts','generate'])assert.equal((await request('/api/contracts/'+endpoint,denied)).status,409,endpoint);
   assert.equal((await request('/api/contracts/templates',{...denied,template_name:'内部禁止',filename:'test.docx',format:'docx',content:wordTemplate().toString('base64')})).status,409);
   const generated=await request('/api/contracts/generate',input);assert.equal(generated.status,200,JSON.stringify(generated.data));assert.equal(generated.data.generation_snapshot.order_nature,'EXTERNAL');assert.equal(generated.data.generation_snapshot.quote.total,650.3);
  });
 }finally{
  if(host.exitCode===null){host.stdin.end('stop');await once(host,'exit');}
  await fs.rm(directory,{recursive:true,force:true});
 }
});
