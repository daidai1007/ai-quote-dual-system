import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import net from 'node:net';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('real HTTP API requires sessions and enforces all private route scopes',{timeout:180000},async t=>{
 const pg=await startLocalPostgres();let child;
 try{
  pg.query(`CREATE SCHEMA calc;
   CREATE TABLE calc.ordering_company(company_id bigint,company_code text PRIMARY KEY,company_name text,contact_name text,contact_phone text,company_address text,is_active boolean);
   CREATE TABLE calc.company_quote_history(history_id bigint,company_id bigint,quote_id text,product_code text,material_code text,variant_code text,width_mm numeric,height_mm numeric,depth_mm numeric,created_at timestamptz,request_payload jsonb);
   CREATE TABLE calc.client_order_workspace(order_number text,workspace_payload jsonb,updated_at timestamptz);
   INSERT INTO calc.client_order_workspace VALUES('unmapped-old-workspace','{"note":"旧私有测试工作区"}',now());
   CREATE TABLE calc."历史价格"(source_row_no bigint,dingtalk_contract_no text,tax_included_unit_price numeric,customer_name text,specification text,cabinet_type text);
   CREATE TABLE calc.cabinet_template(template_code text,template_name text,default_width_mm numeric,default_height_mm numeric,default_depth_mm numeric,is_active boolean);
   CREATE TABLE calc.experience_product(experience_product_id bigint,product_code text,product_name text,is_active boolean);
   CREATE TABLE calc.experience_product_model(model_id bigint,experience_product_id bigint,model_code text,width_mm numeric,height_mm numeric,depth_mm numeric,is_active boolean);
   CREATE TABLE calc.material(material_code text,material_name text,is_active boolean);
   CREATE TABLE calc.spray_price(coating_type text,is_active boolean);
   INSERT INTO calc.cabinet_template VALUES('JE','本机公共产品',100,100,100,true);
   INSERT INTO calc.material VALUES('SECC','公共材料',true);
   INSERT INTO calc.ordering_company VALUES(1,'A','张客户',NULL,NULL,NULL,true),(2,'B','李客户',NULL,NULL,NULL,true);
   INSERT INTO calc."历史价格" VALUES(1,'local-private-A',100,'同客户','100*100*100','JE'),(2,'local-private-B',200,'同客户','100*100*100','JE'),(3,'unmapped',300,'同客户','100*100*100','JE');`);
  for(const file of ['quote_scheme_center_v1.sql','quote_analysis_v1.sql','quote_name_scope_v1.sql'])pg.query(await readFile(new URL('../database/migrations/'+file,import.meta.url),'utf8'));
  const listener=net.createServer();listener.listen(0,'127.0.0.1');await once(listener,'listening');const port=listener.address().port;await new Promise(r=>listener.close(r));
  const env={...process.env,AI_QUOTE_API_HOST:'127.0.0.1',AI_QUOTE_API_PORT:String(port),PORT:String(port),AI_QUOTE_API_KEY:'local-test-only',
    AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:String(pg.connection.port),AI_QUOTE_DB_NAME:'postgres',AI_QUOTE_DB_USER:pg.connection.user,PSQL_PATH:pg.connection.psql,
    AI_QUOTE_PRINCIPALS_JSON:JSON.stringify([{api_key_sha256:createHash('sha256').update('old-admin-test-key').digest('hex'),user_id:'legacy-admin',display_name:'旧管理员测试身份',role:'ADMIN'}])};
  for(const key of ['DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGPASSFILE','PGOPTIONS','PGPASSWORD','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','RENDER'])delete env[key];
  env.PGSSLMODE='disable';env.PGCONNECT_TIMEOUT='5';
  child=spawn(process.execPath,['api/server.mjs'],{cwd:new URL('../',import.meta.url),env,windowsHide:true,stdio:['ignore','pipe','pipe']});
  let errors='';child.stderr.on('data',b=>{errors+=b.toString();});
  const base=`http://127.0.0.1:${port}`;
  for(let i=0;i<100;i++){
   try{if((await fetch(base+'/health')).ok)break;}catch{}
   if(child.exitCode!==null)throw new Error('Local API failed: '+errors);
   await new Promise(r=>setTimeout(r,50));
  }
  const req=async(path,{token,body,method=body?'POST':'GET',extra={}}={})=>{
   const response=await fetch(base+path,{method,headers:{'x-ai-quote-key':'local-test-only','Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...extra},body:body?JSON.stringify(body):undefined});
   return {status:response.status,data:await response.json()};
  };
  const login=async name=>{const r=await req('/api/name-login',{body:{name}});assert.equal(r.status,200);return r.data;};
  const a=await login('张三'),b=await login('李四'),all=await login('姜艳娟');
  const payload=name=>({snapshot:{document:{order_nature:'EXTERNAL'},company:name,scheme_summary:{company:name,product_summary:'JE',quoted_amount:100},draft_items:[]},operator_name:'伪造操作人',role:'ADMIN',scope:'ALL'});
  const one=await req('/api/quote-schemes',{token:a.token,body:payload('张客户')}),two=await req('/api/quote-schemes',{token:b.token,body:payload('李客户')});
  assert.equal(one.status,201);assert.equal(two.status,201);
  await t.test('missing, forged and old shared credentials never bypass login',async()=>{
   for(const path of ['/api/quote-schemes','/api/quote-analysis','/api/companies/catalog'])assert.equal((await req(path)).status,401);
   assert.equal((await req('/api/quote-schemes',{extra:{'x-ai-quote-key':'old-admin-test-key'}})).status,401);
   assert.equal((await req('/api/quote-schemes',{token:a.token,extra:{'x-ai-quote-key':'old-admin-test-key'}})).data.total,1);
   assert.equal((await req('/api/quote-schemes',{token:'x'.repeat(43),extra:{'x-user-id':a.person.user_id,'x-role':'ADMIN'}})).status,401);
   assert.equal((await req('/api/name-login',{body:{name:'新姓名',scope:'ALL'}})).status,400);
  });
  await t.test('lists, direct reads, copy and foreign writes use server identity',async()=>{
   assert.equal((await req('/api/quote-schemes?scope=ALL&role=ADMIN',{token:a.token})).data.total,1);
   assert.equal((await req('/api/quote-schemes/'+two.data.scheme_no,{token:a.token})).status,404);
   assert.equal((await req('/api/quote-schemes/'+two.data.scheme_no+'/copy',{token:a.token,body:{expected_version:1}})).status,404);
   assert.equal((await req('/api/quote-schemes/'+one.data.scheme_no,{token:all.token,method:'PUT',body:{...payload('改名'),expected_version:999}})).status,409);
   const read=await req('/api/quote-schemes/'+one.data.scheme_no,{token:all.token});assert.equal(read.data.can_write,true);assert.equal(read.data.creator_name,'张三');
   assert.equal((await req('/api/quote-schemes',{token:all.token})).data.total,2);
   assert.deepEqual((await req('/api/companies/catalog',{token:a.token})).data.items.map(x=>x.company_name),['张客户']);
  });
  await t.test('HTTP body guards reject foreign snapshot references before creating a scheme',async()=>{
   const foreignLine='11111111-1111-4111-8111-111111111111';
   pg.query(`INSERT INTO calc.quote_name_owner(resource_kind,resource_key,owner_user_id,confirmed_by_name,mapping_source)
     VALUES('QUOTE_LINE','${foreignLine}','${b.person.user_id}','local fixture','SESSION_CREATED');`);
   const before=pg.query('SELECT count(*) FROM calc.quote_scheme;');
   for(const person of [a,await login('戴晨丽1')]){
    const forged=payload('forged private snapshot');
    forged.snapshot.quote_management={rows:[{quote_line_id:foreignLine}]};
    const result=await req('/api/quote-schemes',{token:person.token,body:forged});
    assert.equal(result.status,403,JSON.stringify(result.data));
   }
   assert.equal(pg.query('SELECT count(*) FROM calc.quote_scheme;'),before);
  });
  await t.test('workspace and imported private history are scoped without disabling public software',async()=>{
   assert.equal((await req('/api/orders/workspace/save',{token:a.token,body:{order_number:'same-local-key',payload:{note:'张三本机测试'}}})).data.saved,true);
   assert.equal((await req('/api/orders/workspace/load',{token:b.token,body:{order_number:'same-local-key'}})).data.found,false);
   assert.equal((await req('/api/orders/workspace/load',{token:a.token,body:{order_number:'same-local-key'}})).data.payload.note,'张三本机测试');
   assert.equal((await req('/api/orders/workspace/load',{token:b.token,body:{order_number:'same-local-key',owner_user_id:a.person.user_id}})).status,403);
   assert.equal((await req('/api/orders/workspace/load',{token:all.token,body:{order_number:'same-local-key',owner_user_id:a.person.user_id}})).data.payload.note,'张三本机测试');
   assert.equal((await req('/api/orders/workspace/load',{token:b.token,body:{order_number:'unmapped-old-workspace'}})).data.found,false);
   assert.equal((await req('/api/orders/workspace/load',{token:all.token,body:{order_number:'unmapped-old-workspace'}})).data.legacy_read_only,true);
   const text=v=>"'"+v.replaceAll("'","''")+"'";
   pg.query(`INSERT INTO calc.quote_name_owner(resource_kind,resource_key,owner_user_id,confirmed_by_name,mapping_source) VALUES('HISTORY_PRICE','1',${text(a.person.user_id)},'测试','USER_CONFIRMED_LEGACY'),('HISTORY_PRICE','2',${text(b.person.user_id)},'测试','USER_CONFIRMED_LEGACY');`);
   const body={company_name:'同客户',specification:'100*100*100',cabinet_type:'JE'};
   assert.deepEqual((await req('/api/history-prices/match',{token:a.token,body})).data.items.map(x=>x.dingtalk_contract_no),['local-private-A']);
   assert.equal((await req('/api/history-prices/match',{token:all.token,body})).data.items.length,3);
   assert.equal((await req('/health')).status,200);
   const publicCatalog=await req('/api/products/catalog',{token:b.token});assert.equal(publicCatalog.status,200);assert.equal(publicCatalog.data.items[0].product_code,'JE');
  });
  await t.test('real analysis returns own data and empty first-user state',async()=>{
   assert.equal((await req('/api/quote-analysis',{token:a.token})).data.details.length,1);
   assert.equal((await req('/api/quote-analysis?creator=李四&scope=ALL',{token:a.token})).data.details.length,0);
   const fresh=await login('从未登记过的有效姓名');assert.equal((await req('/api/quote-analysis',{token:fresh.token})).data.details.length,0);
   for(const name of ['翟晓峰','戴晨丽']){const p=await login(name);assert.equal((await req('/api/quote-analysis',{token:p.token})).data.details.length,2);}
  });
  await t.test('visible source copies belong to the current person and leave the original owner unchanged',async()=>{
   const copied=await req('/api/quote-schemes/'+two.data.scheme_no+'/copy',{token:all.token,body:{expected_version:1,operator_name:'李四'}});
   assert.equal(copied.status,201);
   const detail=await req('/api/quote-schemes/'+copied.data.scheme_no,{token:all.token});
   assert.equal(detail.data.creator_user_id,all.person.user_id);assert.equal(detail.data.can_write,true);
   assert.equal((await req('/api/quote-schemes/'+two.data.scheme_no,{token:b.token})).data.creator_user_id,b.person.user_id);
   assert.equal((await req('/api/quote-schemes',{token:b.token})).data.total,1);
  });
  await t.test('manager revision accepts persisted legacy references while ordinary users remain isolated',async()=>{
   const owner=await login('戴晨丽');
   const created=await req('/api/quote-schemes',{token:owner.token,body:payload('本机旧修订客户')});assert.equal(created.status,201);
   const oldLine='AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA',sourceLine='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
   const stored=payload('本机旧修订客户').snapshot;stored.draft_items=[{quote_line_id:oldLine,source_quote_line_id:sourceLine}];
   const literal=v=>"convert_from(decode('"+Buffer.from(v).toString('hex')+"','hex'),'UTF8')";
   pg.query(`UPDATE calc.quote_scheme SET status='REVISING' WHERE scheme_no=${literal(created.data.scheme_no)};
    UPDATE calc.quote_scheme_snapshot SET snapshot_payload=${literal(JSON.stringify(stored))}::jsonb
    WHERE scheme_id=(SELECT scheme_id FROM calc.quote_scheme WHERE scheme_no=${literal(created.data.scheme_no)});`);
   const updated=payload('本机旧修订客户');updated.snapshot.draft_items=[{quote_line_id:oldLine.toLowerCase(),source_quote_line_id:sourceLine}];updated.expected_version=1;
   const accepted=await req('/api/quote-schemes/'+created.data.scheme_no,{token:owner.token,method:'PUT',body:updated});assert.equal(accepted.status,200,JSON.stringify(accepted.data));
   const detail=await req('/api/quote-schemes/'+created.data.scheme_no,{token:owner.token});assert.equal(detail.data.status,'REVISING');assert.equal(detail.data.can_write,true);
   for(const other of [a])assert.equal((await req('/api/quote-schemes/'+created.data.scheme_no,{token:other.token,method:'PUT',body:{...updated,expected_version:2}})).status,403);
   const forged=structuredClone(updated);forged.snapshot.draft_items[0].quote_line_id='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
   assert.equal((await req('/api/quote-schemes/'+created.data.scheme_no,{token:owner.token,method:'PUT',body:forged})).status,403);
  });
  await t.test('all three real sessions modify revise print and export another creators quote',async()=>{
   for(const name of ['戴晨丽','姜艳娟','翟晓峰']){
    const manager=await login(name),created=await req('/api/quote-schemes',{token:b.token,body:payload('跨人员本机客户')});assert.equal(created.status,201);
    const no=created.data.scheme_no,path='/api/quote-schemes/'+no;
    let detail=await req(path,{token:manager.token});assert.equal(detail.data.can_write,true);
    const saved=await req(path,{token:manager.token,method:'PUT',body:{...payload('跨人员本机客户'),expected_version:detail.data.lock_version}});assert.equal(saved.status,200,JSON.stringify(saved.data));
    detail=await req(path,{token:manager.token});
    assert.equal((await req(path+'/export-result',{token:manager.token,body:{...payload('跨人员本机客户'),kind:'XLSX',succeeded:true,expected_version:detail.data.lock_version}})).status,200);
    detail=await req(path,{token:manager.token});assert.equal(detail.data.creator_user_id,b.person.user_id);assert.equal(detail.data.last_editor_name,name);
    assert.equal((await req(path+'/revision',{token:manager.token,body:{expected_version:detail.data.lock_version}})).status,200);
    detail=await req(path,{token:manager.token});assert.equal(detail.data.status,'REVISING');
    assert.equal((await req(path+'/export-result',{token:manager.token,body:{...payload('跨人员本机客户'),kind:'PRINT',succeeded:true,expected_version:detail.data.lock_version}})).status,200);
    detail=await req(path,{token:manager.token});assert.equal(detail.data.status,'QUOTED');assert.equal(detail.data.creator_user_id,b.person.user_id);
    assert.equal((await req(path,{token:a.token,method:'PUT',body:{...payload('伪造'),expected_version:detail.data.lock_version,can_manage_all_quotes:true,role:'ADMIN'}})).status,409);
   }
  });
  await t.test('logout revokes the token',async()=>{
   assert.equal((await req('/api/name-logout',{token:a.token,body:{}})).status,200);
   assert.equal((await req('/api/quote-schemes',{token:a.token})).status,401);
   assert.equal((await req('/api/quote-schemes',{token:b.token})).status,200);
  });
 }finally{
  if(child&&child.exitCode===null){const exited=once(child,'exit');child.kill();await exited;}
  await pg.close();
 }
});
