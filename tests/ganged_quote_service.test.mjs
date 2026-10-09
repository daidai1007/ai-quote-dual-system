import assert from 'node:assert/strict';
import test from 'node:test';
import {createBatchReadExecutor, validateGangedBatch, calculateGangedBatch} from '../api/ganged_quote_service.mjs';
import {formulaTemplateSql} from '../api/formula_template_query.mjs';
import {createCabinetMaterialService} from '../api/cabinet_material_service.mjs';

const cabinets = [1000, 800].map((width, index) => ({
  quote_id: `test-${index}`, product_code: 'JP_SINGLE', material_code: 'SECC',
  width_mm: width, height_mm: 2100, depth_mm: 600, single_door_count: 1, double_door_count: 0,
  quote_date: '2026-10-09', waste_factor: 1.2, material_unit_price_override: 4.2,
  galvanized_sheet_unit_price_override: 4.55, carbon_steel_unit_price_override: 4.2, attachments: [],
}));
const childResult = child => ({
  formula_cost: {material_cost: child.width_mm, auxiliary_cost: 20, labor_cost: 30,
    spray_cost: 40, management_fee: 3.9, attachment_fee: 0, total_cost: child.width_mm + 93.9,
    net_material_weight_kg: child.width_mm / 10, corrected_material_weight_kg: child.width_mm * 1.2 / 10,
    product_area_m2: child.width_mm / 100},
  quick_quote: {base_price: child.width_mm * 2, total_cost: child.width_mm * 2, attachment_fee: 0},
});
const batch = (extra = {}) => validateGangedBatch({cabinets, ...extra}, child => child);

test('conditional template query versions complete rules and omits unchanged payloads', () => {
  const sql = formulaTemplateSql("JP_SINGLE'", "v'1");
  assert.match(sql, /JP_SINGLE''/);
  assert.match(sql, /v''1/);
  assert.match(sql, /md5\(to_jsonb\(t\)::text\)/);
  assert.match(sql, /template_weight_formula/);
  assert.match(sql, /template_area_formula/);
  assert.match(sql, /option_cells/);
  assert.match(sql, /THEN NULL ELSE template/);
});

test('batch shares concurrent identical reads but never caches quote writes or later requests', async () => {
  const calls = [];
  const run = async sql => {calls.push(sql); return '1';};
  const first = createBatchReadExecutor(run);
  await Promise.all([first('SELECT rules FROM calc.cabinet_material_rule'), first('SELECT rules FROM calc.cabinet_material_rule')]);
  assert.equal(calls.length, 1);
  for (const sql of ['UPDATE calc.dual_quote_result SET x=1', 'BEGIN; SELECT 1; COMMIT;', 'SELECT calc.calculate_dual_quote(1)']) {
    await Promise.all([first(sql), first(sql)]);
  }
  assert.equal(calls.length, 7);
  await first('SELECT rules FROM calc.cabinet_spray_rule');
  await createBatchReadExecutor(run)('SELECT rules FROM calc.cabinet_material_rule');
  assert.equal(calls.length, 9);
});

test('failed reads are evicted rather than retained', async () => {
  let calls = 0;
  const read = createBatchReadExecutor(async () => {if (++calls === 1) throw new Error('failed'); return '2';});
  await assert.rejects(read('SELECT 1'), /failed/);
  assert.equal(await read('SELECT 1'), '2');
});

test('batch result matches individual sums and keeps input order even when second child finishes first', async () => {
  let active = 0, peak = 0;
  const result = await calculateGangedBatch(batch(), {calculateChild: async child => {
    peak = Math.max(peak, ++active);
    await new Promise(resolve => setTimeout(resolve, child.width_mm === 1000 ? 25 : 5));
    --active;
    return childResult(child);
  }});
  assert.equal(peak, 2);
  assert.equal(result.ganged_batch_contract, 1);
  assert.equal(result.formula_cost.material_cost, 1800);
  assert.equal(result.formula_cost.total_cost, cabinets.reduce((total, child) => total + childResult(child).formula_cost.total_cost, 0));
  assert.equal(result.formula_cost.net_material_weight_kg, 180);
  assert.equal(result.formula_cost.corrected_material_weight_kg, 216);
  assert.deepEqual(result.formula_cost.ganged_cabinet_costs.map(row => row.width_mm), [1000, 800]);
  assert.deepEqual(result.formula_cost.ganged_cabinet_costs.map(row => row.cabinet_index), [1, 2]);
  assert.equal(result.quick_quote.total_cost, 3600);
});

test('different widths use the same rules read but produce independent material costs and weights', async () => {
  let reads = 0;
  const data = {data_version: 'test', default_waste_factor: 1.2, fixed_rules: [],
    materials: [{material_code: 'SECC', density_g_cm3: 7.85}],
    rules: [{rule_id: 1, family: 'JP', single_door_count: 1, double_door_count: 0,
      part_name: '箱体', sheet_thickness_mm: 1.5, area_formula: '宽度*高度*0.000001',
      quantity_rule: {kind: 'CONSTANT', value: 1}},
      {rule_id: 2, family: 'JP', single_door_count: 0, double_door_count: 1,
        part_name: '箱体', sheet_thickness_mm: 1.5, area_formula: '宽度*高度*0.000001',
        quantity_rule: {kind: 'CONSTANT', value: 1}}]};
  const service = createCabinetMaterialService({runPsql: createBatchReadExecutor(async () => {++reads; return JSON.stringify(data);})});
  const weights = await Promise.all(cabinets.map((child, index) => service.calculate(index
    ? {...child, product_code:'JP_DOUBLE', single_door_count:0, double_door_count:1} : child)));
  assert.equal(reads, 1);
  assert.ok(weights[0].material_cost > weights[1].material_cost);
  assert.ok(weights[0].corrected_material_weight_kg > weights[1].corrected_material_weight_kg);
  assert.equal(data.materials[0].material_unit_price, undefined, 'shared data must not be mutated');
});

test('snapshot is created once after all children, preserves two fixed-base indices and ignores injected base', async () => {
  const calls = [];
  const attachment_payload = {
    quote_id: 'parent', ganged_cabinet_count: 2, ganged_cabinets: cabinets,
    attachments: [0, 1].map(ganged_cabinet_index => ({attachment_price_id: ganged_cabinet_index + 1,
      ganged_cabinet_index, quantity: 1, manual_inputs: {'底座高度': 100}})),
    base_result: {formula_cost: {total_cost: -999}},
  };
  const result = await calculateGangedBatch(batch({attachment_payload, attachment_total: 999}), {
    calculateChild: async child => {calls.push(child.quote_id); return childResult(child);},
    snapshotGanged: async snapshot => {
      calls.push('snapshot');
      assert.deepEqual(snapshot.ganged_cabinet_inputs.map(row => row.width_mm), [1000, 800]);
      assert.deepEqual(snapshot.attachments.map(row => row.ganged_cabinet_index), [0, 1]);
      assert.equal(snapshot.base_result.formula_cost.material_cost, 1800);
      return {...snapshot.base_result, attachment_contract: 2};
    },
  });
  assert.deepEqual(calls, ['test-0', 'test-1', 'snapshot']);
  assert.equal(result.attachment_contract, 2);
});

test('child failure publishes no aggregate or attachment snapshot', async () => {
  let snapshots = 0;
  await assert.rejects(calculateGangedBatch(batch(), {
    calculateChild: async child => {if (child.width_mm === 800) throw new Error('child failed'); return childResult(child);},
    snapshotGanged: async () => {++snapshots;},
  }), /child failed/);
  assert.equal(snapshots, 0);
});

test('invalid batches are rejected before calculations', () => {
  for (const count of [0, 1, 21]) assert.throws(() => batch({cabinets: Array(count).fill(cabinets[0])}), /requires/);
  assert.throws(() => batch({cabinets: [cabinets[0], cabinets[0]]}), /unique/);
  assert.throws(() => batch({cabinets: [cabinets[0], {...cabinets[1], attachments: [{}]}]}), /附件/);
  assert.throws(() => batch({attachment_payload: {ganged_cabinet_count: 3}}), /数量/);
  assert.throws(() => batch({area_total: -1}), /non-negative/);
});
