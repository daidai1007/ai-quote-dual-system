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
  'extend_jp_frame_formula_template.sql',
);

test('JP frame formula extension is complete, transactional, and idempotent', async () => {
  const sql = await readFile(migrationPath, 'utf8');
  assert.match(sql, /\bBEGIN;/);
  assert.match(sql, /\bCOMMIT;/);
  assert.ok(sql.includes("t.template_code IN ('JP_SINGLE', 'JP_DOUBLE')"));
  assert.ok(sql.includes('WHERE NOT EXISTS'));
  assert.ok(sql.includes("RAISE EXCEPTION 'JP frame formula migration mismatch: %'"));
  assert.ok(sql.includes('t.template_id AS target_template_id'));
  assert.ok(sql.includes('SELECT s.target_template_id,'));
  assert.ok(sql.includes('r.material_id AS seed_material_id'));
  assert.ok(sql.includes('r.process_route AS seed_process_route'));
  assert.ok(sql.includes('r.is_purchasable AS seed_is_purchasable'));
  assert.ok(sql.includes('existing.template_id = s.target_template_id'));
  assert.ok(sql.includes('count(r.rule_id) AS frame_rule_count'));
  assert.ok(sql.includes('failed.frame_rule_count'));
  assert.ok(sql.includes("WHEN 42 THEN '=IF(AND($B$23=1,$B$14=1,$B$25=0),$B$9-$B$15"));
  assert.ok(sql.includes("WHEN 43 THEN '=IF(AND($B$14=1,$B$9<>1),($B$9-$B$15)*4,)"));
  assert.ok(sql.includes("'{formulas,8}'"));
  assert.doesNotMatch(sql, /format\([^\n]*count\(r\.rule_id\)/);
  assert.doesNotMatch(sql, /\br\.\*/);
  assert.doesNotMatch(sql, /\bs\.template_id\b/);
  assert.doesNotMatch(sql, /t\.template_id\s*,\s*r\.\*/);
  assert.doesNotMatch(sql, /\bDELETE\s+FROM\b/i);

  const rows = [...sql.matchAll(
    /^  \((3[5-9]|4[0-3]), convert_from\(decode\('([0-9a-f]+)'/gm,
  )];
  assert.deepEqual(rows.map((match) => Number(match[1])), [35, 36, 37, 38, 39, 40, 41, 42, 43]);
  for (const [, sourceRow, rawHex] of rows) {
    const raw = JSON.parse(Buffer.from(rawHex, 'hex').toString('utf8'));
    assert.equal(raw.source_row_no, Number(sourceRow));
    assert.ok(
      raw.values.length === 22 || raw.values.length === 23,
      `row ${sourceRow} has unexpected D:Z value width`,
    );
    assert.equal(raw.formulas.length, 23);
    assert.ok(raw.formulas[9], `row ${sourceRow} is missing weight formula`);
    assert.ok(raw.formulas[21], `row ${sourceRow} is missing area formula`);
  }
});
