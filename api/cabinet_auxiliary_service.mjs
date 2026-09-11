import {evaluateFormula,round} from './attachment_formula.mjs';

const valueSql=value=>value==null?'NULL':typeof value==='number'?String(value):
  `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const finite=(value,label,{zero=false}={})=>{const n=Number(value);if(!Number.isFinite(n)||(zero?n<0:n<=0))throw new Error(`${label}必须是有效${zero?'非负':'正'}数`);return n;};
const familyOf=value=>{const code=String(value||'').trim().toUpperCase();return /^(JP|JS)_WIDE_EXP$/.test(code)?code:code.split('_')[0];};
function quantity(rule,environment){
  const q=rule.quantity_rule||{};
  if(q.kind==='CONSTANT')return finite(q.value,'辅材内部数量',{zero:true});
  if(q.kind==='HEIGHT_GT')return environment.height_mm>Number(q.threshold)?Number(q.when_true):Number(q.when_false);
  throw new Error(`不支持的辅材数量规则：${q.kind||'空'}`);
}

export function calculateCabinetAuxiliary(profile,lines,environment){
  if(!profile)throw new Error('没有适用的柜体辅材 BOM 门型');
  const variables={宽度:finite(environment.width_mm,'宽度'),高度:finite(environment.height_mm,'高度'),深度:finite(environment.depth_mm,'深度')};
  const sprayUnitPrice=finite(environment.spray_unit_price,'喷塑单价',{zero:true});
  const details=lines.map(line=>{
    const internalQuantity=quantity(line,environment);
    let lengthM=null,sprayArea=0,baseCost;
    if(line.cost_kind==='UNIT')baseCost=internalQuantity*finite(line.unit_price,`${line.item_name}单价`,{zero:true});
    else{
      lengthM=Math.max(0,evaluateFormula(line.length_formula,variables));
      baseCost=lengthM*internalQuantity*finite(line.unit_price,`${line.item_name}单价`,{zero:true});
      if(line.cost_kind==='LENGTH_WITH_SPRAY')sprayArea=lengthM*finite(line.spray_width_m,`${line.item_name}喷塑展开宽度`)*internalQuantity;
    }
    const sprayCost=sprayArea*sprayUnitPrice,lineTotal=baseCost+sprayCost;
    return {line_id:line.line_id,line_no:Number(line.line_no),item_code:line.item_code,item_name:line.item_name,
      spec_model:line.spec_model,material_name:line.material_name,internal_quantity:internalQuantity,
      unit:lengthM==null?'件':'米',unit_price:Number(line.unit_price),length_per_piece_m:lengthM==null?null:round(lengthM,8),
      spray_area_m2:round(sprayArea,8),spray_unit_price:sprayArea? sprayUnitPrice:0,
      base_cost:round(baseCost,8),spray_cost:round(sprayCost,8),line_total:round(lineTotal,8),
      quantity_rule:line.quantity_rule,length_formula:line.length_formula,notes:line.notes,
      source_total_formula:line.source_total_formula,source_sheet:line.source_sheet,source_row_no:line.source_row_no};
  });
  return {data_version:environment.data_version,product_code:profile.product_code,single_door_count:Number(profile.single_door_count),
    double_door_count:Number(profile.double_door_count),spray_unit_price:sprayUnitPrice,
    auxiliary_spray_area_m2:round(details.reduce((sum,row)=>sum+row.spray_area_m2,0),8),
    auxiliary_spray_cost:round(details.reduce((sum,row)=>sum+row.spray_cost,0),2),
    auxiliary_cost:round(details.reduce((sum,row)=>sum+row.line_total,0),2),source_sheet:profile.source_sheet,lines:details};
}

export function createCabinetAuxiliaryService({runPsql}){
  const query=async sql=>{const output=await runPsql(sql);return JSON.parse(output.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  return {async calculate(input){
    const family=familyOf(input.product_code);if(!['JA','JE','JS','JP','JM'].includes(family))return null;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(input.quote_date||''))throw new Error('报价日期无效');
    let data;
    try{data=await query(`SELECT jsonb_build_object('data_version',v.data_version,
      'profile',(SELECT to_jsonb(p) FROM calc.cabinet_auxiliary_profile p WHERE p.data_version=v.data_version
        AND p.product_code=${valueSql(family)} AND p.single_door_count=${Number(input.single_door_count||0)}
        AND p.double_door_count=${Number(input.double_door_count||0)}),
      'lines',(SELECT coalesce(jsonb_agg(to_jsonb(l) ORDER BY l.line_no,l.line_id),'[]') FROM calc.cabinet_auxiliary_line l
        JOIN calc.cabinet_auxiliary_profile p USING(profile_id) WHERE p.data_version=v.data_version
        AND p.product_code=${valueSql(family)} AND p.single_door_count=${Number(input.single_door_count||0)}
        AND p.double_door_count=${Number(input.double_door_count||0)}),
      'spray_unit_price',CASE WHEN ${valueSql(input.coating_type)}='不喷塑' THEN 0
        ELSE calc.get_spray_unit_price(${valueSql(input.quote_date)}::date,${valueSql(input.coating_type)}) END)
      FROM calc.cabinet_auxiliary_catalog_version v WHERE v.status='ACTIVE';`);}
    catch(error){if(/cabinet_auxiliary_(catalog_version|profile|line).*does not exist/i.test(String(error?.message||error)))return null;throw error;}
    if(!data)return null;
    return calculateCabinetAuxiliary(data.profile,data.lines,{...input,data_version:data.data_version,spray_unit_price:data.spray_unit_price});
  },async persist(quoteId,result,auxiliary){
    if(!auxiliary)return;
    const formula=result.formula_cost||{},quick=result.quick_quote||{};
    const difference=Number.isFinite(Number(quick.total_cost))&&Number.isFinite(Number(formula.total_cost))?round(Number(quick.total_cost)-Number(formula.total_cost),2):null;
    const output=await runPsql(`UPDATE calc.dual_quote_result SET formula_auxiliary_cost=${valueSql(formula.auxiliary_cost)},
      formula_total_cost=${valueSql(formula.total_cost)},difference_cost=${valueSql(difference)},
      cabinet_auxiliary_version=${valueSql(auxiliary.data_version)},cabinet_auxiliary_snapshot=${valueSql(JSON.stringify(auxiliary))}::jsonb,
      updated_at=current_timestamp WHERE quote_id=${valueSql(quoteId)} RETURNING 1;`);
    if(!String(output||'').trim().split(/\r?\n/).some(line=>line.trim()==='1'))throw new Error(`柜体辅材快照未保存：报价 ${quoteId} 不存在`);
  }};
}

export function applyCabinetAuxiliary(result,auxiliary){
  if(!auxiliary)return result;
  const formula={...(result.formula_cost||{})},old=Number(formula.auxiliary_cost);
  if(!Number.isFinite(old)||!Number.isFinite(Number(formula.total_cost)))throw new Error('数据库基础公式辅材成本缺失，不能应用最新辅材规则');
  formula.auxiliary_cost=auxiliary.auxiliary_cost;
  formula.total_cost=round(Number(formula.total_cost)-old+auxiliary.auxiliary_cost,2);
  Object.assign(formula,{cabinet_auxiliary_version:auxiliary.data_version,cabinet_auxiliary_source_sheet:auxiliary.source_sheet,
    cabinet_auxiliary_lines:auxiliary.lines,cabinet_auxiliary_spray_area_m2:auxiliary.auxiliary_spray_area_m2,
    cabinet_auxiliary_spray_cost:auxiliary.auxiliary_spray_cost});
  return {...result,formula_cost:formula};
}
