import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('document-box update contains exactly the two requested active prices',()=>{
  const sql=fs.readFileSync(new URL('./01-update-active-prices.sql',import.meta.url),'utf8');
  assert.match(sql,/\('A3资料盒',30\)/); assert.match(sql,/\('A4资料盒',20\)/);
  assert.match(sql,/matched<>2/); assert.match(sql,/status='ACTIVE'/);
  assert.match(sql,/quick_face_price=u\.new_price,price=round\(u\.new_price,2\)/);
});
