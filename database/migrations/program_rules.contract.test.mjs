import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (name) => readFile(path.join(root, 'database', 'migrations', name), 'utf8');

test('formula experience matching is perimeter-first and ratio-scaled', async () => {
  const sql = await read('migrate_experience_formula_dimension_matching.sql');
  for (const expected of [
    'ORDER BY material_rank, perimeter_distance, dimension_distance, epm.model_id DESC',
    'ORDER BY material_rank, perimeter_distance, dimension_distance, r.labor_rule_id DESC',
    'ORDER BY perimeter_distance, dimension_distance, e.auxiliary_experience_id DESC',
    'ORDER BY perimeter_distance, dimension_distance, e.updated_at DESC, e.experience_spray_price_id DESC',
    'ROUND(v_match.labor_cost * v_ratio, 2)',
    'ROUND(v_match.direct_spray_cost * v_ratio, 6)',
  ]) assert.ok(sql.includes(expected), `missing SQL contract: ${expected}`);
  assert.match(sql, /v_match\.material_weight_kg \* v_ratio/);
});

test('quick quote matches nearest perimeter and scales nonstandard cost fields', async () => {
  const sql = await read('phase2_quick_quote.sql');
  assert.ok(sql.includes('ORDER BY perimeter_distance, distance, model_rank, range_rank'));
  assert.ok(sql.includes('ROUND(b.quick_material_cost * b.perimeter_ratio, 6)'));
  assert.ok(sql.includes('ROUND(b.quick_labor_cost * b.perimeter_ratio, 6)'));
  assert.ok(sql.includes('ROUND(b.quick_spray_cost * b.perimeter_ratio, 6)'));
  assert.ok(sql.includes('COALESCE(b.quick_base_price,b.quick_total_cost)\n           * b.perimeter_ratio'));
});
