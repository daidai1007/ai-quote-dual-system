import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./01-replace-light-switch.sql',import.meta.url),'utf8');

test('灯开关替换脚本仅写入3个指定型号与价格',()=>{
  const rows=[...sql.matchAll(/^\s*\('([^']+)',([\d.]+),(\d+),(\d+)\)[,;]$/gm)]
    .map(([,model,cost,quick,row])=>({model,cost:Number(cost),quick:Number(quick),row:Number(row)}));
  assert.deepEqual(rows,[
    {model:'220V',cost:27.56,quick:50,row:1},
    {model:'24V-0.28m',cost:34.06,quick:50,row:2},
    {model:'24V-0.6m',cost:40.06,quick:50,row:3},
  ]);
  assert.match(sql,/category_level1='灯开关'/);
  assert.match(sql,/DELETE FROM calc\.attachment_classification/);
  assert.match(sql,/SET is_active=false/);
  assert.match(sql,/'照明灯\/行程开关'/);
  assert.match(sql,/'FIXED',i\.formula_cost/);
  assert.match(sql,/quick_face_price/);
  assert.match(sql,/attachment_cost_rule_binding/);
  assert.match(sql,/COMMIT;/);
});
