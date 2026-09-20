import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const sql=fs.readFileSync(new URL('./01-update-prices.sql',import.meta.url),'utf8');

test('JA and JE quick-price update contains all eight exact material-size targets',()=>{
  const rows=[...sql.matchAll(/^\s*\('(JA_SINGLE|JE_SINGLE)','(SECC|SUS304|SUS316)',(\d+),(\d+),(\d+),(\d+)\)[,;]$/gm)];
  assert.equal(rows.length,8);
  assert.equal(rows.filter(([,p,m,w,h,d,v])=>p==='JA_SINGLE'&&m==='SECC'&&w==='300'&&h==='300'&&d==='210'&&v==='291').length,1);
  assert.equal(rows.filter(([,p,m,w,h,d,v])=>p==='JA_SINGLE'&&m!=='SECC'&&w==='600'&&h==='380'&&d==='350'&&v==='1055').length,2);
  assert.equal(rows.filter(([,p,m,w,h,d,v])=>p==='JE_SINGLE'&&w==='800'&&h==='1200'&&d==='300'&&v===(m==='SECC'?'1187':'2276')).length,3);
  assert.match(sql,/matched<>1/); assert.match(sql,/quick_base_price=u\.new_price,quick_total_cost=u\.new_price/);
});
