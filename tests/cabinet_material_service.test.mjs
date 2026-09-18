import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {calculateCabinetMaterial,calculateCabinetMaterialFixed,applyCabinetMaterial} from '../api/cabinet_material_service.mjs';
import {calculateAttachment} from '../api/attachment_cost.mjs';

const materials=[
  {material_code:'SECC',density_g_cm3:7.85,material_unit_price:5},
  {material_code:'SUS304',density_g_cm3:7.93,material_unit_price:20},
  {material_code:'SUS316',density_g_cm3:7.98,material_unit_price:30},
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

test('experience weight is billed directly without applying the requested waste factor',()=>{
  const fixed=[{fixed_rule_id:1,product_code:'JQ_EXP',profile_code:null,material_codes:['SECC'],model_code:'JQ609648',
    width_mm:600,height_mm:960,depth_mm:480,material_weight_kg:54,allow_dimension_scale:true,
    apply_waste_factor:false,source_sheet:'JQ',source_row_no:3}];
  const result=calculateCabinetMaterialFixed(fixed,{...environment,product_code:'JQ_EXP',model_code:'JQ609648',
    material_code:'SECC',width_mm:600,height_mm:960,depth_mm:480,waste_factor:1.8});
  assert.equal(result.net_material_weight_kg,54);
  assert.equal(result.corrected_material_weight_kg,54);
  assert.equal(result.material_cost,270);
  assert.equal(result.waste_factor,1);
  assert.equal(result.requested_waste_factor,1.8);
  assert.equal(result.waste_factor_applied,false);
  assert.equal(result.match_method,'FIXED_EXACT');
});

test('experience weight uses nearest perimeter scaling and SECC density fallback only when needed',()=>{
  const fixed=[{fixed_rule_id:1,product_code:'JP_WIDE_EXP',profile_code:null,material_codes:['SECC'],model_code:'JP131860',
    width_mm:1300,height_mm:1800,depth_mm:600,material_weight_kg:224.4,allow_dimension_scale:true,
    apply_waste_factor:false,source_sheet:'JP超宽柜',source_row_no:3}];
  const result=calculateCabinetMaterialFixed(fixed,{...environment,product_code:'JP_WIDE_EXP',model_code:'CUSTOM',
    material_code:'SUS304',width_mm:1400,height_mm:1800,depth_mm:600,waste_factor:1.6});
  const expected=224.4*(3800/3700)*(7.93/7.85);
  assert.ok(Math.abs(result.corrected_material_weight_kg-expected)<1e-7);
  assert.equal(result.waste_factor,1);
  assert.equal(result.match_method,'FIXED_DIMENSION_SCALE');
  assert.equal(result.density_converted_from,'SECC');
});

test('explicit stainless experience row has priority over SECC density conversion',()=>{
  const fixed=[
    {fixed_rule_id:1,product_code:'JQ_EXP',profile_code:null,material_codes:['SECC'],model_code:'JQ609648',width_mm:600,height_mm:960,depth_mm:480,material_weight_kg:54,allow_dimension_scale:true,source_sheet:'JQ',source_row_no:3},
    {fixed_rule_id:2,product_code:'JQ_EXP',profile_code:null,material_codes:['SUS304','SUS316'],model_code:'JQ609648',width_mm:600,height_mm:960,depth_mm:480,material_weight_kg:44,allow_dimension_scale:true,source_sheet:'JQ',source_row_no:7},
  ];
  const result=calculateCabinetMaterialFixed(fixed,{...environment,product_code:'JQ_EXP',model_code:'JQ609648',
    material_code:'SUS304',width_mm:600,height_mm:960,depth_mm:480});
  assert.equal(result.corrected_material_weight_kg,44);
  assert.equal(result.density_converted_from,null);
});

test('all 241 workbook rows execute for every imported product/profile/door group',()=>{
  const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-material/generated/cabinet-material-bundle.json',import.meta.url)));
  assert.equal(bundle.rules.length,241);
  const jsSides=bundle.rules.filter(rule=>rule.family==='JS'&&rule.part_name==='左右侧板-1');
  assert.equal(jsSides.length,10);
  assert.ok(jsSides.every(rule=>rule.area_formula==='(高度+50.5)*(深度+64)*0.000001'));
  assert.ok(jsSides.every(rule=>JSON.stringify(rule.quantity_rule)===JSON.stringify({kind:'JS_DEPTH_HEIGHT',when_true:1,when_false:2})));
  assert.equal(bundle.fixed_rules.length,46);
  assert.ok(bundle.fixed_rules.every(rule=>rule.apply_waste_factor===false));
  assert.equal(bundle.fixed_rules.find(rule=>rule.product_code==='JQ_EXP'&&rule.model_code==='JQ609648'&&rule.material_codes.includes('SECC')).material_weight_kg,54);
  assert.equal(bundle.fixed_rules.find(rule=>rule.product_code==='JQ_EXP'&&rule.model_code==='JQ609648'&&rule.material_codes.includes('SUS304')).material_weight_kg,44);
  assert.equal(bundle.fixed_rules.find(rule=>rule.product_code==='OP_TABLE_EXP'&&rule.model_code==='JM601210'&&rule.material_codes.includes('SUS316')).material_weight_kg,77.3);
  assert.deepEqual([...new Set(bundle.fixed_rules.filter(rule=>rule.product_code==='JC_EXP').map(rule=>rule.profile_code))].sort(),['LUXURY','STANDARD']);
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

test('every JS rear-panel reinforcement uses one piece only above width 1000',()=>{
  const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-material/generated/cabinet-material-bundle.json',import.meta.url)));
  const rules=bundle.rules.filter(rule=>rule.family==='JS'&&rule.part_name==='后背板加强筋');
  assert.equal(rules.length,4);
  assert.ok(rules.every(rule=>JSON.stringify(rule.quantity_rule)===JSON.stringify(
    {kind:'WIDTH_GT',threshold:1000,when_true:1,when_false:0})));
  for(const rule of rules){
    const base={...environment,product_code:'JS',cabinet_body_thickness_mm:rule.body_thickness_profile_mm,
      single_door_count:rule.single_door_count,double_door_count:rule.double_door_count};
    const atLimit=calculateCabinetMaterial(bundle.rules,{...base,width_mm:1000});
    const above=calculateCabinetMaterial(bundle.rules,{...base,width_mm:1001});
    assert.equal(atLimit.part_details.find(row=>row.part_name==='后背板加强筋').internal_quantity,0);
    assert.equal(above.part_details.find(row=>row.part_name==='后背板加强筋').internal_quantity,1);
  }
});
