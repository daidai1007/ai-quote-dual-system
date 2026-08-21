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
  'sync_unified_door_formula_templates.sql',
);

const decodeHexJson = (value) => JSON.parse(Buffer.from(value, 'hex').toString('utf8'));

test('unified door formula migration is complete and isolated', async () => {
  const sql = await readFile(migrationPath, 'utf8');
  const dockerfile = await readFile(path.join(root, 'Dockerfile'), 'utf8');
  assert.ok(
    dockerfile.includes(
      'COPY database/migrations/sync_unified_door_formula_templates.sql ./database/migrations/',
    ),
    'Render image must include the manual migration',
  );
  assert.match(sql, /\bBEGIN;/);
  assert.match(sql, /\bCOMMIT;/);
  assert.ok(sql.includes('CREATE TEMP TABLE desired_formula_rule'));
  assert.ok(sql.includes('CREATE TEMP TABLE desired_formula_mapping'));
  assert.ok(sql.includes("RAISE EXCEPTION 'Missing formula templates: %'"));
  assert.ok(sql.includes("RAISE EXCEPTION 'Missing formula mappings: %'"));
  assert.ok(sql.includes("RAISE EXCEPTION 'Post-migration mismatch: %'"));
  assert.doesNotMatch(sql, /quick_quote_experience/i);

  const expectedRows = new Map([
    ['JS_SINGLE', 21],
    ['JS_DOUBLE', 21],
    ['JP_SINGLE', 22],
    ['JP_DOUBLE', 22],
    ['JA_SINGLE', 21],
    ['JE_SINGLE', 21],
    ['JE_DOUBLE', 21],
  ]);
  const rulePattern = /^  \('([A-Z_]+)', \d+, \d+, convert_from\(decode\('[0-9a-f]+'/gm;
  const ruleCounts = new Map();
  for (const [, code] of sql.matchAll(rulePattern)) {
    ruleCounts.set(code, (ruleCounts.get(code) ?? 0) + 1);
  }
  assert.deepEqual(ruleCounts, expectedRows);
  assert.equal([...ruleCounts.values()].reduce((sum, count) => sum + count, 0), 149);

  const mappingPattern = /^  \('([A-Z_]+)', '([^']+)', convert_from\(decode\('([0-9a-f]+)'[\s\S]*?'(H\d+)', '(N\d+)'\)[,;]/gm;
  const mappings = new Map();
  for (const [, code, sourceSheet, optionHex, weightCell, areaCell] of sql.matchAll(mappingPattern)) {
    mappings.set(code, {
      sourceSheet,
      options: decodeHexJson(optionHex),
      weightCell,
      areaCell,
    });
  }
  assert.equal(mappings.size, 7);
  for (const code of expectedRows.keys()) assert.ok(mappings.has(code), `missing ${code}`);

  for (const code of ['JS_SINGLE', 'JS_DOUBLE']) {
    assert.equal(mappings.get(code).sourceSheet, 'JS');
    assert.equal(mappings.get(code).options.single_door, 'B17');
    assert.equal(mappings.get(code).options.double_door, 'B11');
    assert.equal(mappings.get(code).weightCell, 'H28');
    assert.equal(mappings.get(code).areaCell, 'N28');
  }
  for (const code of ['JP_SINGLE', 'JP_DOUBLE']) {
    assert.equal(mappings.get(code).sourceSheet, 'JP');
    assert.equal(mappings.get(code).options.single_door, 'B24');
    assert.equal(mappings.get(code).options.double_door, 'B11');
    assert.equal(mappings.get(code).weightCell, 'H29');
    assert.equal(mappings.get(code).areaCell, 'N29');
  }
  assert.equal(mappings.get('JA_SINGLE').options.single_door, 'B16');
  assert.equal(mappings.get('JA_SINGLE').options.double_door, 'B17');
  for (const code of ['JE_SINGLE', 'JE_DOUBLE']) {
    assert.equal(mappings.get(code).options.single_door, 'B16');
    assert.equal(mappings.get(code).options.double_door, 'B17');
  }
});
