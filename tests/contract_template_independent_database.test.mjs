// Own disposable loopback cluster; no business database or settings are used.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import {createContractService} from '../api/contract_service.mjs';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {wordTemplate,excelTemplate,mapped,sampleQuote,sampleValues} from './helpers/contract_fixtures.mjs';

test('customer template library is independent of quotes; versions, permissions and later matching stay intact',{timeout:180000},async t=>{
 const pg=await startLocalPostgres();
 const q=value=>value==null?'NULL':`'${String(value).replaceAll("'","''")}'`;
 const owner={userId:'independent-owner',displayName:'本机模板维护人',role:'USER'};
 const colleague={userId:'independent-colleague',displayName:'本机同事',role:'USER'};
 const manager={userId:'independent-manager',displayName:'本机全部权限人员',role:'USER',can_view_all_quotes:true};
 try{
  pg.query('CREATE SCHEMA calc;CREATE TABLE calc.ordering_company(company_code text,company_name text);');
  for(const file of ['quote_scheme_center_v1.sql','contract_templates_v1.sql','contract_scheme_status_v1.sql'])
   pg.query(await readFile(new URL('../database/migrations/'+file,import.meta.url),'utf8'));
  const service=createContractService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:q});
  const company='本机提前配置客户';
  const key='contract-name:'+createHash('sha256').update(company).digest('hex');
  const payload=(name,format='docx')=>({customer_name:name,template_name:'独立模板'+format,filename:'independent.'+format,
    format,content:(format==='docx'?wordTemplate():excelTemplate()).toString('base64')});
  let configured,original;
  await t.test('DOCX and XLSX upload and configure with no quote or catalogue customer',async()=>{
   assert.equal(pg.query('SELECT count(*) FROM calc.quote_scheme;'),'0');
   for(const format of ['docx','xlsx']){
    const uploaded=await service.upload(owner,payload(company,format));
    const inspected=await service.inspect(owner,uploaded.template_version_id);
    assert.equal(inspected.template.customer_code,key);assert.equal(inspected.template.customer_name,company);
    const result=await service.configure(owner,uploaded.template_version_id,{expected_version:1,mapping:mapped(inspected.inspection,format)});
    assert.equal(result.version_no,2);assert.equal(result.configured,true);
    if(format==='docx'){configured=await service.inspect(owner,result.template_version_id);original=uploaded;}
   }
   assert.equal(pg.query('SELECT count(*) FROM calc.quote_scheme;'),'0');
   assert.equal(pg.query('SELECT count(*) FROM calc.ordering_company;'),'0');
   assert.equal(pg.query('SELECT count(*) FROM calc.contract_generation;'),'0');
   assert.equal((await service.bootstrap(owner)).sources.length,0);
  });
  await t.test('shared list exposes both templates with owner-only maintenance',async()=>{
   const boot=await service.bootstrap(colleague);
   assert.equal(boot.templates.length,2);assert.ok(boot.templates.every(row=>row.can_use&&!row.can_write));
   for(const person of [colleague,manager]){
    await assert.rejects(service.upload(person,{...payload(company),group_id:original.group_id,expected_version:2}),e=>e.statusCode===404);
    await assert.rejects(service.configure(person,configured.template.template_version_id,{expected_version:2,mapping:configured.template.field_mapping}),e=>e.statusCode===404);
   }
  });
  await t.test('standalone new versions keep identity, CAS and immutable old file/mapping',async()=>{
   const before=pg.query(`SELECT encode(file_content,'hex') FROM calc.contract_template_version WHERE template_version_id=${original.template_version_id};`);
   await assert.rejects(service.upload(owner,{...payload('另一家公司'),group_id:original.group_id,expected_version:2}),e=>e.statusCode===400);
   const input={...payload(company),group_id:original.group_id,expected_version:2};delete input.customer_name;
   const uploaded=await service.upload(owner,input);assert.equal(uploaded.version_no,3);
   await assert.rejects(service.upload(owner,input),e=>e.statusCode===409);
   const inspected=await service.inspect(owner,uploaded.template_version_id);
   assert.equal(inspected.template.customer_name,company);assert.equal(inspected.template.field_mapping,null);
   const result=await service.configure(owner,uploaded.template_version_id,{expected_version:3,mapping:mapped(inspected.inspection,'docx')});
   configured=await service.inspect(owner,result.template_version_id);
   const history=await service.versions(owner,result.template_version_id);
   assert.deepEqual(history.items.map(row=>row.version_no),[4,3,2,1]);
   assert.equal(pg.query(`SELECT encode(file_content,'hex') FROM calc.contract_template_version WHERE template_version_id=${original.template_version_id};`),before);
   assert.ok((await service.inspect(owner,original.template_version_id)).template.field_mapping==null);
  });
  await t.test('catalogue resolution rejects forged codes; duplicate name, blank name and shared identity stay blocked',async()=>{
   pg.query("INSERT INTO calc.ordering_company VALUES('CATALOG-A','本机已有客户');");
   const created=await service.upload(owner,payload('本机已有客户'));
   assert.equal((await service.inspect(owner,created.template_version_id)).template.customer_code,'CATALOG-A');
   await assert.rejects(service.upload(owner,{...payload('本机已有客户'),customer_code:'FORGED'}),e=>e.statusCode===400);
   await assert.rejects(service.upload(owner,payload(company)),e=>e.statusCode===409);
   for(const customer_name of ['',null,'\n','请选择客户'])await assert.rejects(service.upload(owner,{...payload(company),customer_name}));
   await assert.rejects(service.upload({userId:'shared-client:x'},payload(company)),e=>e.statusCode===401);
  });
  await t.test('later formal quote uses pre-created name-key template after catalogue code is assigned',async()=>{
   pg.query(`INSERT INTO calc.ordering_company VALUES('LATER-CATALOG',${q(company)});`);
   await assert.rejects(service.upload(owner,payload(company)),e=>e.statusCode===409);
   const quotes=createQuoteSchemeService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:q,sqlNumber:value=>String(Number(value))});
   const snapshot={document:{order_nature:'EXTERNAL'},company,
    scheme_summary:{company,quoted_amount:650.3},draft_items:sampleQuote.items.map(row=>({
      name:row.name,quantity:row.quantity,attachments:[],formula:{material_cost:row.unit_price,auxiliary_cost:0,labor_cost:0,spray_cost:0,management_fee:0},
      formula_discount:1,quote_display:{...row}}))};
   const created=await quotes.create(owner,{snapshot,operator_name:owner.displayName});
   await quotes.exportResult(owner,created.scheme_no,{expected_version:1,kind:'XLSX',succeeded:true,snapshot,operator_name:owner.displayName});
   const input={scheme_no:created.scheme_no,version_no:1,template_version_id:configured.template.template_version_id,
    method:'QUICK',fields:sampleValues,request_id:randomUUID()};
   const record=await service.generate(owner,input);
   assert.equal(record.generation_snapshot.quote.total,650.3);
   assert.equal(record.generation_snapshot.fields.buyer_name,company);
   assert.equal(record.generation_snapshot.template_borrowed,false);
   assert.equal(pg.query(`SELECT customer_code FROM calc.contract_template_group WHERE group_id=${q(original.group_id)}::uuid;`),key);
  });
 }finally{await pg.close();}
});
