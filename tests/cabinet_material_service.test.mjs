import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {calculateCabinetMaterial,applyCabinetMaterial} from '../api/cabinet_material_service.mjs';
import {calculateAttachment} from '../api/attachment_cost.mjs';

const materials=[
  {material_code:'SECC',density_g_cm3:7.85,material_unit_price:5},
  {material_code:'SUS304',density_g_cm3:7.93,material_unit_price:20},
];
const rules=[
  {rule_id:1,family:'JS',body_thickness_profile_mm:1.5,single_door_count:1,double_door_count:0,
    part_name:'安装板',area_formula:'(高度-72)*(宽度-26.6)*0.000001',sheet_thickness_mm:2.5,
    quantity_rule:{kind:'CONSTANT',value:1},fixed_material_code:'SECC',source_sheet:'JS',source_row_no:5,source_column:'A:F'},
  {rule_id:2,family:'JS',body_thickness_profile_mm:1.5,single_door_count:1,double_door_count:0,
    part_name:'顶板',area_formula:'(宽度+20)*(深度+10)*0.000001',sheet_thickness_mm:1.5,
    quantity_rule:{kind:'CONSTANT',value:2},fixed_material_code:null,source_sheet:'JS',source_row_no:6,source_column:'A:F'},
  {rule_id:3,family:'JS',body_thickness_profile_mm:2,single_door_count:1,double_door_count:0,
    part_name:'顶板',area_formula:'宽度*深度*0.000001',sheet_thickness_mm:2,
    quantity_rule:{kind:'CONSTANT',value:1},fixed_material_code:null,source_sheet:'JS',source_row_no:6,source_column:'H:M'},
];
const environment={data_version:'cabinet-material-test-v1',product_code:'JS',material_code:'SUS304',
  width_mm:1000,height_mm:1800,depth_mm:600,single_door_count:1,double_door_count:0,
  cabinet_body_thickness_mm:1.5,waste_factor:1.2,materials};

test('cabinet net weight, billable weight and cost use the selected factor once',()=>{
  const result=calculateCabinetMaterial(rules,environment);
  const installationArea=(1800-72)*(1000-26.6)*0.000001;
  const topArea=(1000+20)*(600+10)*0.000001;
  const expectedNet=installationArea*2.5*1*7.85+topArea*1.5*2*7.93;
  const expectedCost=installationArea*2.5*7.85*1.2*5+topArea*1.5*2*7.93*1.2*20;
  assert.ok(Math.abs(result.net_material_weight_kg-expectedNet)<1e-7);
  assert.ok(Math.abs(result.corrected_material_weight_kg-expectedNet*1.2)<1e-7);
  assert.equal(result.material_cost,Math.round(expectedCost*100)/100);
  assert.deepEqual(result.material_details.map(x=>x.material_code).sort(),['SECC','SUS304']);
});

test('operator waste factor overrides the 1.2 default and profile 2 is exact',()=>{
  const result=calculateCabinetMaterial(rules,{...environment,cabinet_body_thickness_mm:2,waste_factor:1.35});
  assert.equal(result.part_details.length,1);
  assert.equal(result.waste_factor,1.35);
  assert.equal(result.net_material_weight_kg,1000*600*0.000001*2*7.93);
  assert.equal(result.corrected_material_weight_kg,result.net_material_weight_kg*1.35);
});

test('base quote material cost and total are replaced while other components stay intact',()=>{
  const material=calculateCabinetMaterial(rules,environment);
  const applied=applyCabinetMaterial({formula_cost:{material_cost:999,auxiliary_cost:10,total_cost:1200},quick_quote:{total_cost:1500}},material);
  assert.equal(applied.formula_cost.total_cost,1200-999+material.material_cost);
  assert.equal(applied.formula_cost.auxiliary_cost,10);
  assert.equal(applied.quick_quote.total_cost,1500);
});

test('dynamic attachments do not use the cabinet waste factor',()=>{
  const item={attachment_price_id:1,price:100};
  const dynamic={rule_id:1,rule_kind:'DYNAMIC',product_codes:[],weight_formula:'宽度*0.001',
    area_formula:'0',auxiliary_formula:'0',labor_formula:'0'};
  const base={product_code:'JS',width_mm:1000,height_mm:1800,depth_mm:600,material_code:'SECC',
    density_g_cm3:7.85,material_unit_price:5,spray_unit_price:10,coating_type:'橘纹',quote_date:'2026-09-11'};
  const first=calculateAttachment({quantity:2},item,[dynamic],{...base,waste_factor:1.2});
  const second=calculateAttachment({quantity:2},item,[dynamic],{...base,waste_factor:1.8});
  assert.equal(first.formula_amount,second.formula_amount);
  assert.equal(first.weight,second.weight);
});

test('wide product codes are not collapsed into ordinary JS or JP material rules',()=>{
  assert.throws(()=>calculateCabinetMaterial(rules,{...environment,product_code:'JS_WIDE_EXP'}),/最新柜体材料表没有 JS_WIDE_EXP/);
});

test('all 241 workbook rows execute for every imported product/profile/door group',()=>{
  const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-material/generated/cabinet-material-bundle.json',import.meta.url)));
  assert.equal(bundle.rules.length,241);
  const groups=new Map();
  for(const rule of bundle.rules){
    const key=[rule.family,rule.body_thickness_profile_mm,rule.single_door_count,rule.double_door_count].join('|');
    groups.set(key,{family:rule.family,body:rule.body_thickness_profile_mm,single:rule.single_door_count,double:rule.double_door_count});
  }
  for(const group of groups.values()){
    const input={...environment,product_code:group.family,single_door_count:group.single,double_door_count:group.double,
      cabinet_body_thickness_mm:group.body??1.5,waste_factor:1.2};
    const result=calculateCabinetMaterial(bundle.rules,input);
    assert.ok(result.part_details.length>0,JSON.stringify(group));
    assert.ok(result.part_details.every(row=>row.area_m2>=0&&row.net_weight_kg>=0),JSON.stringify(group));
    assert.ok(Math.abs(result.corrected_material_weight_kg-result.net_material_weight_kg*1.2)<1e-7,JSON.stringify(group));
  }
});
