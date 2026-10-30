import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID,createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {createContractService} from '../api/contract_service.mjs';
import {wordTemplate,sampleQuote,mapped} from './helpers/contract_fixtures.mjs';

test('first quotation confirms for contract without adjustment/export; display version stays bound and access checks remain',{timeout:180000},async()=>{
 const pg=await startLocalPostgres(),q=v=>v==null?'NULL':`'${String(v).replaceAll("'","''")}'`;
 const person=name=>({userId:'name-user:'+createHash('sha256').update(name).digest('hex'),displayName:name,identityMode:'NAME_ONLY',role:'USER',scope:'OWN'});
 const owner=person('本机人员甲'),other=person('其他本机人员');
 const quoteService=createQuoteSchemeService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:q,sqlNumber:v=>String(Number(v))});
 const contracts=createContractService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:q});
 const snapshot=(nature='EXTERNAL',number=1)=>({document:{order_nature:nature},company:'本机测试客户 A',analysis_customer:{customer_code:'LOCAL-A'},
  draft_items:sampleQuote.items.map(r=>({name:r.name,quantity:r.quantity,attachments:[],formula:{material_cost:10,auxiliary_cost:2,labor_cost:3,spray_cost:1,management_fee:1},quote_display:{...r}})),
  quote_management:{schema:1,current:number,versions:Array.from({length:number},(_,i)=>({version:i+1,items:[],company:'本机测试客户 A',sealed:true,confirmed:true,order_nature:nature}))}});
 const input=(s,lock=1)=>({snapshot:s,expected_version:lock,quote_version:s.quote_management.current,request_id:randomUUID(),operator_name:owner.displayName});
 try{
  pg.query("CREATE SCHEMA calc;CREATE TABLE calc.dual_quote_result(quote_id text);CREATE TABLE calc.ordering_company(company_code text,company_name text);INSERT INTO calc.ordering_company VALUES('LOCAL-A','本机测试客户 A');");
  for(const name of ['quote_scheme_center_v1.sql','quote_analysis_v1.sql','quote_name_scope_v1.sql','contract_templates_v1.sql'])pg.query(await readFile(new URL('../database/migrations/'+name,import.meta.url),'utf8'));
  pg.query(await readFile(new URL('../database/migrations/contract_scheme_status_v1.sql',import.meta.url),'utf8'));
  const first=await quoteService.create(owner,{snapshot:snapshot(),operator_name:owner.displayName});
  const firstInput=input(snapshot());
  const result=await quoteService.confirmForContract(owner,first.scheme_no,firstInput);
  assert.equal(result.status,'QUOTED');assert.equal(result.source_version_no,1);assert.equal(result.quote_version,1);
  assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_scheme_export;')),0,'must not invent a print/XLSX receipt');
  assert.equal(Number(pg.query("SELECT count(*) FROM calc.quote_scheme_audit WHERE action='CONTRACT_CONFIRMED';")),1);
  assert.equal((await quoteService.confirmForContract(owner,first.scheme_no,firstInput)).reused,true);
  await assert.rejects(()=>quoteService.confirmForContract(owner,first.scheme_no,{...firstInput,snapshot:{...firstInput.snapshot,company:'其他合成客户'}}),e=>e.statusCode===409);
  await assert.rejects(()=>quoteService.exportResult(owner,first.scheme_no,{...firstInput,kind:'CONTRACT',succeeded:true}),e=>e.statusCode===400);
  const initial=(await contracts.bootstrap(owner)).sources.find(r=>r.scheme_no===first.scheme_no);assert.equal(Number(initial.quote_version),1);
  const revised=await quoteService.revision(owner,first.scheme_no,result.lock_version,owner.displayName);
  const third=snapshot('EXTERNAL',3);third.quote_management.versions[0]=firstInput.snapshot.quote_management.versions[0];
  const confirmed=await quoteService.confirmForContract(owner,first.scheme_no,input(third,revised.lock_version));
  assert.equal(confirmed.source_version_no,2);assert.equal(confirmed.quote_version,3);
  const sources=(await contracts.bootstrap(owner)).sources.filter(r=>r.scheme_no===first.scheme_no);
  assert.deepEqual(sources.map(r=>[r.version_no,Number(r.quote_version)]).sort((a,b)=>a[0]-b[0]),[[1,1],[2,3]]);
  const upload=await contracts.upload(owner,{scheme_no:first.scheme_no,version_no:2,customer_code:'LOCAL-A',template_name:'本机合成合同',filename:'synthetic.docx',format:'docx',content:wordTemplate().toString('base64')});
  const inspect=await contracts.inspect(owner,upload.template_version_id);
  const configured=await contracts.configure(owner,upload.template_version_id,{mapping:mapped(inspect.inspection,'docx'),expected_version:inspect.template.lock_version});
  const generated=await contracts.generate(owner,{scheme_no:first.scheme_no,version_no:2,template_version_id:configured.template_version_id,method:'QUICK',request_id:randomUUID(),fields:{sign_date:'2026-10-29'}});
  assert.equal(generated.generation_snapshot.source_version,2);assert.equal(generated.generation_snapshot.source_quote_version,3);assert.equal(generated.generation_snapshot.fields.source_version,'3');
  assert.equal(generated.generation_snapshot.quote.total,650.3);
  const old=await contracts.quote(owner,{scheme_no:first.scheme_no,version_no:1,method:'QUICK'});assert.equal(old.quote_version,1);
  for(const nature of ['INTERNAL','UNCLASSIFIED']){
   const s=snapshot(nature);const created=await quoteService.create(owner,{snapshot:s,operator_name:owner.displayName});
   await assert.rejects(()=>quoteService.confirmForContract(owner,created.scheme_no,input(s)),e=>e.statusCode===409);
   assert.equal((await quoteService.get(owner,created.scheme_no)).status,'DRAFT');
  }
  const draft=await quoteService.create(owner,{snapshot:snapshot(),operator_name:owner.displayName});
  await assert.rejects(()=>quoteService.confirmForContract(other,draft.scheme_no,input(snapshot())),e=>e.statusCode===409);
  await assert.rejects(()=>quoteService.confirmForContract(owner,draft.scheme_no,input(snapshot(),99)),e=>e.statusCode===409);
  await assert.rejects(()=>quoteService.confirmForContract(owner,draft.scheme_no,{...input(snapshot()),quote_version:2}),e=>e.statusCode===409);
  const pending=snapshot();pending.quote_management.versions[0].pending_confirmation=true;
  await assert.rejects(()=>quoteService.confirmForContract(owner,draft.scheme_no,input(pending)),e=>e.statusCode===409);
  assert.equal((await quoteService.get(owner,draft.scheme_no)).status,'DRAFT');
  for(const name of ['戴晨丽','姜艳娟','翟晓峰']){
   const global={...person(name),scope:'ALL',can_view_all_quotes:true,can_manage_all_quotes:true};
   const foreign=await quoteService.create(owner,{snapshot:snapshot(),operator_name:owner.displayName});
   const confirmed=await quoteService.confirmForContract(global,foreign.scheme_no,input(snapshot()));assert.equal(confirmed.status,'QUOTED');
   assert.equal((await quoteService.get(owner,foreign.scheme_no)).creator_user_id,owner.userId);
  }
 }finally{await pg.close();}
});
