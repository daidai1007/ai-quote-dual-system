import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {randomUUID,createHash} from 'node:crypto';
import {createContractService} from '../api/contract_service.mjs';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {wordTemplate,excelTemplate,mapped,sampleQuote,sampleValues} from './helpers/contract_fixtures.mjs';

test('contract lifecycle on disposable loopback PostgreSQL; immutable files, own writes, ALL reads, CAS and retries',{timeout:180000},async t=>{
 const pg=await startLocalPostgres();
 const q=v=>v==null?'NULL':`'${String(v).replaceAll("'","''")}'`;
 try{
  pg.query('CREATE SCHEMA calc; CREATE TABLE calc.ordering_company(company_code text,company_name text); INSERT INTO calc.ordering_company VALUES(\'LOCAL-A\',\'本机测试客户 A\');');
  pg.query(await readFile(new URL('../database/migrations/quote_scheme_center_v1.sql',import.meta.url),'utf8'));
  const owner={userId:'local-owner',displayName:'本机人员甲',role:'USER'},other={userId:'local-other',displayName:'本机人员乙',role:'USER'},viewer={userId:'local-viewer',displayName:'全部只读',role:'USER',can_view_all_quotes:true};
  const service=createContractService({runPsql:async s=>pg.query(s),sqlUnicodeText:q});
  assert.equal((await service.bootstrap(owner)).ready,false);
  const migration=await readFile(new URL('../database/migrations/contract_templates_v1.sql',import.meta.url),'utf8');pg.query(migration);pg.query(migration);
  const quotes=createQuoteSchemeService({runPsql:async s=>pg.query(s),sqlUnicodeText:q,sqlNumber:v=>String(Number(v))});
  const snapshot={document:{order_nature:'EXTERNAL'},analysis_customer:{customer_code:'LOCAL-A'},scheme_summary:{company:'本机测试客户 A',quoted_amount:650.3},draft_items:sampleQuote.items.map(r=>({name:r.name,quantity:r.quantity,attachments:[],formula:{material_cost:r.unit_price,auxiliary_cost:0,labor_cost:0,spray_cost:0,management_fee:0},formula_discount:1,quote_display:{...r}}))};
  const created=await quotes.create(owner,{snapshot,operator_name:owner.displayName});
  await quotes.exportResult(owner,created.scheme_no,{expected_version:1,kind:'XLSX',succeeded:true,snapshot,operator_name:owner.displayName});
  const source={scheme_no:created.scheme_no,version_no:1};
  assert.equal((await service.bootstrap(owner)).sources.length,1);
  assert.equal((await service.bootstrap(other)).sources.length,0);
  await assert.rejects(()=>service.bootstrap({userId:'shared-client:x',displayName:'共享',role:'ADMIN'}),e=>e.statusCode===401);
  await assert.rejects(()=>service.quote(other,{...source,method:'QUICK'}),e=>e.statusCode===404);
  const quoteBefore=await quotes.get(owner,created.scheme_no);
  let last;
  for(const [format,make]of [['docx',wordTemplate],['xlsx',excelTemplate]])await t.test(format+' upload → map → draft → generate → reopen → identical download',async()=>{
   const bytes=make();const uploaded=await service.upload(owner,{...source,customer_code:'LOCAL-A',template_name:'本机合同'+format,filename:'local.'+format,format,content:bytes.toString('base64')});
   const inspected=await service.inspect(owner,uploaded.template_version_id);
   const configured=await service.configure(owner,uploaded.template_version_id,{expected_version:1,mapping:mapped(inspected.inspection,format)});
   await assert.rejects(()=>service.configure(owner,uploaded.template_version_id,{expected_version:1,mapping:mapped(inspected.inspection,format)}),e=>e.statusCode===409);
   const fields={...sampleValues,total_amount:1,buyer_name:'伪造客户'};
   const input={...source,template_version_id:configured.template_version_id,method:'QUICK',fields};
   const draft=await service.saveDraft(owner,input);
   assert.equal((await service.bootstrap(owner)).drafts.at(0).draft_id,draft.draft_id);
   const saved=await service.saveDraft(owner,{...input,...draft,expected_version:draft.lock_version});assert.equal(saved.lock_version,2);
   await assert.rejects(()=>service.saveDraft(owner,{...input,...draft,expected_version:1}),e=>e.statusCode===409);
   await assert.rejects(()=>service.saveDraft(other,{...input,...saved,expected_version:2}),e=>[404,409].includes(e.statusCode));
   const request_id=randomUUID();const record=await service.generate(owner,{...input,request_id});last=record;
   assert.equal(record.generation_snapshot.quote.total,650.3);assert.equal(record.generation_snapshot.fields.buyer_name,'本机测试客户 A');assert.equal(record.generation_snapshot.fields.total_amount,650.3);
   const file=await service.download(owner,record.record_id);assert.equal(createHash('sha256').update(file.bytes).digest('hex'),record.file_sha256);
   assert.deepEqual((await service.download(owner,record.record_id)).bytes,file.bytes);
   assert.equal((await service.generate(owner,{...input,request_id})).record_id,record.record_id);
   await assert.rejects(()=>service.generate(owner,{...input,request_id,fields:{...fields,contract_no:'CHANGED'}}),e=>e.statusCode===409);
   await assert.rejects(()=>service.generate(owner,{...input,request_id:randomUUID(),fields:{...fields,sign_date:'2026-02-30'}}),/日期/);
   await assert.rejects(()=>service.download(other,record.record_id),e=>e.statusCode===404);
   await assert.rejects(()=>service.download(viewer,record.record_id),e=>e.statusCode===404);assert.equal((await service.record(viewer,record.record_id)).generation_snapshot.quote.total,650.3);
   await assert.rejects(()=>service.configure(viewer,configured.template_version_id,{expected_version:2,mapping:mapped(inspected.inspection,format)}),e=>e.statusCode===404);
   assert.throws(()=>pg.query(`UPDATE calc.contract_generation SET file_sha256='forged' WHERE record_id=${q(record.record_id)};`),/immutable/);
   assert.throws(()=>pg.query(`DELETE FROM calc.contract_template_version WHERE template_version_id=${configured.template_version_id};`),/immutable/);
   const original=await service.inspect(owner,configured.template_version_id);
   await service.setTemplate(owner,configured.template_version_id,{expected_version:2,enabled:false,is_default:false});
   await assert.rejects(()=>service.generate(owner,{...input,request_id:randomUUID()}),/停用/);
   assert.deepEqual((await service.download(owner,record.record_id)).bytes,file.bytes);
   await service.upload(owner,{...source,customer_code:'LOCAL-A',template_name:'ignored',group_id:original.template.group_id,expected_version:3,filename:'new.'+format,format,content:bytes.toString('base64')});
   assert.equal((await service.versions(owner,configured.template_version_id)).items.length,3);
   assert.deepEqual((await service.download(owner,record.record_id)).bytes,file.bytes);
  });
  assert.deepEqual(await quotes.get(owner,created.scheme_no),quoteBefore);
  assert.equal((await service.bootstrap(owner)).records.length,2);
  assert.equal((await service.bootstrap(other)).records.length,0);
  assert.equal((await service.bootstrap(viewer)).records.length,2);
  assert.ok(Number(pg.query('SELECT count(*) FROM calc.contract_audit;'))>=16);
  assert.throws(()=>pg.query('DELETE FROM calc.contract_audit;'),/immutable/);
  await t.test('history searches and pages remain scoped past one hundred records',async()=>{
   pg.query(`INSERT INTO calc.contract_generation(record_id,record_no,request_id,input_sha256,owner_user_id,owner_name,customer_code,customer_name,customer_contract_no,source_scheme_id,source_version_no,template_version_id,quote_method,generation_snapshot,file_format,file_content,file_sha256)
    SELECT md5('local-record-'||n)::uuid,'HT-LOCAL-PAGE-'||n,md5('local-request-'||n)::uuid,r.input_sha256,r.owner_user_id,r.owner_name,r.customer_code,r.customer_name,'PAGE-'||n,r.source_scheme_id,r.source_version_no,r.template_version_id,r.quote_method,r.generation_snapshot,r.file_format,r.file_content,r.file_sha256 FROM calc.contract_generation r CROSS JOIN generate_series(1,101)n WHERE r.record_id=${q(last.record_id)}::uuid;`);
   const first=await service.listRecords(owner,{page:1}),second=await service.listRecords(owner,{page:2});assert.equal(first.total,103);assert.equal(first.items.length,100);assert.equal(second.items.length,3);
   assert.equal((await service.listRecords(owner,{search:'PAGE-101'})).items.length,1);assert.equal((await service.listRecords(other,{search:'PAGE'})).total,0);assert.equal((await service.listRecords(viewer,{})).total,103);
   await assert.rejects(()=>service.listRecords(owner,{page:0}),e=>e.statusCode===400);
  });

 }finally{await pg.close();}
});
