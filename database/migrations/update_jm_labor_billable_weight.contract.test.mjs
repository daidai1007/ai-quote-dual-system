import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./update_jm_labor_billable_weight.sql',import.meta.url),'utf8');

test('JM labor migration versions the catalog and uses the confirmed billable-weight formulas',()=>{
  assert.match(sql,/cabinet-labor-01249192a2981dc7-v2/);
  assert.doesNotMatch(sql,/weight_basis/);
  assert.match(sql,/197\.2715 \+ 1\.423229 × 计价材料重量/);
  assert.match(sql,/292\.5932 \+ 2\.756249 × 计价材料重量（去掉安装板的重量）/);
  assert.match(sql,/\["SUS304","SUS316"\]/);
  assert.match(sql,/\["安装板"\]/);
  assert.match(sql,/v_count<>58/);
  assert.match(sql,/status='RETIRED'/);
  assert.match(sql,/status='ACTIVE'/);
});
