// Pure in-memory PostgreSQL integration. Never connects to an existing database.
// AI_QUOTE_PGLITE_MODULE points to an isolated test-only PGlite installation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import ExcelJS from '@excel.js/exceljs';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {jcQuickMatchSql} from '../api/jc_quick_match.mjs';
import {quickMatchOverrideSql} from '../api/quick_match_override.mjs';
import {PRICING_BASIS,quickOrderLineBreakdown} from '../quick_discount_rules.mjs';
import {quickQuotationAmount} from './quotation_layout_reader.mjs';

if(!process.env.AI_QUOTE_PGLITE_MODULE)throw new Error('Set AI_QUOTE_PGLITE_MODULE to the test-only PGlite module');
const {PGlite}=await import(pathToFileURL(process.env.AI_QUOTE_PGLITE_MODULE));
const db=new PGlite();
await db.exec(`CREATE SCHEMA calc;CREATE TABLE calc.quick_quote_experience (
 quick_rule_id bigint,product_code text,model_code text,material_code text,
 reference_width_mm numeric,reference_height_mm numeric,reference_depth_mm numeric,
 min_width_mm numeric,max_width_mm numeric,min_height_mm numeric,max_height_mm numeric,min_depth_mm numeric,max_depth_mm numeric,
 quick_material_cost numeric,quick_auxiliary_cost numeric,quick_labor_cost numeric,quick_attachment_fee numeric,
 quick_spray_cost numeric,quick_management_fee numeric,quick_base_price numeric,quick_total_cost numeric,
 effective_from date,effective_to date,is_active boolean,source_file text,source_sheet text,source_row_no integer);`);
const cases=JSON.parse(fs.readFileSync(new URL('./fixtures/jc_profiles.json',import.meta.url)));
for(const [i,row] of cases.entries())await db.query(`INSERT INTO calc.quick_quote_experience
 (quick_rule_id,product_code,model_code,material_code,reference_width_mm,reference_height_mm,reference_depth_mm,
 quick_material_cost,quick_auxiliary_cost,quick_labor_cost,quick_attachment_fee,quick_spray_cost,quick_management_fee,
 quick_base_price,quick_total_cost,effective_from,is_active,source_sheet)
 VALUES ($1,'JC_EXP',$2,'SECC',600,1600,$3,10,20,30,0,40,50,$4,$4,'2026-01-01',true,$5)`,
 [i+1,row.model,row.depth,(i+1)*1000,row.profile==='STANDARD'?'豪华型旧表名':'标配型旧表名']);
const input={product_code:'JC_EXP',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:600,quote_date:'2026-11-26'};
const query=async value=>(await db.query(`SELECT * FROM ${jcQuickMatchSql(value)} matched`)).rows;
test.after(async()=>db.close());
for(const [i,row]of cases.entries())test(`SQL: ${row.model} selects the correct face row despite misleading sheet names`,async()=>{
 const [result]=await query({...input,variant_code:row.profile,depth_mm:row.depth});
 assert.equal(result.model_code,row.model);assert.equal(Number(result.quick_total_cost),(i+1)*1000);
});
test('SQL: same-profile filtering precedes dimension ranking and scales nonstandard sizes',async()=>{
 const [result]=await query({...input,variant_code:'LUXURY',width_mm:650});
 assert.equal(result.model_code,'JC601660-2');
 assert.ok(Math.abs(Number(result.quick_total_cost)-3000*2850/2800)<.000001);
});
test('SQL: missing, inactive, expired or different-material records do not borrow the other profile',async()=>{
 await db.exec(`UPDATE calc.quick_quote_experience SET is_active=false WHERE model_code LIKE '%-2'`);
 assert.deepEqual(await query({...input,variant_code:'LUXURY'}),[]);
 await db.exec(`UPDATE calc.quick_quote_experience SET is_active=true,effective_to='2026-01-02' WHERE model_code LIKE '%-2'`);
 assert.deepEqual(await query({...input,variant_code:'LUXURY'}),[]);
 assert.deepEqual(await query({...input,variant_code:'STANDARD',material_code:'SUS316'}),[]);
 await db.exec(`UPDATE calc.quick_quote_experience SET effective_to=null WHERE model_code LIKE '%-2'`);
});
test('SQL: manual catalogue rematch and unequal ganged children retain the selected configuration',async()=>{
 for(const profile of ['STANDARD','LUXURY']){
  const sizes=[{width_mm:600,height_mm:1600,depth_mm:600},{width_mm:600,height_mm:1600,depth_mm:800}];
  const env={...input,variant_code:profile,ganged_cabinet_count:2,
    ganged_cabinets:sizes.map(row=>({...row,variant_code:'SINGLE'})),
    quote_result:{quick_quote:{matched_experience:{items:[{product_code:'JC_EXP'},{product_code:'JC_EXP'}]}}}};
  const output=(await db.query(quickMatchOverrideSql(env,sizes))).rows[0];
  const rows=Object.values(output)[0];
  assert.deepEqual(rows.map(row=>row.matched_experience.model_code),cases.filter(row=>row.profile===profile).map(row=>row.model));
  assert.deepEqual(rows.map(row=>Number(row.base_price)),profile==='STANDARD'?[1000,2000]:[3000,4000]);
 }
});
test('SQL face results retain their type and amount through real Excel export',async()=>{
 const items=[];
 for(const row of cases.filter(row=>row.depth===600)){
  const [matched]=await query({...input,variant_code:row.profile});
  const base=Number(matched.quick_total_cost),quick={base_price:base,attachment_fee:0,total_cost:base};
  const amount=quickOrderLineBreakdown({quote:quick,attachments:[],discount:.5,cabinetQuantity:2,gangedCabinetCount:1,freightFee:12});
  items.push({...input,variant_code:row.profile,model_code:row.model,name:row.label,product_family:row.label,
   specification:'600*600*1600',quantity:2,quick_discount:.5,freight_fee:12,attachments:[],quick,
   formula:{material_cost:100,auxiliary_cost:10,labor_cost:20,spray_cost:30,attachment_fee:0,management_fee:10,total_cost:170},
   pricing_basis:PRICING_BASIS,attachment_contract:2,
   quote_display:{attachment_source:'popup_v1',attachments:[],name:row.label,specification:'600*600*1600',
    unit:'台',quantity:2,discount:.5,unit_price:amount.equivalentUnitTotal,total:amount.lineTotal,
    attachment_face_price:0,material_difference:0,quick_base_price:base,quick_attachment_fee:0,quick_total_cost:base}});
 }
 const folder=process.env.AI_QUOTE_JC_QA_OUTPUT||await fsp.mkdtemp(path.join(os.tmpdir(),'jc-export-'));
 await fsp.mkdir(folder,{recursive:true});
 try{
  const source=path.join(folder,'jc-export.json'),file=path.join(folder,'jc-export.xlsx');
  await fsp.writeFile(source,JSON.stringify({quote_id:'JC-OFFLINE',quote_date:'2026-11-26',items}));
  await promisify(execFile)(process.execPath,[path.resolve('export_dual_quote_workbook.mjs'),source,file],{windowsHide:true});
  const workbook=new ExcelJS.Workbook();await workbook.xlsx.readFile(file);
  const sheet=workbook.getWorksheet('报价');
  for(const [index,item]of items.entries()){
   const row=11+index;
   assert.equal(sheet.getCell(`B${row}`).value,item.name);
   assert.equal(sheet.getCell(`F${row}`).value.result,item.quote_display.unit_price);
   assert.equal(quickQuotationAmount(sheet.getCell(`G${row}`)),item.quote_display.total);
  }
  assert(workbook.getWorksheet('成本'));
 }finally{if(!process.env.AI_QUOTE_JC_QA_OUTPUT)await fsp.rm(folder,{recursive:true,force:true});}
});
