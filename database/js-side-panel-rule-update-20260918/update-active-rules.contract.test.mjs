import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./01-update-active-rules.sql',import.meta.url),'utf8');
test('JS side-panel material and spray updates are active-version scoped',()=>{
  assert.match(sql,/material_rows<>10 OR spray_rows<>10/);
  assert.equal((sql.match(/SET area_formula='\(高度\+50\.5\)\*\(深度\+64\)\*0\.000001'/g)||[]).length,2);
  assert.ok((sql.match(/"kind":"JS_DEPTH_HEIGHT","when_true":1,"when_false":2/g)||[]).length>=4);
  assert.ok((sql.match(/status='ACTIVE'/g)||[]).length>=6);
  assert.match(sql,/COMMIT;/);
});
