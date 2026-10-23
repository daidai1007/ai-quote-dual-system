import test from 'node:test';
import assert from 'node:assert/strict';
import {createNameLoginService,normalizeName,nameUserId,ALL_QUOTE_NAMES} from '../api/name_login_service.mjs';

test('all valid names enter; only the three exact names see ALL',()=>{
  const service=createNameLoginService();
  for(const name of ALL_QUOTE_NAMES){const p=service.login({name}).person;assert.equal(p.scope,'ALL');assert.equal(p.can_manage_all_quotes,true);}
  for(const name of ['张三','新人员','姜艳娟2','翟晓峰管理员','戴晨丽1']){const p=service.login({name}).person;assert.equal(p.scope,'OWN');assert.equal(p.can_manage_all_quotes,false);}
  assert.equal(normalizeName('  张三  '),'张三');
  assert.equal(nameUserId(' 张三 '),nameUserId('张三'));
  for(const name of ['',null,42,'x'.repeat(101),'张\u0000三','张\n三','\u200b张三'])assert.throws(()=>service.login({name}));
  assert.throws(()=>service.login({name:'张三',role:'ADMIN'}));
  assert.throws(()=>service.login({name:'张三',can_manage_all_quotes:true}));
});
test('stable IDs, random tokens, expiry, revocation and bounded sessions',()=>{
  let now=1000;const service=createNameLoginService({now:()=>now,ttlMs:10,maxSessions:3});
  const a=service.login({name:'张三'}),b=service.login({name:'张三'});
  assert.equal(a.person.user_id,b.person.user_id);assert.notEqual(a.token,b.token);
  assert.equal(createNameLoginService().login({name:'张三'}).person.user_id,a.person.user_id);
  const req={headers:{authorization:'Bearer '+a.token}};
  assert.equal(service.requireSession(req).displayName,'张三');service.logout(req);assert.throws(()=>service.requireSession(req));
  assert.throws(()=>service.requireSession({headers:{'x-ai-quote-key':'old-shared'}}));
  assert.throws(()=>service.requireSession({headers:{authorization:'Bearer '+a.person.user_id}}));
  now+=11;assert.throws(()=>service.requireSession({headers:{authorization:'Bearer '+b.token}}));
  const small=createNameLoginService({maxSessions:1});small.login({name:'一'});assert.throws(()=>small.login({name:'二'}),{statusCode:503});
});
