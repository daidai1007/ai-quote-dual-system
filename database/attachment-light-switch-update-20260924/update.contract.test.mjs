import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sql=fs.readFileSync(new URL('./01-replace-light-switch.sql',import.meta.url),'utf8');

test('照明灯/行程开关脚本写入5条指定快速价和固定成本',()=>{
  const rows=[...sql.matchAll(/^\s*\('([^']+)',(NULL|'[^']+'),([\d.]+),(\d+),'([^']+)',(\d+)\)[,;]$/gm)]
    .map(([,name,model,cost,quick,unit,row])=>({
      name,model:model==='NULL'?null:model.slice(1,-1),cost:Number(cost),quick:Number(quick),unit,row:Number(row)
    }));
  assert.deepEqual(rows,[
    {name:'行程开关',model:null,cost:19.06,quick:25,unit:'个',row:1},
    {name:'照明灯220V长款',model:null,cost:8.5,quick:25,unit:'个',row:2},
    {name:'照明灯220V短款',model:null,cost:7.8,quick:25,unit:'个',row:3},
    {name:'照明灯24V-0.28m',model:null,cost:15,quick:25,unit:'个',row:4},
    {name:'照明灯24V-0.6m',model:null,cost:21,quick:25,unit:'个',row:5},
  ]);
  assert.match(sql,/category_level1 IN \('灯开关','照明灯\/行程开关'\)/);
  assert.match(sql,/SET is_active=false/);
  assert.match(sql,/GREATEST\(CURRENT_DATE,p\.effective_from \+ 1\)/);
  assert.match(sql,/'FIXED',i\.formula_cost/);
  assert.doesNotMatch(sql,/THEN 'ITEM'/);
  assert.match(sql,/THEN 'DESCRIPTION' ELSE 'MODEL'/);
  assert.match(sql,/attachment_cost_rule_binding/);
  assert.match(sql,/<>5/);
  assert.match(sql,/COMMIT;/);
});
