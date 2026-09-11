import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {applyCabinetSpray,calculateCabinetSpray} from '../api/cabinet_spray_service.mjs';

const rules=[
  {rule_id:1,family:'JS',body_thickness_profile_mm:1.5,single_door_count:1,double_door_count:0,
    part_name:'侧板',area_formula:'(宽度+50.5)*(深度+64)*0.000001',quantity_rule:{kind:'CONSTANT',value:2},
    source_sheet:'JS',source_row_no:3,source_column:'A:D'},
  {rule_id:2,family:'JS',body_thickness_profile_mm:2,single_door_count:1,double_door_count:0,
    part_name:'侧板',area_formula:'宽度*深度*0.000001',quantity_rule:{kind:'CONSTANT',value:1},
    source_sheet:'JS',source_row_no:3,source_column:'G:J'},
];
const environment={data_version:'cabinet-spray-test-v1',product_code:'JS',width_mm:1000,height_mm:1800,depth_mm:600,
  single_door_count:1,double_door_count:0,cabinet_body_thickness_mm:1.5,coating_type:'橘纹',spray_unit_price:12};

test('spray cost is formula area times internal quantity times current spray unit price',()=>{
  const result=calculateCabinetSpray(rules,environment);
  const expectedArea=(1000+50.5)*(600+64)*0.000001*2;
  assert.ok(Math.abs(result.product_area_m2-expectedArea)<1e-8);
  assert.equal(result.spray_cost,Math.round(expectedArea*12*100)/100);
  assert.equal(result.part_details[0].internal_quantity,2);
});

test('zero spray unit price is valid and waste factor never changes spray',()=>{
  const first=calculateCabinetSpray(rules,{...environment,spray_unit_price:0,waste_factor:1.2});
  const second=calculateCabinetSpray(rules,{...environment,spray_unit_price:0,waste_factor:1.8});
  assert.equal(first.spray_cost,0);assert.equal(second.spray_cost,0);
  assert.equal(first.product_area_m2,second.product_area_m2);
});

test('body thickness selects the exact spray profile',()=>{
  const result=calculateCabinetSpray(rules,{...environment,cabinet_body_thickness_mm:2});
  assert.equal(result.part_details.length,1);
  assert.equal(result.product_area_m2,0.6);
});

test('applying spray replaces old spray cost and keeps the quick quote unchanged',()=>{
  const spray=calculateCabinetSpray(rules,environment);
  const result=applyCabinetSpray({formula_cost:{material_cost:200,spray_cost:99,total_cost:500},quick_quote:{total_cost:800}},spray);
  assert.equal(result.formula_cost.total_cost,500-99+spray.spray_cost);
  assert.equal(result.formula_cost.product_area_m2,spray.product_area_m2);
  assert.equal(result.quick_quote.total_cost,800);
});

test('all 202 workbook spray rules execute for every imported product/profile/door group',()=>{
  const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-spray/generated/cabinet-spray-bundle.json',import.meta.url)));
  assert.equal(bundle.rules.length,202);
  const groups=new Map();
  for(const rule of bundle.rules){
    const key=[rule.family,rule.body_thickness_profile_mm,rule.single_door_count,rule.double_door_count].join('|');
    groups.set(key,{family:rule.family,body:rule.body_thickness_profile_mm,single:rule.single_door_count,double:rule.double_door_count});
  }
  for(const group of groups.values()){
    const result=calculateCabinetSpray(bundle.rules,{...environment,product_code:group.family,
      cabinet_body_thickness_mm:group.body??1.5,single_door_count:group.single,double_door_count:group.double});
    assert.ok(result.part_details.length>0,JSON.stringify(group));
    assert.ok(result.part_details.every(row=>row.area_per_piece_m2>=0&&row.total_area_m2>=0),JSON.stringify(group));
    assert.equal(result.spray_cost,Math.round(result.product_area_m2*environment.spray_unit_price*100)/100);
  }
});

test('wide product codes are not collapsed into ordinary JS or JP spray rules',()=>{
  assert.throws(()=>calculateCabinetSpray(rules,{...environment,product_code:'JS_WIDE_EXP'}),/JS_WIDE_EXP/);
});
