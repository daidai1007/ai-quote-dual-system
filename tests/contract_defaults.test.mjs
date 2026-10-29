import assert from 'node:assert/strict';
import test from 'node:test';
import {randomUUID} from 'node:crypto';
import {unzipSync,strFromU8,strToU8,zipSync} from 'fflate';
import {createContractService,DEFAULT_SELLER_NAME} from '../api/contract_service.mjs';
import {inspectContractTemplate,renderContractTemplate} from '../api/contract_document.mjs';
import {wordTemplate,excelTemplate,mapped,sampleValues,sampleQuote} from './helpers/contract_fixtures.mjs';

const q=value=>"'"+String(value).replaceAll("'","''")+"'";
const principal={userId:'local-default-user',displayName:'本机合同测试人员'};
function offline(format,withContact=false,deliveryMode=''){
 const source={scheme_id:1,scheme_no:'BJ-20261028-000777',version_no:1,customer_name:'本机测试客户',
  catalog_customer_code:'LOCAL-A',snapshot:{company:'本机测试客户',order_nature:'EXTERNAL',document:{order_nature:'EXTERNAL'},
   contract_quote_snapshot:{schema:1,items:[{quantity:2,quote_display:{name:'本机合成柜',quantity:2,unit:'台',unit_price:175,total:350}}]}}};
 let template=format==='docx'?wordTemplate():excelTemplate();
 if(withContact){
  const files=unzipSync(template);
  if(format==='docx')files['word/document.xml']=strToU8(strFromU8(files['word/document.xml']).replace('<w:tbl>',
   '<w:p><w:r><w:t>客户联系人：{{buyer_contact}}</w:t></w:r></w:p><w:tbl>'));
  else files['xl/worksheets/sheet1.xml']=strToU8(strFromU8(files['xl/worksheets/sheet1.xml']).replace('</sheetData>',
   '<row r="20"><c r="A20" t="inlineStr"><is><t>客户联系人</t></is></c><c r="B20" t="inlineStr"><is><t>{{buyer_contact}}</t></is></c></row></sheetData>'));
  template=Buffer.from(zipSync(files));
 }
 const deliveryText=deliveryMode==='placeholder'?'{{delivery_date}}':'交货日期：合同签订后30天内交付';
 if(deliveryMode){
  const files=unzipSync(template);
  if(format==='docx')files['word/document.xml']=strToU8(strFromU8(files['word/document.xml']).replace('<w:tbl>',
   `<w:p><w:r><w:t>${deliveryText}</w:t></w:r></w:p><w:tbl>`));
  else files['xl/worksheets/sheet1.xml']=strToU8(strFromU8(files['xl/worksheets/sheet1.xml']).replace('</sheetData>',
   `<row r="21"><c r="A21" t="inlineStr"><is><t>${deliveryText}</t></is></c></row></sheetData>`));
  template=Buffer.from(zipSync(files));
 }
 const inspection=inspectContractTemplate(template,format),mapping=mapped(inspection,format);
 if(deliveryMode==='literal')mapping.fields.push({source:'delivery_date',target:inspection.locations.find(loc=>loc.text===deliveryText).id,find:deliveryText});
 let file,fields,statements=[];
 const service=createContractService({sqlUnicodeText:q,runPsql:async sql=>{
  statements.push(sql);
  if(sql.includes("to_regclass('calc.contract_generation')"))return 'true';
  if(sql.includes("'snapshot',v.snapshot_payload"))return JSON.stringify(source);
  if(sql.includes('request_id=')&&sql.startsWith('SELECT'))return 'null';
  if(sql.includes('FROM calc.contract_template_version v JOIN calc.contract_template_group'))return JSON.stringify({
   customer_code:'LOCAL-A',enabled:true,field_mapping:mapping,content:template.toString('base64'),file_format:format,
   template_name:'本机模板',version_no:1,template_version_id:1});
  if(sql.includes('INSERT INTO calc.contract_generation(')){
   file=Buffer.from(sql.match(/decode\('([0-9a-f]+)','hex'\)/)[1],'hex');
   const text=sql.match(/'(\{[^\n]*"order_nature":"EXTERNAL"[^\n]*\})'::jsonb/);
   assert.ok(text,'immutable generation snapshot stored');
   fields=JSON.parse(text[1].replaceAll("''","'")).fields;
   return JSON.stringify({record_id:randomUUID(),record_no:'HT-LOCAL-001',generation_snapshot:{fields}});
  }
  throw Error('Unexpected offline query: '+sql.slice(0,160));
 }});
 return {service,file:()=>file,fields:()=>fields,statements};
}
const input=fields=>({scheme_no:'BJ-20261028-000777',version_no:1,template_version_id:1,method:'QUICK',request_id:randomUUID(),fields:{sign_date:'2026-10-28',...fields}});
for(const format of ['docx','xlsx']){
 test(`${format}: no delivery-date input preserves the original template clause even with a legacy mapping`,async()=>{
  const o=offline(format,false,'literal');
  await o.service.generate(principal,input({}));
  const xml=strFromU8(unzipSync(o.file())[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
  assert.ok(xml.includes('交货日期：合同签订后30天内交付'));
  assert.equal(o.fields().delivery_date,undefined);
  assert.ok(xml.includes(DEFAULT_SELLER_NAME));assert.ok(xml.includes('175'));
 });
 test(`${format}: an unresolved old delivery-date placeholder asks for template completion`,async()=>{
  await assert.rejects(offline(format,false,'placeholder').service.generate(principal,input({})),/请在客户合同模板中填写交货日期或交货条款/);
 });
 test(`${format}: mapped buyer contact may be missing or blank, and provided contact is preserved`,async()=>{
  for(const contact of [undefined,'','本机人工联系人']){
   const o=offline(format,true);
   await o.service.generate(principal,input(contact===undefined?{}:{buyer_contact:contact}));
   assert.equal(o.fields().buyer_contact,contact??'');
   const xml=strFromU8(unzipSync(o.file())[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
   assert.ok(!xml.includes('{{buyer_contact}}'));assert.ok(xml.includes('客户联系人'));
   if(contact)assert.ok(xml.includes(contact));
   assert.ok(xml.includes(DEFAULT_SELLER_NAME));assert.ok(xml.includes('175'));
  }
 });
 test(`${format}: omitted or empty customer number generates with default supplier and internal record`,async()=>{
  for(const fields of [{},{contract_no:''}]){
   const o=offline(format),result=await o.service.generate(principal,input(fields));
   assert.equal(result.record_no,'HT-LOCAL-001');
   assert.equal(o.fields().contract_no,'');assert.equal(o.fields().seller_name,DEFAULT_SELLER_NAME);
   const zip=unzipSync(o.file()),xml=strFromU8(zip[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
   assert.ok(xml.includes(DEFAULT_SELLER_NAME));assert.ok(!xml.includes('{{contract_no}}'));
   assert.ok(xml.includes('175'));
  }
 });
 test(`${format}: manually supplied supplier and customer number are preserved`,async()=>{
  const o=offline(format);await o.service.generate(principal,input({seller_name:'本机人工供方',contract_no:'CUSTOMER-001'}));
  assert.equal(o.fields().seller_name,'本机人工供方');assert.equal(o.fields().contract_no,'CUSTOMER-001');
  const xml=strFromU8(unzipSync(o.file())[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
  assert.ok(xml.includes('本机人工供方'));assert.ok(xml.includes('CUSTOMER-001'));
 });
 test(`${format}: missing required mapped fields still fail, and blank contract number renders`,()=>{
  const bytes=format==='docx'?wordTemplate():excelTemplate(),mapping=mapped(inspectContractTemplate(bytes,format),format);
  assert.doesNotThrow(()=>renderContractTemplate(bytes,format,mapping,{...sampleValues,contract_no:''},sampleQuote.items));
  assert.throws(()=>renderContractTemplate(bytes,format,mapping,{...sampleValues,contract_no:'',seller_name:''},sampleQuote.items),/供方名称/);
  assert.throws(()=>renderContractTemplate(bytes,format,mapping,{...sampleValues,contract_no:'',sign_date:''},sampleQuote.items),/签约日期/);
 });
}
test('optional customer number retains length and control-character checks',async()=>{
 for(const contract_no of ['x'.repeat(201),'BAD\nNUMBER'])await assert.rejects(
  offline('docx').service.generate(principal,input({contract_no})),/客户合同编号/);
});
