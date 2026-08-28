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
  'repair_jp_frame_eager_if_formulas.sql',
);

test('JP eager-IF repair is transactional, scoped, and self-verifying', async () => {
  const sql = await readFile(migrationPath, 'utf8');
  assert.match(sql, /\bBEGIN;/);
  assert.match(sql, /\bCOMMIT;/);
  assert.ok(sql.includes("t.template_code IN ('JP_SINGLE', 'JP_DOUBLE')"));
  assert.ok(sql.includes("r.source_row_no = replacement.source_row_no"));
  assert.ok(sql.includes("'{formulas,8}'"));
  assert.ok(sql.includes('$B$9-$B$15'));
  assert.ok(sql.includes('2*$B$9-$B$15'));
  assert.ok(sql.includes("RAISE EXCEPTION 'JP eager-IF formula repair mismatch: %'"));
  assert.doesNotMatch(sql, /\$B\$9\/\$B\$15/);
  assert.doesNotMatch(sql, /\bDELETE\s+FROM\b/i);
});
