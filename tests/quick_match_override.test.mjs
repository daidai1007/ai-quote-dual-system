import {quickQuotationAmount} from './quotation_layout_reader.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import ExcelJS from '@excel.js/exceljs';
import {checkedMatchSizes, createQuickMatchOverrideService, quickMatchOverrideSql} from '../api/quick_match_override.mjs';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {PRICING_BASIS, quickOrderLineBreakdown, moneySum} from '../quick_discount_rules.mjs';

const id = '11111111-1111-4111-8111-111111111111';
const size = (width_mm, depth_mm, height_mm) => ({width_mm, depth_mm, height_mm});
const environment = () => ({product_code:'JA', material_code:'SECC', quote_date:'2026-10-19',
  ...size(590,230,600), coating_type:'橘纹',ganged_cabinet_count:1,ganged_cabinets:[],
  quote_result:{quote_id:'test-order',formula_cost:{material_cost:100,auxiliary_cost:10,labor_cost:20,
    attachment_fee:10,spray_cost:30,management_fee:10.2,total_cost:180.2},
    quick_quote:{base_price:500,attachment_fee:20,total_cost:520}}});

function match(index, dimensions, price) {
  return {cabinet_index:index,base_price:price,dimension_distance:10,
    matched_experience:{quick_rule_id:index+10,product_code:'JA_SINGLE',
      reference_width_mm:dimensions.width_mm,reference_depth_mm:dimensions.depth_mm,
      reference_height_mm:dimensions.height_mm,manual_match:true}};
}

function harness(env=environment(), matches=[match(0,size(600,250,600),600)], failSave=false) {
  const queries=[], snapshots=new Map([[id,{environment:structuredClone(env),attachments:[]}]]);
  let persisted;
  const execute=async sql=>{
    queries.push(sql);
    if(sql.startsWith('SELECT jsonb_build_object(\'environment\''))
      return JSON.stringify({environment:env,quote_id:'test-order'});
    if(sql.startsWith('SELECT coalesce(jsonb_agg')) return JSON.stringify(matches);
    if(sql.startsWith('BEGIN;')) {
      if(failSave) throw new Error('simulated transaction rollback');
      const jsonValues=[...sql.matchAll(/decode\('([a-f0-9]+)','hex'\)/g)]
        .map(row=>Buffer.from(row[1],'hex').toString()).filter(text=>text.startsWith('{'));
      const next=JSON.parse(jsonValues[0]);
      snapshots.set(next.quote_line_id,{environment:next,attachments:[]});
      persisted=next;
      return JSON.stringify({quote_line_id:next.quote_line_id,quick_quote:next.quote_result.quick_quote});
    }
    // Confirmation/export snapshot lookup; the real hydration logic runs below.
    return JSON.stringify(Object.fromEntries(snapshots));
  };
  return {service:createQuickMatchOverrideService({runPsql:execute}), queries, snapshots, execute,
    get persisted(){return persisted;}};
}

test('manual lookup keeps the existing function and original perimeter ratio, never prices client dimensions as actual specs',()=>{
  const sql=quickMatchOverrideSql(environment(),[size(600,250,600)]);
  assert.match(sql,/calc\.match_quick_quote\(/);
  assert.match(sql,/COALESCE\(q\.quick_base_price,q\.quick_total_cost\) \* \(590\+230\+600\)/);
  assert.match(sql,/qm\.reference_width_mm\+qm\.reference_height_mm\+qm\.reference_depth_mm/);
  assert.match(sql,/600,600,250/); // Existing DB signature is width,height,depth.
  assert.match(sql,/qm\.dimension_distance=0/);
  assert.match(sql,/qm\.reference_width_mm=600 AND qm\.reference_depth_mm=250/);
  assert.doesNotMatch(sql,/\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER)\b/);
  assert.ok(sql.includes(Buffer.from('JA_SINGLE').toString('hex')));
});

test('success appends an immutable price snapshot; original costs, dimensions and old order stay untouched',async()=>{
  const env=environment(), before=structuredClone(env), h=harness(env);
  const result=await h.service({quote_line_id:id,matched_sizes:[size(600,250,600)],base_price:1});
  assert.notEqual(result.quote_line_id,id);
  assert.equal(result.source_quote_line_id,id);
  assert.equal(result.quick_quote.base_price,600);
  assert.equal(result.quick_quote.total_cost,620);
  assert.equal(result.quick_quote.match_method,'manual_dimension');
  assert.deepEqual(env,before);
  assert.deepEqual(h.persisted.quote_result.formula_cost,env.quote_result.formula_cost);
  assert.equal(h.persisted.width_mm,590);
  assert.equal(h.persisted.depth_mm,230);
  assert.match(h.queries.at(-1),/INSERT INTO calc\.attachment_quote_line/);
  assert.doesNotMatch(h.queries.at(-1),/calc\.attachment_selection/);
  assert.equal(h.persisted.quick_match_source_line_id,id);
  assert.doesNotMatch(h.queries.at(-1),/\b(?:UPDATE|DELETE|calculate_dual_quote)\b/);
});

test('no exact directory price is a safe failure, not another nearest match or a zero quote',async()=>{
  const h=harness(environment(),[]);
  await assert.rejects(h.service({quote_line_id:id,matched_sizes:[size(601,251,601)]}),/没有完全对应/);
  assert.equal(h.queries.length,2);
  assert.equal(h.persisted,undefined);
});

test('invalid shapes, numbers and SQL injection are rejected before database reads',async()=>{
  const h=harness();
  for(const input of [null,[],{}, {quote_line_id:'bad',matched_sizes:[size(1,2,3)]},
    {quote_line_id:id,matched_sizes:[size('1);DROP TABLE x',2,3)]},
    {quote_line_id:id,matched_sizes:[size(true,2,3)]},
    {quote_line_id:id,matched_sizes:[size(0,2,3)]},
    {quote_line_id:id,matched_sizes:Array(21).fill(size(1,2,3))}])
    await assert.rejects(h.service(input));
  assert.equal(h.queries.length,0);
  assert.deepEqual(checkedMatchSizes([size('600.5','300','1800')]),[size(600.5,300,1800)]);
});

test('ganged matching is per-child and all-or-nothing, with no multiplication by quantity',async()=>{
  const env=environment();
  env.ganged_cabinet_count=2;env.ganged_cabinets=[size(590,230,600),size(800,600,2000)];
  const sizes=[size(600,250,600),size(800,600,2000)];
  const matches=[match(0,sizes[0],600),match(1,sizes[1],1400)];
  const h=harness(env,matches);
  const result=await h.service({quote_line_id:id,matched_sizes:sizes,quantity:100});
  assert.equal(result.quick_quote.base_price,2000);
  assert.equal(result.quick_quote.total_cost,2020);
  assert.deepEqual(result.quick_quote.matched_experience.items,matches.map(row=>row.matched_experience));
  assert.equal(h.queries[1].match(/calc\.match_quick_quote/g).length,2);
  const partial=harness(env,[matches[0]]);
  await assert.rejects(partial.service({quote_line_id:id,matched_sizes:sizes}),/没有完全对应/);
  assert.equal(partial.queries.length,2);
  await assert.rejects(h.service({quote_line_id:id,matched_sizes:[sizes[0]]}),/数量/);
});

test('transaction failures never publish a new client price',async()=>{
  const h=harness(environment(),[match(0,size(600,250,600),600)],true);
  await assert.rejects(h.service({quote_line_id:id,matched_sizes:[size(600,250,600)]}),/rollback/);
  assert.equal(h.persisted,undefined);
  assert.equal(h.snapshots.size,1);
});

for (const count of [1,2]) test(`real ${count}-cabinet quote/export uses new price and keeps popup manual attachments, discount and freight`,async()=>{
  const env=environment(), sizes=[size(600,250,600)];
  if(count===2) {
    env.ganged_cabinet_count=2;
    env.ganged_cabinets=[size(590,230,600),size(800,600,2000)];
    sizes.push(size(800,600,2000));
  }
  const basePrice=count===2?2000:600;
  const matches=sizes.map((value,index)=>match(index,value,index?1400:600));
  const h=harness(env,matches), result=await h.service({quote_line_id:id,matched_sizes:sizes});
  const rows=[{custom:true,item_name:'人工附件',quantity:1,formula_amount:15,quick_amount:85,
    custom_amount_edited:true,quick_amount_override:85}];
  const quick={...result.quick_quote,attachment_fee:85,total_cost:basePrice+85};
  const line=quickOrderLineBreakdown({quote:quick,attachments:rows,discount:.8,cabinetQuantity:3,gangedCabinetCount:count,freightFee:12});
  const quoted={...env,quantity:3,quick_discount:.8,freight_fee:12,
    name:'人工匹配柜',specification:'590*230*600',attachment_contract:2,pricing_basis:PRICING_BASIS,
    quote_line_id:result.quote_line_id,attachments:structuredClone(rows),quick,
    quote_display:{attachment_source:'popup_v1',attachments:structuredClone(rows),name:'人工匹配柜',
      specification:'590*230*600',unit:'台',quantity:3,discount:.8,
      unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:line.attachmentFee,
      material_difference:0,quick_base_price:basePrice,quick_attachment_fee:85,quick_total_cost:basePrice+85}};
  const docs=createAttachmentService({runPsql:h.execute});
  const output=await docs.hydrateDocument({items:[quoted]});
  assert.equal(output.items[0].quick.base_price,basePrice);
  for(const [key,value] of Object.entries(rows[0])) assert.deepEqual(output.items[0].attachments[0][key],value);
  assert.equal(output.items[0].quote_display.total,line.lineTotal);
  assert.equal(output.items[0].quote_display.unit_price,line.equivalentUnitTotal);
  assert.equal(output.items[0].quote_line_id,result.quote_line_id);
  assert.equal(h.queries.filter(sql=>sql.startsWith('BEGIN;')).length,1,'document export must not reprice or persist again');
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'manual-matched-quote-'));
  try {
    const input=path.join(folder,'input.json'),file=path.join(folder,'quote.xlsx');
    await fs.writeFile(input,JSON.stringify({...output,quote_id:'MANUAL-MATCH-TEST',quote_date:'2026-10-19'}));
    await promisify(execFile)(process.execPath,[path.resolve('export_dual_quote_workbook.mjs'),input,file],{windowsHide:true});
    const workbook=new ExcelJS.Workbook();await workbook.xlsx.readFile(file);
    const sheet=workbook.getWorksheet('报价');
    assert.equal(sheet.getCell('F11').value,line.equivalentUnitTotal);
    assert.equal(quickQuotationAmount(sheet.getCell('G11')),line.lineTotal);
  } finally { await fs.rm(folder,{recursive:true,force:true}); }
});
