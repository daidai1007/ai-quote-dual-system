import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./enforce_quick_quote_dimension_only.sql',import.meta.url),'utf8');
const rollback=fs.readFileSync(new URL('../quick-quote-dimension-only-20260914/03-rollback-width-priority.sql',import.meta.url),'utf8');

test('quick quotation ignores door/model and matches width before perimeter',()=>{
  assert.match(sql,/CREATE OR REPLACE FUNCTION calc\.match_quick_quote/);
  assert.match(sql,/\(JS\|JP\|JA\|JE\)_\(SINGLE\|DOUBLE\)/);
  assert.match(sql,/\(JM\|JK\)_\(SINGLE\|DOUBLE\)/);
  assert.doesNotMatch(sql,/model_rank/);
  assert.match(sql,/abs\(p_width_mm-q\.reference_width_mm\) AS width_distance/);
  assert.match(sql,/ORDER BY width_distance,perimeter_distance,distance,range_rank/);
  assert.doesNotMatch(sql,/ORDER BY perimeter_distance,distance,range_rank/);
  assert.match(sql,/exact_dimension/);
  assert.match(sql,/match_quick_quote\('JE_SINGLE','任意型号A'/);
  assert.match(sql,/match_quick_quote\('JE_DOUBLE','任意型号B'/);
  assert.match(sql,/v_single_price IS DISTINCT FROM v_double_price/);
  assert.match(sql,/\bBEGIN;/);
  assert.match(sql,/\bCOMMIT;/);
});

test('width-priority rollback restores the immediately previous matcher only',()=>{
  assert.match(rollback,/CREATE OR REPLACE FUNCTION calc\.match_quick_quote/);
  assert.match(rollback,/ORDER BY perimeter_distance,distance,range_rank/);
  assert.doesNotMatch(rollback,/width_distance/);
  assert.doesNotMatch(rollback,/\b(?:INSERT|UPDATE|DELETE)\b/i);
  assert.match(rollback,/\bBEGIN;/);
  assert.match(rollback,/\bCOMMIT;/);
});
