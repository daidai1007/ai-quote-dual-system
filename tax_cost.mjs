import {withAttachmentCostAllocation} from './attachment_cost_allocation.mjs';
import {money,moneySum,moneyProduct,quickOrderLineBreakdown,quickFreightFee,materialDifferenceAmount,
 MANAGEMENT_COST_KEYS,MANUFACTURING_COST_BASIS} from './quick_discount_rules.mjs';

export const TAX_COST_BASIS='quoted_less_display_costs_15pct_v1';
export const hasTaxCost=item=>item?.tax_cost_basis===TAX_COST_BASIS||item?.formula?.tax_cost_basis===TAX_COST_BASIS;
const keys=['material_cost','auxiliary_cost','attachment_fee','spray_cost'];
const finite=value=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value));
const fail=(message,code='MISSING_COSTS')=>Object.assign(new Error(message),{statusCode:422,code});

export function withTaxCostForItem(item,formula=item.formula,{validateFrozen=false,frozen=item.formula}={}){
 if(!hasTaxCost(item))return formula;
 const result=withAttachmentCostAllocation(formula,item.attachments||[]),allocation=result.cost_allocation;
 if(allocation&&!allocation.complete)throw fail('税费所需附件成本分项尚未完整，请重新计算');
 const costs=allocation?.totals||result;
 const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments||[],discount:item.quick_discount??1,
  cabinetQuantity:item.quantity??1,gangedCabinetCount:item.ganged_cabinet_count??1,freightFee:quickFreightFee(item),materialDifference:materialDifferenceAmount(item)});
 const inputs={quoted_unit_price:line.equivalentUnitTotal,...Object.fromEntries(keys.map(key=>[key,costs[key]])),freight_fee:item.freight_fee??item.freight??0};
 if(!Object.values(inputs).every(finite))throw fail('税费计算所需报价或成本尚未完整，请重新计算');
 const deductions=moneySum([...keys.map(key=>inputs[key]),inputs.freight_fee]);
 const base=moneySum([inputs.quoted_unit_price,-deductions]);
 if(base<0)throw fail(`税费计算失败：报价 ${money(inputs.quoted_unit_price).toFixed(2)} 元小于材料、辅材、附件、成本运费及喷涂成本合计 ${deductions.toFixed(2)} 元，税费基数为 ${base.toFixed(2)} 元。请核对报价和成本数据。`,'NEGATIVE_BASE');
 const amount=moneyProduct(base,.15);
 if(validateFrozen&&(!finite(frozen?.tax_cost)||money(frozen.tax_cost)!==amount))throw fail('税费与当前报价及成本分项不一致，请重新计算','STALE_TAX');
 Object.assign(result,{tax_cost:amount,tax_cost_basis:TAX_COST_BASIS,tax_cost_base:base,tax_cost_rate:.15,
  tax_cost_inputs:Object.fromEntries(Object.entries(inputs).map(([key,value])=>[key,money(value)]))});
 delete result.tax_cost_error;delete result.tax_cost_error_code;
 const manufacturing=result.manufacturing_cost_basis===MANUFACTURING_COST_BASIS?result.manufacturing_cost:0;
 result.total_cost=moneySum([...MANAGEMENT_COST_KEYS.map(key=>result[key]),manufacturing,result.management_fee,amount]);
 return withAttachmentCostAllocation(result,item.attachments||[]);
}
