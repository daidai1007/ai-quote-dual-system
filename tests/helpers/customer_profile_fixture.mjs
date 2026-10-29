import {randomUUID} from 'node:crypto';
import {unzipSync,strFromU8,strToU8,zipSync} from 'fflate';
import {createContractService} from '../../api/contract_service.mjs';
import {CUSTOMER_PROFILE_FIELDS} from '../../api/customer_profile.mjs';
import {inspectContractTemplate} from '../../api/contract_document.mjs';
import {wordTemplate,excelTemplate,mapped} from './contract_fixtures.mjs';
export const NAME='本机需方资料客户';
export const FIELDS={buyer_address:'本机测试地址',buyer_phone:'057100000001',buyer_fax:'057100000002',buyer_contact:'',
 buyer_representative:'本机需方代表',buyer_agent:'本机代理人',buyer_bank_name:'本机测试银行',buyer_bank_account:'9000000000000000001',buyer_tax_no:'T00000000000000001'};
export const principal={userId:'local-profile-user',displayName:'本机资料维护人员'};
export const input=(fields={})=>({scheme_no:'BJ-20261028-000777',version_no:1,template_version_id:1,method:'QUICK',request_id:randomUUID(),fields:{sign_date:'2026-10-28',...fields}});
const q=value=>"'"+String(value).replaceAll("'","''")+"'";
export function profileFixture({format='docx',recordExists=true,ready=true,denied=false,matches=1}={}){
 const state={row:recordExists?{company_code:'LOCAL-A',company_name:NAME,contract_profile:{...FIELDS},contract_profile_version:2}:null,ready,records:[],queries:[],files:[]};
 const files=unzipSync(format==='docx'?wordTemplate():excelTemplate());
 if(format==='docx')files['word/document.xml']=strToU8(strFromU8(files['word/document.xml']).replace('<w:tbl>',
  Object.entries(CUSTOMER_PROFILE_FIELDS).map(([key,label])=>`<w:p><w:r><w:t>${label}：{{${key}}}</w:t></w:r></w:p>`).join('')+'<w:tbl>'));
 else files['xl/worksheets/sheet1.xml']=strToU8(strFromU8(files['xl/worksheets/sheet1.xml']).replace('</sheetData>',
  Object.entries(CUSTOMER_PROFILE_FIELDS).map(([key,label],i)=>`<row r="${21+i}"><c r="A${21+i}" t="inlineStr"><is><t>${label}</t></is></c><c r="B${21+i}" t="inlineStr"><is><t>{{${key}}}</t></is></c></row>`).join('')+'</sheetData>'));
 const template=Buffer.from(zipSync(files)),mapping=mapped(inspectContractTemplate(template,format),format);
 const source=()=>({scheme_id:1,scheme_no:'BJ-20261028-000777',version_no:1,customer_name:NAME,catalog_customer_code:'LOCAL-A',
  customer_profile_matches:recordExists?matches:0,customer_profile_record:state.row,snapshot:{company:NAME,document:{order_nature:'EXTERNAL'},
   contract_quote_snapshot:{schema:1,items:[{quantity:2,quote_display:{name:'本机合成柜',quantity:2,unit:'台',unit_price:175,total:350}}]}}});
 const service=createContractService({sqlUnicodeText:q,runPsql:async sql=>{
  state.queries.push(sql);
  if(sql.includes('information_schema.columns'))return JSON.stringify(state.ready);
  if(sql.includes("to_regclass('calc.contract_generation')"))return 'true';
  if(sql.includes("'snapshot',v.snapshot_payload"))return JSON.stringify(denied?null:source());
  if(sql.includes('UPDATE calc.ordering_company SET')){
   const expected=Number(sql.match(/AND contract_profile_version=(\d+)/)[1]);
   if(expected!==(state.row?.contract_profile_version||0))return 'null';
   const profile=JSON.parse(sql.match(/contract_profile='((?:''|[^'])*)'::jsonb/)[1].replaceAll("''","'"));
   state.row={company_code:'LOCAL-A',company_name:NAME,contract_profile:profile,contract_profile_version:expected+1,
    contact_name:sql.match(/SET contact_name='((?:''|[^'])*)'/)[1].replaceAll("''","'"),
    contact_phone:sql.match(/contact_phone='((?:''|[^'])*)'/)[1].replaceAll("''","'"),
    company_address:sql.match(/company_address='((?:''|[^'])*)'/)[1].replaceAll("''","'")};
   return JSON.stringify(state.row);
  }
  if(sql.includes('request_id=')&&sql.startsWith('SELECT'))return 'null';
  if(sql.includes('FROM calc.contract_template_version v JOIN calc.contract_template_group'))return JSON.stringify({
   customer_code:'LOCAL-A',enabled:true,field_mapping:mapping,content:template.toString('base64'),file_format:format,template_name:'本机需方模板',version_no:1,template_version_id:1});
  if(sql.includes('INSERT INTO calc.contract_generation(')){
   const snapshot=JSON.parse(sql.match(/'(\{[^\n]*"order_nature":"EXTERNAL"[^\n]*\})'::jsonb/)[1].replaceAll("''","'"));
   const file=Buffer.from(sql.match(/decode\('([0-9a-f]+)','hex'\)/)[1],'hex');state.files.push(file);
   const result={record_id:randomUUID(),record_no:'HT-LOCAL-'+(state.records.length+1),generation_snapshot:snapshot};state.records.push(result);
   return JSON.stringify(result);
  }
  throw Error('Unexpected offline query: '+sql.slice(0,140));
 }});
 return {service,state};
}
