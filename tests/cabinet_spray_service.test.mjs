import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {applyCabinetSpray,calculateCabinetSpray,calculateCabinetSprayFixed} from '../api/cabinet_spray_service.mjs';

const rules=[
  {rule_id:1,family:'JS',body_thickness_profile_mm:1.5,single_door_count:1,double_door_count:0,
    part_name:'左右侧板-1',area_formula:'(高度+50.5)*(深度+64)*0.000001',
    quantity_rule:{kind:'JS_DEPTH_HEIGHT',when_true:1,when_false:2},
    source_sheet:'JS',source_row_no:3,source_column:'A:D'},
  {rule_id:2,family:'JS',body_thickness_profile_mm:2,single_door_count:1,double_door_count:0,
    part_name:'侧板',area_formula:'宽度*深度*0.000001',quantity_rule:{kind:'CONSTANT',value:1},
    source_sheet:'JS',source_row_no:3,source_column:'G:J'},
];
const environment={data_version:'cabinet-spray-test-v1',product_code:'JS',width_mm:1000,height_mm:1800,depth_mm:600,
  single_door_count:1,double_door_count:0,cabinet_body_thickness_mm:1.5,coating_type:'橘纹',spray_unit_price:12};

test('spray cost is formula area times internal quantity times current spray unit price',()=>{
  const result=calculateCabinetSpray(rules,environment);
  const expectedArea=(1800+50.5)*(600+64)*0.000001*2;
  assert.ok(Math.abs(result.product_area_m2-expectedArea)<1e-8);
  assert.equal(result.spray_cost,Math.round(expectedArea*12*100)/100);
  assert.equal(result.part_details[0].internal_quantity,2);
});

test('JS side-panel spray quantity is one only for depth 350..1000 and height below 1000',()=>{
  const one=calculateCabinetSpray(rules,{...environment,height_mm:999,depth_mm:350});
  const high=calculateCabinetSpray(rules,{...environment,height_mm:1000,depth_mm:350});
  const shallow=calculateCabinetSpray(rules,{...environment,height_mm:999,depth_mm:349});
  assert.equal(one.part_details[0].internal_quantity,1);
  assert.equal(high.part_details[0].internal_quantity,2);
  assert.equal(shallow.part_details[0].internal_quantity,2);
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
  const jsSides=bundle.rules.filter(rule=>rule.family==='JS'&&rule.part_name==='左右侧板-1');
  assert.equal(jsSides.length,10);
  assert.ok(jsSides.every(rule=>rule.area_formula==='(高度+50.5)*(深度+64)*0.000001'));
  assert.ok(jsSides.every(rule=>JSON.stringify(rule.quantity_rule)===JSON.stringify({kind:'JS_DEPTH_HEIGHT',when_true:1,when_false:2})));
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

test('all 46 experience spray prices are imported from the complete workbook',()=>{
  const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-spray/generated/cabinet-spray-bundle.json',import.meta.url)));
  assert.equal(bundle.fixed_rules.length,46);
  assert.deepEqual(Object.fromEntries(['JC_EXP','JQ_EXP','JP_WIDE_EXP','JS_WIDE_EXP','OP_TABLE_EXP'].map(code=>
    [code,bundle.fixed_rules.filter(rule=>rule.product_code===code).length])),
    {JC_EXP:4,JQ_EXP:8,JP_WIDE_EXP:12,JS_WIDE_EXP:12,OP_TABLE_EXP:10});
});

test('fixed experience spray uses exact dimensions and material',()=>{
  const fixed=[{fixed_rule_id:1,product_code:'JQ_EXP',profile_code:null,material_codes:['SECC'],model_code:'JQ609648',
    width_mm:600,height_mm:960,depth_mm:480,spray_cost:49.5,allow_dimension_scale:true,source_sheet:'JQ',source_row_no:3}];
  const result=calculateCabinetSprayFixed(fixed,{...environment,product_code:'JQ_EXP',material_code:'SECC',width_mm:600,height_mm:960,depth_mm:480});
  assert.equal(result.spray_cost,49.5);assert.equal(result.match_method,'FIXED_EXACT');assert.equal(result.reference_model_code,'JQ609648');
});

test('fixed experience spray keeps established nearest-dimension perimeter scaling',()=>{
  const fixed=[{fixed_rule_id:1,product_code:'JP_WIDE_EXP',profile_code:null,material_codes:['SECC'],model_code:'JP131860',
    width_mm:1300,height_mm:1800,depth_mm:600,spray_cost:312,allow_dimension_scale:true,source_sheet:'JP超宽柜',source_row_no:3}];
  const result=calculateCabinetSprayFixed(fixed,{...environment,product_code:'JP_WIDE_EXP',material_code:'SECC',width_mm:1400,height_mm:1800,depth_mm:600});
  assert.equal(result.match_method,'FIXED_DIMENSION_SCALE');
  assert.equal(result.spray_cost,Math.round(312*(3800/3700)*100)/100);
});

test('JC fixed spray selects the explicit luxury or standard profile',()=>{
  const fixed=[
    {fixed_rule_id:1,product_code:'JC_EXP',profile_code:'LUXURY',material_codes:['SECC'],model_code:'JC601660',width_mm:600,height_mm:1600,depth_mm:600,spray_cost:86,allow_dimension_scale:true,source_sheet:'JC（豪华型）',source_row_no:3},
    {fixed_rule_id:2,product_code:'JC_EXP',profile_code:'STANDARD',material_codes:['SECC'],model_code:'JC601660',width_mm:600,height_mm:1600,depth_mm:600,spray_cost:86,allow_dimension_scale:true,source_sheet:'JC（标配版）',source_row_no:3},
  ];
  assert.equal(calculateCabinetSprayFixed(fixed,{...environment,product_code:'JC_EXP',material_code:'SECC',model_code:'JC601660-1',width_mm:600,height_mm:1600,depth_mm:600}).source_sheet,'JC（豪华型）');
  assert.equal(calculateCabinetSprayFixed(fixed,{...environment,product_code:'JC_EXP',material_code:'SECC',model_code:'JC601660-2',width_mm:600,height_mm:1600,depth_mm:600}).source_sheet,'JC（标配版）');
});

test('no-spray selection makes fixed experience spray zero',()=>{
  const fixed=[{fixed_rule_id:1,product_code:'JQ_EXP',profile_code:null,material_codes:['SECC'],model_code:'JQ609648',width_mm:600,height_mm:960,depth_mm:480,spray_cost:49.5,allow_dimension_scale:true,source_sheet:'JQ',source_row_no:3}];
  const result=calculateCabinetSprayFixed(fixed,{...environment,coating_type:'不喷塑',product_code:'JQ_EXP',material_code:'SECC',width_mm:600,height_mm:960,depth_mm:480});
  assert.equal(result.spray_cost,0);
});

test('fixed spray replacement preserves base area and unit price fields',()=>{
  const result=applyCabinetSpray({formula_cost:{product_area_m2:3.2,spray_unit_price:12,spray_cost:80,total_cost:500},quick_quote:{total_cost:700}},
    {data_version:'spray-v2',method:'FIXED',match_method:'FIXED_EXACT',product_code:'JQ_EXP',product_area_m2:null,spray_unit_price:null,
      spray_cost:49.5,part_details:[],source_sheet:'JQ',source_row_no:3});
  assert.equal(result.formula_cost.product_area_m2,3.2);assert.equal(result.formula_cost.spray_unit_price,12);
  assert.equal(result.formula_cost.total_cost,469.5);assert.equal(result.quick_quote.total_cost,700);
});
