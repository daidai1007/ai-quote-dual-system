import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./01-update-js-jm-prices.sql',import.meta.url),'utf8');

test('JS and JM quick-price update is complete and narrowly scoped',()=>{
  const rows=[...sql.matchAll(/^\s*\('(JS_SINGLE|JM)',(NULL|'[^']+'),(\d+),(\d+),(\d+),(\d+\.\d+)\)[,;]$/gm)];
  assert.equal(rows.length,11);
  assert.equal(rows.filter(([,product])=>product==='JS_SINGLE').length,1);
  assert.equal(rows.filter(([,product])=>product==='JM').length,10);
  assert.equal(rows.filter(([,product,model])=>product==='JM'&&model==='NULL').length,10);
  assert.match(sql,/material_code='SECC'/);
  assert.match(sql,/matched<>1/);
  assert.doesNotMatch(sql,/q\.model_code=u\.model_code/);
  assert.match(sql,/SET quick_base_price=u\.new_price,[\s\S]*quick_total_cost=u\.new_price/);
  assert.match(sql,/COMMIT;/);
});
