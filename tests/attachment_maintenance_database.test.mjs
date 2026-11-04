// Creates its own disposable loopback-only cluster. Never uses database config.
import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync,spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {randomUUID} from 'node:crypto';
import {createAttachmentMaintenance} from '../api/attachment_maintenance.mjs';
import {nameUserId} from '../api/name_login_service.mjs';
import {createAttachmentService,sqlValue} from '../api/attachment_service.mjs';
import ExcelJS from '@excel.js/exceljs';

const root=path.resolve(import.meta.dirname,'..');
const enabled=process.env.ATTACHMENT_MAINTENANCE_DB_TEST==='1';
const principal=name=>({displayName:name,userId:nameUserId(name),identityMode:'NAME_ONLY'});
const payload=()=>({action:'CREATE',request_id:randomUUID(),reason:'合成数据测试',products:[],
 item:{item_name:'本地固定附件',model_code:'LOCAL-FIXED',unit:'件',category_level1:'其他附件',quick_face_price:'85.123456789',width_mm:100,height_mm:200,depth_mm:50},cost_rules:[{fixed_cost:'48.125'}]});
const freePort=async()=>{const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const port=s.address().port;await new Promise(r=>s.close(r));return port;};
test('fixed maintenance SQL, immutable history and authenticated HTTP in disposable PostgreSQL', {skip:!enabled,timeout:120000},async t=>{
 const folder=fs.mkdtempSync(path.join(root,'.codex-tmp','attachment-maintenance-pg-')),data=path.join(folder,'data'),bin='G:/PostgreSQL/18/bin';
 const env={...process.env,PGCLIENTENCODING:'UTF8'};for(const k of Object.keys(env))if(k.startsWith('PG')&&k!=='PGCLIENTENCODING'||k==='DATABASE_URL')delete env[k];
 const run=(exe,args,input)=>execFileSync(path.join(bin,exe),args,{input,encoding:'utf8',windowsHide:true,timeout:30000,env,stdio:exe==='pg_ctl.exe'?'ignore':['pipe','pipe','pipe']})?.trim()??'';
 const port=await freePort();let child;
 run('initdb.exe',['-D',data,'-U','attachment_test','-A','trust','--encoding=UTF8','--no-locale']);
 try{
  run('pg_ctl.exe',['-D',data,'-l',path.join(folder,'server.log'),'-w','start','-o',`-h 127.0.0.1 -p ${port}`]);
  const sql=text=>run('psql.exe',['-X','-w','-h','127.0.0.1','-p',String(port),'-U','attachment_test','-d','postgres','-v','ON_ERROR_STOP=1','-A','-t','-q'],text);
  for(const f of ['tests/fixtures/attachment_online_schema_20260911.sql','database/migrations/attachment_cost_v2.sql','database/attachment-v2/02b-snapshot-guards.sql','tests/fixtures/attachment_api_base_stub.sql','database/migrations/attachment_maintenance.sql'])sql(fs.readFileSync(path.join(root,f),'utf8'));
  sql(fs.readFileSync(path.join(root,'database/migrations/attachment_maintenance.sql'),'utf8'));
  sql("INSERT INTO calc.attachment_catalog_version(data_version,source_sha256,status,source_file,audit_report) VALUES('local-v1',repeat('a',64),'ACTIVE','SYNTHETIC','{}');");
  const baselineCount=Number(sql('SELECT count(*) FROM calc.attachment_price;'));
  const service=createAttachmentMaintenance({runPsql:async text=>sql(text)}),actor=principal('戴晨丽');
  const quote=createAttachmentService({env:{},runPsql:async text=>sql(text),calculateBase:async input=>({quote_id:input.quote_id,
   formula_cost:{material_cost:100,auxiliary_cost:10,labor_cost:20,spray_cost:15,management_fee:8.7,total_cost:153.7,attachment_fee:0},
   quick_quote:{base_price:500,total_cost:500,attachment_fee:0},risk_flags:[]})});
  let created,oldResult,document,beforeHydrated,beforeFrozen,edited;
  const raw=payload();
  await t.test('create, exact decimal price, FIXED rule, classification and list',async()=>{
   created=await service.save(actor,raw);assert.equal(created.saved,true);
   const list=await service.list(actor);assert.equal(list.items.length,1);assert.equal(list.items[0].editable,true);
   assert.equal(list.items[0].quick_face_price,'85.123456789');assert.equal(list.items[0].rules[0].fixed_cost,'48.125');
   assert.equal(sql('SELECT count(*) FROM calc.attachment_maintenance_audit;'),'1');
  });
  await t.test('same request retry idempotent; repeated name rejected and transaction rolled back',async()=>{
   const replay=await service.save(actor,raw);assert.equal(replay.replayed,true);assert.equal(replay.attachment_price_id,created.attachment_price_id);
   await assert.rejects(service.save(actor,payload()),e=>e.statusCode===409);
   assert.equal(Number(sql('SELECT count(*) FROM calc.attachment_price;')),baselineCount+1);
  });
  await t.test('save synthetic quote using original attachment and freeze gross margin input',async()=>{
   const input={quote_id:'LOCAL_HISTORY',product_code:'JP_SINGLE',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,quote_date:'2026-11-03',coating_type:'橘纹',attachments:[{attachment_price_id:created.attachment_price_id,quantity:2}],material_unit_price_override:5};
   oldResult=await quote.calculate(input);assert.equal(oldResult.attachments[0].status,'FIXED');assert.equal(oldResult.attachments[0].formula_amount,96.25);
   const item={...input,name:'本地测试柜',quantity:3,attachment_contract:2,quote_line_id:oldResult.quote_line_id,attachments:oldResult.attachments,formula:oldResult.formula_cost,quick:oldResult.quick_quote};
   document={quote_id:'LOCAL_HISTORY_DOC',company_name:'本地测试客户',order_nature:'EXTERNAL',quote_date:input.quote_date,items:[item]};
   beforeHydrated=await quote.hydrateDocument(document);
   sql(`CREATE TABLE calc.local_saved_document(payload jsonb);INSERT INTO calc.local_saved_document VALUES(${sqlValue(JSON.stringify(document))}::jsonb);`);
   beforeFrozen=sql('SELECT jsonb_agg(to_jsonb(s) ORDER BY attachment_selection_id) FROM calc.attachment_selection s;');
  });
  await t.test('edit appends new catalog/rule IDs and preserves original price, rules, amounts',async()=>{
   const list=await service.list(actor),row=list.items[0];
   edited=await service.save(actor,{action:'EDIT',request_id:randomUUID(),attachment_price_id:row.attachment_price_id,reason:'合成调价',
    item:{...raw.item,quick_face_price:'100.5'},cost_rules:[{rule_id:row.rules[0].rule_id,fixed_cost:'60'}]});
   assert.notEqual(edited.attachment_price_id,created.attachment_price_id);
   assert.equal(sql(`SELECT quick_face_price::text FROM calc.attachment_price WHERE attachment_price_id=${created.attachment_price_id};`),'85.123456789');
   assert.equal(sql(`SELECT fixed_cost FROM calc.attachment_cost_rule WHERE rule_id=${row.rules[0].rule_id};`),'48.125');
   assert.equal(sql('SELECT jsonb_agg(to_jsonb(s) ORDER BY attachment_selection_id) FROM calc.attachment_selection s;'),beforeFrozen);
   assert.equal((await service.list(actor)).items.length,1);
   assert.equal((await quote.catalog()).items[0].attachment_price_id,edited.attachment_price_id);
   await assert.rejects(service.save(actor,{action:'DISABLE',request_id:randomUUID(),attachment_price_id:created.attachment_price_id,reason:'旧页面提交'}),e=>e.statusCode===409);
  });
  await t.test('saved/reopened historical document hydrates identically after price edit',async()=>{
   const reopened=JSON.parse(sql('SELECT payload FROM calc.local_saved_document;'));
   const after=await quote.hydrateDocument(reopened);assert.deepEqual(after,beforeHydrated);
   const fresh=await quote.calculate({quote_id:'LOCAL_NEW',product_code:'JP_SINGLE',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,quote_date:'2026-11-03',coating_type:'橘纹',attachments:[{attachment_price_id:edited.attachment_price_id,quantity:2}],material_unit_price_override:5});
   assert.equal(fresh.attachments[0].formula_amount,120);assert.equal(fresh.attachments[0].quick_amount,201);
   assert.notEqual(fresh.formula_cost.total_cost,oldResult.formula_cost.total_cost);
  });
  await t.test('historical Excel public quote, costs and attachment sheet stay identical after edit',async()=>{
   const out=path.join(root,'test-output','attachment-maintenance-history');fs.mkdirSync(out,{recursive:true});
   const after=await quote.hydrateDocument(JSON.parse(sql('SELECT payload FROM calc.local_saved_document;')));
   const values=[];
   for(const [label,document] of [['before',beforeHydrated],['after',after]]){
    const inputFile=path.join(out,label+'.json'),bookFile=path.join(out,label+'.xlsx');
    fs.writeFileSync(inputFile,JSON.stringify(document));
    execFileSync(process.execPath,['export_dual_quote_workbook.mjs',inputFile,bookFile],{cwd:root,encoding:'utf8',windowsHide:true});
    const workbook=new ExcelJS.Workbook();await workbook.xlsx.readFile(bookFile);
    values.push(workbook.worksheets.map(s=>({name:s.name,rows:s.getSheetValues()})));
   }
   assert.deepEqual(values[0],values[1]);
  });
  await t.test('disable/enable append revisions; retired IDs still hydrate and cannot be selected new',async()=>{
   const disabled=await service.save(actor,{action:'DISABLE',request_id:randomUUID(),attachment_price_id:edited.attachment_price_id,reason:'停用测试'});
   assert.equal((await quote.catalog()).items.length,0);assert.equal((await service.list(actor)).items[0].is_active,false);
   assert.deepEqual(await quote.hydrateDocument(document),beforeHydrated);
   const enabled=await service.save(principal('吕芝森'),{action:'ENABLE',request_id:randomUUID(),attachment_price_id:disabled.attachment_price_id,reason:'启用测试'});
   assert.equal((await quote.catalog()).items[0].attachment_price_id,enabled.attachment_price_id);
   assert.equal(sql(`SELECT count(*) FROM calc.attachment_maintenance_audit WHERE actor_name=${sqlValue('吕芝森')};`),'1');
  });
  await t.test('multiple fixed material rules preserve scopes and formula edit is rejected',async()=>{
   const active=(await service.list(actor)).items[0];const rule=active.rules[0].rule_id;
   sql(`INSERT INTO calc.attachment_cost_rule_material VALUES(${rule},'SECC');
    INSERT INTO calc.attachment_cost_rule(data_version,import_key,category_level1,item_name,method,fixed_cost,source_file,source_sheet,source_row_no,raw_values)
     VALUES('local-v1','extra-material','其他附件','本地固定附件','FIXED',80,'LOCAL','LOCAL',1,'{}');
    INSERT INTO calc.attachment_cost_rule_binding SELECT ${active.attachment_price_id},rule_id FROM calc.attachment_cost_rule WHERE import_key='extra-material';
    INSERT INTO calc.attachment_cost_rule_material SELECT rule_id,'SUS304' FROM calc.attachment_cost_rule WHERE import_key='extra-material';`);
   const item=(await service.list(actor)).items[0];assert.equal(item.rules.length,2);
   const changed=await service.save(actor,{action:'EDIT',request_id:randomUUID(),attachment_price_id:item.attachment_price_id,reason:'多材质调价',item:raw.item,cost_rules:item.rules.map(r=>({rule_id:r.rule_id,fixed_cost:Number(r.fixed_cost)+1}))});
   const current=(await service.list(actor)).items[0];assert.deepEqual(current.rules.map(r=>r.materials),[['SECC'],['SUS304']]);
   sql(`UPDATE calc.attachment_cost_rule SET method='CALCULATED',fixed_cost=NULL WHERE rule_id=${current.rules[0].rule_id};`);
   await assert.rejects(service.save(actor,{action:'DISABLE',request_id:randomUUID(),attachment_price_id:changed.attachment_price_id,reason:'拒绝公式'}),e=>e.statusCode===409);
  });
  await t.test('late classification failure rolls back catalog, audit and active flags atomically',async()=>{
   const input=payload();input.item.item_name='本地回滚测试';const first=await service.save(actor,input);
   const row=(await service.list(actor)).items.find(r=>r.attachment_price_id===first.attachment_price_id);
   const before=sql('SELECT jsonb_agg(to_jsonb(p) ORDER BY attachment_price_id) FROM calc.attachment_price p;');
   const audits=sql('SELECT count(*) FROM calc.attachment_maintenance_audit;');
   await assert.rejects(service.save(actor,{action:'EDIT',request_id:randomUUID(),attachment_price_id:row.attachment_price_id,reason:'非法分类回滚',
    item:{...input.item,category_level1:'26'},cost_rules:row.rules.map(r=>({rule_id:r.rule_id,fixed_cost:'99'}))}));
   assert.equal(sql('SELECT jsonb_agg(to_jsonb(p) ORDER BY attachment_price_id) FROM calc.attachment_price p;'),before);
   assert.equal(sql('SELECT count(*) FROM calc.attachment_maintenance_audit;'),audits);
  });
  await t.test('two maintainers cannot overwrite the same old revision',async()=>{
   const input=payload();input.item.item_name='本地并发测试';const added=await service.save(actor,input);
   const row=(await service.list(actor)).items.find(r=>r.attachment_price_id===added.attachment_price_id);
   const edit={action:'EDIT',attachment_price_id:row.attachment_price_id,reason:'并发调价测试',item:input.item,cost_rules:row.rules.map(r=>({rule_id:r.rule_id,fixed_cost:'51'}))};
   const result=await Promise.allSettled([service.save(actor,{...edit,request_id:randomUUID()}),service.save(principal('吕芝森'),{...edit,request_id:randomUUID()})]);
   assert.equal(result.filter(r=>r.status==='fulfilled').length,1);assert.equal(result.find(r=>r.status==='rejected').reason.statusCode,409);
  });
  await t.test('deployment grant script works for an existing non-owner API role',async()=>{
   sql('CREATE ROLE attachment_local_api NOLOGIN;GRANT USAGE ON SCHEMA calc TO attachment_local_api;CREATE ROLE attachment_unprivileged NOLOGIN;');
   sql('\\set attachment_api_role attachment_local_api\n'+fs.readFileSync(path.join(root,'database/attachment-maintenance/02-grant-api-role.sql'),'utf8'));
   assert.equal(sql("SELECT has_function_privilege('attachment_unprivileged','calc.maintain_fixed_attachment(jsonb,text,text)','EXECUTE');"),'f');
   const scoped=createAttachmentMaintenance({runPsql:async text=>sql('SET ROLE attachment_local_api;'+text+';RESET ROLE;')});
   const input=payload();input.item.item_name='本地非所有者角色测试';assert.equal((await scoped.save(actor,input)).saved,true);
   assert.ok((await scoped.list(actor)).items.length>0);assert.ok((await scoped.audit(actor)).items.length>0);
   sql(fs.readFileSync(path.join(root,'database/attachment-maintenance/01-readonly-preflight.sql'),'utf8'));
   sql(fs.readFileSync(path.join(root,'database/attachment-maintenance/03-readonly-verify.sql'),'utf8'));
  });
  await t.test('audit and saved selections remain append-only',async()=>{
   assert.throws(()=>sql("UPDATE calc.attachment_maintenance_audit SET reason='tamper';"),/append-only/);
   assert.throws(()=>sql('DELETE FROM calc.attachment_selection;'),/不可覆盖或删除/);
  });
  await t.test('HTTP uses real name sessions; 4 maintainers allowed, ordinary reads/writes forbidden',async()=>{
   const apiPort=await freePort();const serverEnv={...env,PORT:String(apiPort),AI_QUOTE_API_HOST:'127.0.0.1',AI_QUOTE_API_KEY:'local-attachment-maintenance-only',DATABASE_URL:`postgresql://attachment_test@127.0.0.1:${port}/postgres`,PSQL_PATH:path.join(bin,'psql.exe')};
   delete serverEnv.AI_QUOTE_ATTACHMENT_V2_VERSION;delete serverEnv.AI_QUOTE_SCHEME_PRINCIPALS;
   child=spawn(process.execPath,['api/server.mjs'],{cwd:root,env:serverEnv,windowsHide:true,stdio:['ignore','pipe','pipe']});let stderr='';child.stderr.on('data',x=>stderr+=x);child.stdout.on('data',()=>{});
   const base=`http://127.0.0.1:${apiPort}`;
   const call=async(route,payload,token)=>{const res=await fetch(base+route,{method:payload===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-AI-Quote-Key':serverEnv.AI_QUOTE_API_KEY,...(token?{Authorization:'Bearer '+token}:{})},body:payload===undefined?undefined:JSON.stringify(payload)});return {status:res.status,body:await res.json()};};
   let up=false;for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok){up=true;break;}}catch{}await new Promise(r=>setTimeout(r,30));}assert.ok(up,stderr);
   assert.equal((await call('/api/attachments/maintenance')).status,401);
   for(const name of ['戴晨丽','姜艳娟','翟晓峰','吕芝森']){
    const login=await call('/api/name-login',{name});assert.equal(login.status,200);
    assert.equal((await call('/api/attachments/maintenance',undefined,login.body.token)).status,200);
    const input=payload();input.item.item_name='HTTP '+name;
    assert.equal((await call('/api/attachments/maintenance',input,login.body.token)).status,200);
    const duplicate=payload();duplicate.item.item_name=input.item.item_name;
    assert.equal((await call('/api/attachments/maintenance',duplicate,login.body.token)).status,409);
    assert.equal((await call('/api/attachments/maintenance/history',undefined,login.body.token)).status,200);
    if(name==='吕芝森')assert.equal(login.body.person.can_manage_all_quotes,false);
   }
   const user=(await call('/api/name-login',{name:'普通同事'})).body.token;
   assert.equal((await call('/api/attachments/maintenance/capabilities',undefined,user)).body.can_maintain,false);
   assert.equal((await call('/api/attachments/maintenance',undefined,user)).status,403);
   assert.equal((await call('/api/attachments/maintenance',payload(),user)).status,403);
   assert.equal((await call('/api/attachments/catalog',{item_name:'bypass',price:1},user)).status,403);
   assert.equal((await call('/api/attachments/catalog?v=2',undefined,user)).status,200);
  });
 }finally{
  if(child){child.kill();await new Promise(resolve=>child.exitCode!==null?resolve():child.once('exit',resolve));}
  if(fs.existsSync(path.join(data,'postmaster.pid')))run('pg_ctl.exe',['-D',data,'-w','stop','-m','fast']);
  // Keep test evidence; no directory deletion or shared server operations.
 }
});
