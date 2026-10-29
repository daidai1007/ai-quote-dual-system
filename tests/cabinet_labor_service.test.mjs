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
  const result=applyCabinetLabor({formula_cost:{material_cost:887,auxiliary_cost:0,spray_cost:0,attachment_fee:0,labor_cost:100,management_fee:13,total_cost:1000},quick_quote:quick},labor);
  assert.equal(result.formula_cost.management_fee,71.22);
  assert.equal(result.formula_cost.management_fee_rate,.06);
  assert.equal(result.formula_cost.total_cost,1258.22);assert.deepEqual(result.quick_quote,quick);
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

test('JS WIDE screenshot midpoint uses width/perimeter/area matching without a false conflict',()=>{
  const environment={data_version:bundle.data_version,product_code:'JS_WIDE_EXP',material_code:'SECC',
    width_mm:1350,height_mm:1250,depth_mm:400}; // 200mm base is a separate attachment.
  for(const rules of [bundle.rules,[...bundle.rules].reverse()]){
    const result=calculateCabinetLabor(rules,environment,null);
    assert.equal(result.matched_rule.model_code,'JS131860');
    assert.equal(result.matched_rule.labor_cost,390);
    assert.equal(result.labor_cost,316.22); // 390 * (1350+1250+400)/(1300+1800+600)
    assert.equal(result.perimeter_ratio,.810811);
    assert.equal(result.perimeter_difference,700);
    assert.equal(result.dimension_distance,345000);
  }
});

test('fixed labor retains exact dimensions and explicit model boundaries',()=>{
  const env={product_code:'JS_WIDE_EXP',material_code:'SECC',width_mm:1300,height_mm:1800,depth_mm:600};
  const exact=calculateCabinetLabor(bundle.rules,env,null);
  assert.equal(exact.labor_cost,390);assert.equal(exact.match_method,'FIXED_EXACT');
  const selected=calculateCabinetLabor(bundle.rules,{...env,model_code:'JS141860',width_mm:1350,height_mm:1250,depth_mm:400},null);
  assert.equal(selected.matched_rule.model_code,'JS141860');
  assert.equal(selected.labor_cost,323.68); // Explicit model retains its 410 yuan standard.
});

const fixed=(overrides={})=>({rule_kind:'FIXED',product_code:'JS_WIDE_EXP',material_codes:['SECC'],
  width_mm:1300,height_mm:1800,depth_mm:600,labor_cost:390,allow_dimension_scale:true,
  source_sheet:'合成规则',source_row_no:3,...overrides});
const midpoint={product_code:'JS_WIDE_EXP',material_code:'SECC',width_mm:1350,height_mm:1250,depth_mm:400};

test('width priority precedes perimeter and euclidean distance',()=>{
  const rules=[fixed({model_code:'PERIMETER',width_mm:1200,height_mm:1400,depth_mm:400,labor_cost:600}),
    fixed({model_code:'DISTANCE',width_mm:1350,height_mm:1250,depth_mm:450,labor_cost:900,source_row_no:4})];
  const result=calculateCabinetLabor(rules,midpoint,null);
  assert.equal(result.matched_rule.model_code,'DISTANCE');assert.equal(result.labor_cost,885.25);
});

test('equal perimeter and distance use persisted rule identity then source order, independent of input order',()=>{
  const env={...midpoint,height_mm:1800,depth_mm:600};
  const first=fixed({rule_id:40,source_row_no:9});
  const later=fixed({rule_id:41,model_code:'JS141860',width_mm:1400,labor_cost:410,source_row_no:4});
  for(const rows of [[first,later],[later,first]])assert.equal(calculateCabinetLabor(rows,env,null).matched_rule.rule_id,41);
  delete first.rule_id;delete later.rule_id;
  for(const rows of [[first,later],[later,first]])assert.equal(calculateCabinetLabor(rows,env,null).matched_rule.source_row_no,9);
});

test('actual duplicates and truly unresolved matching priorities still fail closed',()=>{
  const a=fixed(),b=fixed({labor_cost:999});
  assert.throws(()=>calculateCabinetLabor([a,b],{...midpoint,width_mm:1300,height_mm:1800,depth_mm:600},null),/人工固定成本存在同级冲突/);
  assert.throws(()=>calculateCabinetLabor([a,b],midpoint,null),/非标尺寸人工规则存在同级冲突/);
});

test('scaled labor audit survives formula composition; sales and management semantics remain unchanged',()=>{
  const labor=calculateCabinetLabor(bundle.rules,midpoint,null);
  const quick={base_price:1200,attachment_fee:0,total_cost:1200};
  const result=applyCabinetLabor({formula_cost:{material_cost:100,auxiliary_cost:20,spray_cost:10,attachment_fee:0},quick_quote:quick},labor,8);
  assert.equal(result.formula_cost.labor_cost,316.22);
  assert.equal(result.formula_cost.labor_reference_model_code,'JS131860');
  assert.equal(result.formula_cost.labor_reference_height_mm,1800);
  assert.equal(result.formula_cost.labor_dimension_distance,345000);
  assert.equal(result.formula_cost.management_fee,27.25); // (100+20+10+316.22+8)*6%
  assert.equal(result.formula_cost.total_cost,473.47);
  assert.deepEqual(result.quick_quote,quick);
});
