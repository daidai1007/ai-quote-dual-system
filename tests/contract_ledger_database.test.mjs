import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID,createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {unzipSync,strFromU8} from 'fflate';
import {createContractService} from '../api/contract_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {ledgerFixture,ledgerExcelTemplate,ledgerWordTemplate} from './helpers/contract_ledger_fixtures.mjs';
import {wordTemplate} from './helpers/contract_fixtures.mjs';

test('ledger contracts use real local SQL, shared templates, private drafts, immutable output and preserved quote boundaries',
 {timeout:180000},async t=>{
 const pg=await startLocalPostgres(),q=v=>`'${String(v).replaceAll("'","''")}'`;
 const owner={userId:'ledger-owner',displayName:'本机台账人员甲',role:'USER'},other={userId:'ledger-other',displayName:'本机台账人员乙',role:'USER'},all={userId:'ledger-all',displayName:'全部报价人员',scope:'ALL',can_view_all_quotes:true};
 try{
  pg.query("CREATE SCHEMA calc;CREATE TABLE calc.ordering_company(company_code text,company_name text);INSERT INTO calc.ordering_company VALUES('LOCAL-NY','杭州诺玥科技有限公司'),('LOCAL-FY','杭州方圆塑机股份有限公司');");
  for(const file of ['quote_scheme_center_v1.sql','contract_templates_v1.sql'])pg.query(await readFile(new URL('../database/migrations/'+file,import.meta.url),'utf8'));
  const service=createContractService({runPsql:async sql=>pg.query(sql),sqlUnicodeText:q});
  assert.equal((await service.ledger.bootstrap(owner)).ready,false);
  const migration=await readFile(new URL('../database/migrations/contract_ledger_v1.sql',import.meta.url),'utf8');pg.query(migration);pg.query(migration);
  await assert.rejects(()=>service.ledger.bootstrap({userId:'shared-client:legacy'}),e=>e.statusCode===401);
  const template=await service.ledger.upload(owner,{customer_key:'NUOYUE',template_name:'本机合成台账模板',filename:'synthetic.xlsx',format:'xlsx',content:ledgerExcelTemplate().toString('base64')});
  assert.equal(template.auto_configured,true);
  const input={...ledgerFixture(),template_version_id:template.template_version_id,request_id:randomUUID()};
  const draft=await service.ledger.saveDraft(owner,input);const opened=await service.ledger.draft(owner,draft.draft_id);
  const numericRows=rows=>rows.map(r=>({...r,quantity:Number(r.quantity),unit_price:Number(r.unit_price),total:Number(r.total)}));
  assert.deepEqual(numericRows(opened.input_payload.records),numericRows(input.records));
  await assert.rejects(()=>service.ledger.draft(other,draft.draft_id),e=>e.statusCode===404);
  await assert.rejects(()=>service.ledger.saveDraft(other,{...input,draft_id:draft.draft_id,expected_version:1}),e=>e.statusCode===409);
  await assert.rejects(()=>service.ledger.saveDraft(owner,{...input,draft_id:draft.draft_id,expected_version:99}),e=>e.statusCode===409);
  input.remarks[input.records[0].record_id]='本机修改备注，保存后冻结';input.remarks[input.records[1].record_id]='';
  const generated=await service.ledger.generate(owner,input);assert.equal(generated.records.length,2);
  const first=generated.records.find(r=>r.generation_snapshot.fields.contract_no==='SYNTHETIC-001');
  assert.equal(first.generation_snapshot.quote.total,650.3);
  assert.equal(first.generation_snapshot.quote.items[0].remark,input.remarks[input.records[0].record_id]);
  assert.equal(first.generation_snapshot.original_records[0].remark,input.records[0].remark);
  const file=await service.download(owner,first.record_id);assert.equal(createHash('sha256').update(file.bytes).digest('hex'),first.file_sha256);
  const parts=unzipSync(file.bytes),xml=strFromU8(parts['xl/worksheets/sheet1.xml']);
  assert(xml.includes('本机修改备注，保存后冻结'));assert(xml.includes('原有条款金额500元，不参与替换'));
  assert(xml.includes('650.3'));assert(strFromU8(parts['xl/workbook.xml']).includes("$A$1:$H$14"));
  assert.equal((await service.ledger.generate(owner,input)).records.length,2);
  assert.equal(Number(pg.query('SELECT count(*) FROM calc.ledger_contract_generation;')),2);
  await assert.rejects(()=>service.ledger.generate(owner,{...input,remarks:{}}),e=>e.statusCode===409);
  assert.throws(()=>pg.query(`UPDATE calc.ledger_contract_generation SET customer_contract_no='changed';`),/immutable/);
  await assert.rejects(()=>service.record(other,first.record_id),e=>e.statusCode===404);
  assert.equal((await service.record(all,first.record_id)).source_kind,'LEDGER');
  await assert.rejects(()=>service.download(all,first.record_id),e=>e.statusCode===404);
  assert.equal((await service.listRecords(owner)).total,2);assert.equal((await service.listRecords(other)).total,0);
  assert.equal((await service.listRecords(all)).items[0].source_kind,'LEDGER');
  // Named colleagues may use the template, not alter another maintainer's copy.
  const shared=await service.ledger.bootstrap(other);assert.equal(shared.templates[0].can_use,true);assert.equal(shared.templates[0].can_write,false);
  await assert.rejects(()=>service.configure(other,template.template_version_id,{mapping:{},expected_version:1}),e=>e.statusCode===404);
  const ownCopy=await service.ledger.generate(other,{...input,request_id:randomUUID()});assert.equal(ownCopy.records[0].owner_user_id,other.userId);
  // New ledger support must never manufacture a quote or loosen its source FK.
  assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_scheme;')),0);
  assert.equal(Number(pg.query("SELECT count(*) FROM information_schema.columns WHERE table_schema='calc' AND table_name='contract_generation' AND column_name='source_scheme_id' AND is_nullable='NO';")),1);
  await assert.rejects(()=>service.generate(owner,{scheme_no:'BJ-20261029-000001',version_no:1,template_version_id:template.template_version_id,method:'QUICK',fields:{},request_id:randomUUID()}),e=>e.statusCode===404);
  const fy=await service.ledger.upload(owner,{customer_key:'FANGYUAN',template_name:'本机方圆合成模板',filename:'synthetic.docx',format:'docx',content:ledgerWordTemplate().toString('base64')});
  const fyInput={...ledgerFixture('FANGYUAN'),template_version_id:fy.template_version_id,request_id:randomUUID()};
  const fyGenerated=await service.ledger.generate(owner,fyInput);assert.equal(fyGenerated.records.length,1);
  assert.equal(fyGenerated.records[0].generation_snapshot.quote.items.length,2);
  await assert.rejects(()=>service.ledger.generate(owner,{...fyInput,template_version_id:template.template_version_id,request_id:randomUUID()}),e=>e.statusCode===400);
  const incomplete=await service.ledger.upload(owner,{customer_key:'FANGYUAN',template_name:'本机缺少备注的模板',filename:'incomplete.docx',format:'docx',content:wordTemplate().toString('base64')});
  assert.equal(incomplete.auto_configured,false,'a template without a remark column needs explicit configuration');
  await assert.rejects(()=>service.ledger.generate(owner,{...fyInput,template_version_id:incomplete.template_version_id,request_id:randomUUID()}),e=>e.statusCode===400);
  const beforeRevision=await service.inspect(owner,template.template_version_id);
  const revision=await service.configure(owner,template.template_version_id,{mapping:beforeRevision.template.field_mapping,expected_version:beforeRevision.template.lock_version});
  const afterRevision=await service.ledger.bootstrap(owner);
  assert(afterRevision.templates.some(t=>t.template_version_id===template.template_version_id),'saved drafts retain access to their original configured template version');
  assert(afterRevision.templates.some(t=>t.template_version_id===revision.template_version_id));
  assert.equal((await service.ledger.draft(owner,draft.draft_id)).input_payload.template_version_id,template.template_version_id);
  const fromOldVersion=await service.ledger.generate(owner,{...input,request_id:randomUUID()});
  assert(fromOldVersion.records.every(r=>r.generation_snapshot.template_version_id===template.template_version_id));
  pg.query(await readFile(new URL('../database/migrations/contract_ledger_v1.preflight.sql',import.meta.url),'utf8'));
  const verifySql=await readFile(new URL('../database/migrations/contract_ledger_v1.verify.sql',import.meta.url),'utf8');
  assert.equal(pg.query(verifySql).split('\n').at(-1),'t|t');
  // Comma-separated has_table_privilege lists accept ANY permission. Verification
  // must require every needed permission, not treat SELECT alone as write access.
  pg.query('CREATE ROLE synthetic_ledger_readonly NOLOGIN; GRANT USAGE ON SCHEMA calc TO synthetic_ledger_readonly; GRANT SELECT ON calc.ledger_contract_draft,calc.ledger_contract_generation TO synthetic_ledger_readonly;');
  assert.equal(pg.query('SET ROLE synthetic_ledger_readonly;'+verifySql+'RESET ROLE;').split('\n').at(-1),'f|f');
  pg.query('GRANT INSERT,UPDATE ON calc.ledger_contract_draft TO synthetic_ledger_readonly; GRANT INSERT ON calc.ledger_contract_generation TO synthetic_ledger_readonly;');
  assert.equal(pg.query('SET ROLE synthetic_ledger_readonly;'+verifySql+'RESET ROLE;').split('\n').at(-1),'t|t');
  console.log('PASS: disposable DB, batch idempotency/immutability, CAS drafts, rendered bytes and unchanged quotation constraints');
 }finally{await pg.close();}
});
