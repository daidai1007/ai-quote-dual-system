import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {allocateAttachmentCosts,withAttachmentCostAllocation} from '../attachment_cost_allocation.mjs';
import {applyAttachmentTotals} from '../api/attachment_service.mjs';
import {moneySum} from '../quick_discount_rules.mjs';
const fixture=JSON.parse(fs.readFileSync(new URL('./fixtures/formula_attachment_allocation.json',import.meta.url)));

test('A manual cost units remain fixed costs alongside B formula allocations',()=>{
 const rows=structuredClone(fixture.attachments);
 rows.push({item_name:'人工成本公式附件',status:'CALCULATED',cost_method:'FORMULA',quantity:2,
  formula_cost_edited:true,formula_unit_cost_override:7.5,formula_amount:15,
  material_cost:1,spray_cost:1,auxiliary_cost:1,labor_cost:1});
 rows.push({item_name:'人工成本快速附件',status:'QUICK_ONLY',quantity:2,
  formula_cost_edited:true,formula_unit_cost_override:2.5,formula_amount:5});
 const result=allocateAttachmentCosts({...fixture.formula,attachment_fee:82},rows,{strict:true});
 assert.equal(result.fixed_cost,32);assert.equal(result.attachment_total,82);
 assert.equal(result.lines.at(-2).method,'FIXED');assert.equal(result.lines.at(-1).method,'FIXED');
 assert.deepEqual(result.attachment_parts,{material_cost:35,spray_cost:5,auxiliary_cost:3,labor_cost:7});
 assert.equal(fixture.formula.attachment_fee,62);
});

test('formula attachment components classify once, preserve fixed/manual costs and original billing',()=>{
 const before=structuredClone(fixture);
 const value=withAttachmentCostAllocation(fixture.formula,fixture.attachments,{strict:true});
 assert.deepEqual(value.cost_allocation.totals,fixture.expected);
 assert.equal(value.attachment_fee,62);assert.equal(value.material_cost,100);
 assert.equal(moneySum(Object.values(value.cost_allocation.totals)),value.total_cost);
 assert.deepEqual(withAttachmentCostAllocation(value,fixture.attachments,{strict:true}),value);
 assert.deepEqual(fixture,before);
});
test('API result and management fee include each cost once for ordinary and ganged sets',()=>{
 const base={formula_cost:{...fixture.formula,attachment_fee:0},quick_quote:{base_price:500,attachment_fee:0,total_cost:500}};
 const value=applyAttachmentTotals(base,fixture.attachments,8);
 assert.equal(value.formula_cost.total_cost,235.8);assert.equal(value.formula_cost.management_fee,13.8);
 assert.deepEqual(value.formula_cost.cost_allocation.totals,fixture.expected);
 assert.deepEqual(applyAttachmentTotals(value,fixture.attachments,8),value);
});
test('rounding and negative quantities retain the original attachment amount',()=>{
 for(const sign of [1,-1]){
  const row={status:'CALCULATED',quantity:3,attachment_price_sign:sign,formula_amount:.06*sign,
   material_cost:.005,spray_cost:.005,auxiliary_cost:.005,labor_cost:.005};
  const v=allocateAttachmentCosts({attachment_fee:row.formula_amount},[row],{strict:true});
  assert.deepEqual(Object.values(v.attachment_parts),[.02*sign,.01*sign,.02*sign,.01*sign]);
  assert.equal(moneySum(Object.values(v.attachment_parts)),row.formula_amount);
 }
});
test('missing or inconsistent formula components require recalculation rather than zero-fill',()=>{
 const rows=structuredClone(fixture.attachments);delete rows[0].material_cost;
 assert.equal(allocateAttachmentCosts(fixture.formula,rows).complete,false);
 assert.throws(()=>allocateAttachmentCosts(fixture.formula,rows,{strict:true}),/重新计算/);
 rows[0].material_cost=999;
 assert.throws(()=>allocateAttachmentCosts(fixture.formula,rows,{strict:true}),/分项与原成本不一致/);
 assert.equal(allocateAttachmentCosts(fixture.formula,[fixture.attachments[1]]),null);
 assert.throws(()=>allocateAttachmentCosts({attachment_fee:.01},[{status:'CALCULATED',quantity:1,formula_amount:.01,
  material_cost:0,spray_cost:0,auxiliary_cost:0,labor_cost:0}],{strict:true}),/不一致/);
});
