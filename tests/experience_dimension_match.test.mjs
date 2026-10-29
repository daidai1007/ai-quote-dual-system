import assert from 'node:assert/strict';
import test from 'node:test';
import {experienceDimensionRank,compareExperienceDimensions} from '../api/experience_dimension_match.mjs';
import {calculateCabinetMaterialFixed} from '../api/cabinet_material_service.mjs';
import {calculateCabinetSprayFixed} from '../api/cabinet_spray_service.mjs';
import {calculateCabinetAuxiliaryFixed} from '../api/cabinet_auxiliary_service.mjs';
import {calculateCabinetLabor} from '../api/cabinet_labor_service.mjs';

const target={product_code:'JS_WIDE_EXP',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:400,
  materials:[{material_code:'SECC',density_g_cm3:7.85,material_unit_price:1}],coating_type:'橘纹'};
const rule=(id,width,height,depth,price)=>({fixed_rule_id:id,rule_id:id,source_row_no:id,source_sheet:'SYNTHETIC',
  rule_kind:'FIXED',product_code:'JS_WIDE_EXP',model_code:'SYNTHETIC-'+id,material_codes:['SECC'],
  width_mm:width,height_mm:height,depth_mm:depth,allow_dimension_scale:true,apply_waste_factor:false,
  material_weight_kg:price,spray_cost:price,auxiliary_cost:price,labor_cost:price});
const methods=[
  ['material',(r,e)=>calculateCabinetMaterialFixed(r,e).material_cost],
  ['spray',(r,e)=>calculateCabinetSprayFixed(r,e).spray_cost],
  ['auxiliary',(r,e)=>calculateCabinetAuxiliaryFixed(r,e).auxiliary_cost],
  ['labor',(r,e)=>calculateCabinetLabor(r,e,null).labor_cost],
];

test('surface area uses all six faces and comes before the former 3D distance tie-breaker',()=>{
  const a=rule(1,600,1900,100,100),b=rule(2,600,1000,1000,200);
  assert.deepEqual(experienceDimensionRank(a,target),[0,0,900000,180000]);
  assert.deepEqual(experienceDimensionRank(b,target),[0,0,720000,720000]);
  assert.ok(compareExperienceDimensions(b,a,target)<0);
});

for(const [name,calculate] of methods){
  test(`${name}: width outranks a closer perimeter and area`,()=>{
    const rows=[rule(1,600,2000,1000,100),rule(2,601,1600,399,9999)];
    assert.equal(calculate(rows,target),72.22); // 100 * 2600/3600, original scaling.
  });
  test(`${name}: nearest perimeter wins at the same width`,()=>{
    const rows=[rule(1,600,1900,100,100),rule(2,600,1800,1000,9999)];
    assert.equal(calculate(rows,target),100);
  });
  test(`${name}: area resolves the first two ties without interpolation or price changes`,()=>{
    const rows=[rule(1,600,1900,100,100),rule(2,600,1000,1000,200),rule(3,601,1600,399,9999)];
    assert.equal(calculate(rows,target),200);
    assert.equal(calculate([...rows].reverse(),target),200);
    assert.equal(calculate(rows,{...target,height_mm:1900,depth_mm:100}),100);
  });
}
