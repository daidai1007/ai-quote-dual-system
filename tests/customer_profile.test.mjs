import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {unzipSync,strFromU8} from 'fflate';
import {cleanCustomerProfile,customerProfileView} from '../api/customer_profile.mjs';
import {profileFixture,FIELDS,NAME,principal,input} from './helpers/customer_profile_fixture.mjs';

test('account, tax, phone and fax remain strings with every digit and leading zero intact',()=>{
 const p=cleanCustomerProfile(FIELDS);
 for(const key of ['buyer_phone','buyer_fax','buyer_bank_account','buyer_tax_no'])assert.equal(p[key],FIELDS[key]);
 for(const key of Object.keys(FIELDS))assert.throws(()=>cleanCustomerProfile({...FIELDS,[key]:123}),/文本/);
 assert.throws(()=>cleanCustomerProfile({...FIELDS,other:'x'}),/不支持/);
 assert.throws(()=>cleanCustomerProfile({...FIELDS,buyer_phone:'x\n'}),/格式/);
});
test('existing contact, phone and address columns work before the optional profile migration',()=>{
 const profile=customerProfileView({customer_name:NAME,customer_code:'LOCAL-A'},
  {contact_name:'本机联系人',contact_phone:'05710001',company_address:'本机旧地址'},1);
 assert.equal(profile.version,0);assert.equal(profile.fields.buyer_contact,'本机联系人');
 assert.equal(profile.fields.buyer_phone,'05710001');assert.equal(profile.fields.buyer_bank_account,'');
 const newer=customerProfileView({customer_name:NAME,customer_code:'LOCAL-A'},
  {company_address:'本机更新地址',contract_profile:{buyer_address:'本机旧地址'}},1);
 assert.equal(newer.fields.buyer_address,'本机更新地址');
});
test('authorized profile read and version-checked update use the quoted customer identity',async()=>{
 const o=profileFixture();const initial=await o.service.customerProfile(principal,input());
 assert.equal(initial.customer_name,NAME);assert.equal(initial.version,2);
 const changed={...FIELDS,buyer_agent:'本机新代理人'};
 const saved=await o.service.saveCustomerProfile(principal,{...input(),expected_version:2,customer_name:'FORGED',customer_code:'OTHER',fields:changed});
 assert.equal(saved.version,3);assert.equal(saved.fields.buyer_agent,'本机新代理人');assert.equal(saved.customer_code,'LOCAL-A');
 const sql=o.state.queries.find(s=>s.includes('UPDATE calc.ordering_company SET'));
 assert.ok(sql.includes("company_code='LOCAL-A'"));assert.ok(!sql.includes('FORGED'));assert.ok(sql.includes("'CUSTOMER_PROFILE'"));
 assert.ok(sql.includes('FROM allowed'));assert.ok(sql.includes("s.status<>'VOID'"));assert.ok(sql.includes('creator_user_id'));
 await assert.rejects(o.service.saveCustomerProfile(principal,{...input(),expected_version:2,fields:FIELDS}),/其他人修改/);
 assert.equal(o.state.row.contract_profile.buyer_agent,'本机新代理人');
 const partial=await o.service.saveCustomerProfile(principal,{...input(),expected_version:3,fields:{buyer_agent:'本机仅更新代理人'}});
 assert.equal(partial.fields.buyer_bank_account,FIELDS.buyer_bank_account);assert.equal(partial.fields.buyer_phone,FIELDS.buyer_phone);
});
test('new customer details can be created once without adding another customer table',async()=>{
 const o=profileFixture({recordExists:false});
 const saved=await o.service.saveCustomerProfile(principal,{...input(),expected_version:0,fields:FIELDS});
 assert.equal(saved.version,1);assert.equal(saved.fields.buyer_bank_account,FIELDS.buyer_bank_account);
});
test('old database or ambiguous customer blocks save clearly without altering existing information',async()=>{
 for(const config of [{ready:false},{matches:2}]){
  const o=profileFixture(config),before=structuredClone(o.state.row);
  await assert.rejects(o.service.saveCustomerProfile(principal,{...input(),expected_version:2,fields:FIELDS}),config.ready===false?/暂时无法保存/:/多份同名/);
  assert.deepEqual(o.state.row,before);assert.ok(!o.state.queries.some(s=>s.includes('UPDATE calc.ordering_company SET')));
 }
 await assert.rejects(profileFixture({denied:true}).service.customerProfile(principal,input()),/无权/);
 await assert.rejects(profileFixture().service.customerProfile({},input()),/姓名会话/);
});
for(const format of ['docx','xlsx'])test(`${format}: all buyer details fill automatically, manual overrides and historical copies remain stable`,async()=>{
 const o=profileFixture({format});
 const first=await o.service.generate(principal,input());
 assert.equal(first.generation_snapshot.fields.buyer_name,NAME);
 for(const [key,value] of Object.entries(FIELDS))assert.equal(first.generation_snapshot.fields[key],value);
 assert.equal(first.generation_snapshot.customer_profile_version,2);
 const xml=strFromU8(unzipSync(o.state.files[0])[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
 for(const value of Object.values(FIELDS).filter(Boolean))assert.ok(xml.includes(value));
 if(format==='xlsx')assert.match(xml,/<c[^>]*r="B28"[^>]*t="inlineStr"/);
 assert.ok(!xml.includes('{{buyer_'));assert.equal(first.generation_snapshot.quote.total,350);
 const frozen=structuredClone(first);
 o.state.row.contract_profile.buyer_bank_name='本机更新后的银行';o.state.row.contract_profile_version=3;
 const second=await o.service.generate(principal,input({buyer_address:'本次合同地址',buyer_phone:'',buyer_name:'FORGED'}));
 assert.equal(second.generation_snapshot.fields.buyer_bank_name,'本机更新后的银行');
 assert.equal(second.generation_snapshot.fields.buyer_address,'本次合同地址');assert.equal(second.generation_snapshot.fields.buyer_phone,'');
 assert.equal(second.generation_snapshot.fields.buyer_name,NAME);assert.deepEqual(first,frozen);
});
test('prepared migration only extends the existing customer table and contains no customer data',()=>{
 const sql=readFileSync(new URL('../database/migrations/customer_contract_profile_v1.sql',import.meta.url),'utf8');
 assert.ok(sql.includes('ALTER TABLE calc.ordering_company'));assert.ok(sql.includes('contract_profile_version'));
 assert.ok(!/CREATE TABLE|INSERT INTO|DROP TABLE|DELETE FROM/i.test(sql));
 const server=readFileSync(new URL('../api/server.mjs',import.meta.url),'utf8');
 assert.ok(server.includes("resource==='customer-profile-save'"));assert.ok(server.includes("resource==='customer-profile'"));
 assert.ok(readFileSync(new URL('../Dockerfile',import.meta.url),'utf8').includes('COPY api/customer_profile.mjs ./api/'));
 assert.ok(readFileSync(new URL('../.dockerignore',import.meta.url),'utf8').includes('!api/customer_profile.mjs'));
});
