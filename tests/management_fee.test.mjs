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

test('all executable SQL entrypoints and generated labor imports use the current fee rule',async()=>{
  for(const file of ['database/migrations/create_total_cost_calculation.sql',
    'database/migrations/create_total_cost_by_spray_cost.sql','database/migrations/create_quote_total_function.sql',
    'database/migrations/create_attachment_selection_and_fee.sql','database/migrations/enforce_management_fee_6_percent.sql',
    'database/migrations/cabinet_labor_v1.sql','database/cabinet-labor/web/01-create.sql']) {
    const source=await fs.readFile(new URL('../'+file,import.meta.url),'utf8');
    assert.doesNotMatch(source,/0\.13|13%/,file);
    assert.match(source,/0\.06/,file);
  }
  const stage=await fs.readFile(new URL('../database/cabinet-labor/web/02-stage.sql',import.meta.url),'utf8');
  const hex=stage.match(/decode\('([0-9a-f]+)'/)?.[1];
  assert.equal(JSON.parse(Buffer.from(hex,'hex').toString('utf8')).management_fee_rate,.06);
  const exporter=await fs.readFile(new URL('../export_dual_quote_workbook.mjs',import.meta.url),'utf8');
  assert.doesNotMatch(exporter,/历史管理费用|历史人工成本的|management_fee_rate\s*\?\?\s*0\.13/);
  const client=await fs.readFile(new URL('../desktop_client/layout_refresh.py',import.meta.url),'utf8');
  assert.doesNotMatch(client,/base_management|original_refresh\(self\)/);
});
