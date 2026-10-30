export const THICKNESS_SURCHARGE_BASIS='cabinet_cost_weight_vs_1_5_v1';
export const DEFAULT_THICKNESS_COEFFICIENT=10;
const finite=value=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value));
const roundWeight=value=>Math.round(value*1e8)/1e8;
export const usesThicknessSurcharge=input=>/^(JS|JA|JE|JP|JM)(?:_(?:SINGLE|DOUBLE))?$/.test(String(input?.product_code||'').trim().toUpperCase())
  &&Number(input?.cabinet_body_thickness_mm)>1.5;

// Both profiles use the same catalogue, dimensions, material, doors and waste.
export function compareThicknessWeights(actual,reference){
  if(!actual||!reference||Number(actual.body_thickness_profile_mm)<=1.5||Number(reference.body_thickness_profile_mm)!==1.5)
    throw new Error('料厚差价缺少输入料厚或1.5mm成本材料重量规则，请核对材料目录后重新计算');
  for(const result of [actual,reference])if(!finite(result.corrected_material_weight_kg)||Number(result.corrected_material_weight_kg)<0)
    throw new Error('料厚差价的成本材料重量无效');
  const difference=roundWeight(Number(actual.corrected_material_weight_kg)-Number(reference.corrected_material_weight_kg));
  if(difference<0)throw new Error('料厚差价的输入料厚成本材料重量小于1.5mm，请核对材料规则');
  return {basis:THICKNESS_SURCHARGE_BASIS,weight_basis:'COST_WITH_WASTE',selected_thickness_mm:Number(actual.body_thickness_profile_mm),
    selected_cost_weight_kg:Number(actual.corrected_material_weight_kg),reference_cost_weight_kg:Number(reference.corrected_material_weight_kg),
    weight_difference_kg:difference,waste_factor:Number(actual.waste_factor),data_version:actual.data_version,cabinet_count:1};
}
export function aggregateThicknessComparisons(results){
  const rows=results.map(result=>result.formula_cost?.thickness_comparison).filter(row=>row?.basis===THICKNESS_SURCHARGE_BASIS);
  if(!rows.length)return undefined;
  return {basis:THICKNESS_SURCHARGE_BASIS,weight_basis:'COST_WITH_WASTE',
    selected_cost_weight_kg:roundWeight(rows.reduce((sum,row)=>sum+row.selected_cost_weight_kg,0)),
    reference_cost_weight_kg:roundWeight(rows.reduce((sum,row)=>sum+row.reference_cost_weight_kg,0)),
    weight_difference_kg:roundWeight(rows.reduce((sum,row)=>sum+row.weight_difference_kg,0)),
    cabinet_count:rows.length,children:rows};
}
export function thicknessWeightDifference(item={}){
  if(item.item_type==='standalone_attachment')return 0;
  const comparison=(item.formula||{}).thickness_comparison;
  if(comparison?.basis!==THICKNESS_SURCHARGE_BASIS)return 0;
  const requested=item.waste_factor??item.scheme2_cost_settings?.waste_factor;
  const weight=row=>{
    const original=row.waste_factor,target=requested??original;
    if(!finite(original)||Number(original)<=0||!finite(target)||Number(target)<=0
      ||!finite(row.selected_cost_weight_kg)||!finite(row.reference_cost_weight_kg))throw new Error('料厚差价的计价重量或废料系数无效，请重新计算');
    const difference=roundWeight((Number(row.selected_cost_weight_kg)-Number(row.reference_cost_weight_kg))*Number(target)/Number(original));
    if(difference<0)throw new Error('料厚差价的重量差不能为负数');
    return difference;
  };
  return Array.isArray(comparison.children)?roundWeight(comparison.children.reduce((sum,row)=>sum+weight(row),0)):weight(comparison);
}
export function thicknessCoefficient(item={}){
  const value=item.thickness_surcharge_coefficient??item.scheme2_cost_settings?.thickness_surcharge_coefficient??DEFAULT_THICKNESS_COEFFICIENT;
  if(!finite(value)||Number(value)<0)throw new Error('料厚补价系数必须为有效的非负金额');
  return Number(value);
}
