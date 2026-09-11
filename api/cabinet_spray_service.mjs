import {evaluateFormula,round} from './attachment_formula.mjs';

const valueSql=value=>value==null?'NULL':typeof value==='number'?String(value):
  `convert_from(decode('${Buffer.from(String(value)).toString('hex')}','hex'),'UTF8')`;
const finite=(value,label,{allowZero=false,max=1e7}={})=>{
  const n=Number(value);if(!Number.isFinite(n)||(allowZero?n<0:n<=0)||n>max)throw new Error(`${label}必须是有效${allowZero?'非负':'正'}数`);return n;
};
const familyOf=code=>{const value=String(code||'').trim().toUpperCase();return /^(JP|JS)_WIDE_EXP$/.test(value)?value:value.split('_')[0];};
function quantity(rule,environment){
  const q=rule.quantity_rule||{},d=environment.depth_mm,h=environment.height_mm;
  if(q.kind==='CONSTANT')return finite(q.value,'喷塑内部数量',{allowZero:true});
  if(q.kind==='JS_DEPTH_HEIGHT')return d>=350&&d<=1000&&h<1000?Number(q.when_true):Number(q.when_false);
  throw new Error(`不支持的柜体喷塑数量规则：${q.kind||'空'}`);
}

export function calculateCabinetSpray(rules,environment){
  const family=familyOf(environment.product_code),single=Number(environment.single_door_count||0),double=Number(environment.double_door_count||0);
  const candidates=rules.filter(rule=>rule.family===family&&Number(rule.single_door_count)===single&&Number(rule.double_door_count)===double);
  if(!candidates.length)throw new Error(`最新柜体喷塑表没有 ${family} 门型 ${single}/${double} 的规则`);
  const profiles=[...new Set(candidates.map(rule=>rule.body_thickness_profile_mm).filter(value=>value!=null).map(Number))];
  const requested=environment.cabinet_body_thickness_mm==null?1.5:finite(environment.cabinet_body_thickness_mm,'柜体料厚',{max:20});
  const selected=profiles.length>1?candidates.filter(rule=>Math.abs(Number(rule.body_thickness_profile_mm)-requested)<1e-9):candidates;
  if(!selected.length)throw new Error(`${family} 没有柜体料厚 ${requested} mm 的喷塑规则`);
  const variables={宽度:finite(environment.width_mm,'宽度'),高度:finite(environment.height_mm,'高度'),深度:finite(environment.depth_mm,'深度')};
  const details=selected.map(rule=>{
    const areaPerPiece=evaluateFormula(rule.area_formula,variables);
    if(!Number.isFinite(areaPerPiece)||areaPerPiece<0)throw new Error(`${rule.part_name}喷塑面积无效`);
    const internalQuantity=quantity(rule,environment),totalArea=areaPerPiece*internalQuantity;
    return {rule_id:rule.rule_id,part_name:rule.part_name,area_per_piece_m2:round(areaPerPiece,10),
      internal_quantity:internalQuantity,total_area_m2:round(totalArea,10),area_formula:rule.area_formula,
      quantity_rule:rule.quantity_rule,source_sheet:rule.source_sheet,source_row_no:rule.source_row_no,source_column:rule.source_column};
  });
  const unitPrice=finite(environment.spray_unit_price,'喷塑单价',{allowZero:true});
  const area=round(details.reduce((sum,row)=>sum+row.total_area_m2,0),8);
  return {data_version:environment.data_version,family,single_door_count:single,double_door_count:double,
    body_thickness_profile_mm:profiles.length>1?requested:(profiles[0]??null),coating_type:environment.coating_type,
    spray_unit_price:unitPrice,product_area_m2:area,spray_cost:round(area*unitPrice,2),part_details:details};
}

export function createCabinetSprayService({runPsql}){
  const query=async sql=>{const output=await runPsql(sql);return JSON.parse(output.trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
  return {async calculate(input){
    const family=familyOf(input.product_code);if(!['JS','JP','JA','JE','JK','JM'].includes(family))return null;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(input.quote_date||''))throw new Error('报价日期无效');
    let data;
    try {data=await query(`SELECT jsonb_build_object(
      'data_version',v.data_version,
      'rules',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.source_sheet,r.source_row_no,r.source_column),'[]')
        FROM calc.cabinet_spray_rule r WHERE r.data_version=v.data_version AND r.family=${valueSql(family)}),
      'spray_unit_price',CASE WHEN ${valueSql(input.coating_type)}='不喷塑' THEN 0
        ELSE calc.get_spray_unit_price(${valueSql(input.quote_date)}::date,${valueSql(input.coating_type)}) END
      ) FROM calc.cabinet_spray_catalog_version v WHERE v.status='ACTIVE';`);}
    catch(error){
      if(/cabinet_spray_(catalog_version|rule).*does not exist/is.test(String(error?.message||error)))return null;
      throw error;
    }
    if(!data)return null;
    return calculateCabinetSpray(data.rules,{...input,data_version:data.data_version,spray_unit_price:data.spray_unit_price});
  },async persist(quoteId,result,spray){
    if(!spray)return;
    const formula=result.formula_cost||{};
    const snapshot={data_version:spray.data_version,family:spray.family,body_thickness_profile_mm:spray.body_thickness_profile_mm,
      single_door_count:spray.single_door_count,double_door_count:spray.double_door_count,coating_type:spray.coating_type,
      spray_unit_price:spray.spray_unit_price,product_area_m2:spray.product_area_m2,spray_cost:spray.spray_cost,part_details:spray.part_details};
    const output=await runPsql(`UPDATE calc.dual_quote_result SET formula_product_area_m2=${valueSql(formula.product_area_m2)},
      formula_spray_cost=${valueSql(formula.spray_cost)},formula_total_cost=${valueSql(formula.total_cost)},
      difference_cost=${valueSql(Number.isFinite(Number(result.quick_quote?.total_cost))&&Number.isFinite(Number(formula.total_cost))?round(Number(result.quick_quote.total_cost)-Number(formula.total_cost),2):null)},
      cabinet_spray_version=${valueSql(spray.data_version)},cabinet_spray_snapshot=${valueSql(JSON.stringify(snapshot))}::jsonb,
      updated_at=current_timestamp WHERE quote_id=${valueSql(quoteId)} RETURNING 1;`);
    if(!String(output||'').trim().split(/\r?\n/).some(line=>line.trim()==='1'))throw new Error(`柜体喷塑快照未保存：报价 ${quoteId} 不存在`);
  }};
}

export function applyCabinetSpray(result,spray){
  if(!spray)return result;
  const formula={...(result.formula_cost||{})},old=Number(formula.spray_cost);
  if(!Number.isFinite(old)||!Number.isFinite(Number(formula.total_cost)))throw new Error('数据库基础公式喷塑成本缺失，不能应用最新柜体喷塑规则');
  formula.spray_cost=spray.spray_cost;formula.product_area_m2=spray.product_area_m2;
  formula.total_cost=round(Number(formula.total_cost)-old+spray.spray_cost,2);
  Object.assign(formula,{spray_unit_price:spray.spray_unit_price,cabinet_spray_version:spray.data_version,
    cabinet_spray_part_details:spray.part_details});
  return {...result,formula_cost:formula};
}
