/** Offline service/Office regressions. SQL is captured, never executed. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createContractService} from '../api/contract_service.mjs';
import {inspectContractTemplate} from '../api/contract_document.mjs';
import {nameUserId} from '../api/name_login_service.mjs';
import {canManageAllQuotes} from '../api/quote_access_scope.mjs';
import {wordTemplate,excelTemplate,mapped,sampleQuote} from './helpers/contract_fixtures.mjs';
import {unzipSync,strFromU8} from 'fflate';

const person=(displayName,global=false)=>({userId:nameUserId(displayName),displayName,
 identityMode:'NAME_ONLY',scope:global?'ALL':'OWN',can_manage_all_quotes:global,can_view_all_quotes:global,role:'USER'});
const uploader=person('本机上传同事'),colleague=person('本机使用同事'),third=person('本机另一同事'),manager=person('姜艳娟',true);
const BUYER='本机共享模板客户',CUSTOMER='LOCAL-SHARED',GROUP='88888888-8888-4888-8888-888888888888';
const OWN_NO='BJ-20261028-000101',OTHER_NO='BJ-20261028-000102';
const RID='88888888-8888-4888-8888-888888888889';
const q=value=>"'"+String(value).replaceAll("'","''")+"'";
const literals=sql=>[...sql.matchAll(/'((?:''|[^'])*)'/g)].map(m=>m[1].replaceAll("''","'"));

function fixture({format='docx',customer=CUSTOMER,enabled=true,configured=true,internal=false}={}){
 const bytes=format==='docx'?wordTemplate():excelTemplate();
 const mapping=mapped(inspectContractTemplate(bytes,format),format);
 const snapshot={company:BUYER,order_nature:internal?'INTERNAL':'EXTERNAL',document:{order_nature:internal?'INTERNAL':'EXTERNAL'},contract_quote_snapshot:{schema:1,items:sampleQuote.items.map((r,i)=>({formula:{},quote_display:{...r,formula_unit_price:i?50.1:100,formula_total:i?150.3:200}}))}};
 const template={group_id:GROUP,template_version_id:1,version_no:1,customer_code:customer,customer_name:BUYER,
  template_name:'同事共享模板',owner_user_id:uploader.userId,owner_name:uploader.displayName,lock_version:1,
  enabled,is_default:false,field_mapping:configured?mapping:null,file_format:format,original_filename:'local.'+format,content:bytes.toString('base64')};
 const statements=[],saved=[];let generation;
 const permitted=(predicate,owner)=>predicate==='TRUE'||predicate===`g.owner_user_id=${q(owner)}`;
 const flag=(sql,name)=>{
  const value=new RegExp(`(TRUE|g\\.owner_user_id='[^']+') AS ${name}`).exec(sql)?.[1];
  return permitted(value,uploader.userId);
 };
 const as=p=>createContractService({sqlUnicodeText:q,runPsql:async sql=>{
  statements.push(sql);
  if(sql.includes('AS matching_customer_template'))return 'true';
  if(sql.includes("to_regclass('calc.ledger_contract_generation')"))return 'false';
  if(sql.includes("to_regclass('calc.contract_generation')"))return 'true';
  if(sql.includes("'snapshot',v.snapshot_payload")){
   const owner=sql.includes(q(OWN_NO))?uploader:colleague;
   if(p.userId!==owner.userId&&!canManageAllQuotes(p))return 'null';
   return JSON.stringify({scheme_id:owner===uploader?101:102,scheme_no:owner===uploader?OWN_NO:OTHER_NO,version_no:1,customer_name:BUYER,catalog_customer_code:CUSTOMER,snapshot});
  }
  if(sql.includes("'product_summary',s.product_summary"))return JSON.stringify([uploader,colleague].filter(owner=>owner.userId===p.userId||canManageAllQuotes(p)).map(owner=>({scheme_no:owner===uploader?OWN_NO:OTHER_NO,version_no:1,customer_name:BUYER,catalog_customer_code:CUSTOMER})));
  if(sql.includes('FROM calc.contract_template_group g JOIN LATERAL')){
   const predicate=/v ON TRUE WHERE (.*?)\)t;/.exec(sql)?.[1];
   if(!permitted(predicate,uploader.userId))return '[]';
   return JSON.stringify([{...template,content:undefined,field_mapping:undefined,configured:!!template.field_mapping,can_write:flag(sql,'can_write'),can_use:flag(sql,'can_use')}]);
  }
  if(sql.includes('FROM calc.contract_template_version v JOIN calc.contract_template_group')){
   const predicate=/WHERE v.template_version_id=\d+ AND (.*?)\) t\)/.exec(sql)?.[1];
   return JSON.stringify(permitted(predicate,uploader.userId)?template:null);
  }
  if(sql.startsWith('SELECT')&&sql.includes('FROM calc.contract_template_version WHERE group_id='))return JSON.stringify([{version_no:1,original_filename:'local.'+format,configured:!!template.field_mapping,created_at:'2026-10-28'}]);
  if(sql.startsWith('SELECT')&&sql.includes('request_id='))return 'null';
  if(sql.includes('INSERT INTO calc.contract_generation(')){
   const data=literals(sql).find(v=>v.startsWith('{"scheme_no":'));
   const binary=Buffer.from([...sql.matchAll(/decode\('([a-f0-9]+)','hex'\)/g)].at(-1)[1],'hex');
   assert.equal(binary.subarray(0,2).toString(),'PK','actual rendered Office archive');
   generation={record_id:RID,owner_user_id:p.userId,generation_snapshot:JSON.parse(data),file_format:format,file_sha256:createHash('sha256').update(binary).digest('hex'),content:binary.toString('base64')};
   return JSON.stringify(generation);
  }
  if(sql.startsWith('SELECT')&&sql.includes('FROM calc.contract_generation r WHERE record_id=')){
   const ownRead=sql.includes(`r.owner_user_id=${q(p.userId)}`);
   return JSON.stringify(generation&&(generation.owner_user_id===p.userId||!ownRead&&p.can_view_all_quotes)?generation:null);
  }
  if(sql.includes('INSERT INTO calc.contract_generation_draft(')){
   const draft={draft_id:RID,lock_version:1,input_payload:JSON.parse(literals(sql).find(v=>v.startsWith('{"scheme_no":'))),owner_user_id:p.userId};saved.push(draft);return JSON.stringify(draft);
  }
  if(sql.includes('FROM calc.contract_generation_draft d'))return JSON.stringify(saved.filter(r=>r.owner_user_id===p.userId));
  if(sql.includes('FROM calc.contract_generation r JOIN')){
   const visible=generation&&(p.userId===generation.owner_user_id||p.can_view_all_quotes);
   return sql.includes('count(*)::text')?String(visible?1:0):JSON.stringify(visible?[generation]:[]);
  }
  if(sql.includes('WITH owned AS(UPDATE calc.contract_template_group'))return JSON.stringify(p.userId===uploader.userId&&sql.includes(`g.owner_user_id=${q(uploader.userId)}`)?{template_version_id:2,version_no:2,group_id:GROUP,configured:true}:null);
  if(sql.includes('WITH lock AS(SELECT pg_advisory'))return JSON.stringify({saved:p.userId===uploader.userId&&sql.includes(`g.owner_user_id=${q(uploader.userId)}`)});
  throw Error('Unexpected offline SQL: '+sql.slice(0,160));
 }});
 const input=(p=colleague)=>({scheme_no:p===uploader?OWN_NO:OTHER_NO,version_no:1,template_version_id:1,method:'QUICK',request_id:RID,fields:{contract_no:'LOCAL-SHARING',seller_name:'本机供方',sign_date:'2026-10-28',buyer_name:'FORGED',total_amount:'1'}});
 return {as,input,template,bytes,mapping,statements,saved,generation:()=>generation};
}

test('ordinary named colleagues list all templates with use permission and owner-only maintenance',async()=>{
 const f=fixture();
 for(const p of [uploader,colleague,third,manager]){
  const result=await f.as(p).bootstrap(p);
  assert.equal(result.templates.length,1,p.displayName);
  assert.equal(result.templates[0].can_use,true);
  assert.equal(result.templates[0].can_write,p.userId===uploader.userId);
 }
});
test('ordinary colleagues can inspect template locations and version history',async()=>{
 const f=fixture();for(const p of [colleague,third]){
  const result=await f.as(p).inspect(p,1);assert.equal(result.template.owner_user_id,uploader.userId);assert.equal(result.template.content,undefined);
  assert(result.inspection.rows.length>0);assert.equal((await f.as(p).versions(p,1)).items.length,1);
 }
});
test('missing identity and shared connection identity cannot enumerate or inspect templates',async()=>{
 const f=fixture();for(const p of [{},{userId:'shared-client:test',role:'ADMIN'}]){
  for(const action of [()=>f.as(p).bootstrap(p),()=>f.as(p).inspect(p,1),()=>f.as(p).versions(p,1)])await assert.rejects(action,e=>e.statusCode===401);
 }
});
for(const format of ['docx','xlsx'])for(const method of ['QUICK','FORMULA'])test(`${format} ${method}: ordinary colleague generates from own matching quote using uploader template`,async()=>{
 const f=fixture({format}),service=f.as(colleague),input={...f.input(),method};
 const record=await service.generate(colleague,input);
 assert.equal(record.owner_user_id,colleague.userId);
 assert.equal(record.generation_snapshot.fields.buyer_name,BUYER);
 assert.equal(record.generation_snapshot.fields.total_amount,method==='QUICK'?650.3:350.3);
 assert.equal(record.generation_snapshot.fields.total_amount,record.generation_snapshot.quote.total);
 const archive=unzipSync(Buffer.from(f.generation().content,'base64'));
 assert(strFromU8(archive[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']).includes(BUYER));
 assert(!JSON.stringify(record.generation_snapshot).includes('FORGED'));
 assert.equal((await service.saveDraft(colleague,input)).lock_version,1);
 assert.equal(f.saved[0].owner_user_id,colleague.userId);
});
test('sharing templates does not grant access to another colleagues formal quote',async()=>{
 const f=fixture();for(const action of ['generate','saveDraft'])await assert.rejects(f.as(colleague)[action](colleague,{...f.input(),scheme_no:OWN_NO}),e=>e.statusCode===404);
 assert(!f.statements.some(s=>s.includes('INSERT INTO calc.contract_generation(')||s.includes('INSERT INTO calc.contract_generation_draft(')));
});
test('cross-customer template is rejected for both generation and generation drafts',async()=>{
 const f=fixture({customer:'DIFFERENT-CUSTOMER'});
 for(const action of ['generate','saveDraft'])await assert.rejects(f.as(colleague)[action](colleague,f.input()),/客户模板与正式报价客户不一致/);
 assert(!f.statements.some(s=>s.includes('INSERT INTO calc.contract_generation(')||s.includes('INSERT INTO calc.contract_generation_draft(')));
});
for(const options of [{enabled:false},{configured:false}])test('disabled or unconfigured template stays visible but cannot generate or save a generation draft '+JSON.stringify(options),async()=>{
 const f=fixture(options);assert.equal((await f.as(colleague).bootstrap(colleague)).templates.length,1);
 for(const action of ['generate','saveDraft'])await assert.rejects(f.as(colleague)[action](colleague,f.input()),/尚未配置或已停用/);
});
test('ordinary colleagues and global managers cannot configure, disable, default or overwrite another uploader template',async()=>{
 const f=fixture();for(const p of [colleague,third,manager]){
  await assert.rejects(f.as(p).configure(p,1,{mapping:f.mapping,expected_version:1}),e=>e.statusCode===404);
  for(const settings of [{enabled:false,is_default:false},{enabled:true,is_default:true}])await assert.rejects(f.as(p).setTemplate(p,1,{...settings,expected_version:1}),e=>e.statusCode===404);
  if(p!==third)await assert.rejects(f.as(p).upload(p,{scheme_no:OTHER_NO,version_no:1,customer_code:CUSTOMER,template_name:'ignored',group_id:GROUP,expected_version:1,filename:'local.docx',format:'docx',content:f.bytes.toString('base64')}),e=>[404,409].includes(e.statusCode));
 }
});
test('uploader retains field configuration, enabled/default settings and new-version upload',async()=>{
 const f=fixture(),service=f.as(uploader);
 assert.equal((await service.configure(uploader,1,{mapping:f.mapping,expected_version:1})).configured,true);
 assert.equal((await service.setTemplate(uploader,1,{enabled:true,is_default:true,expected_version:1})).saved,true);
 assert.equal((await service.upload(uploader,{scheme_no:OWN_NO,version_no:1,customer_code:CUSTOMER,template_name:'ignored',group_id:GROUP,expected_version:1,filename:'local.docx',format:'docx',content:f.bytes.toString('base64')})).version_no,2);
});
test('generated records and drafts remain owned even though templates are shared',async()=>{
 const f=fixture();await f.as(colleague).generate(colleague,f.input());await f.as(colleague).saveDraft(colleague,f.input());
 const other=await f.as(uploader).bootstrap(uploader);assert.equal(other.templates.length,1);assert.equal(other.records.length,0);assert.equal(other.drafts.length,0);
 const own=await f.as(colleague).bootstrap(colleague);assert.equal(own.records.length,1);assert.equal(own.drafts.length,1);
 await assert.rejects(f.as(uploader).record(uploader,RID),e=>e.statusCode===404);
 await assert.rejects(f.as(manager).download(manager,RID),e=>e.statusCode===404);
 assert.equal((await f.as(manager).record(manager,RID)).owner_user_id,colleague.userId);
});
