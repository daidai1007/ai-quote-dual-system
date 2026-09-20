import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const load=name=>JSON.parse(fs.readFileSync(new URL(`../database/${name}/generated/${name}-bundle.json`,import.meta.url)));

test('JA and JE double-door bend rules use quantity four in material and spray',()=>{
  const material=load('cabinet-material').rules.filter(r=>r.single_door_count===0&&r.double_door_count===1&&
    ((r.family==='JA'&&r.part_name==='走线弯角件')||(r.family==='JE'&&r.part_name==='走线弯角件1')));
  const spray=load('cabinet-spray').rules.filter(r=>r.single_door_count===0&&r.double_door_count===1&&
    ['JA','JE'].includes(r.family)&&r.part_name==='走线弯角件');
  assert.equal(material.length,3); assert.equal(spray.length,3);
  assert.ok([...material,...spray].every(r=>r.quantity_rule.kind==='CONSTANT'&&r.quantity_rule.value===4));
});

test('online update is active-version scoped and validates three rows per rule type',()=>{
  const sql=fs.readFileSync(new URL('../database/ja-je-bend-rule-update-20260920/01-update-active-rules.sql',import.meta.url),'utf8');
  assert.match(sql,/v\.status='ACTIVE'/); assert.match(sql,/material_rows<>3 OR spray_rows<>3/);
  assert.match(sql,/"kind":"CONSTANT","value":4/);
});
