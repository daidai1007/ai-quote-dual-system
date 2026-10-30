import test from 'node:test';
import assert from 'node:assert/strict';
import {usesThicknessSurcharge,compareThicknessWeights,aggregateThicknessComparisons,thicknessWeightDifference} from '../api/thickness_surcharge.mjs';
import {createCabinetMaterialService,applyCabinetMaterial,calculateCabinetMaterial} from '../api/cabinet_material_service.mjs';
import {calculateCabinetSpray} from '../api/cabinet_spray_service.mjs';
import {thicknessSurchargeAmount,materialDifferenceAmount,quickOrderLineBreakdown,manufacturingFormulaForItem,MANUFACTURING_COST_BASIS} from '../quick_discount_rules.mjs';

export const input=(code='JS',thickness=2)=>({product_code:code,cabinet_body_thickness_mm:thickness,
  width_mm:1000,height_mm:1000,depth_mm:600,single_door_count:1,double_door_count:0,quote_date:'2026-10-30',
  material_code:'SECC',waste_factor:1.2,carbon_steel_unit_price_override:4.2,galvanized_sheet_unit_price_override:4.55});
export const rules=()=>['JS','JA','JE','JP','JM'].flatMap(family=>[1.5,2,2.5].flatMap(profile=>[
  {rule_id:1,family,body_thickness_profile_mm:profile,single_door_count:1,double_door_count:0,
    part_name:'柜体',area_formula:'宽度*高度*0.000001',sheet_thickness_mm:profile,quantity_rule:{kind:'CONSTANT',value:1}},
  {rule_id:2,family,body_thickness_profile_mm:profile,single_door_count:1,double_door_count:0,
    part_name:'安装板',area_formula:'1',sheet_thickness_mm:2.5,fixed_material_code:'SGCC',quantity_rule:{kind:'CONSTANT',value:1}}]));
export const materialService=()=>createCabinetMaterialService({runPsql:async()=>JSON.stringify({data_version:'synthetic-thickness',default_waste_factor:1.2,
  rules:rules(),fixed_rules:[],materials:[{material_code:'SECC',density_g_cm3:7.85},{material_code:'SGCC',density_g_cm3:7.85}]})});
export function sample(){
 const comparison=compareThicknessWeights({body_thickness_profile_mm:2,corrected_material_weight_kg:42.39,waste_factor:1.2,data_version:'local'},
   {body_thickness_profile_mm:1.5,corrected_material_weight_kg:37.68,waste_factor:1.2,data_version:'local'});
 return {product_code:'JS',material_code:'SECC',cabinet_body_thickness_mm:2,quantity:3,
   formula:{thickness_comparison:comparison},quick:{base_price:1000,attachment_fee:100,total_cost:1100},
   attachments:[{item_name:'接地线',quantity:1,quick_amount:100}],quick_discount:.5,freight_fee:30};
}
test('five families at arbitrary body thickness compare same-version cost weights including waste',async()=>{
 for(const code of ['JS','JA','JE','JP','JM','JS_SINGLE','JP_DOUBLE']){
  const env=input(code);if(code==='JP_DOUBLE')env.product_code='JP';
  assert.equal(usesThicknessSurcharge(env),true);
  const result=await materialService().calculate(env);
  assert.equal(result.thickness_comparison.weight_difference_kg,4.71);
  assert.equal(result.thickness_comparison.selected_cost_weight_kg,42.39);
  assert.equal(result.thickness_comparison.reference_cost_weight_kg,37.68);
  const quick={base_price:1000,total_cost:1000,attachment_fee:0};
  const priced=applyCabinetMaterial({formula_cost:{},quick_quote:quick},result);
  assert.deepEqual(priced.quick_quote,quick);assert.equal(thicknessSurchargeAmount({formula:priced.formula_cost}),47.1);
 }
 for(const code of ['JK','JC_EXP','JS_WIDE_EXP','JP_WIDE_EXP','STANDALONE_ATTACHMENT'])assert.equal(usesThicknessSurcharge(input(code)),false);
 assert.equal(usesThicknessSurcharge(input('JS',1.5)),false);
 for(const thickness of [1.6,2.5,3.2])assert.equal(usesThicknessSurcharge(input('JS',thickness)),true);
 assert.equal((await materialService().calculate(input('JS',1.5))).thickness_comparison,undefined);
 const custom=await materialService().calculate(input('JS',3.2));
 assert.equal(custom.thickness_comparison.weight_difference_kg,16.014);
 assert.equal(custom.part_details.find(p=>p.part_name==='安装板').sheet_thickness_mm,2.5);
});
test('only original 1.5mm parts change; original 2 and 2.5mm parts and database formulas remain intact',()=>{
 const source=rules().filter(r=>r.family==='JS'&&r.body_thickness_profile_mm===1.5);
 source.push({...source[0],part_name:'门板',sheet_thickness_mm:2});
 const before=structuredClone(source);
 const env={...input('JS',2.375),materials:[{material_code:'SECC',density_g_cm3:7.85,material_unit_price:4.2},
   {material_code:'SGCC',density_g_cm3:7.85,material_unit_price:4.55}]};
 const priced=calculateCabinetMaterial(source,env);
 assert.deepEqual(priced.part_details.map(row=>[row.part_name,row.sheet_thickness_mm]),[['柜体',2.375],['安装板',2.5],['门板',2]]);
 const baseline=calculateCabinetMaterial(source,{...env,cabinet_body_thickness_mm:1.5});
 assert.equal(compareThicknessWeights(priced,baseline).weight_difference_kg,8.2425);
 assert.deepEqual(source,before);
 assert.throws(()=>calculateCabinetMaterial(source,{...env,cabinet_body_thickness_mm:1.25}),error=>error.statusCode===422&&/不能小于1.5/.test(error.message));
});
test('custom thickness reuses baseline spray formulas while existing exact spray profiles stay intact',()=>{
 const base={family:'JS',single_door_count:1,double_door_count:0,part_name:'柜体',area_formula:'1',quantity_rule:{kind:'CONSTANT',value:1}};
 const source=[{...base,body_thickness_profile_mm:1.5},{...base,body_thickness_profile_mm:2,area_formula:'2'}];
 const before=structuredClone(source),env={...input('JS',2.375),spray_unit_price:26};
 assert.equal(calculateCabinetSpray(source,env).spray_cost,26);
 assert.equal(calculateCabinetSpray(source,{...env,cabinet_body_thickness_mm:2}).spray_cost,52);
 assert.deepEqual(source,before);
});
test('surcharge stays outside discount and quantity applies once; base attachment and freight unchanged',()=>{
 const item=sample(),before=structuredClone(item);
 for(const discount of [0,.5,.8,1]){
  const extra=materialDifferenceAmount(item);
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,discount,cabinetQuantity:3,freightFee:30,materialDifference:extra});
  assert.equal(line.equivalentUnitTotal,1000*discount+100+30+47.1);
  assert.equal(line.lineTotal,Math.round((1000*discount+177.1)*3*100)/100);
 }
 assert.deepEqual(item,before);
});
test('manual coefficient zero and custom amount; waste rescaling never applies twice',()=>{
 const item=sample();item.thickness_surcharge_coefficient=12;assert.equal(thicknessSurchargeAmount(item),56.52);
 item.thickness_surcharge_coefficient=0;assert.equal(thicknessSurchargeAmount(item),0);
 item.thickness_surcharge_coefficient=10;item.scheme2_cost_settings={waste_factor:1.5};
 assert.equal(thicknessWeightDifference(item),5.8875);assert.equal(thicknessSurchargeAmount(item),58.88);
 assert.equal(thicknessSurchargeAmount(item),58.88);
 for(const value of [-1,'NaN',true,'']){item.thickness_surcharge_coefficient=value;assert.throws(()=>thicknessSurchargeAmount(item));}
});
test('ganged sums only eligible comparisons without multiplying by split count',()=>{
 const item=sample(),child={formula_cost:item.formula};
 const comparison=aggregateThicknessComparisons([child,{formula_cost:{}},child]);
 assert.equal(comparison.weight_difference_kg,9.42);item.formula={thickness_comparison:comparison};
 assert.equal(thicknessSurchargeAmount(item),94.2);
});
test('SUS316 existing surcharge is added separately; legacy and independent snapshots remain unchanged',()=>{
 const item=sample();item.material_code='SUS316';item.formula.corrected_material_weight_kg=10;
 assert.equal(materialDifferenceAmount(item),297.1);
 assert.equal(thicknessSurchargeAmount({...item,item_type:'standalone_attachment'}),0);
 assert.equal(thicknessSurchargeAmount({formula:{corrected_material_weight_kg:100},cabinet_body_thickness_mm:2,product_code:'JS'}),0);
});
test('fees derived from quote include the new undiscounted amount under existing 4 and 5 percent rules',()=>{
 const item=sample();item.manufacturing_cost_basis=MANUFACTURING_COST_BASIS;
 Object.assign(item.formula,{material_cost:100,auxiliary_cost:20,labor_cost:30,spray_cost:10,attachment_fee:0});
 const formula=manufacturingFormulaForItem(item);
 assert.equal(formula.manufacturing_quote_unit_price,677.1);
 assert.equal(formula.manufacturing_cost,27.08);assert.equal(formula.management_fee,33.86);
});
