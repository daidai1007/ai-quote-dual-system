import {round} from './attachment_formula.mjs';

export const QUICK_THICKNESS_BASIS='quick_cabinet_2mm_x1_2_v1';
const finite=value=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value));

export function quickThicknessMultiplier(environment={}){
 const code=String(environment.product_code||'').trim().toUpperCase();
 return /^(JS|JA|JE)(?:_(?:SINGLE|DOUBLE))?$/.test(code)
  && Number(environment.cabinet_body_thickness_mm)===2 ? 1.2 : 1;
}

// Apply to the server-matched cabinet face only, before the ordinary selective
// discount. A recorded unadjusted base prevents refresh/override compounding.
export function applyQuickThickness(quick,environment,{sourceBase}={}){
 if(!quick||typeof quick!=='object')return quick;
 const prior=quick.body_thickness_pricing_basis===QUICK_THICKNESS_BASIS;
 const factor=quickThicknessMultiplier(environment);
 if(factor===1&&!prior&&sourceBase===undefined)return quick;
 const original=sourceBase!==undefined?sourceBase:prior?quick.body_thickness_unadjusted_base_price:
  quick.base_price??(finite(quick.total_cost)?Number(quick.total_cost)-Number(quick.attachment_fee||0):null);
 if(!finite(original)||Number(original)<0)return quick;
 const base=round(Number(original)*factor,6);
 return {...quick,base_price:base,total_cost:round(base+Number(quick.attachment_fee||0),6),
  body_thickness_pricing_basis:QUICK_THICKNESS_BASIS,
  body_thickness_price_multiplier:factor,body_thickness_unadjusted_base_price:Number(original)};
}

export function applyQuickThicknessResult(result,environment){
 if(!result?.quick_quote)return result;
 const quick=applyQuickThickness(result.quick_quote,environment);
 return quick===result.quick_quote?result:{...result,quick_quote:quick};
}
