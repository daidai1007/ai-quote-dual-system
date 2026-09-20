import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('JS rear-panel update targets all active rules and uses width threshold',()=>{
  const sql=fs.readFileSync(new URL('./01-update-active-rules.sql',import.meta.url),'utf8');
  assert.match(sql,/v\.status='ACTIVE'/);
  assert.match(sql,/r\.family='JS' AND r\.part_name='后背板加强筋'/);
  assert.match(sql,/rule_rows<>4/);
  assert.match(sql,/"kind":"WIDTH_GT","threshold":1000,"when_true":1,"when_false":0/);
});
