import assert from 'node:assert/strict';
import test from 'node:test';
import {apiKeyHash, assertTransition, canReadScheme, loadPrincipalMap, resolvePrincipal, summaryFromSnapshot} from './quote_scheme_service.mjs';

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

test('status transitions reject overwrite-style edits',()=>{
  for(const pair of [['DRAFT','QUOTED'],['QUOTED','ARCHIVED'],['ARCHIVED','QUOTED'],['REVISING','QUOTED']]) assert.doesNotThrow(()=>assertTransition(...pair));
  for(const pair of [['QUOTED','DRAFT'],['VOID','DRAFT'],['ARCHIVED','DRAFT']]) assert.throws(()=>assertTransition(...pair),/invalid quote scheme status transition/);
});

test('snapshot summary uses frozen rows without recalculation',()=>{
  assert.deepEqual(summaryFromSnapshot({company:'测试公司',draft_items:[
    {product_code:'AE',specification:'600*300*800',quoted_total:1234.56},
    {product_code:'JP',specification:'700*400*900',quoted_total:2000},
  ]}),{company:'测试公司',productSummary:'AE 600*300*800；JP 700*400*900',amount:3234.56});
});
