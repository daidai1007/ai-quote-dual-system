import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const migrationPath = path.join(
  root,
  'database',
  'migrations',
  'complete_formula_shared_cells_from_workbooks.sql',
);

test('shared formula completion is complete, guarded, and formula-only', async () => {
  const sql = await readFile(migrationPath, 'utf8');
  assert.match(sql, /\bBEGIN;/);
  assert.match(sql, /\bCOMMIT;/);
  assert.ok(sql.includes('CREATE TEMP TABLE formula_cell_patch'));
  assert.ok(sql.includes("RAISE EXCEPTION 'Existing formula conflicts: %'"));
  assert.ok(sql.includes("RAISE EXCEPTION 'Formula completion mismatch: %'"));
  assert.ok(sql.includes("raw_rule = jsonb_set("));
  assert.doesNotMatch(sql, /quick_quote_experience/i);
  assert.doesNotMatch(sql, /\bDELETE\b/i);
  assert.doesNotMatch(sql, /\bINSERT INTO calc\.cabinet_part_rule\b/i);

  const patchPattern = /^  \('([A-Z_]+)', (\d+), (\d+), convert_from\(decode\('[0-9a-f]+'/gm;
  const counts = new Map();
  let total = 0;
  for (const [, code] of sql.matchAll(patchPattern)) {
    counts.set(code, (counts.get(code) ?? 0) + 1);
    total += 1;
  }
  assert.equal(total, 479);
  assert.deepEqual(counts, new Map([
    ['JA_SINGLE', 52],
    ['JE_DOUBLE', 52],
    ['JE_SINGLE', 52],
    ['JK', 25],
    ['JM', 26],
    ['JP_DOUBLE', 64],
    ['JP_SINGLE', 64],
    ['JS_DOUBLE', 72],
    ['JS_SINGLE', 72],
  ]));
});
