import test from 'node:test';
import assert from 'node:assert/strict';
import {createContractTemplatePolicy} from '../api/contract_template_policy.mjs';
const customer={customer_code:'CURRENT',customer_name:'本机当前需方'};
const template={customer_code:'OTHER',customer_name:'本机模板需方',enabled:true,field_mapping:{fields:[{source:'buyer_name'}]}};
const q=value=>"'"+String(value).replaceAll("'","''")+"'";
test('matching templates retain existing behavior without fallback queries',async()=>{
 const policy=createContractTemplatePolicy({q,query:async()=>assert.fail('matching template needs no fallback query')});
 assert.equal(await policy.validate(customer,{...template,customer_code:'CURRENT'}),false);
});
test('borrowed templates work only when current customer has no configured enabled template',async()=>{
 const policy=createContractTemplatePolicy({q,query:async()=>false});
 assert.equal(await policy.validate(customer,template),true);
 await assert.rejects(createContractTemplatePolicy({q,query:async()=>true}).validate(customer,template),/已有可用模板/);
});
test('borrowing still rejects disabled, unconfigured and unmapped buyer fields',async()=>{
 const policy=createContractTemplatePolicy({q,query:async()=>false});
 for(const value of [{...template,enabled:false},{...template,field_mapping:null},{...template,field_mapping:{fields:[]}}])
   await assert.rejects(policy.validate(customer,value),e=>e.statusCode===400);
});
test('final SQL gate repeats matching-customer check and ledger uses its own customer name',()=>{
 const policy=createContractTemplatePolicy({q,query:async()=>false});
 assert.match(policy.allowedSql(customer),/g.customer_code='CURRENT'.*OR NOT EXISTS/s);
 assert.match(policy.allowedSql(customer),/own_g.enabled AND own_v.field_mapping IS NOT NULL/);
 const ledger=policy.allowedSql({...customer,customer_key:'SYNTHETIC'});
 assert.match(ledger,/btrim\(g.customer_name\)='本机当前需方'/);
 assert.ok(!ledger.includes('LIMIT 1'),'ledger drafts may use older configured versions');
});
