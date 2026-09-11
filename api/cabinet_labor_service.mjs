import {round} from './attachment_formula.mjs';

const valueSql=value=>value==null?'NULL':typeof value==='number'?String(value):
  `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const finite=(value,label,{zero=false}={})=>{const n=Number(value);if(!Number.isFinite(n)||(zero?n<0:n<=0))throw new Error(`${label}必须是有效${zero?'非负':'正'}数`);return n;};
const codeOf=value=>String(value||'').trim().toUpperCase();
const familyOf=value=>{const code=codeOf(value);return /^(JP|JS)_WIDE_EXP$/.test(code)?code:code.split('_')[0];};
const canonicalModel=(model,product)=>product==='JC_EXP'?codeOf(model).replace(/-[12]$/,''):codeOf(model);
function jcProfile(environment){
  const variant=codeOf(environment.variant_code),model=codeOf(environment.model_code);
  if(/LUXURY|DELUXE|豪华/.test(variant)||/-1$/.test(model))return 'LUXURY';
  if(/STANDARD|DEFAULT|标配/.test(variant)||/-2$/.test(model))return 'STANDARD';
  return null;
}
function linearLabor(rule,material){
  if(!material?.part_details?.length)throw new Error(`${rule.product_code} 人工公式需要当前柜体计价材料重量明细`);
  const excluded=new Set(rule.excluded_part_names||[]);
  const eligible=material.part_details.filter(part=>!excluded.has(part.part_name));
  const weight=round(eligible.reduce((sum,part)=>sum+finite(part.billable_weight_kg,`${part.part_name}计价重量`,{zero:true}),0),8);
  return {labor_cost:round(Number(rule.intercept)+Number(rule.slope)*weight,2),labor_billable_weight_kg:weight,
    excluded_part_names:[...excluded],match_method:'LINEAR_WEIGHT',matched_rule:rule};
}
function fixedLabor(rules,environment,product){
  let candidates=rules.filter(rule=>rule.rule_kind==='FIXED'&&rule.product_code===product&&(rule.material_codes||[]).includes(environment.material_code));
  if(product==='JC_EXP'){
    const profile=jcProfile(environment);
    if(!profile)throw new Error('JC 人工成本必须通过型号后缀 -1/-2 或产品配置明确豪华型/标配型');
    candidates=candidates.filter(rule=>rule.profile_code===profile);
  }
  const model=canonicalModel(environment.model_code,product);
  if(model)candidates=candidates.filter(rule=>canonicalModel(rule.model_code,product)===model);
  if(!candidates.length)throw new Error(`${product} ${environment.material_code} 没有适用人工成本规则`);
  const w=finite(environment.width_mm,'宽度'),h=finite(environment.height_mm,'高度'),d=finite(environment.depth_mm,'深度');
  const exact=candidates.filter(rule=>Number(rule.width_mm)===w&&Number(rule.height_mm)===h&&Number(rule.depth_mm)===d);
  if(exact.length>1)throw new Error(`${product} 人工固定成本存在同级冲突`);
  if(exact.length===1)return {labor_cost:round(Number(exact[0].labor_cost),2),labor_billable_weight_kg:null,
    excluded_part_names:[],match_method:'FIXED_EXACT',perimeter_ratio:1,matched_rule:exact[0]};
  const scalable=candidates.filter(rule=>rule.allow_dimension_scale);
  if(!scalable.length)throw new Error(`${product} 没有 ${w}×${h}×${d} 的人工成本规则`);
  scalable.sort((a,b)=>((a.width_mm-w)**2+(a.height_mm-h)**2+(a.depth_mm-d)**2)-((b.width_mm-w)**2+(b.height_mm-h)**2+(b.depth_mm-d)**2));
  const best=scalable[0],distance=(best.width_mm-w)**2+(best.height_mm-h)**2+(best.depth_mm-d)**2;
  if(scalable[1]&&((scalable[1].width_mm-w)**2+(scalable[1].height_mm-h)**2+(scalable[1].depth_mm-d)**2)===distance)
    throw new Error(`${product} 非标尺寸人工规则存在同级冲突`);
  const ratio=(w+h+d)/(Number(best.width_mm)+Number(best.height_mm)+Number(best.depth_mm));
  return {labor_cost:round(Number(best.labor_cost)*ratio,2),labor_billable_weight_kg:null,excluded_part_names:[],
    match_method:'FIXED_DIMENSION_SCALE',perimeter_ratio:round(ratio,6),matched_rule:best};
}

export function calculateCabinetLabor(rules,environment,material){
  const product=codeOf(environment.product_code),family=familyOf(product),linearProducts=new Set(['JS','JP','JA','JE','JK','JM']);
  let calculated;
  if(linearProducts.has(family)&&!product.includes('WIDE')){
    const candidates=rules.filter(rule=>rule.rule_kind==='LINEAR_WEIGHT'&&rule.product_code===family&&(rule.material_codes||[]).includes(environment.material_code));
    if(candidates.length!==1)throw new Error(candidates.length?`${family} ${environment.material_code} 人工公式存在同级冲突`:`${family} ${environment.material_code} 没有适用人工公式`);
    calculated=linearLabor(candidates[0],material);
  }else calculated=fixedLabor(rules,environment,product);
  const managementRate=finite(environment.management_fee_rate,'管理费率',{zero:true});
  return {data_version:environment.data_version,product_code:product,material_code:environment.material_code,
    management_fee_rate:managementRate,management_fee:round(calculated.labor_cost*managementRate,2),...calculated};
}

export function createCabinetLaborService({runPsql}){
  const query=async sql=>{const output=await runPsql(sql);return JSON.parse(output.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  return {async calculate(input,material){
    let data;
    try{data=await query(`SELECT jsonb_build_object('data_version',v.data_version,'management_fee_rate',v.management_fee_rate,
      'rules',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.source_sheet,r.source_row_no),'[]')
        FROM calc.cabinet_labor_rule r WHERE r.data_version=v.data_version))
      FROM calc.cabinet_labor_catalog_version v WHERE v.status='ACTIVE';`);}
    catch(error){if(/cabinet_labor_(catalog_version|rule).*does not exist/i.test(String(error?.message||error)))return null;throw error;}
    if(!data)return null;
    return calculateCabinetLabor(data.rules,{...input,data_version:data.data_version,management_fee_rate:data.management_fee_rate},material);
  },async persist(quoteId,result,labor){
    if(!labor)return;
    const formula=result.formula_cost||{},snapshot={...labor,matched_rule:labor.matched_rule};
    const quick=result.quick_quote||{};
    const difference=Number.isFinite(Number(quick.total_cost))&&Number.isFinite(Number(formula.total_cost))?round(Number(quick.total_cost)-Number(formula.total_cost),2):null;
    const output=await runPsql(`UPDATE calc.dual_quote_result SET formula_labor_cost=${valueSql(formula.labor_cost)},
      formula_management_fee=${valueSql(formula.management_fee)},formula_total_cost=${valueSql(formula.total_cost)},difference_cost=${valueSql(difference)},
      cabinet_labor_version=${valueSql(labor.data_version)},cabinet_labor_snapshot=${valueSql(JSON.stringify(snapshot))}::jsonb,
      updated_at=current_timestamp WHERE quote_id=${valueSql(quoteId)} RETURNING 1;`);
    if(!String(output||'').trim().split(/\r?\n/).some(line=>line.trim()==='1'))throw new Error(`柜体人工快照未保存：报价 ${quoteId} 不存在`);
  }};
}

export function applyCabinetLabor(result,labor){
  if(!labor)return result;
  const formula={...(result.formula_cost||{})},oldLabor=Number(formula.labor_cost),oldManagement=Number(formula.management_fee);
  if(!Number.isFinite(oldLabor)||!Number.isFinite(oldManagement)||!Number.isFinite(Number(formula.total_cost)))throw new Error('数据库基础公式人工或管理费缺失，不能应用最新人工规则');
  formula.labor_cost=labor.labor_cost;formula.management_fee=labor.management_fee;
  formula.total_cost=round(Number(formula.total_cost)-oldLabor-oldManagement+labor.labor_cost+labor.management_fee,2);
  Object.assign(formula,{cabinet_labor_version:labor.data_version,labor_method:labor.match_method,
    labor_billable_weight_kg:labor.labor_billable_weight_kg,labor_excluded_part_names:labor.excluded_part_names,
    labor_source_sheet:labor.matched_rule.source_sheet,labor_source_row_no:labor.matched_rule.source_row_no,
    labor_source_formula:labor.matched_rule.source_formula,management_fee_rate:labor.management_fee_rate,
    labor_perimeter_ratio:labor.perimeter_ratio??null});
  return {...result,formula_cost:formula};
}
