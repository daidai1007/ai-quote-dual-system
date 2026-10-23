import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {withQuotePrincipal} from './quote_access_scope.mjs';
import {createNameLoginService} from './name_login_service.mjs';
import {
  apiKeyHash, assertTransition, canReadScheme, createQuoteSchemeService, loadPrincipalMap,
  operatorNameValue, resolvePrincipal, resolveQuoteSchemePrincipal, summaryFromSnapshot,
} from './quote_scheme_service.mjs';

const principals = loadPrincipalMap(JSON.stringify([
  {api_key_sha256:apiKeyHash('user-key'),user_id:'u1',display_name:'张工',department_id:'d1',role:'USER'},
  {api_key_sha256:apiKeyHash('manager-key'),user_id:'m1',display_name:'李经理',department_id:'d1',role:'DEPARTMENT_MANAGER'},
  {api_key_sha256:apiKeyHash('admin-key'),user_id:'a1',display_name:'管理员',role:'ADMIN'},
]));

test('identity comes only from the authenticated API key',()=>{
  assert.deepEqual(resolvePrincipal({headers:{'x-ai-quote-key':'user-key'}},principals),
    {userId:'u1',displayName:'张工',departmentId:'d1',role:'USER'});
  assert.throws(()=>resolvePrincipal({headers:{'x-ai-quote-key':'unknown'},body:{user_id:'a1'}},principals),/身份尚未配置/);
});

test('shared and mapped keys cannot substitute for a name session',()=>{
  const request={headers:{'x-ai-quote-key':'shared-key'}};
  assert.throws(()=>resolveQuoteSchemePrincipal(request,principals,'shared-key'),{statusCode:401});
  assert.throws(()=>resolveQuoteSchemePrincipal({headers:{'x-ai-quote-key':'admin-key'}},principals),{statusCode:401});
  const sessions=createNameLoginService(),value=sessions.login({name:'张工'});
  const person=sessions.requireSession({headers:{authorization:'Bearer '+value.token}});
  assert.equal(withQuotePrincipal(person,()=>resolveQuoteSchemePrincipal(request,principals,'shared-key')),person);
});

test('operator name is required, normalized and bounded',()=>{
  assert.equal(operatorNameValue({operator_name:'  张\u0000工  '}),'张工');
  assert.throws(()=>operatorNameValue({operator_name:'  '}),/operator_name is required/);
  assert.throws(()=>operatorNameValue({operator_name:'x'.repeat(101)}),/100/);
});

test('ordinary, department manager and admin read scopes stay isolated',()=>{
  const user=resolvePrincipal({headers:{'x-ai-quote-key':'user-key'}},principals);
  const manager=resolvePrincipal({headers:{'x-ai-quote-key':'manager-key'}},principals);
  const admin=resolvePrincipal({headers:{'x-ai-quote-key':'admin-key'}},principals);
  assert.equal(canReadScheme(user,{creator_user_id:'u1',creator_department_id:'d1'}),true);
  assert.equal(canReadScheme(user,{creator_user_id:'u2',creator_department_id:'d1'}),false);
  assert.equal(canReadScheme(user,{creator_user_id:'u3',creator_department_id:'d2',shared:true}),true);
  assert.equal(canReadScheme(manager,{creator_user_id:'u2',creator_department_id:'d1'}),true);
  assert.equal(canReadScheme(manager,{creator_user_id:'u3',creator_department_id:'d2'}),false);
  assert.equal(canReadScheme(admin,{creator_user_id:'u3',creator_department_id:'d2'}),true);
});

test('direct detail reads carry the same server-side owner and share predicate',async()=>{
  const {service,calls}=serviceHarness();
  const user=resolvePrincipal({headers:{'x-ai-quote-key':'user-key'}},principals);
  await service.get(user,'BJ-20261016-000001');
  const sql=calls.at(-1);
  assert.match(sql,/s\.creator_user_id =/);
  assert.match(sql,/calc\.quote_scheme_share/);
  assert.doesNotMatch(sql,/WHERE[\s\S]+body\.user_id/);
});

test('status transitions reject overwrite-style edits',()=>{
  for(const pair of [['DRAFT','QUOTED'],['QUOTED','ARCHIVED'],['ARCHIVED','QUOTED'],['REVISING','QUOTED']]) assert.doesNotThrow(()=>assertTransition(...pair));
  for(const pair of [['QUOTED','DRAFT'],['VOID','DRAFT'],['ARCHIVED','DRAFT']]) assert.throws(()=>assertTransition(...pair),/invalid quote scheme status transition/);
});

test('snapshot summary uses frozen rows without recalculation',()=>{
  assert.deepEqual(summaryFromSnapshot({company:'测试公司',draft_items:[
    {product_code:'AE',specification:'600*300*800',quoted_total:1234.56},
    {product_code:'JP',specification:'700*400*900',quoted_total:2000},
  ]}),{company:'测试公司',productSummary:'AE 600*300*800；JP 700*400*900',amount:3234.56});
  assert.deepEqual(summaryFromSnapshot({company:'旧字段',draft_items:[{quoted_total:1}],scheme_summary:{
    company:'快照公司',product_summary:'AE 600×300×800',quoted_amount:888.88,
  }}),{company:'快照公司',productSummary:'AE 600×300×800',amount:888.88});
});

const sqlText=(value)=>value===null||value===undefined?'NULL':`'${String(value).replaceAll("'","''")}'`;
const serviceHarness=()=>{
  const calls=[];
  const service=createQuoteSchemeService({
    runPsql:async(sql)=>{calls.push(sql); return JSON.stringify({
      scheme_no:'BJ-20261016-000001',status:'DRAFT',version_no:1,lock_version:1,
      saved:true,changed:true,deleted:true,recorded:true,formal_success:false,
    });},
    sqlUnicodeText:sqlText,
    sqlNumber:(value)=>String(Number(value)),
  });
  return {service,calls};
};

test('create persists entered creator name separately from server identity and records copy source version',async()=>{
  const {service,calls}=serviceHarness();
  const principal={userId:'shared-client:abc',displayName:'共享报价客户端',departmentId:null,role:'ADMIN',identityMode:'SELF_REPORTED'};
  await service.create(principal,{operator_name:'王师傅',snapshot:{draft_items:[],scheme_summary:{company:'甲公司',quoted_amount:12}}},{sourceNo:'BJ-20261016-000099'});
  const sql=calls.at(-1);
  assert.match(sql,/creator_name_entered,creator_identity_mode/);
  assert.match(sql,/王师傅/);
  assert.match(sql,/共享报价客户端/);
  assert.match(sql,/SELECT version_no FROM calc\.quote_scheme/);
  assert.match(sql,/jsonb_build_object\('scheme_no',scheme_no,'version_no',version_no/);
  assert.match(sql,/AT TIME ZONE 'Asia\/Shanghai'/);
});

test('preview success is logged but cannot finalize a draft or require a snapshot',async()=>{
  const {service,calls}=serviceHarness();
  const principal={userId:'shared-client:abc',displayName:'共享报价客户端',departmentId:null,role:'ADMIN',identityMode:'SELF_REPORTED'};
  const result=await service.exportResult(principal,'BJ-20261016-000001',{
    operator_name:'王师傅',kind:'PREVIEW',succeeded:true,expected_version:1,
  });
  assert.equal(result.formal_success,false);
  assert.match(calls.at(-1),/'formal_success',FALSE/);
  assert.match(calls.at(-1),/PREVIEW/);
});

test('formal export freezes a server-canonical document snapshot only on the first finalization',async()=>{
  const {service,calls}=serviceHarness();
  const principal={userId:'shared-client:abc',displayName:'共享报价客户端',departmentId:null,role:'ADMIN',identityMode:'SELF_REPORTED'};
  await service.exportResult(principal,'BJ-20261016-000001',{
    operator_name:'王师傅',kind:'XLSX',succeeded:true,expected_version:1,
    snapshot:{draft_items:[],document:{scheme_no:'伪造编号',version_no:999,order_nature:'EXTERNAL'}},
  });
  const sql=calls.at(-1);
  assert.match(sql,/jsonb_build_object\('scheme_no',scheme_no,'version_no',version_no\)/);
  assert.match(sql,/t\.status IN \('DRAFT','REVISING'\)/);
  assert.match(sql,/JOIN snap saved_snapshot USING\(scheme_id\)/);
  assert.match(sql,/actor_name_snapshot,detail\)[\s\S]+王师傅/);
});

test('creator search targets the immutable entered-name snapshot',async()=>{
  const {service,calls}=serviceHarness();
  const principal={userId:'shared-client:abc',displayName:'共享报价客户端',departmentId:null,role:'ADMIN',identityMode:'SELF_REPORTED'};
  await service.list(principal,{creator:'王师傅',page:1,page_size:20});
  assert.match(calls.at(-1),/s\.creator_name_entered ILIKE/);
  assert.match(calls.at(-1),/creator_name',creator_name_entered/);
});

test('autosave enforces editable status and optimistic lock on the server',async()=>{
  const {service,calls}=serviceHarness();
  const principal={userId:'shared-client:abc',displayName:'共享报价客户端',departmentId:null,role:'ADMIN',identityMode:'SELF_REPORTED'};
  await service.save(principal,'BJ-20261016-000001',{
    operator_name:'李师傅',expected_version:7,
    creator_user_id:'forged-client-user',
    snapshot:{draft_items:[],document:{scheme_no:'forged-client-number'},scheme_summary:{quoted_amount:20}},
  });
  const sql=calls.at(-1);
  assert.match(sql,/s\.status IN \('DRAFT','REVISING'\)/);
  assert.match(sql,/s\.lock_version=7 FOR UPDATE/);
  assert.match(sql,/last_editor_name_snapshot='李师傅'/);
  assert.match(sql,/jsonb_build_object\('scheme_no',scheme_no,'version_no',version_no\)/);
  assert.doesNotMatch(sql,/creator_user_id='forged-client-user'/);
});

test('HTTP routes require name sessions; service authoritatively replaces entered names',async()=>{
  const source=await readFile(new URL('./server.mjs',import.meta.url),'utf8');
  assert.match(source,/nameSessions.requireSession\(req\)/);
  assert.match(source,/const principal = req.namePrincipal/);
  assert.match(source,/snapshot: source\.snapshot, operator_name: input\.operator_name/);
  assert.match(source,/schemeNo, input\.expected_version, input\.operator_name/);
  assert.match(source,/schemeNo, action, input\.expected_version, input\.operator_name/);
  assert.match(source,/searchParams\.get\('operator_name'\)/);
});

test('state transitions qualify unchanged timestamps against the updated table',async()=>{
  const {service,calls}=serviceHarness();
  const principal={userId:'local-admin',displayName:'管理员',departmentId:null,role:'ADMIN'};
  for(const action of ['archive','restore','void']) {
    await service.transition(principal,'BJ-20261016-000001',action,7,'测试操作人');
    const sql=calls.at(-1);
    assert.match(sql,/ELSE s\.archived_at END/);
    assert.match(sql,/ELSE s\.voided_at END/);
    assert.doesNotMatch(sql,/ELSE (?:archived_at|voided_at) END/);
    assert.match(sql,/s\.lock_version=7/);
    assert.match(sql,/INSERT INTO calc\.quote_scheme_audit/);
  }
});
