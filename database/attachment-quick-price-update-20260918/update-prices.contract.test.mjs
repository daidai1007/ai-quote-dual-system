import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./01-update-active-prices.sql',import.meta.url),'utf8');

test('fan and filter quick-price update is active-version scoped and complete',()=>{
  const rows=[...sql.matchAll(/^\s*\('([^']+)',(\d+)\)[,;]$/gm)];
  assert.equal(rows.length,17);
  assert.equal(new Set(rows.map(([,name])=>name)).size,17);
  assert.match(sql,/attachment_catalog_version WHERE status='ACTIVE'/);
  assert.match(sql,/matched <> 17/);
  assert.match(sql,/SET quick_face_price=u\.new_price,[\s\S]*price=round\(u\.new_price,2\)/);
  assert.match(sql,/COMMIT;/);
});
