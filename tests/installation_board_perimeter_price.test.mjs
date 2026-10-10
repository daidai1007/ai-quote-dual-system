// Offline only: price extension, guarded SQL snapshot and export hydration.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { calculateAttachment } from '../api/attachment_cost.mjs';
import { round } from '../api/attachment_formula.mjs';
import { createAttachmentService, applyAttachmentTotals } from '../api/attachment_service.mjs';

const board = { attachment_price_id:1, data_version:'offline', item_name:'安装板',
  category_level1:'安装板', category_level2:'', unit:'件', price:363.51,
  width_mm:600, height_mm:1800, depth_mm:600, rules:[] };
const environment = { product_code:'JP', material_code:'SECC', width_mm:500,
  height_mm:1700, depth_mm:900, coating_type:'橘纹', quote_date:'2026-10-10' };

test('installation-board perimeter amount, exact size, quantity, deduction and depth exclusion',()=>{
  for (const [quantity,sign] of [[1,1],[3,1],[2,-1]]) {
    const row=calculateAttachment({quantity,attachment_price_sign:sign,unit_price_override:1,size_match_ratio:999},board,[],environment);
    assert.equal(row.status,'QUICK_ONLY');
    assert.equal(row.face_price,363.51);
    assert.equal(row.unit_price_override,333.2175);
    assert.equal(row.quick_amount,round(333.2175*quantity*sign));
    assert.equal(row.catalogue_quick_amount,round(363.51*quantity*sign));
    assert.equal(calculateAttachment({quantity,attachment_price_sign:sign},board,[],{...environment,depth_mm:100}).quick_amount,row.quick_amount);
  }
  const exact=calculateAttachment({quantity:1},board,[],{...environment,width_mm:600,height_mm:1800});
  assert.equal(exact.quick_amount,363.51);
  assert.equal(exact.size_match_exact,true);
  assert.equal(exact.unit_price_override,undefined);
  const normal=calculateAttachment({quantity:1},{...board,item_name:'固定底座',category_level1:'底座'},[],environment);
  assert.equal(normal.quick_amount,363.51);
  const dispatched=calculateAttachment({quantity:1},{...board,item_name:'安装板单发'},[],environment);
  assert.equal(dispatched.quick_amount,363.51);
});

test('quick total changes without changing installation-board formula cost',()=>{
  const row=calculateAttachment({quantity:1},board,[{rule_id:1,method:'FIXED',fixed_cost:50.83}],environment);
  const result=applyAttachmentTotals({quick_quote:{total_cost:1000,attachment_fee:0},formula_cost:{total_cost:500,attachment_fee:0}},[row]);
  assert.equal(result.quick_quote.total_cost,1333.22);
  assert.equal(result.quick_quote.attachment_fee,333.22);
  assert.equal(result.formula_cost.total_cost,550.83);
});

test('installation-board costs use actual face dimensions, never catalogue size or perimeter-scaled cost',()=>{
  const bundle=JSON.parse(readFileSync(new URL('../database/attachment-v2/generated/attachment-bundle.json',import.meta.url)));
  const actual={...environment,density_g_cm3:7.85,material_unit_price:4.2,spray_unit_price:26};
  for (const [product,source,offsetW,offsetH] of [
    ['JP',3,26.6,72],['JA_SINGLE',4,44,25],['JE_SINGLE',5,44,30],['JM',6,44,30],['JK',40,25,15],
  ]) {
    const rule=bundle.rules.find(value=>value.source_row_no===source);
    const catalog={...board,item_name:product==='JK'?'JK安装板':'安装板'};
    const row=calculateAttachment({quantity:3,manual_inputs:{宽度:9999,高度:9999}},catalog,[rule],{...actual,product_code:product});
    const expectedWeight=(actual.height_mm-offsetH)*(actual.width_mm-offsetW)*2.5*actual.density_g_cm3*1e-6;
    assert.equal(row.status,'CALCULATED');
    assert.ok(Math.abs(row.weight_kg-expectedWeight)<1e-9);
    assert.equal(row.material_cost,round(expectedWeight*actual.material_unit_price,8));
    assert.equal(row.formula_amount,round(3*row.formula_unit_cost));
    const matchedSizeCost=calculateAttachment({quantity:3},catalog,[rule],{...actual,product_code:product,
      width_mm:board.width_mm,height_mm:board.height_mm});
    assert.notEqual(row.formula_unit_cost,matchedSizeCost.formula_unit_cost);
    assert.notEqual(row.formula_amount,round(matchedSizeCost.formula_amount*row.size_match_ratio));
    assert.equal(row.quick_amount,999.65);
  }
});

test('immutable catalogue audit price and scaled quote/export snapshots both survive',async()=>{
  let snapshot, insertSql;
  const service=createAttachmentService({env:{},
    calculateBase:async()=>({quick_quote:{total_cost:1000,attachment_fee:0},formula_cost:{total_cost:500,attachment_fee:0}}),
    runPsql:async sql=>{
      if(sql.includes('attachment_catalog_version')) return JSON.stringify([{data_version:'offline',status:'ACTIVE'}]);
      if(sql.includes('FROM (SELECT p.attachment_price_id')) return JSON.stringify([board]);
      if(sql.includes('density_g_cm3')) return JSON.stringify({density_g_cm3:7.85,spray_unit_price:26});
      if(sql.startsWith('BEGIN;')) {
        insertSql=sql;
        const jsons=[...sql.matchAll(/decode\('([0-9a-f]+)','hex'\)/g)].map(m=>Buffer.from(m[1],'hex').toString('utf8'))
          .filter(value=>value.startsWith('{')).map(value=>JSON.parse(value));
        const env=jsons.find(value=>value.quote_result);
        const cost=jsons.find(value=>value.catalogue_quick_amount!==undefined);
        snapshot={environment:env,attachments:[cost]};
        return JSON.stringify(snapshot);
      }
      if(sql.includes('FROM calc.attachment_quote_line l')) return JSON.stringify(snapshot);
      throw new Error('Unexpected offline SQL');
    }});
  const input={...environment,material_unit_price_override:4.2,quote_id:'offline-quote',attachments:[{attachment_price_id:1,quantity:1}]};
  const result=await service.calculate(input);
  assert.equal(result.attachments[0].quick_amount,333.22);
  assert.equal(result.quick_quote.total_cost,1333.22);
  // Existing DB CHECK(quantity * quick_face_price) and catalogue guard stay valid.
  assert.match(insertSql,/quick_face_price,quick_amount/);
  assert.match(insertSql,/,363\.51,363\.51,/);
  const hydrated=await service.hydrateDocument({items:[{...environment,attachment_contract:2,
    quote_line_id:result.quote_line_id,attachments:input.attachments,quantity:3}]});
  assert.equal(hydrated.items[0].quick.total_cost,1333.22);
  assert.equal(hydrated.items[0].attachments[0].quick_amount,333.22);
  assert.equal(hydrated.items[0].attachments[0].unit_price_override,333.2175);
});
