/** User-confirmed 2026-10-26 JP auxiliary weight; pricing BOM is unchanged. */
import {round} from './attachment_formula.mjs';

export const JP_AUXILIARY_WEIGHT_BASIS='jp_auxiliary_frame_weight_v1';
const parts=Object.freeze([
  {name:'横梁',dimension:'width_mm',deduction:88,quantity:4},
  {name:'纵梁',dimension:'depth_mm',deduction:98,quantity:4},
  {name:'左立柱(1712)',dimension:'height_mm',deduction:98,quantity:2},
  {name:'右立柱(1712)',dimension:'height_mm',deduction:98,quantity:2},
]);
export function jpAuxiliaryWeight(input){
  const code=String(input.product_code||'').trim().toUpperCase();
  if(code.split('_')[0]!=='JP'||code.includes('WIDE'))return null;
  const rows=parts.map(part=>{
    const value=Number(input[part.dimension]);
    if(!Number.isFinite(value)||value<=0)throw Error('JP 辅材重量缺少有效宽度、深度或高度。');
    const length=Math.max(0,value-part.deduction);
    const weight=length*1.5*198*part.quantity*7.85*0.000001*1.2;
    return {item_name:part.name,dimension:part.dimension,dimension_mm:value,deduction_mm:part.deduction,
      length_mm:length,internal_quantity:part.quantity,sheet_thickness_mm:1.5,developed_width_mm:198,
      density_g_cm3:7.85,waste_factor:1.2,weight_kg:round(weight,8)};
  });
  return {basis:JP_AUXILIARY_WEIGHT_BASIS,quantity_basis:'ONE_SET',
    weight_kg:round(rows.reduce((sum,row)=>sum+row.weight_kg,0),8),lines:rows};
}
