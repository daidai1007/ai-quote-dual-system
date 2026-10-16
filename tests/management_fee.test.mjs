import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import {applyManagementFee,MANAGEMENT_FEE_BASIS} from '../quick_discount_rules.mjs';
import {applyAttachmentTotals} from '../api/attachment_service.mjs';
import {calculateGangedBatch} from '../api/ganged_quote_service.mjs';

const cases=JSON.parse(await fs.readFile(new URL('./fixtures/management_fee.json',import.meta.url),'utf8'));
for(const sample of cases) test(`management: ${sample.name}`,()=>{
  const before=structuredClone(sample.quote),result=applyManagementFee(sample.quote,sample.freight);
  assert.equal(result.management_fee_rate,.06);
  assert.equal(result.management_fee_basis,MANAGEMENT_FEE_BASIS);
  assert.equal(result.management_fee_base,sample.base);
  assert.equal(result.management_fee,sample.fee);
  assert.equal(result.total_cost,sample.total);
  assert.deepEqual(sample.quote,before,'source snapshot is immutable');
  assert.deepEqual(applyManagementFee(result,sample.freight),result,'refresh must not compound the fee');
});

test('attachment refresh reprices management without altering quick sales',()=>{
  const quick={base_price:500,attachment_fee:80,total_cost:580};
  const result=applyAttachmentTotals({formula_cost:cases[0].quote,quick_quote:quick},
    [{status:'FIXED',formula_amount:60,quick_amount:80}],50);
  assert.equal(result.formula_cost.management_fee,16.2);
  assert.equal(result.formula_cost.total_cost,236.2);
  assert.deepEqual(result.quick_quote,quick);
});

test('ganged management is rounded once on whole-set costs, not child management sums',async()=>{
  const result=await calculateGangedBatch({cabinets:[{},{}],attachmentTotal:0,areaTotal:0},
    {calculateChild:async()=>({formula_cost:applyManagementFee({material_cost:.08,auxiliary_cost:0,
      labor_cost:0,spray_cost:0,attachment_fee:0}),quick_quote:{base_price:1,total_cost:1,attachment_fee:0}})});
  assert.equal(result.formula_cost.management_fee,.01);
  assert.equal(result.formula_cost.total_cost,.17);
  assert.equal(result.quick_quote.total_cost,2);
});
