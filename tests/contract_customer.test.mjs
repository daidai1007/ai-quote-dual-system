import assert from 'node:assert/strict';
import test from 'node:test';
import {contractCustomer,contractCustomerNameSql} from '../api/contract_customer.mjs';
import {createContractService} from '../api/contract_service.mjs';
import {inspectContractTemplate} from '../api/contract_document.mjs';
import {wordTemplate,excelTemplate,mapped} from './helpers/contract_fixtures.mjs';
import {unzipSync,strFromU8} from 'fflate';

const NAME='本机正式报价测试客户甲';
const row={scheme_no:'BJ-20261028-000777',version_no:2,customer_name:NAME,
  snapshot_customer_code:'WRONG',snapshot_customer_name:'本机旧客户'};
const principal={userId:'local-contract-user',displayName:'本机合同测试人员',scope:'OWN'};
const q=value=>"'"+String(value).replaceAll("'","''")+"'";

test('quotation buyer name controls matching; stale unrelated code is never reused',()=>{
 const buyer=contractCustomer(row);
 assert.equal(buyer.customer_name,NAME);assert.match(buyer.customer_code,/^contract-name:[0-9a-f]{64}$/);
 assert.notEqual(buyer.customer_code,'WRONG');assert.equal(buyer.customer_code,contractCustomer({...row,snapshot_customer_code:null}).customer_code);
 assert.equal(buyer.snapshot_customer_name,undefined);
 assert.notEqual(buyer.customer_code,contractCustomer({...row,customer_name:NAME+'乙'}).customer_code);
});
test('unique catalogue match and consistent existing references remain compatible',()=>{
 assert.equal(contractCustomer({...row,catalog_customer_code:'LOCAL-A'}).customer_code,'LOCAL-A');
 assert.equal(contractCustomer({...row,snapshot_customer_name:NAME,snapshot_customer_code:'VALID'}).customer_code,'VALID');
 assert.equal(contractCustomer({...row,customer_name:' '+NAME+' '}).customer_name,NAME);
});
test('blank buyer or placeholder is never silently assigned to another customer',()=>{
 for(const customer_name of ['', '请选择客户',null])assert.throws(()=>contractCustomer({...row,customer_name}),/未填写客户名称/);
 const none=contractCustomer({...row,customer_name:'无'});
 assert.equal(none.customer_name,'无');assert.match(none.customer_code,/^contract-name:/);
 assert.notEqual(none.customer_code,'WRONG');
});
test('formal sheet company precedes summary and legacy fallback; analysis name never overwrites it',()=>{
 const sql=contractCustomerNameSql();
 const names=["v.snapshot_payload->>'company'","v.snapshot_payload#>>'{scheme_summary,company}'",'s.company_name'];
 for(let i=1;i<names.length;i++)assert.ok(sql.indexOf(names[i-1])<sql.indexOf(names[i]));
 assert.match(sql,/NOT IN \('','未选择客户'/);
 assert.ok(!sql.includes("'无'"),'literal quotation buyer 无 must win over stale summary/catalogue names');
 assert.ok(!sql.includes('analysis_customer'));
});

function offline({format='docx', denied=false, internal=false, templateCode, buyerName=NAME}={}) {
 const statements=[];let generated;
 const bytes=format==='docx'?wordTemplate():excelTemplate();
 const mapping=mapped(inspectContractTemplate(bytes,format),format);
 const snapshot={company:buyerName,scheme_summary:{company:'本机旧汇总客户'},analysis_customer:{customer_name:'本机旧客户',customer_code:'WRONG'},
   order_nature:internal?'INTERNAL':'EXTERNAL',document:{order_nature:internal?'INTERNAL':'EXTERNAL'},
   contract_quote_snapshot:{schema:1,items:[{name:'本机合成柜',quantity:2,formula:{},
     quote_display:{name:'本机合成柜',quantity:2,unit:'台',unit_price:175,total:350,
       formula_unit_price:100,formula_total:200,specification:'800*600*1800'}}]}};
 const buyerRow={...row,customer_name:buyerName};
 const source={...buyerRow,scheme_id:77,snapshot};
 const service=createContractService({sqlUnicodeText:q,runPsql:async sql=>{
  statements.push(sql);
  if(sql.includes("to_regclass('calc.ledger_contract_generation')"))return 'false';
  if(sql.includes("to_regclass('calc.contract_generation')"))return 'true';
  if(sql.includes("'snapshot',v.snapshot_payload"))return JSON.stringify(denied?null:source);
  if(sql.includes("'product_summary',s.product_summary"))return JSON.stringify([buyerRow]);
  if(sql.includes('request_id=')&&sql.startsWith('SELECT'))return 'null';
  if(sql.includes('FROM calc.contract_template_version v JOIN calc.contract_template_group'))return JSON.stringify({
    customer_code:templateCode??contractCustomer(buyerRow).customer_code,enabled:true,field_mapping:mapping,content:bytes.toString('base64'),
    file_format:format,template_name:'本机合同模板',version_no:1,template_version_id:1});
  if(sql.includes('INSERT INTO calc.contract_generation(')){
   const blob=sql.match(/decode\('([a-f0-9]+)','hex'\)/);
   assert.ok(blob,'actual rendered Office bytes');
   generated=Buffer.from(blob[1],'hex');
   assert.ok(sql.includes(q(buyerName)));assert.ok(!sql.includes(q('FORGED')));
   return JSON.stringify({record_id:'77777777-7777-4777-8777-777777777777',generation_snapshot:{fields:{buyer_name:buyerName}}});
  }
  if(sql.includes('FROM calc.contract_template_group g JOIN LATERAL')||sql.includes('FROM calc.contract_generation_draft'))return '[]';
  if(sql.includes('count(*) FROM calc.contract_generation'))return '0';
  if(sql.includes('FROM calc.contract_generation r JOIN'))return '[]';
  throw Error('Unexpected offline query: '+sql.slice(0,150));
 }});
 return {service,statements,bytes:()=>generated};
}

for(const buyerName of [NAME,'无'])test(`service uses ${buyerName} for quote read and bootstrap without a catalogue entry`,async()=>{
 const {service,statements}=offline({buyerName});
 const quote=await service.quote(principal,{scheme_no:row.scheme_no,version_no:2,method:'QUICK'});
 assert.equal(quote.customer_name,buyerName);assert.equal(quote.quote.total,350);
 const boot=await service.bootstrap(principal);assert.equal(boot.sources[0].customer_code,quote.customer_code);
 assert.equal(boot.sources[0].customer_name,buyerName);
 for(const sql of statements.filter(s=>s.includes('JOIN calc.quote_scheme_version'))){
  assert.ok(sql.includes(contractCustomerNameSql()));assert.match(sql,/s.status<>'VOID'/);
  assert.match(sql,/creator_user_id/);
 }
 assert.ok(statements.every(s=>s.startsWith('SELECT')),'reads never mutate customers or quotes');
});
for(const buyerName of [NAME,'无'])for(const format of ['docx','xlsx'])for(const method of ['QUICK','FORMULA'])test(`actual ${format} ${method} contract takes ${buyerName} from formal quote and preserves frozen prices`,async()=>{
 const o=offline({format,buyerName});
 const response=await o.service.generate(principal,{scheme_no:row.scheme_no,version_no:2,template_version_id:1,method,
  request_id:'77777777-7777-4777-8777-777777777777',fields:{contract_no:'LOCAL-CONTRACT',seller_name:'本机供方',sign_date:'2026-10-28',buyer_name:'FORGED'}});
 assert.equal(response.generation_snapshot.fields.buyer_name,buyerName);
 const zip=unzipSync(o.bytes());
 const document=strFromU8(zip[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
 assert.ok(document.includes(buyerName));assert.ok(!document.includes('FORGED'));
 assert.ok(document.includes(method==='QUICK'?'175':'100'));
 assert.ok(o.statements.every(sql=>!/(?:UPDATE|DELETE FROM|INSERT INTO) calc\.(?:ordering_company|quote_scheme\b|quote_scheme_snapshot|quote_scheme_version)/.test(sql)));
});
test('formal-source permissions, external-only gate and cross-customer template validation remain active',async()=>{
 await assert.rejects(offline({denied:true}).service.quote(principal,{scheme_no:row.scheme_no,version_no:2,method:'QUICK'}),/无权/);
 await assert.rejects(offline({internal:true}).service.quote(principal,{scheme_no:row.scheme_no,version_no:2,method:'QUICK'}),/仅外部/);
 await assert.rejects(offline().service.quote({},{scheme_no:row.scheme_no,version_no:2,method:'QUICK'}),/姓名会话/);
 await assert.rejects(offline({templateCode:'OTHER'}).service.generate(principal,{scheme_no:row.scheme_no,version_no:2,template_version_id:1,method:'QUICK',
  request_id:'77777777-7777-4777-8777-777777777777',fields:{contract_no:'LOCAL'}}),/客户模板与正式报价客户不一致/);
});
