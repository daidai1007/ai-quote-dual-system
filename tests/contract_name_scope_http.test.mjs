import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {wordTemplate,excelTemplate,mapped} from './helpers/contract_fixtures.mjs';

test('real name session protects contract metadata, writes and original Office output',{timeout:180000},async t=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'contract-name-http-'));const state=path.join(directory,'host.json');
 const host=spawn(process.execPath,[fileURLToPath(new URL('./helpers/contract_test_host.mjs',import.meta.url)),state],{cwd:new URL('../',import.meta.url),windowsHide:true,stdio:['pipe','pipe','pipe']});
 let output='';host.stderr.on('data',b=>output+=b.toString());
 try{
  let config;
  for(let i=0;i<1100;i++){
   try{config=JSON.parse(await fs.readFile(state,'utf8'));break;}catch{}
   if(host.exitCode!==null)throw Error('Local host failed: '+output.slice(-1500));
   await new Promise(r=>setTimeout(r,100));
  }
  assert.ok(config,'local host readiness');
  const request=async(route,{token,body,raw,method=(body||raw)?'POST':'GET',binary=false}={})=>{
   const response=await fetch(config.base+route,{method,headers:{'X-AI-Quote-Key':config.key,'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:raw??(body?JSON.stringify(body):undefined)});
   return {status:response.status,data:binary?Buffer.from(await response.arrayBuffer()):await response.json(),headers:response.headers};
  };
  const login=async name=>{const result=await request('/api/name-login',{body:{name}});assert.equal(result.status,200);return result.data;};
  const owner=await login('本机人员甲'),other=await login('其他本机人员'),all=await login('姜艳娟');
  await t.test('connection key or forged name header cannot read contracts',async()=>{
   assert.equal((await request('/api/contracts/bootstrap')).status,401);
   assert.equal((await request('/api/contracts/bootstrap',{token:'x'.repeat(43)})).status,401);
  });
  await t.test('authenticated malformed bodies and existing monetary inputs still return 400',async()=>{
   for(const body of [[],{item_name:'',price:-1}])assert.equal((await request('/api/attachments/catalog',{token:owner.token,body})).status,400);
   assert.equal((await request('/api/quotes/calculate-dual',{token:owner.token,raw:'{'})).status,400);
   const base={product_code:'js_single',material_code:'SECC',width_mm:1000,height_mm:1800,depth_mm:600};
   for(const [field,attachment]of [['quantity',{item_name:'附件',quantity:0}],['width',{item_name:'附件',quantity:1,width_mm:0}],['override',{item_name:'附件',quantity:1,unit_price_override:-1}]]){
    const result=await request('/api/quotes/calculate-dual',{token:owner.token,body:{...base,quote_id:'LOCAL-BAD-'+field,attachments:[attachment]}});assert.equal(result.status,400,JSON.stringify(result.data));
   }
   assert.equal((await request('/api/quotes/calculate-dual',{token:owner.token,body:{...base,quote_id:'LOCAL-BAD-DOOR',single_door_count:2,double_door_count:1}})).status,400);
   assert.equal((await request('/api/company-history',{token:owner.token,body:{...base,company_code:'TEST',payload:[]}})).status,400);
  });
  const upload=await request('/api/contracts/templates',{token:owner.token,body:{scheme_no:config.scheme_no,version_no:1,customer_code:'LOCAL-A',template_name:'本机姓名权限合同',filename:'local.docx',format:'docx',content:wordTemplate().toString('base64')}});assert.equal(upload.status,201);
  const inspect=await request('/api/contracts/templates/'+upload.data.template_version_id,{token:owner.token});
  const configured=await request('/api/contracts/templates/'+upload.data.template_version_id+'/configure',{token:owner.token,body:{expected_version:1,mapping:mapped(inspect.data.inspection,'docx')}});assert.equal(configured.status,200);
  const input={scheme_no:config.scheme_no,version_no:1,template_version_id:configured.data.template_version_id,method:'QUICK',fields:{contract_no:'LOCAL-AUTH',seller_name:'本机供方',sign_date:'2026-10-22'},request_id:randomUUID()};
  const generated=await request('/api/contracts/generate',{token:owner.token,body:input});assert.equal(generated.status,200,JSON.stringify(generated.data));const record=generated.data;
  const file=await request('/api/contracts/records/'+record.record_id+'/file',{token:owner.token,binary:true});assert.equal(file.status,200);assert.equal(createHash('sha256').update(file.data).digest('hex'),record.file_sha256);
  await t.test('OWN cannot enumerate or directly open another person’s resources',async()=>{
   const list=await request('/api/contracts/bootstrap?scope=ALL&user_id='+owner.person.user_id,{token:other.token});assert.equal(list.data.records.length,0);assert.equal(list.data.templates.length,0);
   for(const route of ['/api/contracts/records/'+record.record_id,'/api/contracts/records/'+record.record_id+'/file','/api/contracts/templates/'+configured.data.template_version_id])assert.equal((await request(route,{token:other.token})).status,404);
   assert.equal((await request('/api/contracts/generate',{token:other.token,body:{...input,request_id:randomUUID(),role:'ADMIN',owner_user_id:owner.person.user_id}})).status,404);
  });
  await t.test('three global operators generate Word and Excel from another creators quote and template',async()=>{
   const list=await request('/api/contracts/bootstrap',{token:all.token});assert.equal(list.data.records.length,1);assert.equal(list.data.templates[0].can_write,false);assert.equal(list.data.templates[0].can_use,true);assert.equal(list.data.sources.length,1);
   assert.equal((await request('/api/contracts/records/'+record.record_id,{token:all.token})).data.generation_snapshot.quote.total,650.3);
   assert.equal((await request('/api/contracts/records/'+record.record_id+'/file',{token:all.token})).status,404);
   assert.equal((await request('/api/contracts/templates/'+configured.data.template_version_id+'/settings',{token:all.token,body:{expected_version:2,enabled:false,is_default:false}})).status,404);
   const xupload=await request('/api/contracts/templates',{token:owner.token,body:{scheme_no:config.scheme_no,version_no:1,customer_code:'LOCAL-A',template_name:'本机跨人员Excel合同',filename:'local.xlsx',format:'xlsx',content:excelTemplate().toString('base64')}});assert.equal(xupload.status,201);
   const xi=await request('/api/contracts/templates/'+xupload.data.template_version_id,{token:owner.token});
   const xc=await request('/api/contracts/templates/'+xupload.data.template_version_id+'/configure',{token:owner.token,body:{expected_version:1,mapping:mapped(xi.data.inspection,'xlsx')}});assert.equal(xc.status,200);
   for(const name of ['戴晨丽','姜艳娟','翟晓峰']){
    const manager=await login(name);
    for(const [format,templateId]of [['docx',input.template_version_id],['xlsx',xc.data.template_version_id]]){
     const payload={...input,template_version_id:templateId,request_id:randomUUID(),fields:{...input.fields,contract_no:'GLOBAL-'+name+'-'+format}};
     const draft=await request('/api/contracts/drafts',{token:manager.token,body:payload});assert.equal(draft.status,200,JSON.stringify(draft.data));
     const generated=await request('/api/contracts/generate',{token:manager.token,body:payload});assert.equal(generated.status,200,JSON.stringify(generated.data));assert.equal(generated.data.generation_snapshot.quote.total,650.3);
     const detail=await request('/api/contracts/records/'+generated.data.record_id,{token:manager.token});assert.equal(detail.data.owner_user_id,manager.person.user_id);
     const file=await request('/api/contracts/records/'+generated.data.record_id+'/file',{token:manager.token,binary:true});assert.equal(file.status,200);assert.equal(createHash('sha256').update(file.data).digest('hex'),generated.data.file_sha256);
     assert.equal((await request('/api/contracts/records/'+generated.data.record_id+'/file',{token:other.token})).status,404);
    }
    const quote=await request('/api/quote-schemes/'+config.scheme_no,{token:manager.token});assert.equal(quote.data.creator_user_id,owner.person.user_id);
   }
  });
  await t.test('idempotency and revoked sessions keep existing files protected',async()=>{
   assert.equal((await request('/api/contracts/generate',{token:owner.token,body:input})).data.record_id,record.record_id);
   await request('/api/name-logout',{token:owner.token,body:{}});
   assert.equal((await request('/api/contracts/records/'+record.record_id+'/file',{token:owner.token})).status,401);
  });
 }finally{
  if(host.exitCode===null){host.stdin.end('done\n');await once(host,'exit');}
  const resolved=path.resolve(directory);if(path.dirname(resolved)!==path.resolve(os.tmpdir())||!path.basename(resolved).startsWith('contract-name-http-'))throw Error('Unexpected test cleanup path');await fs.rm(resolved,{recursive:true,force:true});
 }
});
