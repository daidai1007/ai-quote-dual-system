import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {canMaintainAttachments,normalizeMaintenance,createAttachmentMaintenance} from '../api/attachment_maintenance.mjs';
import {nameUserId,createNameLoginService} from '../api/name_login_service.mjs';
const person=name=>({displayName:name,userId:nameUserId(name),identityMode:'NAME_ONLY'});
const create=()=>({action:'CREATE',request_id:randomUUID(),reason:'本地测试',products:['JP_SINGLE'],
 item:{item_name:'本地测试附件',model_code:'LOCAL-1',unit:'件',category_level1:'其他附件',quick_face_price:'85.123456789'},cost_rules:[{fixed_cost:'48'}]});
for(const name of ['戴晨丽','姜艳娟','翟晓峰','吕芝森'])test(`${name} has separate attachment capability`,()=>assert.equal(canMaintainAttachments(person(name)),true));
test('ordinary/fabricated identity cannot manage; 吕芝森 quote scope is unchanged',()=>{
 assert.equal(canMaintainAttachments({...person('普通人员'),can_manage_all_quotes:true}),false);
 assert.equal(canMaintainAttachments({displayName:'戴晨丽',userId:'invented',identityMode:'NAME_ONLY'}),false);
 const session=createNameLoginService().login({name:'吕芝森'});assert.equal(session.person.can_manage_all_quotes,false);assert.equal(session.person.scope,'OWN');
});
test('fixed input preserves decimal precision and explicit zero',()=>{
 const input=create();assert.equal(normalizeMaintenance(input).item.quick_face_price,'85.123456789');
 input.cost_rules[0].fixed_cost=0;assert.equal(normalizeMaintenance(input).cost_rules[0].fixed_cost,'0');
});
for(const bad of ['',null,true,-1,'NaN','Infinity','0;DROP TABLE x','-0.01'])test(`invalid cost rejected ${String(bad)}`,()=>{
 const input=create();input.cost_rules[0].fixed_cost=bad;assert.throws(()=>normalizeMaintenance(input));
});
test('formula mutation, forged actor, invalid product, duplicate rules rejected',()=>{
 const a=create();a.cost_rules[0].formulas={};assert.throws(()=>normalizeMaintenance(a));
 const b=create();b.actor_name='戴晨丽';assert.throws(()=>normalizeMaintenance(b));
 const c=create();c.products=['UNKNOWN'];assert.throws(()=>normalizeMaintenance(c));
 const d={...create(),action:'EDIT',attachment_price_id:1,cost_rules:[{rule_id:1,fixed_cost:2},{rule_id:1,fixed_cost:3}]};assert.throws(()=>normalizeMaintenance(d));
});
test('permissions checked before database; absent migration gives actionable error',async()=>{
 let calls=0;const service=createAttachmentMaintenance({runPsql:async()=>{calls++;return 'false';}});
 await assert.rejects(service.list(person('普通人员')),e=>e.statusCode===403);assert.equal(calls,0);
 await assert.rejects(service.save(person('普通人员'),create()),e=>e.statusCode===403);assert.equal(calls,0);
 await assert.rejects(service.list(person('戴晨丽')),e=>e.statusCode===503);assert.equal(calls,1);
});
test('query encodes SQL metacharacters as data, does not interpolate names',async()=>{
 let last='';const service=createAttachmentMaintenance({runPsql:async sql=>{last=sql;return sql.includes('to_regprocedure')?'true':'{"saved":true}';}});
 const input=create();input.item.item_name="本地');DROP TABLE x;--";await service.save(person('戴晨丽'),input);
 assert.ok(!last.includes(input.item.item_name));assert.match(last,/decode\('[a-f0-9]+'/);
});
