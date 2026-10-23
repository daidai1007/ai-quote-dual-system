/** Real HTTP, actual Excel and an owned temporary PostgreSQL cluster only. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import ExcelJS from '@excel.js/exceljs';

test('colleague delivery persists exact versions without widening quote or contract permissions',{timeout:180000},async t=>{
 const folder=await fs.mkdtemp(path.join(os.tmpdir(),'quote-delivery-http-')),state=path.join(folder,'host.json');
 const child=spawn(process.execPath,[fileURLToPath(new URL('./helpers/contract_test_host.mjs',import.meta.url)),state,'--quote-delivery'],{windowsHide:true,stdio:['pipe','pipe','pipe']});
 let errors='';child.stderr.on('data',d=>errors+=d);
 try{
  let cfg;for(let i=0;i<1100;i++){try{cfg=JSON.parse(await fs.readFile(state,'utf8'));break;}catch{}if(child.exitCode!==null)throw Error(errors);await new Promise(r=>setTimeout(r,100));}assert.ok(cfg);
  const tokens={};let person='本机人员甲';
  const request=async(route,body,method=body?'POST':'GET',who=person)=>{
   const res=await fetch(cfg.base+route,{method,headers:{'X-AI-Quote-Key':cfg.key,'Content-Type':'application/json',...(tokens[who]?{Authorization:'Bearer '+tokens[who]}:{})},body:body?JSON.stringify(body):undefined});
   return {status:res.status,data:await res.json()};
  };
  const login=async name=>{const r=await request('/api/name-login',{name},'POST',name);assert.equal(r.status,200);tokens[name]=r.data.token;};
  for(const name of ['本机人员甲','本机接收乙','未接收丙','戴晨丽','姜艳娟','翟晓峰'])await login(name);
  const base='/api/quote-deliveries';let source=cfg.scheme_no,externalId,internalId,firstBatch;
  const formalSnapshot=(kind,amount=175,quoteVersion=1)=>({company:'本机测试客户 A',analysis_customer:{customer_code:'LOCAL-A'},
   document:{order_nature:kind,quote_date:'2026-10-23'},scheme_summary:{company:'本机测试客户 A',quoted_amount:amount*2},
   quote_management:{schema:1,current:quoteVersion,versions:[]},
   draft_items:[{name:'发送样本柜',quantity:2,formula:{material_cost:98765},quote_display:{name:'发送样本柜',specification:'400×300×200',quantity:2,unit:'台',unit_price:amount,total:amount*2,remark:'指定版本备注'}}]});
  const createFormal=async kind=>{const snapshot=formalSnapshot(kind);const created=await request('/api/quote-schemes',{snapshot});assert.equal(created.status,201);
   const r=await request('/api/quote-schemes/'+created.data.scheme_no+'/export-result',{expected_version:1,kind:'XLSX',succeeded:true,snapshot});assert.equal(r.status,200);return created.data.scheme_no;};
  await t.test('unauthenticated, foreign ownership and invalid recipient requests fail',async()=>{
   assert.equal((await request(base,undefined,'GET','anonymous')).status,401);
   assert.ok((await request(base+'/colleagues')).data.items.some(p=>p.name==='本机接收乙'));
   assert.deepEqual((await request(base+'/versions?scheme_no='+source,undefined,'GET','本机接收乙')).data.items,[]);
   const input={request_id:randomUUID(),scheme_no:source,source_version_no:1,quote_version:1,recipient_names:['本机接收乙'],note:''};
   assert.equal((await request(base,input,'POST','本机接收乙')).status,400);
   assert.equal((await request(base,{...input,recipient_names:['未接收丙']},'POST','本机接收乙')).status,403);
   assert.equal((await request(base,{...input,recipient_names:['本机人员甲']})).status,400);
   assert.equal((await request(base,{...input,quote_version:99})).status,409);
  });
  for(const kind of ['EXTERNAL','INTERNAL'])await t.test(kind+' multi-recipient delivery and idempotent retries',async()=>{
   const no=await createFormal(kind);if(kind==='EXTERNAL')source=no;
   const rows=(await request(base+'/versions?scheme_no='+no)).data.items;assert.equal(rows[0].document.total,350);
   const input={request_id:randomUUID(),scheme_no:no,source_version_no:1,quote_version:1,recipient_names:['本机接收乙','翟晓峰'],note:'请确认指定版本'};
   const before=(await request('/api/quote-schemes/'+no)).data;
   const results=await Promise.all([request(base,input),request(base,input)]);for(const r of results)assert.equal(r.status,201,JSON.stringify(r.data));
   const records=(await request(base+'?mode=sent&scheme_no='+no)).data;assert.equal(records.total,2);assert.ok(records.items.every(r=>!r.read_at&&r.total===350));
   const id=records.items.find(r=>r.recipient_name==='本机接收乙').delivery_id;
   if(kind==='EXTERNAL'){externalId=id;firstBatch=input;}else internalId=id;
   assert.equal((await request(base,{...input,note:'changed'})).status,409);
   assert.deepEqual((await request('/api/quote-schemes/'+no)).data,before);
  });
  await t.test('recipient opens only addressed records, survives re-login, and does not gain original access',async()=>{
   assert.equal((await request(base+'/'+externalId,undefined,'GET','未接收丙')).status,404);
   assert.equal((await request(base+'/'+externalId,undefined,'GET','戴晨丽')).status,404);
   const inbox=(await request(base,undefined,'GET','本机接收乙')).data;assert.equal(inbox.total,2);
   const opened=await request(base+'/'+externalId,undefined,'GET','本机接收乙');assert.equal(opened.status,200);assert.ok(opened.data.read_at);
   assert.equal(opened.data.document.total,350);assert.ok(!JSON.stringify(opened.data).includes('material_cost'));
   const costs=opened.data.document.cost_snapshot;assert.equal(costs.items[0].columns[costs.headers.indexOf('材料成本')],98765);
   await login('本机接收乙');assert.equal((await request(base+'/'+externalId,undefined,'GET','本机接收乙')).data.document_sha256,opened.data.document_sha256);
   assert.equal((await request('/api/quote-schemes/'+source,undefined,'GET','本机接收乙')).status,404);
   assert.equal((await request('/api/quote-schemes/'+source+'/revision',{expected_version:2},'POST','本机接收乙')).status,409);
   assert.equal((await request('/api/quote-schemes/'+source+'/export-result',{expected_version:2,kind:'XLSX',succeeded:true,snapshot:formalSnapshot('EXTERNAL')},'POST','本机接收乙')).status,409);
  });
  await t.test('later formal revisions never change sent V1, Excel and output registration are immutable',async()=>{
   const before=(await request('/api/quote-schemes/'+source)).data;
   const revision=await request('/api/quote-schemes/'+source+'/revision',{expected_version:before.lock_version});assert.equal(revision.status,200);
   const snap=formalSnapshot('EXTERNAL',210,2);
   const exported=await request('/api/quote-schemes/'+source+'/export-result',{expected_version:revision.data.lock_version,kind:'XLSX',succeeded:true,snapshot:snap});assert.equal(exported.status,200);
   const latest=(await request('/api/quote-schemes/'+source)).data;assert.equal(latest.quoted_amount,420);
   const opened=(await request(base+'/'+externalId,undefined,'GET','本机接收乙')).data;assert.equal(opened.document.total,350);assert.equal(opened.document.quote_version,1);
   const res=await fetch(cfg.base+base+'/'+externalId+'/xlsx',{headers:{'X-AI-Quote-Key':cfg.key,Authorization:'Bearer '+tokens['本机接收乙']}});assert.equal(res.status,200);assert.equal(res.headers.get('X-Quote-Document-SHA256'),opened.document_sha256);
   const book=new ExcelJS.Workbook();await book.xlsx.load(Buffer.from(await res.arrayBuffer()));const sheet=book.worksheets[0];assert.equal(sheet.getCell('F10').value,175);assert.equal(sheet.getCell('G11').value,350);assert.equal(sheet.getCell('E2').value,'V1');assert.equal(book.worksheets.length,1);
   for(const kind of ['PRINT','XLSX']){const event={output_id:randomUUID(),kind,document_sha256:opened.document_sha256};for(let i=0;i<2;i++)assert.equal((await request(base+'/'+externalId+'/outputs',event,'POST','本机接收乙')).status,200);assert.equal((await request(base+'/'+externalId+'/outputs',{...event,kind:kind==='PRINT'?'XLSX':'PRINT'},'POST','本机接收乙')).status,409);}
   assert.equal((await request(base+'/'+externalId+'/outputs',{output_id:randomUUID(),kind:'PRINT',document_sha256:'0'.repeat(64)},'POST','本机接收乙')).status,409);
   assert.deepEqual((await request('/api/quote-schemes/'+source)).data,latest);
   assert.equal((await request(base,firstBatch)).status,201);
  });
  await t.test('internal received quotations remain excluded from contracts for all three managers',async()=>{
   const row=(await request(base+'/'+internalId,undefined,'GET','本机接收乙')).data;
   for(const name of ['戴晨丽','姜艳娟','翟晓峰']){
    const bootstrap=await request('/api/contracts/bootstrap',undefined,'GET',name);assert.equal(bootstrap.status,200);assert.ok(!bootstrap.data.sources.some(x=>x.scheme_no===row.document.scheme_no));
    const quote=await request('/api/contracts/quote',{scheme_no:row.document.scheme_no,version_no:1,method:'QUICK'},'POST',name);assert.ok([403,404,409].includes(quote.status),JSON.stringify(quote));
    assert.ok((await request(base+'/versions?scheme_no='+row.document.scheme_no,undefined,'GET',name)).data.items.length);
   }
  });
  await t.test('all three managers can send others formal quotes without changing ownership',async()=>{
   const original=(await request('/api/quote-schemes/'+source)).data;
   for(const name of ['戴晨丽','姜艳娟','翟晓峰']){
    const current=(await request(base+'/versions?scheme_no='+source,undefined,'GET',name)).data.items[0];
    const sent=await request(base,{request_id:randomUUID(),scheme_no:source,source_version_no:current.source_version_no,quote_version:current.quote_version,recipient_names:['未接收丙'],note:'全量权限发送示例'},'POST',name);
    assert.equal(sent.status,201,JSON.stringify(sent));
   }
   assert.deepEqual((await request('/api/quote-schemes/'+source)).data,original);
  });
  await t.test('manual migration is idempotent; immutable rows resist SQL changes and missing schema fails closed',async()=>{
   const connection=cfg.connection;assert.equal(connection.host,'127.0.0.1');assert.equal(connection.user,'quote_regression_test');
   const env={...process.env,PGSSLMODE:'disable',PGCLIENTENCODING:'UTF8'};
   for(const key of ['DATABASE_URL','PGHOST','PGPORT','PGHOSTADDR','PGUSER','PGDATABASE','PGPASSWORD','PGPASSFILE','PGSERVICE','PGSERVICEFILE','PGOPTIONS'])delete env[key];
   const sql=text=>execFileSync(connection.psql,['-X','-w','-h',connection.host,'-p',String(connection.port),'-U',connection.user,'-d',connection.database,'-A','-t','-q','-v','ON_ERROR_STOP=1'],{env,input:text,encoding:'utf8',windowsHide:true,stdio:['pipe','pipe','pipe']}).trim();
   sql(await fs.readFile(new URL('../database/migrations/quote_delivery_v1.sql',import.meta.url),'utf8'));
   for(const command of ["UPDATE calc.quote_delivery_batch SET note='forged';","DELETE FROM calc.quote_delivery_batch;","UPDATE calc.quote_delivery_recipient SET recipient_name='forged';","UPDATE calc.quote_delivery_output SET output_kind='XLSX';"]){assert.throws(()=>sql(command),/immutable/);}
   sql('ALTER TABLE calc.quote_delivery_output RENAME TO quote_delivery_output_test_hidden;');
   try{
    assert.equal((await request(base)).status,503);
    assert.equal((await request('/api/quote-schemes/'+source)).status,200);
    assert.equal((await request('/api/contracts/bootstrap')).status,200);
    await login('本机人员甲');
   }finally{sql('ALTER TABLE calc.quote_delivery_output_test_hidden RENAME TO quote_delivery_output;');}
  });
 }finally{child.stdin.end('stop');await new Promise(resolve=>{if(child.exitCode!==null)return resolve();child.once('exit',resolve);});await fs.rm(folder,{recursive:true,force:true});}
});
