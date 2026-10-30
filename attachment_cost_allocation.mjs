/** Cost classification only. Original cabinet/attachment pricing stays intact. */
import {money,moneySum,moneyProduct,decimalSum,formulaAttachmentLineAmount} from './quick_discount_rules.mjs';
export const ALLOCATION_BASIS='formula_attachments_v1';
export const COST_PARTS=['material_cost','spray_cost','auxiliary_cost','labor_cost'];
const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
export const isFormulaCost=a=>a?.formula_cost_edited!==true&&a?.custom!==true&&(a?.cost_method==='FORMULA'||a?.status==='CALCULATED'||String(a?.calculation_notes||'').includes('公式成本'));
export function allocateAttachmentCosts(formula={},rows=[],{strict=false}={}){
 const active=rows.some(a=>a?.status!=='QUICK_ONLY'&&isFormulaCost(a));
 if(!active)return null;
 const errors=[],lines=[],parts=Object.fromEntries(COST_PARTS.map(k=>[k,0]));let fixed=0;
 for(const [index,a] of rows.entries()){
  if(!a||typeof a!=='object'||(a.status==='QUICK_ONLY'&&a.formula_cost_edited!==true))continue;
  let amount;
  try{amount=money(a.formula_amount??formulaAttachmentLineAmount(a));}catch{errors.push(`${a.item_name||'附件'}：成本尚未完成`);continue;}
  const line={index,name:String(a.item_name||a.name||'附件'),specification:String(a.model_code||a.specification||''),
   unit:String(a.unit||'件'),quantity:Math.abs(Number(a.quantity??1))*(Number(a.quantity??1)<0||Number(a.attachment_price_sign)===-1?-1:1),amount,
   method:isFormulaCost(a)?'FORMULA':'FIXED',components:{}};
  if(line.method==='FIXED'){fixed=moneySum([fixed,amount]);lines.push(line);continue;}
  if(!finite(a.quantity??1)||Number(a.quantity??1)===0||COST_PARTS.some(k=>!finite(a[k]))){
   errors.push(`${line.name}：公式成本缺少材料、喷塑、辅材或人工分项，请重新计算`);lines.push(line);continue;
  }
  const signedQuantity=line.quantity;
  const expected=moneyProduct(decimalSum(COST_PARTS.map(k=>a[k])),signedQuantity);
  if(Math.abs(expected-amount)>.001){errors.push(`${line.name}：公式成本分项与原成本不一致，请重新计算`);lines.push(line);continue;}
  let previous=0;
  for(const [position,key] of COST_PARTS.entries()){
   const cumulative=decimalSum(COST_PARTS.slice(0,position+1).map(k=>a[k]));
   const next=position===COST_PARTS.length-1?amount:moneyProduct(cumulative,signedQuantity);
   const value=moneySum([next,-previous]);previous=next;
   line.components[key]={unit_cost:Number(a[key]),amount:value,formula:String(a.formulas?.[key]||'已保存公式成本分项')};
   parts[key]=moneySum([parts[key],value]);
  }
  lines.push(line);
 }
 const total=moneySum([fixed,...Object.values(parts)]);
 if(!errors.length&&finite(formula.attachment_fee)&&Math.abs(total-money(formula.attachment_fee))>.001)
  errors.push('附件归类合计与原附件成本不一致，请重新计算');
 const totals=Object.fromEntries(COST_PARTS.map(k=>[k,finite(formula[k])?moneySum([formula[k],parts[k]]):null]));
 Object.assign(totals,{attachment_fee:fixed,management_fee:formula.management_fee??null});
 if(formula.tax_cost_basis==='quoted_less_display_costs_15pct_v1')totals.tax_cost=formula.tax_cost??null;
 if(formula.manufacturing_cost_basis==='quoted_unit_4pct_v1')totals.manufacturing_cost=formula.manufacturing_cost??null;
 const result={schema:1,basis:ALLOCATION_BASIS,complete:errors.length===0,totals,attachment_parts:parts,fixed_cost:fixed,
  attachment_total:total,lines,errors};
 if(strict&&errors.length)throw new Error(errors.join('；'));
 return result;
}
export function withAttachmentCostAllocation(formula,rows,options){
 const result={...formula};delete result.cost_allocation;
 const allocation=allocateAttachmentCosts(result,rows,options);
 if(allocation)result.cost_allocation=allocation;
 return result;
}
