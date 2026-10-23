import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {createNameLoginService,ALL_QUOTE_NAMES} from '../api/name_login_service.mjs';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {createQuoteAnalysisService} from '../api/quote_analysis_service.mjs';
import {createPrivateQuoteGuard,q,withQuotePrincipal,ownerInsertSql} from '../api/quote_access_scope.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('real SQL scopes canonical quotes, analysis, private resources and legacy mapping',{timeout:180000},async t=>{
 const pg=await startLocalPostgres();
 try{
  pg.query('CREATE SCHEMA calc;CREATE TABLE calc.ordering_company(company_code text,company_name text);CREATE TABLE calc.dual_quote_result(quote_id text);CREATE TABLE calc.quote_document(quote_id text);');
  for(const migration of ['quote_scheme_center_v1.sql','quote_analysis_v1.sql','quote_name_scope_v1.sql'])pg.query(await readFile(new URL('../database/migrations/'+migration,import.meta.url),'utf8'));
  const sessions=createNameLoginService();const p=name=>{const v=sessions.login({name});return sessions.requireSession({headers:{authorization:'Bearer '+v.token}});};
  const a=p('张三'),b=p('李四'),all=ALL_QUOTE_NAMES.map(p);
  const deps={runPsql:async sql=>pg.query(sql),sqlUnicodeText:q,sqlNumber:v=>String(Number(v))};
  const service=createQuoteSchemeService(deps),analysis=createQuoteAnalysisService(deps),guard=createPrivateQuoteGuard(deps);
  const snapshot=(amount,name)=>({company:name,scheme_summary:{company:name,product_summary:'JE',quoted_amount:amount},draft_items:[{name:'测试柜',product_code:'JE',quantity:2,quote_display:{total:amount,discount:.8,quantity:2}}]});
  const one=await service.create(a,{operator_name:'伪造姓名',creator_user_id:b.userId,snapshot:snapshot(120,'张客户')});
  const assignmentTemplate=await readFile(new URL('../database/migrations/quote_name_scope_assign_confirmed_template.sql',import.meta.url),'utf8');
  assert.throws(()=>pg.query(assignmentTemplate),/template blocked/);
  assert.equal(Number(pg.query('SELECT count(*) FROM calc.quote_name_owner;')),0);
  const two=await service.create(b,{operator_name:'伪造姓名',snapshot:snapshot(340,'李客户')});
  const legacy=await service.create({userId:'legacy-shared',displayName:'旧客户端',role:'USER'},{operator_name:'旧创建人',snapshot:snapshot(999,'旧客户')});
  await t.test('list, counts, direct details and creator cannot escape ownership',async()=>{
   assert.equal((await service.list(a,{})).total,1);assert.equal((await service.list(a,{creator:'李四'})).total,0);
   assert.equal((await service.get(a,two.scheme_no)).found,false);
   const mine=await service.get(a,one.scheme_no);assert.equal(mine.creator_user_id,a.userId);assert.equal(mine.creator_name,'张三');assert.equal(mine.can_write,true);
   for(const admin of all){assert.equal((await service.list(admin,{})).total,3);assert.equal((await service.get(admin,one.scheme_no)).can_write,false);}
   // Old role/department/share declarations do not widen a NAME_ONLY person.
   assert.equal((await service.list({...a,role:'ADMIN',departmentId:'anything'},{})).total,1);
   assert.equal((await withQuotePrincipal(a,()=>service.list({userId:'old-admin',role:'ADMIN'},{}))).total,1);
   pg.query(`INSERT INTO calc.quote_scheme_share(scheme_id,grantee_user_id,granted_by_user_id) SELECT scheme_id,${q(a.userId)},'local-old-admin' FROM calc.quote_scheme WHERE scheme_no=${q(two.scheme_no)};`);
   assert.equal((await service.list(a,{})).total,1);assert.equal((await service.get(a,two.scheme_no)).found,false);
   assert.equal(pg.query(`SELECT detail->>'identity_mode' FROM calc.quote_scheme_audit a JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${q(one.scheme_no)} ORDER BY audit_id LIMIT 1;`),'NAME_ONLY');
  });
  await t.test('ALL is read-only for others; owner status, locks and frozen exports remain',async()=>{
   for(const admin of all){
    await assert.rejects(()=>service.save(admin,one.scheme_no,{operator_name:'x',expected_version:1,snapshot:snapshot(1,'改名')}),{statusCode:409});
    await assert.rejects(()=>service.transition(admin,one.scheme_no,'void',1,'x'),{statusCode:409});
    await assert.rejects(()=>service.exportResult(admin,one.scheme_no,{kind:'XLSX',succeeded:true,operator_name:'x',expected_version:1,snapshot:snapshot(1,'改名')}),{statusCode:409});
   }
   await service.exportResult(a,one.scheme_no,{kind:'XLSX',succeeded:true,expected_version:1,operator_name:'李四',snapshot:snapshot(120,'张客户')});
   assert.equal((await service.get(a,one.scheme_no)).status,'QUOTED');
   assert.equal((await service.get(a,one.scheme_no)).creator_name,'张三');
   await assert.rejects(()=>service.save(a,one.scheme_no,{expected_version:1,operator_name:'x',snapshot:snapshot(1,'x')}),{statusCode:409});
  });
  await t.test('actual analysis scopes totals, details and filter candidates before aggregation',async()=>{
   const mine=await analysis.analyze(a,{});assert.equal(mine.summary.quoted,1);assert.equal(mine.summary.amount,'120.00');assert.equal(mine.details.length,1);
   const noFormal=await analysis.analyze(b,{});assert.equal(noFormal.summary.quoted,0);assert.equal(noFormal.summary.amount,null);
   assert.equal((await analysis.analyze(p('从未登记的姓名'),{})).summary.quoted,0);
   for(const admin of all)assert.equal((await analysis.analyze(admin,{})).details.length,3);
   assert.equal((await analysis.analyze(a,{creator:'李四',scope:'ALL'})).details.length,0);
  });
  await t.test('unmapped legacy is hidden, confirmed mapping grants only its owner without changing creator',async()=>{
   assert.equal((await service.get(a,legacy.scheme_no)).found,false);
   const legacyId=Number(pg.query(`SELECT scheme_id FROM calc.quote_scheme WHERE scheme_no=${q(legacy.scheme_no)};`));
   const approved=assignmentTemplate.replace('-- SET LOCAL','SET LOCAL').replace('VALUES(NULL,NULL,NULL,NULL,NULL)',`VALUES(${legacyId},${q(a.userId)},${q(a.displayName)},'本机测试确认人','已确认的本机合成测试列表')`);
   pg.query(approved);
   assert.equal(pg.query(`SELECT mapping_basis FROM calc.quote_name_owner WHERE resource_kind='SCHEME' AND resource_key=${q(String(legacyId))};`),'已确认的本机合成测试列表');
   assert.equal((await service.get(a,legacy.scheme_no)).creator_user_id,'legacy-shared');assert.equal((await service.list(a,{})).total,2);
  });
  await t.test('private source IDs cannot be claimed, forged through snapshot metadata or read by ALL for writing',async()=>{
   const id='11111111-1111-4111-8111-111111111111';
   pg.query(withQuotePrincipal(a,()=>ownerInsertSql('QUOTE_LINE',q(id))));
   await guard.ownReference(a,id);await assert.rejects(()=>guard.ownReference(b,id),{statusCode:403});await assert.rejects(()=>guard.ownReference(all[0],id),{statusCode:403});
   await assert.rejects(()=>withQuotePrincipal(b,()=>guard.beforeBody({url:'/api/quote-schemes',method:'POST'},{snapshot:{quote_management:{versions:[{items:[{quote_line_id:id}]}]}}})),{statusCode:403});
   await guard.claim(a,'QUOTE_ID','local-quote','calc.dual_quote_result');await assert.rejects(()=>guard.claim(b,'QUOTE_ID','local-quote','calc.dual_quote_result'),{statusCode:403});
   pg.query("INSERT INTO calc.dual_quote_result VALUES('unmapped-old-id');");await assert.rejects(()=>guard.claim(a,'QUOTE_ID','unmapped-old-id','calc.dual_quote_result'),{statusCode:403});
  });
 }finally{await pg.close();}
});
