import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {applyCabinetLabor,calculateCabinetLabor} from '../api/cabinet_labor_service.mjs';

const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-labor/generated/cabinet-labor-bundle.json',import.meta.url)));
const material={part_details:[
  {part_name:'安装板',net_weight_kg:8,billable_weight_kg:10},
  {part_name:'安装纵梁',net_weight_kg:4,billable_weight_kg:5},
  {part_name:'侧板',net_weight_kg:16,billable_weight_kg:20},
]};

test('linear labor uses net cabinet weight and exact stainless exclusions',()=>{
  const secc=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JS_SINGLE',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600},material);
  assert.equal(secc.labor_billable_weight_kg,28);
  assert.equal(secc.labor_cost,Math.round((283.3905+.367734*28)*100)/100);
  const sus=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JS_DOUBLE',material_code:'SUS304',width_mm:800,height_mm:1800,depth_mm:600},material);
  assert.equal(sus.labor_billable_weight_kg,16);
  assert.deepEqual(sus.excluded_part_names,['安装纵梁','安装板']);
  assert.equal(sus.labor_cost,Math.round((547.4286+4.697963*16)*100)/100);
});

test('JM confirmed formulas use net material weight for SECC and stainless steel',()=>{
  const jmRules=[
    {rule_kind:'LINEAR_WEIGHT',product_code:'JM',material_codes:['SECC'],intercept:197.2715,slope:1.423229,
      excluded_part_names:[],source_sheet:'JM',source_row_no:3,source_formula:'人工 = 197.2715 + 1.423229 × 计价材料重量'},
    {rule_kind:'LINEAR_WEIGHT',product_code:'JM',material_codes:['SUS304','SUS316'],intercept:292.5932,slope:2.756249,
      excluded_part_names:['安装板'],source_sheet:'JM',source_row_no:4,
      source_formula:'人工 = 292.5932 + 2.756249 × 计价材料重量（去掉安装板的重量）'},
  ];
  for(const material_code of ['SECC','SUS304','SUS316']){
    const result=calculateCabinetLabor(jmRules,{data_version:'cabinet-labor-20a09683ece5809a-v2',management_fee_rate:.13,
      product_code:'JM',material_code,width_mm:800,height_mm:1500,depth_mm:300},material);
    const [intercept,slope]=material_code==='SECC'?[197.2715,1.423229]:[292.5932,2.756249];
    const expectedWeight=material_code==='SECC'?28:20;
    assert.equal(result.labor_billable_weight_kg,expectedWeight);
    assert.equal(result.labor_cost,Math.round((intercept+slope*expectedWeight)*100)/100);
    assert.deepEqual(result.excluded_part_names,material_code==='SECC'?[]:['安装板']);
  }
});

test('JK 150x80x150 labor uses net weight and returns 63.19',()=>{
  const result=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JK_SINGLE',material_code:'SECC',width_mm:150,height_mm:150,depth_mm:80},
  {part_details:[{part_name:'JK柜体',net_weight_kg:1.36791354,billable_weight_kg:1.64149623}]});
  assert.equal(result.labor_billable_weight_kg,1.36791354);
  assert.equal(result.labor_cost,63.19);
});

test('fixed products match source dimensions and retain existing perimeter scaling',()=>{
  const exact=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JQ_EXP',model_code:'JQ609648-1',material_code:'SECC',width_mm:600,height_mm:960,depth_mm:480},null);
  assert.equal(exact.labor_cost,792);assert.equal(exact.match_method,'FIXED_EXACT');
  const scaled=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JQ_EXP',model_code:'JQ609648-1',material_code:'SECC',width_mm:700,height_mm:960,depth_mm:480},null);
  assert.equal(scaled.labor_cost,Math.round(792*((700+960+480)/(600+960+480))*100)/100);
});

test('JC luxury and standard are never selected ambiguously',()=>{
  assert.throws(()=>calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JC_EXP',model_code:'JC601660',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:600},null),/豪华型\/标配型/);
  const luxury=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JC_EXP',model_code:'JC601660-1',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:600},null);
  const standard=calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JC_EXP',model_code:'JC601660-2',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:600},null);
  assert.equal(luxury.labor_cost,1220);assert.equal(standard.labor_cost,980);
});

test('labor and management replace formula components without changing quick quote',()=>{
  const quick={base_price:2000,total_cost:2100,attachment_fee:100};
  const labor={data_version:'labor-v1',labor_cost:300,management_fee:39,management_fee_rate:.13,
    match_method:'LINEAR_WEIGHT',labor_billable_weight_kg:10,excluded_part_names:[],matched_rule:{source_sheet:'JS',source_row_no:3,source_formula:'x'}};
  const result=applyCabinetLabor({formula_cost:{labor_cost:100,management_fee:13,total_cost:1000},quick_quote:quick},labor);
  assert.equal(result.formula_cost.total_cost,1226);assert.deepEqual(result.quick_quote,quick);
});

test('every imported labor rule is executable and JM stainless gap is explicit',()=>{
  assert.equal(bundle.rules.length,57);
  for(const rule of bundle.rules){
    const materialCode=rule.material_codes[0],product=rule.product_code;
    const environment={data_version:bundle.data_version,management_fee_rate:.13,product_code:product,material_code:materialCode,
      model_code:rule.model_code,width_mm:rule.width_mm??800,height_mm:rule.height_mm??1800,depth_mm:rule.depth_mm??600};
    if(product==='JC_EXP')environment.model_code=`${rule.model_code}-${rule.profile_code==='LUXURY'?1:2}`;
    assert.ok(calculateCabinetLabor(bundle.rules,environment,material).labor_cost>=0,`${rule.source_sheet}!${rule.source_row_no}`);
  }
  assert.throws(()=>calculateCabinetLabor(bundle.rules,{data_version:bundle.data_version,management_fee_rate:.13,
    product_code:'JM',material_code:'SUS304',width_mm:800,height_mm:1500,depth_mm:300},material),/没有适用人工公式/);
});
