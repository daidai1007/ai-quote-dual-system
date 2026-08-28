import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const migrationUrl = new URL(
  './repair_quick_perimeter_and_add_door_installation_strip.sql',
  import.meta.url,
);

test('quick perimeter repair and door strip seed are transactional and idempotent', async () => {
  const sql = await readFile(migrationUrl, 'utf8');
  assert.match(sql, /\bBEGIN;/);
  assert.match(sql, /\bCOMMIT;/);
  assert.match(sql, /CREATE OR REPLACE FUNCTION calc\.match_quick_quote/);
  assert.match(sql, /AS perimeter_distance/);
  assert.match(
    sql,
    /ORDER BY perimeter_distance, distance, model_rank, range_rank,/,
  );
  assert.match(sql, /'JE601230'::TEXT, 600::NUMERIC, 1230::NUMERIC, 300::NUMERIC/);
  assert.match(sql, /selected_model IS DISTINCT FROM 'JE601230'/);
  assert.match(sql, /WHERE NOT EXISTS \(/);
  assert.match(sql, /'门安装条', '门安装条', '所有型号'/);
  assert.match(sql, /source_file, source_sheet, source_row_no, is_active/);
  assert.match(sql, /'repair_quick_perimeter_and_add_door_installation_strip\.sql'/);
  assert.match(sql, /不参与折扣/);
  assert.match(sql, /20, '20', '根', '人工新增'/);
  assert.match(sql, /INSERT INTO calc\.attachment_classification/);
  assert.match(sql, /category_level1 = '门安装条'/);
  assert.doesNotMatch(sql, /\bDELETE\b/i);
});
